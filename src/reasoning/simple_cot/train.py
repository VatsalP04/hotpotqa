import os
import json
import random
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from typing import List, Dict, Any, Optional, Tuple
from tqdm import tqdm
import numpy as np
from pathlib import Path

try:
    from transformer_lens import HookedTransformer
except ImportError:
    HookedTransformer = None

from src.data.loader import load_hotpotqa
from src.reasoning.simple_cot.simple_cot import SimpleCoT, build_paragraphs_from_examples
from src.reasoning.simple_cot.probes import BaselineProbe, AttentionHeadProbe
from src.reasoning.simple_cot.utils import f1_score, calculate_recall, format_for_csv, split_cot_into_sentences
from transformers import AutoTokenizer


class HotpotQADataset(Dataset):
    def __init__(self, examples: List[Dict[str, Any]]):
        self.examples = examples
    
    def __len__(self):
        return len(self.examples)
    
    def __getitem__(self, idx):
        return self.examples[idx]


def balance_classes(examples: List[Dict[str, Any]], seed: int = 42) -> List[Dict[str, Any]]:
    random.seed(seed)
    
    correct_examples = []
    incorrect_examples = []
    
    for ex in examples:
        if ex.get('correct', 0) == 1:
            correct_examples.append(ex)
        else:
            incorrect_examples.append(ex)
    
    min_count = min(len(correct_examples), len(incorrect_examples))
    
    balanced = random.sample(correct_examples, min_count) + random.sample(incorrect_examples, min_count)
    random.shuffle(balanced)
    
    return balanced


def get_answer_token_index(tokenizer, prompt: str, answer: str) -> int:
    full_text = prompt + " " + answer
    prompt_tokens = tokenizer.encode(prompt, add_special_tokens=False)
    full_tokens = tokenizer.encode(full_text, add_special_tokens=False)
    
    if len(full_tokens) <= len(prompt_tokens):
        return len(prompt_tokens) - 1
    
    answer_start_idx = len(prompt_tokens)
    answer_end_idx = len(full_tokens) - 1
    return answer_end_idx


def train_probes(
    model_name: str = "meta-llama/Llama-3.1-8B-Instruct",
    data_dir: str = "data/hotpotqa",
    train_size: int = 28000,
    val_size: int = 7000,
    batch_size: int = 4,
    num_epochs: int = 3,
    learning_rate: float = 1e-4,
    output_dir: str = "outputs/simple_cot",
    save_interval: int = 100,
    seed: int = 42
):
    random.seed(seed)
    torch.manual_seed(seed)
    np.random.seed(seed)
    
    if HookedTransformer is None:
        raise ImportError("transformer_lens is required. Install with: pip install transformer-lens")
    
    os.makedirs(output_dir, exist_ok=True)
    
    print("Loading data...")
    train_data_raw = load_hotpotqa(data_dir, split="train", max_examples=train_size + val_size, shuffle=True, seed=seed)
    
    train_examples_raw = train_data_raw[:train_size]
    val_examples_raw = train_data_raw[train_size:train_size + val_size]
    
    print(f"Loaded {len(train_examples_raw)} train and {len(val_examples_raw)} val examples")
    
    print("Building paragraphs from all examples for InMemoryRetriever...")
    all_examples = train_examples_raw + val_examples_raw
    all_paragraphs = build_paragraphs_from_examples(all_examples)
    print(f"Built {len(all_paragraphs)} unique paragraphs")
    
    print("Initializing SimpleCoT pipeline with InMemoryRetriever...")
    simple_cot = SimpleCoT(model_name=model_name, paragraphs=all_paragraphs)
    
    print("Processing examples and computing correctness...")
    train_examples = []
    val_examples = []
    
    all_results = []
    
    for split_name, examples_raw in [("train", train_examples_raw), ("val", val_examples_raw)]:
        print(f"\nProcessing {split_name} examples...")
        for ex in tqdm(examples_raw, desc=f"Processing {split_name}"):
            question = ex['question']
            gold_answer = ex['answer']
            gold_supporting_facts = ex.get('supporting_facts', [])
            
            result = simple_cot.process(question)
            
            f1, _, _ = f1_score(result['answer'], gold_answer)
            correct = 1 if f1 >= 0.5 else 0
            
            recall = calculate_recall(result['retrieved_paragraphs'], gold_supporting_facts)
            
            gold_sentences = []
            for fact in gold_supporting_facts:
                if len(fact) >= 2:
                    title = fact[0]
                    sent_idx = fact[1]
                    for para in ex.get('context', []):
                        if para[0] == title and sent_idx < len(para[2]):
                            gold_sentences.append(para[2][sent_idx])
            
            csv_row = format_for_csv(
                question=question,
                correct=correct,
                recall=recall,
                answer=result['answer'],
                gold_answer=gold_answer,
                chain_of_thought=result['chain_of_thought'],
                retrieved_paragraphs=result['retrieved_paragraphs'],
                gold_sentences=gold_sentences
            )
            all_results.append(csv_row)
            
            ex_with_result = ex.copy()
            ex_with_result['correct'] = correct
            ex_with_result['result'] = result
            ex_with_result['recall'] = recall
            
            if split_name == "train":
                train_examples.append(ex_with_result)
            else:
                val_examples.append(ex_with_result)
    
    print(f"\nSaving results CSV...")
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(os.path.join(output_dir, "all_results.csv"), index=False)
    print(f"Saved {len(results_df)} results to {os.path.join(output_dir, 'all_results.csv')}")
    
    print("\nBalancing classes...")
    train_examples = balance_classes(train_examples, seed=seed)
    val_examples = balance_classes(val_examples, seed=seed)
    
    print(f"After balancing: {len(train_examples)} train, {len(val_examples)} val")
    
    print("\nLoading model with TransformerLens...")
    model = HookedTransformer.from_pretrained(model_name, device="cuda" if torch.cuda.is_available() else "cpu")
    model.eval()
    
    for param in model.parameters():
        param.requires_grad = False
    
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    d_model = model.cfg.d_model
    num_layers = model.cfg.n_layers
    
    print(f"Model: {model_name}")
    print(f"d_model: {d_model}, num_layers: {num_layers}")
    
    baseline_probe = BaselineProbe(d_model, num_layers).to(model.device)
    attention_probe = AttentionHeadProbe(d_model, num_layers).to(model.device)
    
    baseline_optimizer = torch.optim.Adam(baseline_probe.parameters(), lr=learning_rate)
    attention_optimizer = torch.optim.Adam(attention_probe.parameters(), lr=learning_rate)
    
    criterion = nn.BCEWithLogitsLoss()
    
    train_dataset = HotpotQADataset(train_examples)
    val_dataset = HotpotQADataset(val_examples)
    
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    
    print("\nStarting training...")
    
    for epoch in range(num_epochs):
        print(f"\nEpoch {epoch + 1}/{num_epochs}")
        
        baseline_probe.train()
        attention_probe.train()
        
        train_baseline_losses = []
        train_attention_losses = []
        
        for batch_idx, batch in enumerate(tqdm(train_loader, desc="Training")):
            batch_questions = [ex['question'] for ex in batch]
            batch_results = [ex['result'] for ex in batch]
            batch_labels = torch.tensor([ex['correct'] for ex in batch], dtype=torch.float32).to(model.device)
            
            batch_full_texts = []
            batch_answer_indices = []
            
            for ex, result in zip(batch, batch_results):
                paragraphs = result['retrieved_paragraphs']
                question = ex['question']
                cot = result['chain_of_thought']
                answer = result['answer']
                
                from src.reasoning.simple_cot.prompts import build_answer_prompt
                prompt = build_answer_prompt(paragraphs, question, cot)
                
                full_text = prompt + " " + answer
                batch_full_texts.append(full_text)
                
                answer_idx = get_answer_token_index(tokenizer, prompt, answer)
                batch_answer_indices.append(answer_idx)
            
            max_len = max(len(tokenizer.encode(t, add_special_tokens=False)) for t in batch_full_texts)
            max_len = min(max_len, 2048)
            
            tokenized = tokenizer(
                batch_full_texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=max_len
            ).to(model.device)
            
            with torch.no_grad():
                _, cache = model.run_with_cache(
                    tokenized.input_ids,
                    return_type=None
                )
            
            hidden_states_list = []
            for layer_idx in range(num_layers):
                layer_key = f"blocks.{layer_idx}.hook_resid_post"
                if layer_key in cache:
                    hidden_states_list.append(cache[layer_key])
                else:
                    hidden_states_list.append(torch.zeros(
                        (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                        dtype=torch.float32,
                        device=model.device
                    ))
            
            hidden_states = torch.stack(hidden_states_list, dim=1)
            
            answer_indices = torch.tensor(batch_answer_indices, device=model.device)
            
            batch_size_actual = hidden_states.shape[0]
            seq_len_actual = hidden_states.shape[2]
            
            if batch_size_actual != len(batch_labels):
                batch_labels = batch_labels[:batch_size_actual]
                answer_indices = answer_indices[:batch_size_actual]
            
            answer_indices = torch.clamp(answer_indices, 0, seq_len_actual - 1)
            
            baseline_optimizer.zero_grad()
            attention_optimizer.zero_grad()
            
            baseline_logits = baseline_probe(hidden_states, answer_indices)
            attention_logits = attention_probe(hidden_states)
            
            baseline_loss = 0.0
            attention_loss = 0.0
            
            for layer_idx in range(num_layers):
                baseline_loss += criterion(baseline_logits[:, layer_idx, 0], batch_labels)
                attention_loss += criterion(attention_logits[:, layer_idx], batch_labels)
            
            baseline_loss = baseline_loss / num_layers
            attention_loss = attention_loss / num_layers
            
            total_loss = baseline_loss + attention_loss
            
            total_loss.backward()
            
            baseline_optimizer.step()
            attention_optimizer.step()
            
            train_baseline_losses.append(baseline_loss.item())
            train_attention_losses.append(attention_loss.item())
            
            if (batch_idx + 1) % save_interval == 0:
                print(f"  Batch {batch_idx + 1}: Baseline Loss: {baseline_loss.item():.4f}, Attention Loss: {attention_loss.item():.4f}")
        
        print(f"Epoch {epoch + 1} - Avg Baseline Loss: {np.mean(train_baseline_losses):.4f}, Avg Attention Loss: {np.mean(train_attention_losses):.4f}")
        
        print("Validating...")
        baseline_probe.eval()
        attention_probe.eval()
        
        val_baseline_losses = []
        val_attention_losses = []
        val_baseline_predictions = {layer: [] for layer in range(num_layers)}
        val_attention_predictions = {layer: [] for layer in range(num_layers)}
        val_labels_list = []
        
        with torch.no_grad():
            for batch in tqdm(val_loader, desc="Validating"):
                batch_questions = [ex['question'] for ex in batch]
                batch_results = [ex['result'] for ex in batch]
                batch_labels = torch.tensor([ex['correct'] for ex in batch], dtype=torch.float32).to(model.device)
                
                batch_full_texts = []
                batch_answer_indices = []
                
                for ex, result in zip(batch, batch_results):
                    paragraphs = result['retrieved_paragraphs']
                    question = ex['question']
                    cot = result['chain_of_thought']
                    answer = result['answer']
                    
                    from src.reasoning.simple_cot.prompts import build_answer_prompt
                    prompt = build_answer_prompt(paragraphs, question, cot)
                    
                    full_text = prompt + " " + answer
                    batch_full_texts.append(full_text)
                    
                    answer_idx = get_answer_token_index(tokenizer, prompt, answer)
                    batch_answer_indices.append(answer_idx)
                
                max_len = max(len(tokenizer.encode(t, add_special_tokens=False)) for t in batch_full_texts)
                max_len = min(max_len, 2048)
                
                tokenized = tokenizer(
                    batch_full_texts,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=max_len
                ).to(model.device)
                
                _, cache = model.run_with_cache(
                    tokenized.input_ids,
                    return_type=None
                )
                
                hidden_states_list = []
                for layer_idx in range(num_layers):
                    layer_key = f"blocks.{layer_idx}.hook_resid_post"
                    if layer_key in cache:
                        hidden_states_list.append(cache[layer_key])
                    else:
                        hidden_states_list.append(torch.zeros(
                            (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                            dtype=torch.float32,
                            device=model.device
                        ))
                
                hidden_states = torch.stack(hidden_states_list, dim=1)
                
                answer_indices = torch.tensor(batch_answer_indices, device=model.device)
                
                batch_size_actual = hidden_states.shape[0]
                seq_len_actual = hidden_states.shape[2]
                
                if batch_size_actual != len(batch_labels):
                    batch_labels = batch_labels[:batch_size_actual]
                    answer_indices = answer_indices[:batch_size_actual]
                
                answer_indices = torch.clamp(answer_indices, 0, seq_len_actual - 1)
                
                baseline_logits = baseline_probe(hidden_states, answer_indices)
                attention_logits = attention_probe(hidden_states)
                
                baseline_loss = 0.0
                attention_loss = 0.0
                
                for layer_idx in range(num_layers):
                    baseline_loss += criterion(baseline_logits[:, layer_idx, 0], batch_labels)
                    attention_loss += criterion(attention_logits[:, layer_idx], batch_labels)
                    
                    baseline_probs = torch.sigmoid(baseline_logits[:, layer_idx, 0])
                    attention_probs = torch.sigmoid(attention_logits[:, layer_idx])
                    
                    val_baseline_predictions[layer_idx].extend(baseline_probs.cpu().numpy())
                    val_attention_predictions[layer_idx].extend(attention_probs.cpu().numpy())
                
                baseline_loss = baseline_loss / num_layers
                attention_loss = attention_loss / num_layers
                
                val_baseline_losses.append(baseline_loss.item())
                val_attention_losses.append(attention_loss.item())
                val_labels_list.extend(batch_labels.cpu().numpy())
        
        val_labels_array = np.array(val_labels_list)
        
        try:
            from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score, f1_score as sklearn_f1
        except ImportError:
            print("Warning: sklearn not available, skipping detailed metrics")
            import sys
            sys.exit(1)
        
        baseline_metrics = []
        attention_metrics = []
        
        for layer_idx in range(num_layers):
            baseline_pred = np.array(val_baseline_predictions[layer_idx])
            attention_pred = np.array(val_attention_predictions[layer_idx])
            
            baseline_auc = roc_auc_score(val_labels_array, baseline_pred)
            baseline_acc = accuracy_score(val_labels_array, (baseline_pred >= 0.5).astype(int))
            baseline_prec = precision_score(val_labels_array, (baseline_pred >= 0.5).astype(int), zero_division=0)
            baseline_rec = recall_score(val_labels_array, (baseline_pred >= 0.5).astype(int), zero_division=0)
            baseline_f1 = sklearn_f1(val_labels_array, (baseline_pred >= 0.5).astype(int), zero_division=0)
            
            attention_auc = roc_auc_score(val_labels_array, attention_pred)
            attention_acc = accuracy_score(val_labels_array, (attention_pred >= 0.5).astype(int))
            attention_prec = precision_score(val_labels_array, (attention_pred >= 0.5).astype(int), zero_division=0)
            attention_rec = recall_score(val_labels_array, (attention_pred >= 0.5).astype(int), zero_division=0)
            attention_f1 = sklearn_f1(val_labels_array, (attention_pred >= 0.5).astype(int), zero_division=0)
            
            baseline_metrics.append({
                'layer': layer_idx,
                'auc': baseline_auc,
                'accuracy': baseline_acc,
                'precision': baseline_prec,
                'recall': baseline_rec,
                'f1': baseline_f1
            })
            
            attention_metrics.append({
                'layer': layer_idx,
                'auc': attention_auc,
                'accuracy': attention_acc,
                'precision': attention_prec,
                'recall': attention_rec,
                'f1': attention_f1
            })
        
        baseline_df = pd.DataFrame(baseline_metrics)
        attention_df = pd.DataFrame(attention_metrics)
        
        baseline_df.to_csv(os.path.join(output_dir, f"baseline_probe_metrics_epoch_{epoch + 1}.csv"), index=False)
        attention_df.to_csv(os.path.join(output_dir, f"attention_probe_metrics_epoch_{epoch + 1}.csv"), index=False)
        
        print(f"Saved metrics for epoch {epoch + 1}")
        print(f"Baseline - Best Layer AUC: {baseline_df['auc'].max():.4f} (Layer {baseline_df.loc[baseline_df['auc'].idxmax(), 'layer']})")
        print(f"Attention - Best Layer AUC: {attention_df['auc'].max():.4f} (Layer {attention_df.loc[attention_df['auc'].idxmax(), 'layer']})")
    
    print("\nTraining complete!")
    print(f"Results saved to {output_dir}")


if __name__ == "__main__":
    train_probes()

