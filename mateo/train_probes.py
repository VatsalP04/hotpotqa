"""
train_probes.py

Script to train lightweight probes on Llama-3.1-8B activations for the
HotpotQA decomposition dataset.

Usage:
    python -m mateo.train_probes [mode] [--balance]

Arguments
---------
mode : {"full", "test"}, optional
    - "full" (default): full run with ~3000 examples and 8 layers.
    - "test": tiny smoke test (e.g. 32 examples, 1 layer) to ensure
      everything runs without errors.

--balance : flag, optional
    Deprecated: class balancing is now always applied to the training set.
    This flag is kept for backwards compatibility but has no effect.

Expected runtime on an A100 80GB (rough ballpark):
    - full: ~1–3 minutes with defaults (3k examples, 8 layers, 3 epochs).
    - test: <10 seconds (32 examples, 1 layer, 1 epoch).
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Tuple, Optional

import numpy as np
import torch
from transformer_lens import HookedTransformer
from collections import defaultdict

from mateo.probes import (
    ProbeConfig,
    DenseLinearProbe,
    MassMeanProbe,
)


# Default path; adjust if needed.
JSON_DATASET_PATH = os.path.join(
    "mateo", "training_datasets", "decomposition_dataset.json"
)


def load_hotpot_decomp_dataset(
    json_path: str,
) -> Tuple[Dict[str, List[str]], np.ndarray, np.ndarray]:
    """Load dataset and build context strings + labels.

    Parameters
    ----------
    json_path : str
        Path to the JSON dataset file.

    Returns
    -------
    contexts : dict
        Keys are "planning", "subanswer", "final". Values are lists of context strings.
    y_correct : np.ndarray, shape (N,)
        0/1 labels for answer correctness.
    y_recall_full : np.ndarray, shape (N,)
        1 if recall == 1.0, else 0.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Dataset not found at: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    contexts_planning: List[str] = []
    contexts_subanswer: List[str] = []
    contexts_final: List[str] = []
    correct_labels: List[int] = []
    recall_full_labels: List[int] = []

    for qid, entry in data.items():
        correct = int(entry.get("correct", 0))
        recall = float(entry.get("recall", 0.0))
        recall_full = 1 if abs(recall - 1.0) < 1e-8 else 0

        planning = entry.get("planning", "").strip()
        subanswer_list = entry.get("subanswer", [])
        final = entry.get("final", "").strip()

        # Trim <|eot_id|> if it exists at the end
        if planning.endswith("<|eot_id|>"):
            planning = planning[:-10].rstrip()
        if final.endswith("<|eot_id|>"):
            final = final[:-10].rstrip()

        # For planning and final, use the text directly
        contexts_planning.append(planning)
        contexts_final.append(final)

        # For subanswer, concatenate all subanswers and trim <|eot_id|>
        subanswer_parts = []
        for sa in subanswer_list:
            sa_text = str(sa).strip()
            if sa_text.endswith("<|eot_id|>"):
                sa_text = sa_text[:-10].rstrip()
            if sa_text:
                subanswer_parts.append(sa_text)
        subanswer_text = "\n\n".join(subanswer_parts)
        contexts_subanswer.append(subanswer_text)

        correct_labels.append(correct)
        recall_full_labels.append(recall_full)

    contexts = {
        "planning": contexts_planning,
        "subanswer": contexts_subanswer,
        "final": contexts_final,
    }
    y_correct = np.array(correct_labels, dtype=np.float32)
    y_recall_full = np.array(recall_full_labels, dtype=np.float32)

    return contexts, y_correct, y_recall_full


def make_splits(
    n: int, rng: np.random.Generator
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create train/val/test index splits (70/15/15) after shuffling."""
    indices = np.arange(n)
    rng.shuffle(indices)

    n_train = int(0.7 * n)
    n_val = int(0.15 * n)
    n_test = n - n_train - n_val

    train_idx = indices[:n_train]
    val_idx = indices[n_train : n_train + n_val]
    test_idx = indices[n_train + n_val :]

    return train_idx, val_idx, test_idx


def compute_activations(
    model: "HookedTransformer",
    contexts: List[str],
    layers_to_probe: List[int],
    full_run: bool,
) -> Dict[int, np.ndarray]:
    """Compute hidden activations.

    Parameters
    ----------
    model :
        HookedTransformer instance (Llama-3.1-8B).
    contexts :
        List of input strings.
    layers_to_probe :
        List of layer indices for which to extract resid_post at the final token.
    full_run :
        If False (test mode), we may use slightly larger batch size.

    Returns
    -------
    hidden_per_layer : dict
        layer -> np.ndarray of shape (N, d_model).
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Tokenize each context individually to know exact lengths (no padding).
    print(f"Tokenizing {len(contexts)} examples...")
    tokens_list: List[torch.Tensor] = []
    lengths: List[int] = []
    for text in contexts:
        toks = model.to_tokens(text, prepend_bos=True)  # (1, T)
        toks = toks[0]  # (T,)
        tokens_list.append(toks)
        lengths.append(toks.shape[0])

    n_examples = len(contexts)
    d_model = model.cfg.d_model

    # Preallocate storage on CPU.
    hidden_per_layer: Dict[int, np.ndarray] = {
        layer: np.empty((n_examples, d_model), dtype=np.float32)
        for layer in layers_to_probe
    }

    # Hook names
    hook_names = [f"blocks.{layer}.hook_resid_post" for layer in layers_to_probe]

    def names_filter(name: str) -> bool:
        return name in hook_names

    # Conservative batch size to avoid OOM.
    batch_size = 4 if full_run else 8
    print(
        f"Computing activations for {n_examples} examples "
        f"(batch_size={batch_size}, layers={layers_to_probe})..."
    )

    model.to(device)
    model.eval()

    start = 0
    with torch.no_grad():
        while start < n_examples:
            end = min(start + batch_size, n_examples)
            batch_tokens = tokens_list[start:end]
            batch_lengths = torch.tensor(lengths[start:end], device=device)
            bsz = len(batch_tokens)
            max_len = int(batch_lengths.max().item())

            # Right-pad with arbitrary token id (0); causal mask ensures
            # pads do not influence earlier tokens.
            input_ids = torch.zeros((bsz, max_len), dtype=torch.long, device=device)
            for i, toks in enumerate(batch_tokens):
                L = toks.shape[0]
                input_ids[i, :L] = toks.to(device)

            # Forward with cache
            logits, cache = model.run_with_cache(
                input_ids,
                return_type="logits",
                names_filter=names_filter,
            )

            positions = batch_lengths - 1  # final token index per example
            batch_indices = torch.arange(bsz, device=device)

            # Hidden states per layer (final token)
            for layer in layers_to_probe:
                hook_name = f"blocks.{layer}.hook_resid_post"
                acts = cache[hook_name]  # (bsz, max_len, d_model)
                final_acts = acts[batch_indices, positions, :]  # (bsz, d_model)
                hidden_per_layer[layer][start:end, :] = (
                    final_acts.float().cpu().numpy()
                )

            start = end

            # Free batch cache/logits
            del logits, cache
            if device.type == "cuda":
                torch.cuda.empty_cache()

    return hidden_per_layer


def has_both_classes(y: np.ndarray) -> bool:
    """Return True if y contains both 0 and 1."""
    uniq = np.unique(y)
    return len(uniq) >= 2 and (0.0 in uniq) and (1.0 in uniq)


def calculate_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float, float, float]:
    """Calculate accuracy, precision, recall, and F1 for binary classification.
    
    Parameters
    ----------
    y_true : np.ndarray
        True binary labels (0 or 1).
    y_pred : np.ndarray
        Predicted binary labels (0 or 1).
    
    Returns
    -------
    accuracy : float
        Accuracy score.
    precision : float
        Precision score (TP / (TP + FP)).
    recall : float
        Recall score (TP / (TP + FN)).
    f1 : float
        F1 score (2 * precision * recall / (precision + recall)).
    """
    accuracy = float((y_pred == y_true).mean())
    
    # Calculate TP, FP, FN, TN
    tp = float(((y_pred == 1) & (y_true == 1)).sum())
    fp = float(((y_pred == 1) & (y_true == 0)).sum())
    fn = float(((y_pred == 0) & (y_true == 1)).sum())
    
    # Precision: TP / (TP + FP)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    
    # Recall: TP / (TP + FN)
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    
    # F1: 2 * precision * recall / (precision + recall)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return accuracy, precision, recall, f1


def downsample_balanced(
    indices: np.ndarray, labels: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Downsample indices to balance class distribution.
    
    Parameters
    ----------
    indices : np.ndarray
        Array of indices to downsample from.
    labels : np.ndarray
        Binary labels (0 or 1) corresponding to indices.
    rng : np.random.Generator
        Random number generator for reproducibility.
    
    Returns
    -------
    balanced_indices : np.ndarray
        Downsampled indices with balanced class distribution.
    """
    if len(indices) == 0:
        return indices

    # Get labels for the given indices
    idx_labels = labels[indices]

    # Find indices for each class
    class_0_mask = idx_labels == 0.0
    class_1_mask = idx_labels == 1.0

    class_0_indices = indices[class_0_mask]
    class_1_indices = indices[class_1_mask]

    n_class_0 = len(class_0_indices)
    n_class_1 = len(class_1_indices)

    # If both classes exist, downsample to the smaller class size
    if n_class_0 > 0 and n_class_1 > 0:
        min_size = min(n_class_0, n_class_1)
        if n_class_0 > min_size:
            class_0_indices = rng.choice(class_0_indices, size=min_size, replace=False)
        if n_class_1 > min_size:
            class_1_indices = rng.choice(class_1_indices, size=min_size, replace=False)
        balanced_indices = np.concatenate([class_0_indices, class_1_indices])
        rng.shuffle(balanced_indices)
        return balanced_indices
    else:
        # Only one class exists, return as-is
        return indices


def train_all_probes(
    hidden_per_layer: Dict[int, np.ndarray],
    y_correct: np.ndarray,
    y_recall_full: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    test_idx: np.ndarray,
    layers_to_probe: List[int],
    full_run: bool,
    balance: bool = False,
    rng: Optional[np.random.Generator] = None,
    context_type: str = "planning",
) -> None:
    """Train DenseLinear and MassMean probes on all tasks.
    
    Parameters
    ----------
    balance : bool, default=False
        Deprecated: class balancing is now always applied to the training set.
        This parameter is kept for backwards compatibility but has no effect.
    rng : np.random.Generator, optional
        Random number generator for downsampling. Required for class balancing.
    context_type : str, default="planning"
        Type of context: "planning", "subanswer", or "final".
    
    Note
    ----
    Class balancing is always applied to the training set (not val/test):
    - For "correct" and "correct_given_recall1" tasks: balances based on y_correct.
    - For "recall_full" task: balances based on y_recall_full.
    - The "correct_given_recall1" task only filters to recall=1.0 for the TRAINING set.
    """
    os.makedirs("trained_probes", exist_ok=True)

    if rng is None:
        raise ValueError("rng must be provided for class balancing")

    n = y_correct.shape[0]
    train_mask = np.zeros(n, dtype=bool)
    val_mask = np.zeros(n, dtype=bool)
    test_mask = np.zeros(n, dtype=bool)
    train_mask[train_idx] = True
    val_mask[val_idx] = True
    test_mask[test_idx] = True

    recall1_mask = y_recall_full == 1.0

    tasks = [
        ("correct", y_correct, None),
        ("correct_given_recall1", y_correct, recall1_mask),
        ("recall_full", y_recall_full, None),
    ]

    num_epochs_dense = 3 if full_run else 1
    num_epochs_mass = 50 if full_run else 10

    results: List[Dict[str, object]] = []

    # ---- DenseLinearProbe per layer ----
    print("\n=== Training DenseLinearProbes ===")
    for task_name, y_all, extra_mask in tasks:
        for layer in layers_to_probe:
            X = hidden_per_layer[layer]

            # For correct_given_recall1, only filter training set to recall=1
            # Val and test sets use all examples
            if task_name == "correct_given_recall1" and extra_mask is not None:
                train_m = extra_mask & train_mask
                val_m = val_mask  # Use all val examples
                test_m = test_mask  # Use all test examples
            else:
                base_mask = extra_mask if extra_mask is not None else np.ones(n, dtype=bool)
                train_m = base_mask & train_mask
                val_m = base_mask & val_mask
                test_m = base_mask & test_mask

            if train_m.sum() < 2:
                print(
                    f"[Dense] Skipping layer {layer}, task {task_name}: "
                    f"not enough training examples ({train_m.sum()})."
                )
                continue

            # Always apply class balancing to training set (not val/test)
            if rng is not None:
                train_indices = np.where(train_m)[0]
                # For "correct" tasks, balance based on y_correct
                # For "recall_full" task, balance based on y_recall_full
                if task_name in ("correct", "correct_given_recall1"):
                    balanced_train_indices = downsample_balanced(
                        train_indices, y_correct, rng
                    )
                elif task_name == "recall_full":
                    balanced_train_indices = downsample_balanced(
                        train_indices, y_recall_full, rng
                    )
                else:
                    balanced_train_indices = train_indices

                # Update train_m to only include balanced indices
                train_m_balanced = np.zeros(n, dtype=bool)
                train_m_balanced[balanced_train_indices] = True
                train_m = train_m_balanced

                if train_m.sum() < 2:
                    print(
                        f"[Dense] Skipping layer {layer}, task {task_name}: "
                        f"not enough training examples after balancing ({train_m.sum()})."
                    )
                    continue

            X_train, y_train = X[train_m], y_all[train_m]
            X_val, y_val = (X[val_m], y_all[val_m]) if val_m.sum() > 0 else (None, None)

            cfg = ProbeConfig(
                probe_type="dense_linear",
                layer=layer,
                task_name=task_name,
                use_l1=False,
                l1_lambda=0.0,
            )
            probe = DenseLinearProbe(cfg)
            metrics = probe.fit(
                X_train,
                y_train,
                val_x=X_val,
                val_y=y_val,
                num_epochs=num_epochs_dense,
                lr=1e-3,
                weight_decay=0.0,
                batch_size=256,
                device=None,
                verbose=False,
            )

            test_acc = float("nan")
            test_precision = float("nan")
            test_recall = float("nan")
            test_f1 = float("nan")
            if test_m.sum() > 0:
                X_test, y_test = X[test_m], y_all[test_m]
                probs = probe.predict_proba(X_test)
                preds = (probs >= 0.5).astype(np.float32)
                test_acc, test_precision, test_recall, test_f1 = calculate_metrics(y_test, preds)

            print(
                f"[Dense] Task={task_name:>20} | layer={layer:2d} | "
                f"train_loss={metrics.get('train_loss', float('nan')):.4f} | "
                f"test_acc={test_acc:.3f} | test_prec={test_precision:.3f} | "
                f"test_rec={test_recall:.3f} | test_f1={test_f1:.3f}"
            )

            probe_path = os.path.join(
                "trained_probes", f"dense_layer{layer}_{context_type}_{task_name}.pt"
            )
            probe.save(probe_path)

            results.append(
                {
                    "probe_type": "dense_linear",
                    "context_type": context_type,
                    "task": task_name,
                    "layer": layer,
                    "train_loss": float(metrics.get("train_loss", float("nan"))),
                    "val_loss": float(metrics.get("val_loss", float("nan"))),
                    "test_acc": test_acc,
                    "test_precision": test_precision,
                    "test_recall": test_recall,
                    "test_f1": test_f1,
                }
            )

    # ---- MassMeanProbe per layer ----
    print("\n=== Training MassMeanProbes ===")
    for task_name, y_all, extra_mask in tasks:
        for layer in layers_to_probe:
            X = hidden_per_layer[layer]

            # For correct_given_recall1, only filter training set to recall=1
            # Val and test sets use all examples
            if task_name == "correct_given_recall1" and extra_mask is not None:
                train_m = extra_mask & train_mask
                val_m = val_mask  # Use all val examples
                test_m = test_mask  # Use all test examples
            else:
                base_mask = extra_mask if extra_mask is not None else np.ones(n, dtype=bool)
                train_m = base_mask & train_mask
                val_m = base_mask & val_mask
                test_m = base_mask & test_mask

            # Always apply class balancing to training set (not val/test)
            if rng is not None:
                train_indices = np.where(train_m)[0]
                if task_name in ("correct", "correct_given_recall1"):
                    balanced_train_indices = downsample_balanced(
                        train_indices, y_correct, rng
                    )
                elif task_name == "recall_full":
                    balanced_train_indices = downsample_balanced(
                        train_indices, y_recall_full, rng
                    )
                else:
                    balanced_train_indices = train_indices

                train_m_balanced = np.zeros(n, dtype=bool)
                train_m_balanced[balanced_train_indices] = True
                train_m = train_m_balanced

            X_train, y_train = X[train_m], y_all[train_m]
            X_val, y_val = (X[val_m], y_all[val_m]) if val_m.sum() > 0 else (None, None)

            if X_train.shape[0] < 2 or not has_both_classes(y_train):
                print(
                    f"[MassMean] Skipping layer {layer}, task {task_name}: "
                    f"not enough data or only one class."
                )
                continue

            cfg = ProbeConfig(
                probe_type="mass_mean",
                layer=layer,
                task_name=task_name,
            )
            probe = MassMeanProbe(cfg)
            try:
                metrics = probe.fit(
                    X_train,
                    y_train,
                    val_x=X_val,
                    val_y=y_val,
                    num_epochs=num_epochs_mass,
                    lr=5e-2,
                    device=None,
                    verbose=False,
                )
            except ValueError as e:
                print(
                    f"[MassMean] Error for layer {layer}, task {task_name}: {e}. "
                    "Skipping."
                )
                continue

            test_acc = float("nan")
            test_precision = float("nan")
            test_recall = float("nan")
            test_f1 = float("nan")
            if test_m.sum() > 0:
                X_test, y_test = X[test_m], y_all[test_m]
                probs = probe.predict_proba(X_test)
                preds = (probs >= 0.5).astype(np.float32)
                test_acc, test_precision, test_recall, test_f1 = calculate_metrics(y_test, preds)

            print(
                f"[MassMean] Task={task_name:>20} | layer={layer:2d} | "
                f"train_loss={metrics.get('train_loss', float('nan')):.4f} | "
                f"test_acc={test_acc:.3f} | test_prec={test_precision:.3f} | "
                f"test_rec={test_recall:.3f} | test_f1={test_f1:.3f}"
            )

            probe_path = os.path.join(
                "trained_probes", f"massmean_layer{layer}_{context_type}_{task_name}.pt"
            )
            probe.save(probe_path)

            results.append(
                {
                    "probe_type": "mass_mean",
                    "context_type": context_type,
                    "task": task_name,
                    "layer": layer,
                    "train_loss": float(metrics.get("train_loss", float("nan"))),
                    "val_loss": float(metrics.get("val_loss", float("nan"))),
                    "test_acc": test_acc,
                    "test_precision": test_precision,
                    "test_recall": test_recall,
                    "test_f1": test_f1,
                }
            )

    # Save summary CSV
    csv_path = os.path.join("trained_probes", f"probe_results_summary_{context_type}.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        header = ["probe_type", "context_type", "task", "layer", "train_loss", "val_loss", 
                  "test_acc", "test_precision", "test_recall", "test_f1"]
        f.write(",".join(header) + "\n")
        for row in results:
            f.write(
                f"{row['probe_type']},{row['context_type']},{row['task']},{row['layer']},"
                f"{row['train_loss']},{row['val_loss']},{row['test_acc']},"
                f"{row['test_precision']},{row['test_recall']},{row['test_f1']}\n"
            )
    print(f"\nSaved probe summary to {csv_path}")
    
    return results


def print_best_probes(all_results: List[Dict[str, object]]) -> None:
    """Print the best probes for each context type and task category.
    
    For each context type (planning, subanswer, final):
    - Find best probe for answer prediction (correct or correct_given_recall1)
    - Find best probe for recall prediction (recall_full)
    
    For each, output best accuracy, precision, recall, and F1.
    """
    print("\n" + "="*80)
    print("BEST PROBES SUMMARY")
    print("="*80)
    
    context_types = ["planning", "subanswer", "final"]
    answer_tasks = ["correct", "correct_given_recall1"]
    recall_task = "recall_full"
    
    for context_type in context_types:
        print(f"\n{context_type.upper()}")
        print("-" * 80)
        
        # Filter results for this context type
        context_results = [r for r in all_results if r["context_type"] == context_type]
        
        # Answer prediction: compare correct and correct_given_recall1
        answer_results = [r for r in context_results if r["task"] in answer_tasks]
        
        if answer_results:
            print("\n  Answer Prediction (best across 'correct' and 'correct_given_recall1'):")
            
            # Filter out NaN values
            valid_results = [r for r in answer_results if not np.isnan(r.get("test_acc", np.nan))]
            
            if valid_results:
                # Best accuracy
                best_acc = max(valid_results, key=lambda x: x.get("test_acc", float("-inf")))
                print(f"    Best Accuracy: {best_acc['test_acc']:.4f}")
                print(f"      Probe: {best_acc['probe_type']}, Task: {best_acc['task']}, "
                      f"Layer: {best_acc['layer']}")
                print(f"      Precision: {best_acc['test_precision']:.4f}, "
                      f"Recall: {best_acc['test_recall']:.4f}, F1: {best_acc['test_f1']:.4f}")
                
                # Best precision
                valid_prec = [r for r in valid_results if not np.isnan(r.get("test_precision", np.nan))]
                if valid_prec:
                    best_prec = max(valid_prec, key=lambda x: x.get("test_precision", float("-inf")))
                    print(f"    Best Precision: {best_prec['test_precision']:.4f}")
                    print(f"      Probe: {best_prec['probe_type']}, Task: {best_prec['task']}, "
                          f"Layer: {best_prec['layer']}")
                    print(f"      Accuracy: {best_prec['test_acc']:.4f}, "
                          f"Recall: {best_prec['test_recall']:.4f}, F1: {best_prec['test_f1']:.4f}")
                
                # Best recall
                valid_rec = [r for r in valid_results if not np.isnan(r.get("test_recall", np.nan))]
                if valid_rec:
                    best_rec = max(valid_rec, key=lambda x: x.get("test_recall", float("-inf")))
                    print(f"    Best Recall: {best_rec['test_recall']:.4f}")
                    print(f"      Probe: {best_rec['probe_type']}, Task: {best_rec['task']}, "
                          f"Layer: {best_rec['layer']}")
                    print(f"      Accuracy: {best_rec['test_acc']:.4f}, "
                          f"Precision: {best_rec['test_precision']:.4f}, F1: {best_rec['test_f1']:.4f}")
                
                # Best F1
                valid_f1 = [r for r in valid_results if not np.isnan(r.get("test_f1", np.nan))]
                if valid_f1:
                    best_f1 = max(valid_f1, key=lambda x: x.get("test_f1", float("-inf")))
                    print(f"    Best F1: {best_f1['test_f1']:.4f}")
                    print(f"      Probe: {best_f1['probe_type']}, Task: {best_f1['task']}, "
                          f"Layer: {best_f1['layer']}")
                    print(f"      Accuracy: {best_f1['test_acc']:.4f}, "
                          f"Precision: {best_f1['test_precision']:.4f}, "
                          f"Recall: {best_f1['test_recall']:.4f}")
        
        # Recall prediction: recall_full
        recall_results = [r for r in context_results if r["task"] == recall_task]
        
        if recall_results:
            print("\n  Recall Prediction (recall_full):")
            
            # Filter out NaN values
            valid_results = [r for r in recall_results if not np.isnan(r.get("test_acc", np.nan))]
            
            if valid_results:
                # Best accuracy
                best_acc = max(valid_results, key=lambda x: x.get("test_acc", float("-inf")))
                print(f"    Best Accuracy: {best_acc['test_acc']:.4f}")
                print(f"      Probe: {best_acc['probe_type']}, Task: {best_acc['task']}, "
                      f"Layer: {best_acc['layer']}")
                print(f"      Precision: {best_acc['test_precision']:.4f}, "
                      f"Recall: {best_acc['test_recall']:.4f}, F1: {best_acc['test_f1']:.4f}")
                
                # Best precision
                valid_prec = [r for r in valid_results if not np.isnan(r.get("test_precision", np.nan))]
                if valid_prec:
                    best_prec = max(valid_prec, key=lambda x: x.get("test_precision", float("-inf")))
                    print(f"    Best Precision: {best_prec['test_precision']:.4f}")
                    print(f"      Probe: {best_prec['probe_type']}, Task: {best_prec['task']}, "
                          f"Layer: {best_prec['layer']}")
                    print(f"      Accuracy: {best_prec['test_acc']:.4f}, "
                          f"Recall: {best_prec['test_recall']:.4f}, F1: {best_prec['test_f1']:.4f}")
                
                # Best recall
                valid_rec = [r for r in valid_results if not np.isnan(r.get("test_recall", np.nan))]
                if valid_rec:
                    best_rec = max(valid_rec, key=lambda x: x.get("test_recall", float("-inf")))
                    print(f"    Best Recall: {best_rec['test_recall']:.4f}")
                    print(f"      Probe: {best_rec['probe_type']}, Task: {best_rec['task']}, "
                          f"Layer: {best_rec['layer']}")
                    print(f"      Accuracy: {best_rec['test_acc']:.4f}, "
                          f"Precision: {best_rec['test_precision']:.4f}, F1: {best_rec['test_f1']:.4f}")
                
                # Best F1
                valid_f1 = [r for r in valid_results if not np.isnan(r.get("test_f1", np.nan))]
                if valid_f1:
                    best_f1 = max(valid_f1, key=lambda x: x.get("test_f1", float("-inf")))
                    print(f"    Best F1: {best_f1['test_f1']:.4f}")
                    print(f"      Probe: {best_f1['probe_type']}, Task: {best_f1['task']}, "
                          f"Layer: {best_f1['layer']}")
                    print(f"      Accuracy: {best_f1['test_acc']:.4f}, "
                          f"Precision: {best_f1['test_precision']:.4f}, "
                          f"Recall: {best_f1['test_recall']:.4f}")
    
    print("\n" + "="*80)


def main(
    mode: str,
    balance: bool = False,
) -> None:
    full_run = mode != "test"
    print(
        f"Running in mode: {mode!r} (full_run={full_run}, balance={balance})"
    )

    # Reproducibility
    rng = np.random.default_rng(42)
    torch.manual_seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)

    # Load dataset
    contexts_dict, y_correct, y_recall_full = load_hotpot_decomp_dataset(
        JSON_DATASET_PATH
    )
    n_total = len(contexts_dict["planning"])
    print(f"Loaded {n_total} examples from dataset.")

    # Subsample for full vs test run
    if full_run:
        max_examples = min(3000, n_total)
    else:
        max_examples = min(32, n_total)

    indices = np.arange(n_total)
    rng.shuffle(indices)
    indices = indices[:max_examples]

    # Subsample all context types
    contexts_dict = {
        key: [contexts_list[i] for i in indices]
        for key, contexts_list in contexts_dict.items()
    }
    y_correct = y_correct[indices]
    y_recall_full = y_recall_full[indices]
    n = len(contexts_dict["planning"])
    print(f"Using {n} examples after subsampling (max_examples={max_examples}).")

    # Create splits
    train_idx, val_idx, test_idx = make_splits(n, rng)
    print(
        f"Split sizes: train={len(train_idx)}, val={len(val_idx)}, "
        f"test={len(test_idx)}"
    )

    # Load model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading model 'meta-llama/Llama-3.1-8B-Instruct' on device={device}...")
    model = HookedTransformer.from_pretrained(
        "meta-llama/Llama-3.1-8B-Instruct",
        device=str(device),
        dtype=torch.float16,
    )

    # Decide which layers to probe
    preferred_layers = [4, 8, 12, 16, 20, 24, 28, 31]
    n_layers = model.cfg.n_layers
    layers_available = [l for l in preferred_layers if l < n_layers]
    if not layers_available:
        layers_available = list(range(n_layers))

    if full_run:
        layers_to_probe = layers_available
    else:
        layers_to_probe = [layers_available[-1]]  # final-ish layer only

    print(f"Layers to probe: {layers_to_probe}")

    # Compute activations for each context type
    hidden_per_layer_dict = {}
    for context_type, contexts in contexts_dict.items():
        print(f"\nComputing activations for {context_type}...")
        hidden_per_layer_dict[context_type] = compute_activations(
            model, contexts, layers_to_probe, full_run=full_run
        )

    # Free model; we only need stored features now.
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Train all probes for each context type
    all_results = []
    for context_type in ["planning", "subanswer", "final"]:
        print(f"\n{'='*60}")
        print(f"Training probes for context type: {context_type}")
        print(f"{'='*60}")
        results = train_all_probes(
            hidden_per_layer_dict[context_type],
            y_correct,
            y_recall_full,
            train_idx,
            val_idx,
            test_idx,
            layers_to_probe,
            full_run=full_run,
            balance=balance,
            rng=rng,
            context_type=context_type,
        )
        all_results.extend(results)
    
    # Print summary of best probes
    print_best_probes(all_results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Train lightweight probes on Llama-3.1-8B activations for "
            "HotpotQA decomposition dataset."
        )
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["full", "test"],
        default="full",
        help=(
            "Run mode: 'full' for full training run (default), "
            "'test' for a tiny smoke test that runs very quickly."
        ),
    )
    parser.add_argument(
        "--balance",
        action="store_true",
        default=False,
        help=(
            "Deprecated: class balancing is now always applied to the training set. "
            "This flag is kept for backwards compatibility but has no effect."
        ),
    )
    args = parser.parse_args()
    main(
        args.mode,
        balance=args.balance,
    )

