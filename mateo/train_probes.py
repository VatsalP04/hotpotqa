#%%
# Setup Python Path
import sys
from pathlib import Path

# Add project root to path so we can import modules
try:
    project_root = Path(__file__).parent.parent
except NameError:
    project_root = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

#%%
# Imports and Setup
import os
import json
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from typing import List, Dict, Any
from tqdm import tqdm
import numpy as np
from transformer_lens import HookedTransformer
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score, f1_score as sklearn_f1

from mateo.probes import BaselineProbe, AttentionHeadProbe

#%%
# Configuration
MODEL_NAME = "meta-llama/Llama-3.2-1B-Instruct"
OUTPUT_DIR = str(project_root / "outputs" / "mateo")
JSON_DATASET_PATH = str(project_root / "mateo" / "training_datasets" / "decomposition_dataset.json")

BATCH_SIZE = 32
GRADIENT_ACCUMULATION_STEPS = 1
NUM_EPOCHS = 1
LEARNING_RATE = 1e-5
MAX_SEQ_LEN = 512
SAVE_INTERVAL_WEIGHT_UPDATES = 1

#%%
# Helper Classes
def balance_dataset_classes(items: List[tuple], label_key: str = 'correct', random_seed: int = 42) -> List[tuple]:
    """Balance classes by downsampling the majority class.
    
    Args:
        items: List of (item_id, item_data) tuples
        label_key: Key to use for labels ('correct' or 'recall')
        random_seed: Random seed for reproducibility
    
    Returns:
        Balanced list of items
    """
    import random
    random.seed(random_seed)
    np.random.seed(random_seed)
    
    # Extract labels
    if label_key == 'recall':
        # For recall, convert to binary: 1 if recall == 1.0, else 0
        labels = [1 if item_data.get('recall', 0) == 1.0 else 0 for _, item_data in items]
    else:
        labels = [int(item_data.get(label_key, 0)) for _, item_data in items]
    
    # Separate by class
    class_0_indices = [i for i, label in enumerate(labels) if label == 0]
    class_1_indices = [i for i, label in enumerate(labels) if label == 1]
    
    # Find minority class size
    min_size = min(len(class_0_indices), len(class_1_indices))
    
    # Downsample majority class
    if len(class_0_indices) > min_size:
        class_0_indices = random.sample(class_0_indices, min_size)
    if len(class_1_indices) > min_size:
        class_1_indices = random.sample(class_1_indices, min_size)
    
    # Combine and shuffle
    balanced_indices = class_0_indices + class_1_indices
    random.shuffle(balanced_indices)
    
    return [items[i] for i in balanced_indices]

class JSONDataset(Dataset):
    """Dataset that reads from JSON with decomposition data."""
    def __init__(self, json_path: str, split: str = "train", train_ratio: float = 0.8,
                 filter_recall_one: bool = False, balance_classes: bool = False,
                 balance_on_recall: bool = False, variation: str = "answer_balanced"):
        """
        Args:
            json_path: Path to the JSON dataset file
            split: "train" or "val"
            train_ratio: Ratio of data to use for training (rest for validation)
            filter_recall_one: If True, only include items where recall == 1.0
            balance_classes: If True, balance classes by downsampling majority
            balance_on_recall: If True, balance on recall labels (else on correct labels)
            variation: One of "answer_balanced", "answer_balanced_recall1", "recall_balanced"
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        # Convert dict to list of items
        items = list(self.data.items())
        
        # Apply variation-specific settings
        if variation == "answer_balanced":
            filter_recall_one = False
            balance_classes = True
            balance_on_recall = False
        elif variation == "answer_balanced_recall1":
            filter_recall_one = True
            balance_classes = True
            balance_on_recall = False
        elif variation == "recall_balanced":
            filter_recall_one = False
            balance_classes = True
            balance_on_recall = True
        
        # Filter by recall if needed
        if filter_recall_one:
            items = [(item_id, item_data) for item_id, item_data in items 
                    if item_data.get('recall', 0) == 1.0]
        
        # Split into train/val
        split_idx = int(len(items) * train_ratio)
        if split == "train":
            self.items = items[:split_idx]
        else:
            self.items = items[split_idx:]
        
        # Balance classes if requested
        if balance_classes:
            label_key = 'recall' if balance_on_recall else 'correct'
            self.items = balance_dataset_classes(self.items, label_key=label_key, random_seed=42)
        
        self.variation = variation
    
    def __len__(self):
        return len(self.items)
    
    def __getitem__(self, idx):
        item_id, item_data = self.items[idx]
        
        question = item_data.get('question', '')
        answer = item_data.get('answer', '')
        correct = int(item_data.get('correct', 0))
        recall = float(item_data.get('recall', 0.0))
        subqueries = item_data.get('subqueries', {})
        
        # Construct context from subqueries, including subquery strings
        # Format: subquery_1 + context_1 + subquery_2 + context_2 + ...
        subquery_context_parts = []
        for subquery, context_list in subqueries.items():
            subquery_context_parts.append(subquery)
            # Join context sentences for this subquery
            context_text = " ".join(context_list)
            subquery_context_parts.append(context_text)
        
        # Join all subquery-context pairs with double newlines
        context_text = "\n\n".join(subquery_context_parts)
        
        # Construct prompt (question + subqueries with context, without answer)
        prompt = f"Question: {question}\n\n{context_text}\n\nAnswer:"
        
        # Construct full_text (prompt + answer)
        full_text = f"{prompt} {answer}"
        
        # Determine label based on variation
        if self.variation == "recall_balanced":
            label = 1 if recall == 1.0 else 0
        else:
            label = correct
        
        return {
            'full_text': full_text,
            'correct': correct,
            'recall': recall,
            'label': label,  # The label to predict (varies by variation)
            'question': question,
            'answer': answer,
            'prompt': prompt,
            'item_id': item_id,
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
device = "cuda" if torch.cuda.is_available() else "cpu"
model = HookedTransformer.from_pretrained(
    MODEL_NAME,
    device=device,
    dtype="bfloat16" if device == "cuda" else "float32",
)
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
# Load Datasets for all 3 variations
print("\nLoading datasets from JSON...")
variations = ["answer_balanced", "answer_balanced_recall1", "recall_balanced"]

train_datasets = {}
val_datasets = {}
train_loaders = {}
val_loaders = {}

for variation in variations:
    train_datasets[variation] = JSONDataset(JSON_DATASET_PATH, split="train", variation=variation)
    val_datasets[variation] = JSONDataset(JSON_DATASET_PATH, split="val", variation=variation)
    train_loaders[variation] = DataLoader(train_datasets[variation], batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate_fn)
    val_loaders[variation] = DataLoader(val_datasets[variation], batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)
    print(f"Variation '{variation}': {len(train_datasets[variation])} train, {len(val_datasets[variation])} val examples")

#%%
# Setup Checkpoints, Probes, and Optimizers
checkpoint_dir = os.path.join(OUTPUT_DIR, "checkpoints")
os.makedirs(checkpoint_dir, exist_ok=True)
checkpoint_path = os.path.join(checkpoint_dir, "checkpoint.pt")
results_csv_path = os.path.join(OUTPUT_DIR, "probe_training_results.csv")

# Initialize or load checkpoints for all 6 probes (2 types × 3 variations)
start_epoch = 0
start_batch = 0

# Initialize all probes and optimizers (one per layer per probe per variation)
probes = {}
optimizers = {}

for probe_type in ['baseline', 'attention']:
    for variation in variations:
        # Create one probe per variation (contains all layers)
        key = f"{probe_type}_{variation}"
        if probe_type == 'baseline':
            probes[key] = BaselineProbe(d_model, num_layers).to(model.cfg.device)
        else:
            probes[key] = AttentionHeadProbe(d_model, num_layers).to(model.cfg.device)
        
        # Create separate optimizer for each layer
        for layer_idx in range(num_layers):
            layer_key = f"{key}_layer_{layer_idx}"
            if probe_type == 'baseline':
                # Get only the parameters for this layer's classifier
                layer_params = list(probes[key].classifiers[layer_idx].parameters())
            else:
                # Get only the parameters for this layer (q and v vectors)
                layer_params = [probes[key].q_vectors[layer_idx], probes[key].v_vectors[layer_idx]]
            optimizers[layer_key] = torch.optim.Adam(layer_params, lr=LEARNING_RATE)

if os.path.exists(checkpoint_path):
    print(f"Found checkpoint at {checkpoint_path}, loading...")
    checkpoint = torch.load(checkpoint_path, map_location=model.cfg.device)
    start_epoch = checkpoint['epoch']
    start_batch = checkpoint.get('batch_idx', 0)
    
    # Load probe states if they exist
    for probe_type in ['baseline', 'attention']:
        for variation in variations:
            key = f"{probe_type}_{variation}"
            state_key = f"{key}_state"
            
            if state_key in checkpoint:
                probes[key].load_state_dict(checkpoint[state_key])
            
            # Load layer-specific optimizers
            for layer_idx in range(num_layers):
                layer_key = f"{key}_layer_{layer_idx}"
                opt_key = f"{layer_key}_optimizer_state"
                if opt_key in checkpoint:
                    optimizers[layer_key].load_state_dict(checkpoint[opt_key])
    
    # Backward compatibility: load old single probe format
    if 'baseline_probe_state' in checkpoint and 'answer_balanced' not in str(checkpoint.keys()):
        print("Loading old checkpoint format, converting to new format...")
        probes['baseline_answer_balanced'].load_state_dict(checkpoint['baseline_probe_state'])
        probes['attention_answer_balanced'].load_state_dict(checkpoint['attention_probe_state'])
        # For old format, we can't load layer-specific optimizers, so they'll start fresh
    
    print(f"Resuming from epoch {start_epoch + 1}, batch {start_batch + 1}")
else:
    print("No checkpoint found, starting from scratch")

criterion = nn.BCEWithLogitsLoss()

def load_probes_from_checkpoint(checkpoint_path=None, output_dir=None, model=None, device=None):
    """Load all probes from checkpoint file. Useful after restarting kernel.
    
    Args:
        checkpoint_path: Path to checkpoint file (defaults to OUTPUT_DIR/checkpoints/checkpoint.pt)
        output_dir: Output directory (defaults to OUTPUT_DIR)
        model: Model object (needed for device info)
        device: Device to load probes to (defaults to model.cfg.device or 'cuda'/'cpu')
    
    Returns:
        Dictionary of probes keyed by probe name
    """
    if checkpoint_path is None:
        if output_dir is None:
            output_dir = OUTPUT_DIR
        checkpoint_path = os.path.join(output_dir, "checkpoints", "checkpoint.pt")
    
    if not os.path.exists(checkpoint_path):
        print(f"Checkpoint not found at {checkpoint_path}")
        return None
    
    # Determine device
    if device is None:
        if model is not None:
            device = model.cfg.device
        else:
            device = "cuda" if torch.cuda.is_available() else "cpu"
    
    print(f"Loading probes from {checkpoint_path}")
    checkpoint = torch.load(checkpoint_path, map_location=device)
    
    # Get model dimensions
    if model is not None:
        d_model = model.cfg.d_model
        num_layers = model.cfg.n_layers
    else:
        d_model = globals().get('d_model')
        num_layers = globals().get('num_layers')
        if d_model is None or num_layers is None:
            raise ValueError("Need model object or d_model/num_layers to be defined")
    
    # Load all probes
    loaded_probes = {}
    variations = ["answer_balanced", "answer_balanced_recall1", "recall_balanced"]
    
    for probe_type in ['baseline', 'attention']:
        for variation in variations:
            key = f"{probe_type}_{variation}"
            state_key = f"{key}_state"
            
            if probe_type == 'baseline':
                probe = BaselineProbe(d_model, num_layers).to(device)
            else:
                probe = AttentionHeadProbe(d_model, num_layers).to(device)
            
            if state_key in checkpoint:
                probe.load_state_dict(checkpoint[state_key])
                loaded_probes[key] = probe
            else:
                # Backward compatibility: try old format
                if key == 'baseline_answer_balanced' and 'baseline_probe_state' in checkpoint:
                    probe.load_state_dict(checkpoint['baseline_probe_state'])
                    loaded_probes[key] = probe
                elif key == 'attention_answer_balanced' and 'attention_probe_state' in checkpoint:
                    probe.load_state_dict(checkpoint['attention_probe_state'])
                    loaded_probes[key] = probe
    
    print(f"Loaded {len(loaded_probes)} probes from epoch {checkpoint['epoch'] + 1}")
    return loaded_probes

def save_checkpoint(epoch, batch_idx, probes, optimizers, num_layers, is_last=False):
    """Save training checkpoint for all probes and layer-specific optimizers"""
    checkpoint = {
        'epoch': epoch,
        'batch_idx': batch_idx,
    }
    
    # Save all probe states (one per variation)
    for key in probes:
        checkpoint[f"{key}_state"] = probes[key].state_dict()
    
    # Save all layer-specific optimizer states
    for key in optimizers:
        checkpoint[f"{key}_optimizer_state"] = optimizers[key].state_dict()
    
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
        
        # Set all probes to training mode
        for probe in probes.values():
            probe.train()
        
        # Track losses for all layer-probe combinations
        train_losses = {}
        accumulation_counters = {}
        
        for probe_type in ['baseline', 'attention']:
            for variation in variations:
                for layer_idx in range(num_layers):
                    key = f"{probe_type}_{variation}_layer_{layer_idx}"
                    train_losses[key] = []
                    accumulation_counters[key] = 0
        
        weight_update_count = 0
        
        # Train each variation
        for variation in variations:
            print(f"\nTraining variation: {variation}")
            train_loader = train_loaders[variation]
            
            # Skip batches if resuming mid-epoch (only for first variation)
            batch_start = start_batch if epoch == start_epoch and variation == variations[0] else 0
            if batch_start > 0:
                print(f"Skipping first {batch_start} batches in this epoch...")
                train_iter = iter(train_loader)
                for _ in range(batch_start):
                    next(train_iter, None)
                batches = enumerate(train_iter, start=batch_start)
            else:
                batches = enumerate(train_loader)
            
            for batch_idx, batch in tqdm(batches, desc=f"Training {variation}", total=len(train_loader) if batch_start == 0 else None):
                # Extract full texts and labels from pre-generated dataset
                batch_full_texts = []
                batch_labels = []
                batch_answer_indices = []
                
                for ex in batch:
                    full_text = ex['full_text']
                    label = ex['label']  # Use 'label' which varies by variation
                    
                    batch_full_texts.append(full_text)
                    batch_labels.append(label)
                    
                    # Extract prompt and answer to find answer token index
                    prompt = ex.get('prompt', '')
                    answer = ex.get('answer', '')
                    
                    if not prompt and answer:
                        if answer in full_text:
                            prompt = full_text[:full_text.rfind(answer)].strip()
                        else:
                            prompt = full_text
                    
                    if prompt and answer:
                        answer_idx = get_answer_token_index(tokenizer, prompt, answer)
                    else:
                        tokens = tokenizer.encode(full_text, add_special_tokens=False)
                        answer_idx = len(tokens) - 1
                    
                    batch_answer_indices.append(answer_idx)
                
                batch_labels = torch.tensor(batch_labels, dtype=torch.float32).to(model.cfg.device)
                
                # Tokenize full texts
                tokenized = tokenizer(
                    batch_full_texts,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=MAX_SEQ_LEN,
                ).to(model.cfg.device)
                
                del batch_full_texts
                
                # Run model once with cache to get activations
                with torch.no_grad():
                    _, cache = model.run_with_cache(
                        tokenized.input_ids,
                        return_type=None,
                        names_filter=lambda name: name.endswith("hook_resid_post"),
                    )
                
                # Extract hidden states for all layers
                hidden_states_list = []
                for layer_idx in range(num_layers):
                    layer_key = f"blocks.{layer_idx}.hook_resid_post"
                    if layer_key in cache:
                        hidden_states_list.append(cache[layer_key])
                    else:
                        hidden_states_list.append(torch.zeros(
                            (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                            dtype=torch.bfloat16,
                            device=model.cfg.device
                        ))
                
                del cache, tokenized
                
                hidden_states = torch.stack(hidden_states_list, dim=1)
                del hidden_states_list
                
                hidden_states_for_probes = hidden_states.float()
                
                answer_indices = torch.tensor(batch_answer_indices, device=model.cfg.device)
                
                batch_size_actual = hidden_states_for_probes.shape[0]
                seq_len_actual = hidden_states_for_probes.shape[2]
                
                if batch_size_actual != len(batch_labels):
                    batch_labels = batch_labels[:batch_size_actual]
                    answer_indices = answer_indices[:batch_size_actual]
                
                answer_indices = torch.clamp(answer_indices, 0, seq_len_actual - 1)
                
                # Train each layer-probe combination independently
                for probe_type in ['baseline', 'attention']:
                    probe_key = f"{probe_type}_{variation}"
                    probe = probes[probe_key]
                    
                    # Forward pass to get all layer logits
                    if probe_type == 'baseline':
                        logits = probe(hidden_states_for_probes, answer_indices)
                    else:
                        logits = probe(hidden_states_for_probes)
                    
                    # Train each layer independently
                    for layer_idx in range(num_layers):
                        layer_key = f"{probe_key}_layer_{layer_idx}"
                        optimizer = optimizers[layer_key]
                        
                        # Zero gradients for this layer only
                        if accumulation_counters[layer_key] == 0:
                            optimizer.zero_grad()
                        
                        # Compute loss for this specific layer only
                        if probe_type == 'baseline':
                            layer_logits = logits[:, layer_idx, 0]
                        else:
                            layer_logits = logits[:, layer_idx]
                        
                        loss = criterion(layer_logits, batch_labels)
                        
                        # Scale loss by accumulation steps
                        loss = loss / GRADIENT_ACCUMULATION_STEPS
                        loss.backward(retain_graph=(layer_idx < num_layers - 1))
                        
                        accumulation_counters[layer_key] += 1
                        
                        # Update weights for this layer only
                        if accumulation_counters[layer_key] >= GRADIENT_ACCUMULATION_STEPS:
                            optimizer.step()
                            accumulation_counters[layer_key] = 0
                            weight_update_count += 1
                            
                            if weight_update_count % SAVE_INTERVAL_WEIGHT_UPDATES == 0:
                                print(f"  Weight update {weight_update_count} ({layer_key}): Loss: {loss.item():.4f}")
                        
                        train_losses[layer_key].append(loss.item())
                        
                        del loss
                    
                    del logits
                
                del hidden_states, hidden_states_for_probes
            
            # Handle remaining accumulated gradients for all layer-probe combinations
            for probe_type in ['baseline', 'attention']:
                for variation in variations:
                    for layer_idx in range(num_layers):
                        layer_key = f"{probe_type}_{variation}_layer_{layer_idx}"
                        if accumulation_counters[layer_key] > 0:
                            optimizers[layer_key].step()
                            accumulation_counters[layer_key] = 0
                            weight_update_count += 1
        
        # Save checkpoint after epoch
        save_checkpoint(epoch, 0, probes, optimizers, num_layers, is_last=True)
        
        # Reset start_batch after first epoch
        start_batch = 0
        
        # Print average losses (grouped by probe, showing best layer)
        print(f"\nEpoch {epoch + 1} - Average Losses (showing best layer per probe):")
        for probe_type in ['baseline', 'attention']:
            for variation in variations:
                probe_key = f"{probe_type}_{variation}"
                layer_losses = []
                for layer_idx in range(num_layers):
                    layer_key = f"{probe_key}_layer_{layer_idx}"
                    if train_losses[layer_key]:
                        layer_losses.append((layer_idx, np.mean(train_losses[layer_key])))
                if layer_losses:
                    best_layer, best_loss = min(layer_losses, key=lambda x: x[1])
                    print(f"  {probe_key}: Best Layer {best_layer} - Loss: {best_loss:.4f}")
        
        #%%
        # Validation Loop
        print("\nValidating all probes...")
        
        # Ensure variations is defined (for standalone execution)
        if 'variations' not in globals():
            variations = ["answer_balanced", "answer_balanced_recall1", "recall_balanced"]
        
        # Load probes if they don't exist (for running this cell standalone)
        try:
            _ = probes
        except NameError:
            print("Probes not found, loading from checkpoint...")
            loaded_probes = load_probes_from_checkpoint(model=model)
            if loaded_probes is None:
                raise ValueError("Could not load probes from checkpoint. Please run the setup cells first.")
            probes = loaded_probes
        
        # Load dataloaders if they don't exist (for standalone execution)
        if 'val_loaders' not in globals():
            print("Dataloaders not found, creating...")
            val_loaders = {}
            for variation in variations:
                val_dataset = JSONDataset(JSON_DATASET_PATH, split="val", variation=variation)
                val_loaders[variation] = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn)
        
        # Set all probes to eval mode
        for probe in probes.values():
            probe.eval()
        
        # Track predictions and labels for all layer-probe combinations
        val_predictions = {}
        val_labels = {variation: [] for variation in variations}
        val_losses = {}
        
        for probe_type in ['baseline', 'attention']:
            for variation in variations:
                for layer_idx in range(num_layers):
                    layer_key = f"{probe_type}_{variation}_layer_{layer_idx}"
                    val_predictions[layer_key] = []
                    val_losses[layer_key] = []
        
        # Validate each variation
        for variation in variations:
            print(f"\nValidating variation: {variation}")
            val_loader = val_loaders[variation]
            
            with torch.no_grad():
                for batch in tqdm(val_loader, desc=f"Validating {variation}"):
                    batch_full_texts = []
                    batch_labels = []
                    batch_answer_indices = []
                    
                    for ex in batch:
                        full_text = ex['full_text']
                        label = ex['label']  # Use 'label' which varies by variation
                        
                        batch_full_texts.append(full_text)
                        batch_labels.append(label)
                        
                        prompt = ex.get('prompt', '')
                        answer = ex.get('answer', '')
                        
                        if not prompt and answer:
                            if answer in full_text:
                                prompt = full_text[:full_text.rfind(answer)].strip()
                            else:
                                prompt = full_text
                        
                        if prompt and answer:
                            answer_idx = get_answer_token_index(tokenizer, prompt, answer)
                        else:
                            tokens = tokenizer.encode(full_text, add_special_tokens=False)
                            answer_idx = len(tokens) - 1
                        
                        batch_answer_indices.append(answer_idx)
                    
                    batch_labels = torch.tensor(batch_labels, dtype=torch.float32).to(model.cfg.device)
                    
                    tokenized = tokenizer(
                        batch_full_texts,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                        max_length=MAX_SEQ_LEN,
                    ).to(model.cfg.device)
                    
                    del batch_full_texts
                    
                    _, cache = model.run_with_cache(
                        tokenized.input_ids,
                        return_type=None,
                        names_filter=lambda name: name.endswith("hook_resid_post"),
                    )
                    
                    hidden_states_list = []
                    for layer_idx in range(num_layers):
                        layer_key = f"blocks.{layer_idx}.hook_resid_post"
                        if layer_key in cache:
                            hidden_states_list.append(cache[layer_key])
                        else:
                            hidden_states_list.append(torch.zeros(
                                (tokenized.input_ids.shape[0], tokenized.input_ids.shape[1], d_model),
                                dtype=torch.bfloat16,
                                device=model.cfg.device
                            ))
                    
                    del cache, tokenized
                    
                    hidden_states = torch.stack(hidden_states_list, dim=1)
                    del hidden_states_list
                    
                    hidden_states_for_probes = hidden_states.float()
                    
                    answer_indices = torch.tensor(batch_answer_indices, device=model.cfg.device)
                    
                    batch_size_actual = hidden_states_for_probes.shape[0]
                    seq_len_actual = hidden_states_for_probes.shape[2]
                    
                    if batch_size_actual != len(batch_labels):
                        batch_labels = batch_labels[:batch_size_actual]
                        answer_indices = answer_indices[:batch_size_actual]
                    
                    answer_indices = torch.clamp(answer_indices, 0, seq_len_actual - 1)
                    
                    # Validate each layer-probe combination independently
                    for probe_type in ['baseline', 'attention']:
                        probe_key = f"{probe_type}_{variation}"
                        probe = probes[probe_key]
                        
                        # Forward pass to get all layer logits
                        if probe_type == 'baseline':
                            logits = probe(hidden_states_for_probes, answer_indices)
                        else:
                            logits = probe(hidden_states_for_probes)
                        
                        # Evaluate each layer independently
                        for layer_idx in range(num_layers):
                            layer_key = f"{probe_key}_layer_{layer_idx}"
                            
                            if probe_type == 'baseline':
                                layer_logits = logits[:, layer_idx, 0]
                            else:
                                layer_logits = logits[:, layer_idx]
                            
                            loss = criterion(layer_logits, batch_labels)
                            probs = torch.sigmoid(layer_logits)
                            
                            val_predictions[layer_key].extend(probs.cpu().numpy())
                            val_losses[layer_key].append(loss.item())
                        
                        del logits
                    
                    val_labels[variation].extend(batch_labels.cpu().numpy())
                    del hidden_states, hidden_states_for_probes
        
        #%%
        # Compute and Save Metrics for all probes
        # Get epoch number - try from checkpoint if not defined (for standalone execution)
        if 'epoch' not in locals() and 'epoch' not in globals():
            if os.path.exists(checkpoint_path):
                checkpoint_data = torch.load(checkpoint_path, map_location='cpu')
                epoch = checkpoint_data.get('epoch', 0)
                print(f"Using epoch {epoch + 1} from checkpoint")
            else:
                epoch = 0
                print(f"Epoch not found, using default: {epoch + 1}")
        
        import pandas as pd
        
        # Compute metrics for each layer-probe combination
        for variation in variations:
            val_labels_array = np.array(val_labels[variation])
            
            for probe_type in ['baseline', 'attention']:
                probe_key = f"{probe_type}_{variation}"
                metrics = []
                
                for layer_idx in range(num_layers):
                    layer_key = f"{probe_key}_layer_{layer_idx}"
                    pred = np.array(val_predictions[layer_key])
                    
                    auc = roc_auc_score(val_labels_array, pred)
                    acc = accuracy_score(val_labels_array, (pred >= 0.5).astype(int))
                    prec = precision_score(val_labels_array, (pred >= 0.5).astype(int), zero_division=0)
                    rec = recall_score(val_labels_array, (pred >= 0.5).astype(int), zero_division=0)
                    f1 = sklearn_f1(val_labels_array, (pred >= 0.5).astype(int), zero_division=0)
                    
                    metrics.append({
                        'layer': layer_idx,
                        'auc': auc,
                        'accuracy': acc,
                        'precision': prec,
                        'recall': rec,
                        'f1': f1
                    })
                
                df = pd.DataFrame(metrics)
                filename = f"{probe_key}_metrics_epoch_{epoch + 1}.csv"
                df.to_csv(os.path.join(OUTPUT_DIR, filename), index=False)
                
                print(f"\n{probe_key} - Best Layer AUC: {df['auc'].max():.4f} (Layer {df.loc[df['auc'].idxmax(), 'layer']})")
        
        # Save checkpoint
        save_checkpoint(epoch, 0, probes, optimizers, num_layers, is_last=True)
        print(f"\nCheckpoint saved after epoch {epoch + 1}")

    # print("\nTraining complete!")
    # print(f"Results saved to {OUTPUT_DIR}")
    # print(f"Final checkpoint saved to {checkpoint_path}")

# %%

