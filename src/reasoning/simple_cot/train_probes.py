#%%
# Setup Python Path
import sys
from pathlib import Path

# Add project root to path so we can import src modules
try:
    project_root = Path(__file__).parent.parent.parent.parent
except NameError:
    project_root = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

#%%
# Imports and Setup
import os
import csv
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from typing import List, Dict, Any
from tqdm import tqdm
import numpy as np
from transformer_lens import HookedTransformer

from src.reasoning.simple_cot.probes import BaselineProbe, AttentionHeadProbe

#%%
# Configuration
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
OUTPUT_DIR = str(project_root / "outputs" / "simple_cot")
TRAIN_CSV_PATH = os.path.join(OUTPUT_DIR, "train_dataset.csv")
VAL_CSV_PATH = os.path.join(OUTPUT_DIR, "val_dataset.csv")

BATCH_SIZE = 1
GRADIENT_ACCUMULATION_STEPS = 16
NUM_EPOCHS = 3
LEARNING_RATE = 1e-4
MAX_SEQ_LEN = 512
SAVE_INTERVAL_WEIGHT_UPDATES = 1

#%%
# Helper Classes
class TextDataset(Dataset):
    """Dataset that reads from CSV with pre-generated text."""
    def __init__(self, csv_path: str):
        self.df = pd.read_csv(csv_path, on_bad_lines='skip', engine='python')
    
    def __len__(self):
        return len(self.df)
    
    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        return {
            'full_text': row['full_text'],
            'correct': int(row['correct']),
            'question': row.get('question', ''),
            'answer': row.get('answer', ''),
            'prompt': row.get('prompt', ''),  # Include prompt for answer token index calculation
        }

def collate_fn(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Custom collate function that just returns the list of dictionaries as-is."""
    return batch

def get_answer_token_index(tokenizer, prompt: str, answer: str) -> int:
    """Get the token index where the answer ends in the full text."""
    full_text = prompt + " " + answer
    prompt_tokens = tokenizer.encode(prompt, add_special_tokens=False)
    full_tokens = tokenizer.encode(full_text, add_special_tokens=False)
    
    if len(full_tokens) <= len(prompt_tokens):
        return len(prompt_tokens) - 1
    
    answer_end_idx = len(full_tokens) - 1
    return answer_end_idx

#%%
# Load Model
print("\nLoading model with TransformerLens...")
model = HookedTransformer.from_pretrained(MODEL_NAME, device="cuda" if torch.cuda.is_available() else "cpu")
model.eval()

for param in model.parameters():
    param.requires_grad = False

tokenizer = model.tokenizer
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

d_model = model.cfg.d_model
num_layers = model.cfg.n_layers

print(f"Model: {MODEL_NAME}")
print(f"d_model: {d_model}, num_layers: {num_layers}")

#%%
# Load Datasets
print("\nLoading datasets from CSV...")
train_dataset = TextDataset(TRAIN_CSV_PATH)
val_dataset = TextDataset(VAL_CSV_PATH)

train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate_fn)
val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)

print(f"Loaded {len(train_dataset)} train and {len(val_dataset)} val examples")

#%%
# Setup Checkpoints, Probes, and Optimizers
checkpoint_dir = os.path.join(OUTPUT_DIR, "checkpoints")
os.makedirs(checkpoint_dir, exist_ok=True)
checkpoint_path = os.path.join(checkpoint_dir, "checkpoint.pt")
results_csv_path = os.path.join(OUTPUT_DIR, "probe_training_results.csv")

# Initialize or load checkpoints
start_epoch = 0
start_batch = 0

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
        
        accumulation_counter = 0
        weight_update_count = 0
        accumulated_csv_rows = []
        
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
            # Extract full texts and labels from pre-generated dataset
            batch_full_texts = []
            batch_labels = []
            batch_answer_indices = []
            
            for ex in batch:
                full_text = ex['full_text']
                correct = ex['correct']
                
                batch_full_texts.append(full_text)
                batch_labels.append(correct)
                
                # Extract prompt and answer to find answer token index
                prompt = ex.get('prompt', '')  # Use prompt from CSV if available
                answer = ex.get('answer', '')
                
                # If prompt is in CSV, use it; otherwise extract from full_text
                if not prompt and answer:
                    # Try to find answer in full_text and extract prompt
                    if answer in full_text:
                        prompt = full_text[:full_text.rfind(answer)].strip()
                    else:
                        # Fallback: use full_text as prompt, answer at end
                        prompt = full_text
                
                # Get answer token index
                if prompt and answer:
                    answer_idx = get_answer_token_index(tokenizer, prompt, answer)
                else:
                    # Fallback: use last token
                    tokens = tokenizer.encode(full_text, add_special_tokens=False)
                    answer_idx = len(tokens) - 1
                
                batch_answer_indices.append(answer_idx)
            
            batch_labels = torch.tensor(batch_labels, dtype=torch.float32).to(model.cfg.device)
            
            # Clear cache before forward pass
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            
            # Tokenize full texts
            max_len = max(len(tokenizer.encode(t, add_special_tokens=False)) for t in batch_full_texts)
            max_len = min(max_len, MAX_SEQ_LEN)
            
            tokenized = tokenizer(
                batch_full_texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=max_len
            ).to(model.cfg.device)
            
            # Clear batch_full_texts before forward pass
            del batch_full_texts
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # Run model once with cache to get activations
            with torch.no_grad():
                _, cache = model.run_with_cache(
                    tokenized.input_ids,
                    return_type=None
                )
            
            # Extract hidden states for all layers
            hidden_states_list = []
            for layer_idx in range(num_layers):
                layer_key = f"blocks.{layer_idx}.hook_resid_post"
                if layer_key in cache:
                    hidden_states_list.append(cache[layer_key].detach().clone())
                else:
                    hidden_states_list.append(torch.zeros(
                        (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                        dtype=torch.float32,
                        device=model.cfg.device
                    ))
            
            # Clear cache and tokenized tensors
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
            
            # Forward pass through probes
            baseline_logits = baseline_probe(hidden_states, answer_indices)
            attention_logits = attention_probe(hidden_states)
            
            # Compute losses for all layers
            baseline_loss = 0.0
            attention_loss = 0.0
            
            for layer_idx in range(num_layers):
                baseline_loss += criterion(baseline_logits[:, layer_idx, 0], batch_labels)
                attention_loss += criterion(attention_logits[:, layer_idx], batch_labels)
            
            baseline_loss = baseline_loss / num_layers
            attention_loss = attention_loss / num_layers
            
            total_loss = baseline_loss + attention_loss
            
            # Scale loss by accumulation steps
            total_loss = total_loss / GRADIENT_ACCUMULATION_STEPS
            total_loss.backward()
            
            accumulation_counter += 1
            
            # Update weights after accumulating gradients
            if accumulation_counter >= GRADIENT_ACCUMULATION_STEPS:
                baseline_optimizer.step()
                attention_optimizer.step()
                accumulation_counter = 0
                weight_update_count += 1
                
                # Save checkpoint and results
                if weight_update_count % SAVE_INTERVAL_WEIGHT_UPDATES == 0:
                    # Save checkpoint
                    print(f"  Weight update {weight_update_count} (batch {batch_idx + 1}): Baseline Loss: {baseline_loss.item():.4f}, Attention Loss: {attention_loss.item():.4f}")
                    save_checkpoint(epoch, batch_idx, baseline_probe, attention_probe, baseline_optimizer, attention_optimizer, is_last=True)
                    print(f"  Checkpoint saved at weight update {weight_update_count} (batch {batch_idx + 1})")
            
            train_baseline_losses.append(baseline_loss.item())
            train_attention_losses.append(attention_loss.item())
            
            # Clear intermediate tensors
            del hidden_states, baseline_logits, attention_logits, total_loss
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        # Handle any remaining accumulated gradients at the end of the epoch
        if accumulation_counter > 0:
            baseline_optimizer.step()
            attention_optimizer.step()
            accumulation_counter = 0
            weight_update_count += 1
            
            save_checkpoint(epoch, len(train_loader) - 1, baseline_probe, attention_probe, baseline_optimizer, attention_optimizer, is_last=True)
            print(f"  End of epoch: Leftover gradients applied. Weight update {weight_update_count}.")
        
        # Reset start_batch after first epoch
        start_batch = 0
        
        print(f"Epoch {epoch + 1} - Avg Baseline Loss: {np.mean(train_baseline_losses):.4f}, Avg Attention Loss: {np.mean(train_attention_losses):.4f}")
        
        #%%
        # Validation Loop
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
                batch_full_texts = []
                batch_labels = []
                batch_answer_indices = []
                
                for ex in batch:
                    full_text = ex['full_text']
                    correct = ex['correct']
                    
                    batch_full_texts.append(full_text)
                    batch_labels.append(correct)
                    
                    # Extract prompt and answer
                    prompt = ex.get('prompt', '')
                    answer = ex.get('answer', '')
                    
                    # If prompt is in CSV, use it; otherwise extract from full_text
                    if not prompt and answer:
                        if answer in full_text:
                            prompt = full_text[:full_text.rfind(answer)].strip()
                        else:
                            prompt = full_text
                    
                    # Get answer token index
                    if prompt and answer:
                        answer_idx = get_answer_token_index(tokenizer, prompt, answer)
                    else:
                        tokens = tokenizer.encode(full_text, add_special_tokens=False)
                        answer_idx = len(tokens) - 1
                    
                    batch_answer_indices.append(answer_idx)
                
                batch_labels = torch.tensor(batch_labels, dtype=torch.float32).to(model.cfg.device)
                
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
                        hidden_states_list.append(cache[layer_key].detach().clone())
                    else:
                        hidden_states_list.append(torch.zeros(
                            (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                            dtype=torch.float32,
                            device=model.cfg.device
                        ))
                
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
        
        save_checkpoint(epoch, len(train_loader) - 1, baseline_probe, attention_probe, baseline_optimizer, attention_optimizer, is_last=True)
        
        print(f"Saved metrics for epoch {epoch + 1}")
        print(f"Baseline - Best Layer AUC: {baseline_df['auc'].max():.4f} (Layer {baseline_df.loc[baseline_df['auc'].idxmax(), 'layer']})")
        print(f"Attention - Best Layer AUC: {attention_df['auc'].max():.4f} (Layer {attention_df.loc[attention_df['auc'].idxmax(), 'layer']})")
        print(f"Checkpoint saved after epoch {epoch + 1}")

    print("\nTraining complete!")
    print(f"Results saved to {OUTPUT_DIR}")
    print(f"Final checkpoint saved to {checkpoint_path}")

# %%

