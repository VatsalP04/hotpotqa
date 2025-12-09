"""
train_probes.py

Script to train lightweight probes on Llama-3.1-8B activations for the
HotpotQA decomposition dataset.

Usage:
    python -m mateo.train_probes [mode] [--balance] [--include-retrieval]

Arguments
---------
mode : {"full", "test"}, optional
    - "full" (default): full run with ~3000 examples and 8 layers.
    - "test": tiny smoke test (e.g. 32 examples, 1 layer) to ensure
      everything runs without errors.

--balance : flag, optional
    If set, downsamples training data to balance class distributions.
    - For "correct" tasks: balances answer distribution (correct vs incorrect).
    - For "recall_full" task: balances recall distribution (recall=1.0 vs recall<1.0).

--include-retrieval : flag, optional
    If set, includes retrieved context sentences after each subquery in the input context.
    Format: "Question + Subquery 1 + Retrieved context 1 + ... + Subquery i + 
    Retrieved context i + Answer". Default is to exclude retrieval contexts.

Expected runtime on an A100 80GB (rough ballpark):
    - full: ~1–3 minutes with defaults (3k examples, 8 layers, 3 epochs).
    - test: <10 seconds (32 examples, 1 layer, 1 epoch).
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Tuple

import numpy as np
import torch
from transformer_lens import HookedTransformer

from mateo.probes import (
    ProbeConfig,
    DenseLinearProbe,
    MassMeanProbe,
    UncertaintyProbe,
)


# Default path; adjust if needed.
JSON_DATASET_PATH = os.path.join(
    "mateo", "training_datasets", "decomposition_dataset.json"
)


def load_hotpot_decomp_dataset(
    json_path: str,
    include_retrieval: bool = False,
) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """Load dataset and build context strings + labels.

    Parameters
    ----------
    json_path : str
        Path to the JSON dataset file.
    include_retrieval : bool, default=False
        If True, include retrieved context sentences after each subquery.
        Format: "Question + Subquery 1 + Retrieved context 1 + ... + Subquery i + Retrieved context i + Answer"
        If False, format: "Question + Subquery 1 + ... + Subquery i + Answer"

    Returns
    -------
    contexts : list of str
        Each is "Question + Subquery 1 + ... + Subquery n + Answer" (or with retrieval contexts if enabled).
    y_correct : np.ndarray, shape (N,)
        0/1 labels for answer correctness.
    y_recall_full : np.ndarray, shape (N,)
        1 if recall == 1.0, else 0.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Dataset not found at: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    contexts: List[str] = []
    correct_labels: List[int] = []
    recall_full_labels: List[int] = []

    for qid, entry in data.items():
        question = entry.get("question", "").strip()
        answer = str(entry.get("answer", "")).strip()

        correct = int(entry.get("correct", 0))
        recall = float(entry.get("recall", 0.0))
        recall_full = 1 if abs(recall - 1.0) < 1e-8 else 0

        subqueries = entry.get("subqueries", {})
        # Sort subqueries by key for a deterministic order.
        sq_items = sorted(subqueries.items(), key=lambda kv: kv[0])

        parts: List[str] = []
        parts.append(f"Question: {question}\n")
        for i, (sq_text, sq_evidence) in enumerate(sq_items):
            sq_text_clean = sq_text.strip()
            parts.append(f"Subquery {i+1}: {sq_text_clean}\n")
            
            if include_retrieval and sq_evidence:
                # sq_evidence is a list of retrieved sentences
                retrieved_text = " ".join(str(s).strip() for s in sq_evidence if s)
                if retrieved_text:
                    parts.append(f"Retrieved context {i+1}: {retrieved_text}\n")
        
        parts.append(f"Answer: {answer}")
        context = "".join(parts)

        contexts.append(context)
        correct_labels.append(correct)
        recall_full_labels.append(recall_full)

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


def compute_activations_and_uncertainty(
    model: "HookedTransformer",
    contexts: List[str],
    layers_to_probe: List[int],
    full_run: bool,
) -> Tuple[Dict[int, np.ndarray], np.ndarray]:
    """Compute hidden activations and uncertainty features.

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
    uncertainty_feats : np.ndarray
        Shape (N, 4) with [p_max, margin, entropy, hidden_norm_final].
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
    n_layers = model.cfg.n_layers
    last_layer = n_layers - 1

    # Preallocate storage on CPU.
    hidden_per_layer: Dict[int, np.ndarray] = {
        layer: np.empty((n_examples, d_model), dtype=np.float32)
        for layer in layers_to_probe
    }
    n_uncertainty_features = 4  # [p_max, margin, entropy, hidden_norm]
    uncertainty_feats = np.empty((n_examples, n_uncertainty_features), dtype=np.float32)

    # Hook names
    hook_names = [f"blocks.{layer}.hook_resid_post" for layer in layers_to_probe]
    hook_last_name = f"blocks.{last_layer}.hook_resid_post"
    if hook_last_name not in hook_names:
        hook_names.append(hook_last_name)

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

            # Hidden states per layer
            for layer in layers_to_probe:
                hook_name = f"blocks.{layer}.hook_resid_post"
                acts = cache[hook_name]  # (bsz, max_len, d_model)
                final_acts = acts[batch_indices, positions, :]  # (bsz, d_model)
                hidden_per_layer[layer][start:end, :] = (
                    final_acts.float().cpu().numpy()
                )

            # Uncertainty features from final token logits + final layer norm.
            # Cast to float32 to avoid half-precision underflow in softmax/log.
            logits_last = logits[batch_indices, positions, :].float()  # (bsz, d_vocab)
            probs = torch.softmax(logits_last, dim=-1)  # float32

            p_max, _ = probs.max(dim=-1)  # (bsz,)
            top2, _ = probs.topk(2, dim=-1)
            margin = top2[:, 0] - top2[:, 1]

            probs_clamped = probs.clamp_min(1e-12)
            entropy = -(probs_clamped * probs_clamped.log()).sum(dim=-1)

            h_last = cache[hook_last_name][batch_indices, positions, :].float()
            hidden_norm = h_last.norm(dim=-1)

            # Safety: replace any NaN/inf that might still sneak through.
            entropy = torch.nan_to_num(entropy, nan=0.0, posinf=0.0, neginf=0.0)
            hidden_norm = torch.nan_to_num(hidden_norm, nan=0.0, posinf=1e3, neginf=-1e3)

            feats = torch.stack([p_max, margin, entropy, hidden_norm], dim=-1)
            uncertainty_feats[start:end, :] = feats.float().cpu().numpy()

            start = end

            # Free batch cache/logits
            del logits, cache
            if device.type == "cuda":
                torch.cuda.empty_cache()

    # Final safety on the full array
    uncertainty_feats = np.nan_to_num(
        uncertainty_feats, nan=0.0, posinf=1e3, neginf=-1e3
    )

    return hidden_per_layer, uncertainty_feats


def has_both_classes(y: np.ndarray) -> bool:
    """Return True if y contains both 0 and 1."""
    uniq = np.unique(y)
    return len(uniq) >= 2 and (0.0 in uniq) and (1.0 in uniq)


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
    uncertainty_feats: np.ndarray,
    y_correct: np.ndarray,
    y_recall_full: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    test_idx: np.ndarray,
    layers_to_probe: List[int],
    full_run: bool,
    balance: bool = False,
    rng: np.random.Generator | None = None,
) -> None:
    """Train DenseLinear, MassMean, and Uncertainty probes on all tasks.
    
    Parameters
    ----------
    balance : bool, default=False
        If True, downsample training data to balance class distributions.
        For "correct" tasks, balances based on y_correct.
        For "recall_full" task, balances based on y_recall_full.
    rng : np.random.Generator, optional
        Random number generator for downsampling. Required if balance=True.
    """
    os.makedirs("trained_probes", exist_ok=True)
    
    if balance and rng is None:
        raise ValueError("rng must be provided when balance=True")

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
    num_epochs_uncertainty = 3 if full_run else 1

    results: List[Dict[str, object]] = []

    # ---- DenseLinearProbe per layer ----
    print("\n=== Training DenseLinearProbes ===")
    for task_name, y_all, extra_mask in tasks:
        base_mask = extra_mask if extra_mask is not None else np.ones(n, dtype=bool)
        for layer in layers_to_probe:
            X = hidden_per_layer[layer]

            train_m = base_mask & train_mask
            val_m = base_mask & val_mask
            test_m = base_mask & test_mask

            if train_m.sum() < 2:
                print(
                    f"[Dense] Skipping layer {layer}, task {task_name}: "
                    f"not enough training examples ({train_m.sum()})."
                )
                continue

            # Apply downsampling if balance is enabled
            if balance and rng is not None:
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
            if test_m.sum() > 0:
                X_test, y_test = X[test_m], y_all[test_m]
                probs = probe.predict_proba(X_test)
                preds = (probs >= 0.5).astype(np.float32)
                test_acc = float((preds == y_test).mean())

            print(
                f"[Dense] Task={task_name:>20} | layer={layer:2d} | "
                f"train_loss={metrics.get('train_loss', float('nan')):.4f} | "
                f"test_acc={test_acc:.3f}"
            )

            probe_path = os.path.join(
                "trained_probes", f"dense_layer{layer}_{task_name}.pt"
            )
            probe.save(probe_path)

            results.append(
                {
                    "probe_type": "dense_linear",
                    "task": task_name,
                    "layer": layer,
                    "train_loss": float(metrics.get("train_loss", float("nan"))),
                    "val_loss": float(metrics.get("val_loss", float("nan"))),
                    "test_acc": test_acc,
                }
            )

    # ---- MassMeanProbe per layer ----
    print("\n=== Training MassMeanProbes ===")
    for task_name, y_all, extra_mask in tasks:
        base_mask = extra_mask if extra_mask is not None else np.ones(n, dtype=bool)
        for layer in layers_to_probe:
            X = hidden_per_layer[layer]

            train_m = base_mask & train_mask
            val_m = base_mask & val_mask
            test_m = base_mask & test_mask

            # Apply downsampling if balance is enabled
            if balance and rng is not None:
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
            if test_m.sum() > 0:
                X_test, y_test = X[test_m], y_all[test_m]
                probs = probe.predict_proba(X_test)
                preds = (probs >= 0.5).astype(np.float32)
                test_acc = float((preds == y_test).mean())

            print(
                f"[MassMean] Task={task_name:>20} | layer={layer:2d} | "
                f"train_loss={metrics.get('train_loss', float('nan')):.4f} | "
                f"test_acc={test_acc:.3f}"
            )

            probe_path = os.path.join(
                "trained_probes", f"massmean_layer{layer}_{task_name}.pt"
            )
            probe.save(probe_path)

            results.append(
                {
                    "probe_type": "mass_mean",
                    "task": task_name,
                    "layer": layer,
                    "train_loss": float(metrics.get("train_loss", float("nan"))),
                    "val_loss": float(metrics.get("val_loss", float("nan"))),
                    "test_acc": test_acc,
                }
            )

    # ---- UncertaintyProbe (layer-agnostic) ----
    print("\n=== Training UncertaintyProbes ===")
    X_all = uncertainty_feats
    for task_name, y_all, extra_mask in tasks:
        base_mask = extra_mask if extra_mask is not None else np.ones(n, dtype=bool)

        train_m = base_mask & train_mask
        val_m = base_mask & val_mask
        test_m = base_mask & test_mask

        if train_m.sum() < 2:
            print(
                f"[Uncertainty] Skipping task {task_name}: "
                f"not enough training examples ({train_m.sum()})."
            )
            continue

        # Apply downsampling if balance is enabled
        if balance and rng is not None:
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
                    f"[Uncertainty] Skipping task {task_name}: "
                    f"not enough training examples after balancing ({train_m.sum()})."
                )
                continue

        X_train, y_train = X_all[train_m], y_all[train_m]
        X_val, y_val = (X_all[val_m], y_all[val_m]) if val_m.sum() > 0 else (None, None)

        cfg = ProbeConfig(
            probe_type="uncertainty",
            layer=None,
            task_name=task_name,
            feature_names=["p_max", "margin", "entropy", "hidden_norm"],
        )
        probe = UncertaintyProbe(cfg)
        metrics = probe.fit(
            X_train,
            y_train,
            val_x=X_val,
            val_y=y_val,
            num_epochs=num_epochs_uncertainty,
            lr=1e-2,
            weight_decay=0.0,
            batch_size=64,
            device=None,
            verbose=False,
        )

        test_acc = float("nan")
        if test_m.sum() > 0:
            X_test, y_test = X_all[test_m], y_all[test_m]
            probs = probe.predict_proba(X_test)
            preds = (probs >= 0.5).astype(np.float32)
            test_acc = float((preds == y_test).mean())

        print(
            f"[Uncertainty] Task={task_name:>20} | "
            f"train_loss={metrics.get('train_loss', float('nan')):.4f} | "
            f"test_acc={test_acc:.3f}"
        )

        probe_path = os.path.join(
            "trained_probes", f"uncertainty_{task_name}.pt"
        )
        probe.save(probe_path)

        results.append(
            {
                "probe_type": "uncertainty",
                "task": task_name,
                "layer": None,
                "train_loss": float(metrics.get("train_loss", float("nan"))),
                "val_loss": float(metrics.get("val_loss", float("nan"))),
                "test_acc": test_acc,
            }
        )

    # Save summary CSV
    csv_path = os.path.join("trained_probes", "probe_results_summary.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        header = ["probe_type", "task", "layer", "train_loss", "val_loss", "test_acc"]
        f.write(",".join(header) + "\n")
        for row in results:
            f.write(
                f"{row['probe_type']},{row['task']},{row['layer']},"
                f"{row['train_loss']},{row['val_loss']},{row['test_acc']}\n"
            )
    print(f"\nSaved probe summary to {csv_path}")


def main(mode: str, balance: bool = False, include_retrieval: bool = False) -> None:
    full_run = mode != "test"
    print(
        f"Running in mode: {mode!r} (full_run={full_run}, balance={balance}, "
        f"include_retrieval={include_retrieval})"
    )

    # Reproducibility
    rng = np.random.default_rng(42)
    torch.manual_seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)

    # Load dataset
    contexts, y_correct, y_recall_full = load_hotpot_decomp_dataset(
        JSON_DATASET_PATH, include_retrieval=include_retrieval
    )
    n_total = len(contexts)
    print(f"Loaded {n_total} examples from dataset.")

    # Subsample for full vs test run
    if full_run:
        max_examples = min(3000, n_total)
    else:
        max_examples = min(32, n_total)

    indices = np.arange(n_total)
    rng.shuffle(indices)
    indices = indices[:max_examples]

    contexts = [contexts[i] for i in indices]
    y_correct = y_correct[indices]
    y_recall_full = y_recall_full[indices]
    n = len(contexts)
    print(f"Using {n} examples after subsampling (max_examples={max_examples}).")

    # Create splits
    train_idx, val_idx, test_idx = make_splits(n, rng)
    print(
        f"Split sizes: train={len(train_idx)}, val={len(val_idx)}, "
        f"test={len(test_idx)}"
    )

    # Load model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading model 'meta-llama/Llama-3.1-8B' on device={device}...")
    model = HookedTransformer.from_pretrained(
        "meta-llama/Llama-3.1-8B",
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

    # Filter out examples longer than 2000 tokens (only if include_retrieval is enabled)
    if include_retrieval:
        print("Filtering examples longer than 2000 tokens...")
        max_tokens = 2000
        valid_indices = []
        for i, text in enumerate(contexts):
            toks = model.to_tokens(text, prepend_bos=True)  # (1, T)
            token_length = toks.shape[1]
            if token_length <= max_tokens:
                valid_indices.append(i)

        n_before = len(contexts)
        if len(valid_indices) > 0:
            valid_indices = np.array(valid_indices)
            contexts = [contexts[i] for i in valid_indices]
            y_correct = y_correct[valid_indices]
            y_recall_full = y_recall_full[valid_indices]
        else:
            contexts = []
            y_correct = np.array([], dtype=np.float32)
            y_recall_full = np.array([], dtype=np.float32)
        n_after = len(contexts)
        print(
            f"Filtered {n_before - n_after} examples longer than {max_tokens} tokens. "
            f"Remaining: {n_after} examples."
        )

        if n_after == 0:
            raise ValueError("No examples remaining after filtering by token length.")

        # Recreate splits with the filtered data
        n = n_after
        train_idx, val_idx, test_idx = make_splits(n, rng)
        print(
            f"Split sizes after filtering: train={len(train_idx)}, val={len(val_idx)}, "
            f"test={len(test_idx)}"
        )

    # Compute activations + uncertainty features
    hidden_per_layer, uncertainty_feats = compute_activations_and_uncertainty(
        model, contexts, layers_to_probe, full_run=full_run
    )

    # Free model; we only need stored features now.
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Train all probes
    train_all_probes(
        hidden_per_layer,
        uncertainty_feats,
        y_correct,
        y_recall_full,
        train_idx,
        val_idx,
        test_idx,
        layers_to_probe,
        full_run=full_run,
        balance=balance,
        rng=rng,
    )


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
            "Balance training dataset by downsampling. "
            "For 'correct' tasks, balances answer distribution (correct vs incorrect). "
            "For 'recall_full' task, balances recall distribution (recall=1.0 vs recall<1.0)."
        ),
    )
    parser.add_argument(
        "--include-retrieval",
        action="store_true",
        default=False,
        help=(
            "Include retrieved context sentences after each subquery in the input context. "
            "Format: 'Question + Subquery 1 + Retrieved context 1 + ... + Subquery i + "
            "Retrieved context i + Answer'. Default is to exclude retrieval contexts."
        ),
    )
    args = parser.parse_args()
    main(args.mode, balance=args.balance, include_retrieval=args.include_retrieval)
