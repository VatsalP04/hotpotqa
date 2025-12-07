#%%
# Setup Python Path
import sys
from pathlib import Path

# Add project root to path so we can import src modules
# Works both when running as script and in interactive mode (Jupyter/IPython)
try:
    # When running as script
    project_root = Path(__file__).parent.parent.parent.parent
except NameError:
    # When running in interactive mode (Jupyter/IPython)
    project_root = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

#%%
# Imports and Setup
import os
import json
import random
import csv
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from typing import List, Dict, Any, Optional, Tuple
from tqdm import tqdm
import numpy as np
from transformer_lens import HookedTransformer

from src.data.loader import load_hotpotqa
from src.reasoning.simple_cot.simple_cot import SimpleCoT, build_paragraphs_from_example
from src.reasoning.simple_cot.probes import BaselineProbe, AttentionHeadProbe
from src.reasoning.simple_cot.utils import f1_score, calculate_recall, format_for_csv, split_cot_into_sentences
# We use HookedTransformer's tokenizer, not AutoTokenizer
# Import config to ensure .env file is loaded
import src.config


#%%
# Helper Classes and Functions
class HotpotQADataset(Dataset):
    def __init__(self, examples: List[Dict[str, Any]]):
        self.examples = examples
    
    def __len__(self):
        return len(self.examples)
    
    def __getitem__(self, idx):
        return self.examples[idx]


def collate_fn(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Custom collate function that just returns the list of dictionaries as-is.
    
    This is needed because the default collate function tries to stack tensors,
    but our examples are dictionaries with nested structures of different sizes.
    Since we process each example individually in the training loop, we don't
    need any collation - just return the list as-is.
    """
    return batch


def get_answer_token_index(tokenizer, prompt: str, answer: str) -> int:
    full_text = prompt + " " + answer
    prompt_tokens = tokenizer.encode(prompt, add_special_tokens=False)
    full_tokens = tokenizer.encode(full_text, add_special_tokens=False)
    
    if len(full_tokens) <= len(prompt_tokens):
        return len(prompt_tokens) - 1
    
    answer_start_idx = len(prompt_tokens)
    answer_end_idx = len(full_tokens) - 1
    return answer_end_idx


#%%
# Configuration - Adjust these hyperparameters as needed
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
# Use absolute paths based on project root
DATA_DIR = str(project_root / "data" / "hotpotqa")
TRAIN_SIZE = 28000
VAL_SIZE = 7000
BATCH_SIZE = 1  # Reduced to 1 to save memory - process examples one at a time
GRADIENT_ACCUMULATION_STEPS = 16  # Accumulate gradients over N examples before updating weights
# Effective batch size = BATCH_SIZE * GRADIENT_ACCUMULATION_STEPS = 16
# This gives more stable gradients while keeping memory usage low
NUM_EPOCHS = 3
LEARNING_RATE = 1e-4
OUTPUT_DIR = str(project_root / "outputs" / "simple_cot")
# Save interval in terms of weight updates (must be multiple of GRADIENT_ACCUMULATION_STEPS)
# We save both CSV and checkpoint together when weights are updated
SAVE_INTERVAL_WEIGHT_UPDATES = 1  # Save every N weight updates (3 * 16 = every 48 examples)
MAX_SEQ_LEN = 512  # Reduced from 1024 to save memory


#%%
# Load Data
print("Loading data...")
train_data_raw = load_hotpotqa(DATA_DIR, split="train", max_examples=TRAIN_SIZE + VAL_SIZE, shuffle=True)

train_examples_raw = train_data_raw[:TRAIN_SIZE]
val_examples_raw = train_data_raw[TRAIN_SIZE:TRAIN_SIZE + VAL_SIZE]

print(f"Loaded {len(train_examples_raw)} train and {len(val_examples_raw)} val examples")

# Note: We don't balance classes here because correctness labels are only computed
# during training when we run SimpleCoT on each example. Class balancing would
# require pre-processing all examples, which defeats the purpose of streaming training.


#%%
# Load Model
print("\nLoading model with TransformerLens...")
model = HookedTransformer.from_pretrained(MODEL_NAME, device="cuda" if torch.cuda.is_available() else "cpu")
model.eval()

for param in model.parameters():
    param.requires_grad = False

# Use HookedTransformer's tokenizer instead of AutoTokenizer
tokenizer = model.tokenizer
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

d_model = model.cfg.d_model
num_layers = model.cfg.n_layers

print(f"Model: {MODEL_NAME}")
print(f"d_model: {d_model}, num_layers: {num_layers}")


#%%
# Setup Checkpoints, Probes, and DataLoaders
# Checkpoint and CSV setup
checkpoint_dir = os.path.join(OUTPUT_DIR, "checkpoints")
os.makedirs(checkpoint_dir, exist_ok=True)
checkpoint_path = os.path.join(checkpoint_dir, "checkpoint.pt")
results_csv_path = os.path.join(OUTPUT_DIR, "all_results.csv")

# Initialize or load checkpoints - check CSV first to see where we left off
start_epoch = 0
start_batch = 0

# Check CSV to see how many examples have been processed
if os.path.exists(results_csv_path):
    try:
        # Try to read CSV with error handling for malformed rows
        existing_df = pd.read_csv(results_csv_path, on_bad_lines='skip', engine='python')
        print(f"Found existing results CSV with {len(existing_df)} rows")
        # If CSV exists, we can use it to determine resume position
        if len(existing_df) > 0:
            last_row = existing_df.iloc[-1]
            csv_epoch = last_row.get('epoch', 0)
            csv_batch = last_row.get('batch_idx', 0)
            # Use CSV info if checkpoint doesn't exist or CSV is more recent
            if not os.path.exists(checkpoint_path) or (csv_epoch > start_epoch or (csv_epoch == start_epoch and csv_batch > start_batch)):
                start_epoch = csv_epoch - 1  # CSV has epoch+1, so subtract 1
                start_batch = csv_batch
                print(f"Using CSV to resume from epoch {start_epoch + 1}, batch {start_batch + 1}")
    except Exception as e:
        print(f"Warning: Could not read existing CSV file ({e}). Starting fresh.")
        # Optionally backup the corrupted CSV
        if os.path.exists(results_csv_path):
            backup_path = results_csv_path + ".backup"
            import shutil
            shutil.copy2(results_csv_path, backup_path)
            print(f"Backed up corrupted CSV to {backup_path}")

if os.path.exists(checkpoint_path):
    print(f"Found checkpoint at {checkpoint_path}, loading...")
    checkpoint = torch.load(checkpoint_path, map_location=model.cfg.device)
    start_epoch = checkpoint['epoch']
    start_batch = checkpoint.get('batch_idx', 0)
    
    baseline_probe = BaselineProbe(d_model, num_layers).to(model.cfg.device)
    attention_probe = AttentionHeadProbe(d_model, num_layers).to(model.cfg.device)
    baseline_probe.load_state_dict(checkpoint['baseline_probe_state'])
    attention_probe.load_state_dict(checkpoint['attention_probe_state'])
    
    baseline_optimizer = torch.optim.Adam(baseline_probe.parameters(), lr=LEARNING_RATE)
    attention_optimizer = torch.optim.Adam(attention_probe.parameters(), lr=LEARNING_RATE)
    baseline_optimizer.load_state_dict(checkpoint['baseline_optimizer_state'])
    attention_optimizer.load_state_dict(checkpoint['attention_optimizer_state'])
    
    print(f"Resuming from epoch {start_epoch + 1}, batch {start_batch + 1}")
else:
    print("No checkpoint found, starting from scratch")
    baseline_probe = BaselineProbe(d_model, num_layers).to(model.cfg.device)
    attention_probe = AttentionHeadProbe(d_model, num_layers).to(model.cfg.device)
    baseline_optimizer = torch.optim.Adam(baseline_probe.parameters(), lr=LEARNING_RATE)
    attention_optimizer = torch.optim.Adam(attention_probe.parameters(), lr=LEARNING_RATE)

criterion = nn.BCEWithLogitsLoss()

# Create datasets from raw examples (we'll process them on-the-fly during training)
train_dataset = HotpotQADataset(train_examples_raw)
val_dataset = HotpotQADataset(val_examples_raw)

train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate_fn)
val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)

# Create SimpleCoT LLM client using the SAME HookedTransformer model
# This way we use one model for both processing and training
from src.reasoning.simple_cot.llm_client import HookedTransformerLLMClient
shared_llm_client = HookedTransformerLLMClient(model=model)

def save_checkpoint(epoch, batch_idx, baseline_probe, attention_probe, baseline_optimizer, attention_optimizer, is_last=False):
    """Save training checkpoint"""
    checkpoint = {
        'epoch': epoch,
        'batch_idx': batch_idx,
        'baseline_probe_state': baseline_probe.state_dict(),
        'attention_probe_state': attention_probe.state_dict(),
        'baseline_optimizer_state': baseline_optimizer.state_dict(),
        'attention_optimizer_state': attention_optimizer.state_dict(),
    }
    path = checkpoint_path if is_last else os.path.join(checkpoint_dir, f"checkpoint_epoch_{epoch}_batch_{batch_idx}.pt")
    torch.save(checkpoint, path)


#%%
# Training Loop
# Only execute if this cell is explicitly run (not on import)
# When imported, __name__ will be the module name, not "__main__"
if __name__ == "__main__":
    print("\nStarting training...")
    if start_epoch > 0 or start_batch > 0:
        print(f"Resuming from epoch {start_epoch + 1}, batch {start_batch + 1}")

    for epoch in range(start_epoch, NUM_EPOCHS):
        print(f"\nEpoch {epoch + 1}/{NUM_EPOCHS}")
    
    baseline_probe.train()
    attention_probe.train()
    
    train_baseline_losses = []
    train_attention_losses = []
    
    # Initialize gradient accumulation counter (reset each epoch)
    accumulation_counter = 0
    weight_update_count = 0  # Track number of weight updates for save interval
    accumulated_csv_rows = []  # Accumulate CSV rows across gradient accumulation period
    
    # Skip batches if resuming mid-epoch
    batch_start = start_batch if epoch == start_epoch else 0
    if batch_start > 0:
        print(f"Skipping first {batch_start} batches in this epoch...")
        train_iter = iter(train_loader)
        for _ in range(batch_start):
            next(train_iter, None)
        batches = enumerate(train_iter, start=batch_start)
    else:
        batches = enumerate(train_loader)
    
    for batch_idx, batch in tqdm(batches, desc="Training", total=len(train_loader) if batch_start == 0 else None):
        # Process examples on-the-fly: run SimpleCoT to get chain of thought and answer
        batch_full_texts = []
        batch_answer_indices = []
        batch_labels = []
        batch_csv_rows = []
        
        for ex in batch:
            question = ex['question']
            gold_answer = ex['answer']
            gold_supporting_facts = ex.get('supporting_facts', [])
            
            # Build paragraphs from this example's context only
            example_paragraphs = build_paragraphs_from_example(ex)
            
            # Clear cache before processing to free memory for generation
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # Create SimpleCoT instance with shared LLM client (reuses model)
            simple_cot = SimpleCoT(model_name=MODEL_NAME, paragraphs=example_paragraphs, llm_client=shared_llm_client)
            
            # Process question to get chain of thought and answer
            result = simple_cot.process(question)
            
            # Compute correctness label
            f1, _, _ = f1_score(result['answer'], gold_answer)
            correct = 1 if f1 >= 0.5 else 0
            batch_labels.append(correct)
            
            # Compute recall
            recall = calculate_recall(result['retrieved_paragraphs'], gold_supporting_facts)
            
            # Extract gold sentences
            gold_sentences = []
            for fact in gold_supporting_facts:
                if len(fact) >= 2:
                    title = fact[0]
                    sent_idx = fact[1]
                    for para in ex.get('context', []):
                        if len(para) >= 2 and para[0] == title and sent_idx < len(para[1]):
                            gold_sentences.append(para[1][sent_idx])
            
            # Format CSV row
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
            csv_row['epoch'] = epoch + 1
            csv_row['batch_idx'] = batch_idx
            batch_csv_rows.append(csv_row)
            
            # Build prompt with paragraphs, question, CoT, and answer
            from src.reasoning.simple_cot.prompts import build_answer_prompt
            prompt = build_answer_prompt(result['retrieved_paragraphs'], question, result['chain_of_thought'])
            
            full_text = prompt + " " + result['answer']
            batch_full_texts.append(full_text)
            
            answer_idx = get_answer_token_index(tokenizer, prompt, result['answer'])
            batch_answer_indices.append(answer_idx)
            
            # Clear SimpleCoT instance and result to free memory
            del simple_cot, result, example_paragraphs
        
        # Clear cache periodically after processing batch examples
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        batch_labels = torch.tensor(batch_labels, dtype=torch.float32).to(model.cfg.device)
        
        # Accumulate CSV rows for later saving (we'll save when weights are updated)
        accumulated_csv_rows.extend(batch_csv_rows)
        
        # Aggressive memory clearing before forward pass
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        max_len = max(len(tokenizer.encode(t, add_special_tokens=False)) for t in batch_full_texts)
        max_len = min(max_len, MAX_SEQ_LEN)
        
        tokenized = tokenizer(
            batch_full_texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_len
        ).to(model.cfg.device)
        
        # Clear batch_full_texts before forward pass to free memory
        del batch_full_texts
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        with torch.no_grad():
            _, cache = model.run_with_cache(
                tokenized.input_ids,
                return_type=None
            )
        
        hidden_states_list = []
        for layer_idx in range(num_layers):
            layer_key = f"blocks.{layer_idx}.hook_resid_post"
            if layer_key in cache:
                # Detach and clone to avoid keeping reference to cache
                hidden_states_list.append(cache[layer_key].detach().clone())
            else:
                hidden_states_list.append(torch.zeros(
                    (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                    dtype=torch.float32,
                    device=model.cfg.device
                ))
        
        # Clear cache and tokenized tensors to free memory
        del cache, tokenized
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        hidden_states = torch.stack(hidden_states_list, dim=1)
        del hidden_states_list
        
        answer_indices = torch.tensor(batch_answer_indices, device=model.cfg.device)
        
        batch_size_actual = hidden_states.shape[0]
        seq_len_actual = hidden_states.shape[2]
        
        if batch_size_actual != len(batch_labels):
            batch_labels = batch_labels[:batch_size_actual]
            answer_indices = answer_indices[:batch_size_actual]
        
        answer_indices = torch.clamp(answer_indices, 0, seq_len_actual - 1)
        
        # Zero gradients only on the first accumulation step
        if accumulation_counter == 0:
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
        
        # Scale loss by accumulation steps to get average gradient
        total_loss = total_loss / GRADIENT_ACCUMULATION_STEPS
        total_loss.backward()
        
        accumulation_counter += 1
        
        # Update weights only after accumulating gradients over N examples
        if accumulation_counter >= GRADIENT_ACCUMULATION_STEPS:
            baseline_optimizer.step()
            attention_optimizer.step()
            accumulation_counter = 0
            weight_update_count += 1
            
            # Save CSV and checkpoint together when it's a save interval
            # This ensures they stay in sync - both save at the same frequency
            # CSV rows are accumulated across the save interval period
            if weight_update_count % SAVE_INTERVAL_WEIGHT_UPDATES == 0:
                # Save accumulated CSV rows (accumulated across SAVE_INTERVAL_WEIGHT_UPDATES weight updates)
                if accumulated_csv_rows:
                    # Get all possible column names from all accumulated rows
                    all_column_names = sorted(list(set(key for row_dict in accumulated_csv_rows for key in row_dict.keys())))
                    
                    # Create a DataFrame, ensuring all rows have the same columns
                    batch_df = pd.DataFrame(accumulated_csv_rows, columns=all_column_names)
                    
                    file_exists = os.path.exists(results_csv_path) and os.path.getsize(results_csv_path) > 0
                    batch_df.to_csv(results_csv_path, mode='a', header=not file_exists, index=False, quoting=csv.QUOTE_ALL)
                    del batch_df
                    accumulated_csv_rows = []  # Clear after saving
                
                # Save checkpoint
                print(f"  Weight update {weight_update_count} (batch {batch_idx + 1}): Baseline Loss: {baseline_loss.item():.4f}, Attention Loss: {attention_loss.item():.4f}")
                save_checkpoint(epoch, batch_idx, baseline_probe, attention_probe, baseline_optimizer, attention_optimizer, is_last=True)
                print(f"  Checkpoint and CSV saved at weight update {weight_update_count} (batch {batch_idx + 1})")
                if os.path.exists(results_csv_path):
                    try:
                        existing_df = pd.read_csv(results_csv_path, on_bad_lines='skip', engine='python')
                        print(f"  CSV updated: {len(existing_df)} total rows")
                    except Exception:
                        print(f"  CSV updated (could not verify row count)")
        
        train_baseline_losses.append(baseline_loss.item())
        train_attention_losses.append(attention_loss.item())
        
        # Clear intermediate tensors to free memory
        del hidden_states, baseline_logits, attention_logits, total_loss
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    
    # Handle any remaining accumulated gradients at the end of the epoch
    if accumulation_counter > 0:
        baseline_optimizer.step()
        attention_optimizer.step()
        accumulation_counter = 0
        weight_update_count += 1
        
        # Save any remaining accumulated CSV rows
        if accumulated_csv_rows:
            # Get all possible column names from all accumulated rows
            all_column_names = sorted(list(set(key for row_dict in accumulated_csv_rows for key in row_dict.keys())))
            
            # Create a DataFrame, ensuring all rows have the same columns
            batch_df = pd.DataFrame(accumulated_csv_rows, columns=all_column_names)
            
            file_exists = os.path.exists(results_csv_path) and os.path.getsize(results_csv_path) > 0
            batch_df.to_csv(results_csv_path, mode='a', header=not file_exists, index=False, quoting=csv.QUOTE_ALL)
            del batch_df
            accumulated_csv_rows = []
    
    # Reset start_batch after first epoch
    start_batch = 0
    
    print(f"Epoch {epoch + 1} - Avg Baseline Loss: {np.mean(train_baseline_losses):.4f}, Avg Attention Loss: {np.mean(train_attention_losses):.4f}")
    
    #%%
    # Validation Loop (runs after each epoch)
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
            # Process examples on-the-fly for validation
            batch_full_texts = []
            batch_answer_indices = []
            batch_labels = []
            
            for ex in batch:
                question = ex['question']
                gold_answer = ex['answer']
                
                # Build paragraphs from this example's context only
                example_paragraphs = build_paragraphs_from_example(ex)
                
                # Clear cache before processing to free memory for generation
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                
                # Create SimpleCoT instance with shared LLM client
                simple_cot = SimpleCoT(model_name=MODEL_NAME, paragraphs=example_paragraphs, llm_client=shared_llm_client)
                
                # Process question to get chain of thought and answer
                result = simple_cot.process(question)
                
                # Compute correctness label
                f1, _, _ = f1_score(result['answer'], gold_answer)
                correct = 1 if f1 >= 0.5 else 0
                batch_labels.append(correct)
                
                # Build prompt
                from src.reasoning.simple_cot.prompts import build_answer_prompt
                prompt = build_answer_prompt(result['retrieved_paragraphs'], question, result['chain_of_thought'])
                
                full_text = prompt + " " + result['answer']
                batch_full_texts.append(full_text)
                
                answer_idx = get_answer_token_index(tokenizer, prompt, result['answer'])
                batch_answer_indices.append(answer_idx)
                
                # Clear SimpleCoT instance and result to free memory
                del simple_cot, result, example_paragraphs
            
            # Clear cache periodically after processing batch examples
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            batch_labels = torch.tensor(batch_labels, dtype=torch.float32).to(model.cfg.device)
            
            # Aggressive memory clearing before forward pass
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            
            max_len = max(len(tokenizer.encode(t, add_special_tokens=False)) for t in batch_full_texts)
            max_len = min(max_len, MAX_SEQ_LEN)
            
            tokenized = tokenizer(
                batch_full_texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=max_len
            ).to(model.cfg.device)
            
            # Clear batch_full_texts before forward pass to free memory
            del batch_full_texts
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            _, cache = model.run_with_cache(
                tokenized.input_ids,
                return_type=None
            )
            
            hidden_states_list = []
            for layer_idx in range(num_layers):
                layer_key = f"blocks.{layer_idx}.hook_resid_post"
                if layer_key in cache:
                    # Detach and clone to avoid keeping reference to cache
                    hidden_states_list.append(cache[layer_key].detach().clone())
                else:
                    hidden_states_list.append(torch.zeros(
                        (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                        dtype=torch.float32,
                        device=model.cfg.device
                    ))
            
            # Clear cache and tokenized tensors to free memory
            del cache, tokenized, batch_full_texts
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            hidden_states = torch.stack(hidden_states_list, dim=1)
            del hidden_states_list
            
            answer_indices = torch.tensor(batch_answer_indices, device=model.cfg.device)
            
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
            
            # Clear intermediate tensors to free memory
            del hidden_states, baseline_logits, attention_logits
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    
    #%%
    # Compute and Save Metrics
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
    
    baseline_df.to_csv(os.path.join(OUTPUT_DIR, f"baseline_probe_metrics_epoch_{epoch + 1}.csv"), index=False)
    attention_df.to_csv(os.path.join(OUTPUT_DIR, f"attention_probe_metrics_epoch_{epoch + 1}.csv"), index=False)
    
    # Save checkpoint after each epoch
    save_checkpoint(epoch, len(train_loader) - 1, baseline_probe, attention_probe, baseline_optimizer, attention_optimizer, is_last=True)
    
    print(f"Saved metrics for epoch {epoch + 1}")
    print(f"Baseline - Best Layer AUC: {baseline_df['auc'].max():.4f} (Layer {baseline_df.loc[baseline_df['auc'].idxmax(), 'layer']})")
    print(f"Attention - Best Layer AUC: {attention_df['auc'].max():.4f} (Layer {attention_df.loc[attention_df['auc'].idxmax(), 'layer']})")
    print(f"Checkpoint saved after epoch {epoch + 1}")

    print("\nTraining complete!")
    print(f"Results saved to {OUTPUT_DIR}")
    print(f"Final checkpoint saved to {checkpoint_path}")

# %%
