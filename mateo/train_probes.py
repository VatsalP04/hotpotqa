from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from transformer_lens import HookedTransformer

from mateo.probes import (
    ArrayLike,
    ProbeConfig,
    DenseLinearProbe,
    MassMeanProbe,
    MLPProbe,
    StreamingAttentionProbe,
)


# -------------------------
#  Paths & SAE config
# -------------------------

JSON_DATASET_PATH = os.path.join(
    "mateo", "training_datasets", "decomposition_dataset.json"
)

SAE_RELEASE = "llama_scope_lxr_8x"  # adjust if needed


# -------------------------
#  Dataset loading & splits
# -------------------------


def load_hotpot_decomp_dataset(
    json_path: str,
) -> Tuple[Dict[str, List[str]], np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[List[int]]]:
    """Load dataset and build context strings + labels."""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Dataset not found at: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    contexts_planning: List[str] = []
    contexts_final: List[str] = []
    correct_labels: List[int] = []
    recall_full_labels: List[int] = []

    subanswer_texts: List[str] = []
    subanswer_correct: List[int] = []
    subanswer_recall_full: List[int] = []
    question_to_subanswer_indices: List[List[int]] = []

    for qid, entry in data.items():
        correct = int(entry.get("correct", 0))
        recall = float(entry.get("recall", 0.0))
        recall_full = 1 if abs(recall - 1.0) < 1e-8 else 0

        planning = entry.get("planning", "").strip()
        subanswer_list = entry.get("subanswer", [])
        final = entry.get("final", "").strip()

        # Trim trailing <|eot_id|> if present
        if planning.endswith("<|eot_id|>"):
            planning = planning[:-10].rstrip()
        if final.endswith("<|eot_id|>"):
            final = final[:-10].rstrip()

        contexts_planning.append(planning)
        contexts_final.append(final)

        # Subanswers
        subanswer_indices_for_question: List[int] = []
        for sa in subanswer_list:
            sa_text = str(sa).strip()
            if sa_text.endswith("<|eot_id|>"):
                sa_text = sa_text[:-10].rstrip()
            if sa_text:
                subanswer_indices_for_question.append(len(subanswer_texts))
                subanswer_texts.append(sa_text)
                subanswer_correct.append(correct)
                subanswer_recall_full.append(recall_full)
        question_to_subanswer_indices.append(subanswer_indices_for_question)

        correct_labels.append(correct)
        recall_full_labels.append(recall_full)

    contexts = {
        "planning": contexts_planning,
        "subanswer": subanswer_texts,
        "final": contexts_final,
    }
    y_correct = np.array(correct_labels, dtype=np.float32)
    y_recall_full = np.array(recall_full_labels, dtype=np.float32)
    y_subanswer_correct = np.array(subanswer_correct, dtype=np.float32)
    y_subanswer_recall_full = np.array(subanswer_recall_full, dtype=np.float32)

    return (
        contexts,
        y_correct,
        y_recall_full,
        y_subanswer_correct,
        y_subanswer_recall_full,
        question_to_subanswer_indices,
    )


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


# -------------------------
#  Tokenization & activations
# -------------------------


def tokenize_contexts(
    model: HookedTransformer,
    contexts: List[str],
) -> Tuple[List[torch.Tensor], List[int]]:
    """Tokenize each context separately (no truncation)."""
    tokens_list: List[torch.Tensor] = []
    lengths: List[int] = []
    for text in contexts:
        toks = model.to_tokens(text, prepend_bos=True)  # (1, T)
        toks = toks[0]  # (T,)
        tokens_list.append(toks)
        lengths.append(int(toks.shape[0]))
    return tokens_list, lengths


def compute_token_activations(
    model: HookedTransformer,
    tokens_list: List[torch.Tensor],
    lengths: List[int],
    layers_to_probe: List[int],
    hook_type: str,
    full_run: bool,
    token_pooling: str = "single",
    pool_k: int = 4,
    token_offset: int = 0,
) -> Dict[int, np.ndarray]:
    """Compute pooled residual activations for chosen layers.

    token_pooling:
        - "single": use a single token from the end, offset by token_offset.
            token_offset = 0 -> last token
            token_offset = 1 -> second-to-last, etc.
        - "mean_last_k": mean over the last pool_k tokens.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    n_examples = len(tokens_list)
    d_model = model.cfg.d_model

    hidden_per_layer: Dict[int, np.ndarray] = {
        layer: np.empty((n_examples, d_model), dtype=np.float32)
        for layer in layers_to_probe
    }

    hook_names = [f"blocks.{layer}.hook_{hook_type}" for layer in layers_to_probe]

    def names_filter(name: str) -> bool:
        return name in hook_names

    batch_size = 4 if full_run else 8
    print(
        f"Computing token activations (pooling={token_pooling}, pool_k={pool_k}, "
        f"token_offset={token_offset}) for {n_examples} examples "
        f"(batch_size={batch_size}, layers={layers_to_probe}, hook_type={hook_type})..."
    )

    model.to(device)
    model.eval()

    lengths_tensor = torch.tensor(lengths, device=device)
    start = 0
    with torch.no_grad():
        while start < n_examples:
            end = min(start + batch_size, n_examples)
            batch_tokens = tokens_list[start:end]
            batch_lengths = lengths_tensor[start:end]
            bsz = len(batch_tokens)
            max_len = int(batch_lengths.max().item())

            input_ids = torch.zeros((bsz, max_len), dtype=torch.long, device=device)
            for i, toks in enumerate(batch_tokens):
                L = toks.shape[0]
                input_ids[i, :L] = toks.to(device)

            logits, cache = model.run_with_cache(
                input_ids,
                return_type="logits",
                names_filter=names_filter,
            )

            batch_indices = torch.arange(bsz, device=device)

            for layer in layers_to_probe:
                hook_name = f"blocks.{layer}.hook_{hook_type}"
                acts = cache[hook_name]  # (bsz, max_len, d_model)

                if token_pooling == "single":
                    # Choose a single token from the end with offset
                    # pos = L_i - 1 - token_offset, but clipped to [0, L_i-1]
                    positions = []
                    for i in range(bsz):
                        L_i = int(batch_lengths[i].item())
                        pos_i = max(0, L_i - 1 - token_offset)
                        positions.append(pos_i)
                    positions_t = torch.tensor(positions, device=device, dtype=torch.long)
                    pooled = acts[batch_indices, positions_t, :]  # (bsz, d_model)

                elif token_pooling == "mean_last_k":
                    pooled_list = []
                    for i in range(bsz):
                        L_i = int(batch_lengths[i].item())
                        k_i = min(L_i, pool_k)
                        start_i = L_i - k_i
                        pooled_i = acts[i, start_i:L_i, :].mean(dim=0)
                        pooled_list.append(pooled_i)
                    pooled = torch.stack(pooled_list, dim=0)  # (bsz, d_model)

                else:
                    raise ValueError(
                        f"Unknown token_pooling mode: {token_pooling!r}. "
                        "Expected one of {'single', 'mean_last_k'}."
                    )

                hidden_per_layer[layer][start:end, :] = pooled.float().cpu().numpy()

            start = end
            del logits, cache
            if device.type == "cuda":
                torch.cuda.empty_cache()

    return hidden_per_layer


# -------------------------
#  Metrics & balancing
# -------------------------


def has_both_classes(y: np.ndarray) -> bool:
    uniq = np.unique(y)
    return len(uniq) >= 2 and (0.0 in uniq) and (1.0 in uniq)


def calculate_metrics(
    y_true: np.ndarray, y_pred: np.ndarray
) -> Tuple[float, float, float, float]:
    """Accuracy, precision, recall, F1 for class 0."""
    y_true = y_true.astype(np.float32)
    y_pred = y_pred.astype(np.float32)

    accuracy = float((y_pred == y_true).mean())
    tp = float(((y_pred == 0.0) & (y_true == 0.0)).sum())
    fp = float(((y_pred == 0.0) & (y_true == 1.0)).sum())
    fn = float(((y_pred == 1.0) & (y_true == 0.0)).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return accuracy, precision, recall, f1


def downsample_balanced(
    indices: np.ndarray, labels: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Downsample indices to balance class distribution."""
    if len(indices) == 0:
        return indices

    idx_labels = labels[indices]

    class_0_indices = indices[idx_labels == 0.0]
    class_1_indices = indices[idx_labels == 1.0]

    n0 = len(class_0_indices)
    n1 = len(class_1_indices)

    if n0 == 0 or n1 == 0:
        return indices

    k = min(n0, n1)
    if n0 > k:
        class_0_indices = rng.choice(class_0_indices, size=k, replace=False)
    if n1 > k:
        class_1_indices = rng.choice(class_1_indices, size=k, replace=False)

    balanced = np.concatenate([class_0_indices, class_1_indices])
    rng.shuffle(balanced)
    return balanced


# -------------------------
#  SAE latents (optional)
# -------------------------


def compute_sae_latents_per_layer(
    final_acts_per_layer: Dict[int, np.ndarray],
    layers_for_sae: List[int],
    device: torch.device,
) -> Dict[int, np.ndarray]:
    """Compute SAE latents for pooled activations (via sae_lens)."""
    try:
        from sae_lens import SAE  # type: ignore[import]
    except ImportError as e:
        raise ImportError(
            "sae_lens is required for --use_sae_probes. Install via `pip install sae-lens`."
        ) from e

    sae_latents_per_layer: Dict[int, np.ndarray] = {}

    for layer in layers_for_sae:
        X = final_acts_per_layer[layer]  # (N, d_model)
        N, _ = X.shape
        print(
            f"Loading SAE for layer {layer} "
            f"(release={SAE_RELEASE}, sae_id=l{layer}r_8x)..."
        )

        res = SAE.from_pretrained(
            release=SAE_RELEASE,
            sae_id=f"l{layer}r_8x",
            device=str(device),
        )
        sae = res[0] if isinstance(res, tuple) else res
        sae.eval()

        with torch.no_grad():
            x_t = torch.tensor(X, dtype=torch.float32, device=device)  # (N, D)
            x_t = x_t.unsqueeze(1)  # (N, 1, D)
            latents = sae.encode(x_t)  # (N, 1, K)
            if latents.ndim == 3:
                latents = latents[:, 0, :]
            else:
                latents = latents.view(N, -1)
            sae_latents_per_layer[layer] = latents.float().cpu().numpy()

        del sae, latents, x_t
        if device.type == "cuda":
            torch.cuda.empty_cache()

    return sae_latents_per_layer


# -------------------------
#  Training: dense / mass / mlp on pooled resid
# -------------------------


def train_dense_mass_mlp_for_context(
    context_type: str,
    final_acts_per_layer: Dict[int, np.ndarray],
    y_correct: np.ndarray,
    y_recall_full: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    test_idx: np.ndarray,
    layers_to_probe: List[int],
    full_run: bool,
    balance: bool,
    rng: np.random.Generator,
    hook_type: str,
    probs_dict: Dict[str, np.ndarray],
    meta_dict: Dict[str, Dict[str, Any]],
    completed_keys: set,
    additional_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Train DenseLinear, MassMean, and MLP probes on pooled residuals."""
    print(f"\n=== {context_type.upper()} :: Dense / MassMean / MLP probes ===")

    tasks = [
        ("correct", y_correct, None),
        ("correct_given_recall1", y_correct, (y_recall_full == 1.0)),
        ("recall_full", y_recall_full, None),
    ]

    num_epochs_dense = 10 if full_run else 3
    num_epochs_mass = 100 if full_run else 20
    num_epochs_mlp = 10 if full_run else 3

    for task_name, y_all, train_restrict in tasks:
        for layer in layers_to_probe:
            X = final_acts_per_layer[layer]  # (N, d_model)

            if task_name == "correct_given_recall1" and train_restrict is not None:
                mask_train = train_restrict
                train_ids_task = train_idx[mask_train[train_idx]]
                val_ids_task = val_idx
                test_ids_task = test_idx
            else:
                train_ids_task = train_idx
                val_ids_task = val_idx
                test_ids_task = test_idx

            if len(train_ids_task) < 2:
                print(
                    f"[{context_type}|{task_name}] Skipping layer {layer}: "
                    f"not enough train examples ({len(train_ids_task)})."
                )
                continue

            if balance:
                if task_name in ("correct", "correct_given_recall1"):
                    train_ids_task = downsample_balanced(
                        train_ids_task, y_correct, rng
                    )
                elif task_name == "recall_full":
                    train_ids_task = downsample_balanced(
                        train_ids_task, y_recall_full, rng
                    )
                if len(train_ids_task) < 2:
                    print(
                        f"[{context_type}|{task_name}] Skipping layer {layer}: "
                        f"not enough train examples after balancing ({len(train_ids_task)})."
                    )
                    continue

            X_train, y_train = X[train_ids_task], y_all[train_ids_task]
            X_val, y_val = X[val_ids_task], y_all[val_ids_task]
            X_test, y_test = X[test_ids_task], y_all[test_ids_task]

            # ----- DenseLinear -----
            key = f"{context_type}__{task_name}__dense__L{layer}__{hook_type}__resid"
            if key in completed_keys:
                print(f"[Dense] {context_type:>9} | task={task_name:>20} | layer={layer:2d} | SKIPPED (already completed)")
            else:
                cfg_dense = ProbeConfig(
                    probe_type="dense_linear",
                    layer=layer,
                    task_name=task_name,
                    context_type=context_type,
                    hook_point=hook_type,
                    feature_space="resid",
                )
                dense_probe = DenseLinearProbe(cfg_dense)
                dense_probe.fit(
                    X_train,
                    y_train,
                    val_x=X_val,
                    val_y=y_val,
                    num_epochs=num_epochs_dense,
                    lr=1e-3,
                    batch_size=256,
                    device=None,
                    verbose=False,
                )

                probs_all = dense_probe.predict_proba(X)
                metadata = {
                    "context_type": context_type,
                    "task_name": task_name,
                    "probe_type": "dense",
                    "layer": layer,
                    "hook_type": hook_type,
                    "feature_space": "resid",
                }
                # Save probe as individual file
                probe_file = os.path.join("trained_probes2", f"{key}.pt")
                dense_probe.save(probe_file)
                save_probe_result(
                    key, probs_all.astype(np.float32), metadata,
                    probs_dict, meta_dict, completed_keys, additional_data
                )

                val_probs = probs_all[val_ids_task]
                val_preds = (val_probs >= 0.5).astype(np.float32)
                val_acc, val_prec, val_rec, val_f1 = calculate_metrics(y_val, val_preds)
                print(
                    f"[Dense] {context_type:>9} | task={task_name:>20} | layer={layer:2d} | "
                    f"val_acc={val_acc:.3f} | prec={val_prec:.3f} | rec={val_rec:.3f} | f1={val_f1:.3f}"
                )

            # ----- MassMean -----
            if has_both_classes(y_train):
                key_mm = (
                    f"{context_type}__{task_name}__mass_mean__"
                    f"L{layer}__{hook_type}__resid"
                )
                if key_mm in completed_keys:
                    print(f"[MassMean] {context_type:>9} | task={task_name:>20} | layer={layer:2d} | SKIPPED (already completed)")
                else:
                    cfg_mm = ProbeConfig(
                        probe_type="mass_mean",
                        layer=layer,
                        task_name=task_name,
                        context_type=context_type,
                        hook_point=hook_type,
                        feature_space="resid",
                    )
                    mm_probe = MassMeanProbe(cfg_mm)
                    try:
                        mm_probe.fit(
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
                            f"[MassMean] {context_type}|{task_name}|L{layer}: error {e}; skipping."
                        )
                    else:
                        probs_all_mm = mm_probe.predict_proba(X)
                        metadata_mm = {
                            "context_type": context_type,
                            "task_name": task_name,
                            "probe_type": "mass_mean",
                            "layer": layer,
                            "hook_type": hook_type,
                            "feature_space": "resid",
                        }
                        # Save probe as individual file
                        probe_file = os.path.join("trained_probes2", f"{key_mm}.pt")
                        mm_probe.save(probe_file)
                        save_probe_result(
                            key_mm, probs_all_mm.astype(np.float32), metadata_mm,
                            probs_dict, meta_dict, completed_keys, additional_data
                        )

                        val_probs_mm = probs_all_mm[val_ids_task]
                        val_preds_mm = (val_probs_mm >= 0.5).astype(np.float32)
                        val_acc_mm, val_prec_mm, val_rec_mm, val_f1_mm = calculate_metrics(
                            y_val, val_preds_mm
                        )
                        print(
                            f"[MassMean] {context_type:>9} | task={task_name:>20} | layer={layer:2d} | "
                            f"val_acc={val_acc_mm:.3f} | prec={val_prec_mm:.3f} | "
                            f"rec={val_rec_mm:.3f} | f1={val_f1_mm:.3f}"
                        )

            # ----- MLP -----
            key_mlp = f"{context_type}__{task_name}__mlp__L{layer}__{hook_type}__resid"
            if key_mlp in completed_keys:
                print(f"[MLP]   {context_type:>9} | task={task_name:>20} | layer={layer:2d} | SKIPPED (already completed)")
            else:
                cfg_mlp = ProbeConfig(
                    probe_type="mlp",
                    layer=layer,
                    task_name=task_name,
                    context_type=context_type,
                    hook_point=hook_type,
                    feature_space="resid",
                    hidden_dim=512,
                )
                mlp_probe = MLPProbe(cfg_mlp)
                mlp_probe.fit(
                    X_train,
                    y_train,
                    val_x=X_val,
                    val_y=y_val,
                    num_epochs=num_epochs_mlp,
                    lr=1e-3,
                    batch_size=256,
                    device=None,
                    verbose=False,
                )

                probs_all_mlp = mlp_probe.predict_proba(X)
                metadata_mlp = {
                    "context_type": context_type,
                    "task_name": task_name,
                    "probe_type": "mlp",
                    "layer": layer,
                    "hook_type": hook_type,
                    "feature_space": "resid",
                }
                # Save probe as individual file
                probe_file = os.path.join("trained_probes2", f"{key_mlp}.pt")
                mlp_probe.save(probe_file)
                save_probe_result(
                    key_mlp, probs_all_mlp.astype(np.float32), metadata_mlp,
                    probs_dict, meta_dict, completed_keys, additional_data
                )

                val_probs_mlp = probs_all_mlp[val_ids_task]
                val_preds_mlp = (val_probs_mlp >= 0.5).astype(np.float32)
                val_acc_mlp, val_prec_mlp, val_rec_mlp, val_f1_mlp = calculate_metrics(
                    y_val, val_preds_mlp
                )
                print(
                    f"[MLP]   {context_type:>9} | task={task_name:>20} | layer={layer:2d} | "
                    f"val_acc={val_acc_mlp:.3f} | prec={val_prec_mlp:.3f} | "
                    f"rec={val_rec_mlp:.3f} | f1={val_f1_mlp:.3f}"
                )


# -------------------------
#  Training: SAE dense probes
# -------------------------


def train_sae_dense_for_context(
    context_type: str,
    sae_latents_per_layer: Dict[int, np.ndarray],
    y_correct: np.ndarray,
    y_recall_full: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    test_idx: np.ndarray,
    layers_for_sae: List[int],
    full_run: bool,
    balance: bool,
    rng: np.random.Generator,
    hook_type: str,
    probs_dict: Dict[str, np.ndarray],
    meta_dict: Dict[str, Dict[str, Any]],
    completed_keys: set,
    additional_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Train DenseLinear probes on SAE latents."""
    print(f"\n=== {context_type.upper()} :: SAE Dense probes ===")

    tasks = [
        ("correct", y_correct, None),
        ("correct_given_recall1", y_correct, (y_recall_full == 1.0)),
        ("recall_full", y_recall_full, None),
    ]

    num_epochs_dense = 10 if full_run else 3

    for task_name, y_all, train_restrict in tasks:
        for layer in layers_for_sae:
            X = sae_latents_per_layer[layer]

            if task_name == "correct_given_recall1" and train_restrict is not None:
                mask_train = train_restrict
                train_ids_task = train_idx[mask_train[train_idx]]
                val_ids_task = val_idx
                test_ids_task = test_idx
            else:
                train_ids_task = train_idx
                val_ids_task = val_idx
                test_ids_task = test_idx

            if len(train_ids_task) < 2:
                print(
                    f"[SAE|{context_type}|{task_name}] Skipping layer {layer}: "
                    f"not enough train examples ({len(train_ids_task)})."
                )
                continue

            if balance:
                if task_name in ("correct", "correct_given_recall1"):
                    train_ids_task = downsample_balanced(
                        train_ids_task, y_correct, rng
                    )
                elif task_name == "recall_full":
                    train_ids_task = downsample_balanced(
                        train_ids_task, y_recall_full, rng
                    )
                if len(train_ids_task) < 2:
                    print(
                        f"[SAE|{context_type}|{task_name}] Skipping layer {layer}: "
                        f"not enough train examples after balancing ({len(train_ids_task)})."
                    )
                    continue

            X_train, y_train = X[train_ids_task], y_all[train_ids_task]
            X_val, y_val = X[val_ids_task], y_all[val_ids_task]
            X_test, y_test = X[test_ids_task], y_all[test_ids_task]

            key = f"{context_type}__{task_name}__dense_sae__L{layer}__{hook_type}__sae"
            if key in completed_keys:
                print(f"[SAE-Dense] {context_type:>9} | task={task_name:>20} | layer={layer:2d} | SKIPPED (already completed)")
            else:
                cfg = ProbeConfig(
                    probe_type="dense_linear",
                    layer=layer,
                    task_name=task_name,
                    context_type=context_type,
                    hook_point=hook_type,
                    feature_space="sae",
                )
                probe = DenseLinearProbe(cfg)
                probe.fit(
                    X_train,
                    y_train,
                    val_x=X_val,
                    val_y=y_val,
                    num_epochs=num_epochs_dense,
                    lr=1e-3,
                    batch_size=256,
                    device=None,
                    verbose=False,
                )

                probs_all = probe.predict_proba(X)
                metadata = {
                    "context_type": context_type,
                    "task_name": task_name,
                    "probe_type": "dense_sae",
                    "layer": layer,
                    "hook_type": hook_type,
                    "feature_space": "sae",
                }
                # Save probe as individual file
                probe_file = os.path.join("trained_probes2", f"{key}.pt")
                probe.save(probe_file)
                save_probe_result(
                    key, probs_all.astype(np.float32), metadata,
                    probs_dict, meta_dict, completed_keys, additional_data
                )

                val_probs = probs_all[val_ids_task]
                val_preds = (val_probs >= 0.5).astype(np.float32)
                val_acc, val_prec, val_rec, val_f1 = calculate_metrics(y_val, val_preds)
                print(
                    f"[SAE-Dense] {context_type:>9} | task={task_name:>20} | layer={layer:2d} | "
                    f"val_acc={val_acc:.3f} | prec={val_prec:.3f} | rec={val_rec:.3f} | f1={val_f1:.3f}"
                )


# -------------------------
#  Streaming attention probes
# -------------------------


def train_attention_for_context_streaming(
    context_type: str,
    tokens_list: List[torch.Tensor],
    lengths: List[int],
    model: HookedTransformer,
    y_correct: np.ndarray,
    y_recall_full: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    test_idx: np.ndarray,
    layers_for_attn: List[int],
    full_run: bool,
    balance: bool,
    rng: np.random.Generator,
    hook_type: str,
    probs_dict: Dict[str, np.ndarray],
    meta_dict: Dict[str, Dict[str, Any]],
    completed_keys: set,
    additional_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Train attention-style pooling probes by streaming through the model."""
    print(f"\n=== {context_type.upper()} :: Streaming AttentionPooling probes ===")

    from probes import StreamingAttentionProbe  # avoid circular import at top

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    tasks = [
        ("correct", y_correct, None),
        ("correct_given_recall1", y_correct, (y_recall_full == 1.0)),
        ("recall_full", y_recall_full, None),
    ]

    num_epochs = 3 if full_run else 1
    batch_size = 2

    N = len(tokens_list)
    lengths_np = np.array(lengths, dtype=np.int64)

    for task_name, y_all, train_restrict in tasks:
        for layer in layers_for_attn:
            key = (
                f"{context_type}__{task_name}__attn_pool__"
                f"L{layer}__{hook_type}__resid"
            )
            if key in completed_keys:
                print(f"[Attn]  {context_type:>9} | task={task_name:>20} | layer={layer:2d} | SKIPPED (already completed)")
                continue

            hook_name = f"blocks.{layer}.hook_{hook_type}"

            if task_name == "correct_given_recall1" and train_restrict is not None:
                mask_train = train_restrict
                train_ids_task = train_idx[mask_train[train_idx]]
                val_ids_task = val_idx
                test_ids_task = test_idx
            else:
                train_ids_task = train_idx
                val_ids_task = val_idx
                test_ids_task = test_idx

            if len(train_ids_task) < 2:
                print(
                    f"[Attn|{context_type}|{task_name}] Skipping layer {layer}: "
                    f"not enough train examples ({len(train_ids_task)})."
                )
                continue

            if balance:
                if task_name in ("correct", "correct_given_recall1"):
                    train_ids_task = downsample_balanced(
                        train_ids_task, y_correct, rng
                    )
                elif task_name == "recall_full":
                    train_ids_task = downsample_balanced(
                        train_ids_task, y_recall_full, rng
                    )
                if len(train_ids_task) < 2:
                    print(
                        f"[Attn|{context_type}|{task_name}] Skipping layer {layer}: "
                        f"not enough train examples after balancing ({len(train_ids_task)})."
                    )
                    continue

            d_model = model.cfg.d_model
            probe = StreamingAttentionProbe(d_model=d_model, hidden_dim=128).to(device)
            optimizer = torch.optim.AdamW(probe.parameters(), lr=1e-3, weight_decay=0.0)
            criterion = torch.nn.BCEWithLogitsLoss()

            # Train
            for epoch in range(num_epochs):
                rng.shuffle(train_ids_task)
                total_loss = 0.0
                n_batches = 0

                for start_idx in range(0, len(train_ids_task), batch_size):
                    batch_ids = train_ids_task[start_idx : start_idx + batch_size]
                    B = len(batch_ids)
                    if B == 0:
                        continue

                    batch_lens = lengths_np[batch_ids]
                    max_len = int(batch_lens.max())
                    input_ids = torch.zeros(
                        (B, max_len), dtype=torch.long, device=device
                    )
                    for j, idx in enumerate(batch_ids):
                        toks = tokens_list[int(idx)].to(device)
                        L = toks.shape[0]
                        input_ids[j, :L] = toks

                    lengths_t = torch.tensor(
                        batch_lens, dtype=torch.long, device=device
                    )

                    with torch.no_grad():
                        logits_model, cache = model.run_with_cache(
                            input_ids,
                            return_type="logits",
                            names_filter=lambda name: name == hook_name,
                        )
                        H = cache[hook_name].float()
                    del logits_model, cache

                    y_batch = torch.tensor(
                        y_all[batch_ids], dtype=torch.float32, device=device
                    )

                    probe.train()
                    optimizer.zero_grad()
                    logits_probe = probe(H, lengths_t)
                    loss = criterion(logits_probe, y_batch)
                    loss.backward()
                    optimizer.step()

                    total_loss += float(loss.item())
                    n_batches += 1

                    del H, logits_probe, y_batch, input_ids, lengths_t
                    if device.type == "cuda":
                        torch.cuda.empty_cache()

                if n_batches > 0:
                    avg_loss = total_loss / n_batches
                    print(
                        f"[Attn] {context_type:>9} | task={task_name:>20} | "
                        f"layer={layer:2d} | epoch={epoch+1}/{num_epochs} "
                        f"| train_loss={avg_loss:.4f}"
                    )

            # Compute probs for all examples
            probe.eval()
            probs_all = np.zeros(N, dtype=np.float32)
            all_ids = np.arange(N, dtype=np.int64)

            with torch.no_grad():
                for start_idx in range(0, N, batch_size):
                    batch_ids = all_ids[start_idx : start_idx + batch_size]
                    B = len(batch_ids)
                    if B == 0:
                        continue

                    batch_lens = lengths_np[batch_ids]
                    max_len = int(batch_lens.max())
                    input_ids = torch.zeros(
                        (B, max_len), dtype=torch.long, device=device
                    )
                    for j, idx in enumerate(batch_ids):
                        toks = tokens_list[int(idx)].to(device)
                        L = toks.shape[0]
                        input_ids[j, :L] = toks

                    lengths_t = torch.tensor(
                        batch_lens, dtype=torch.long, device=device
                    )

                    logits_model, cache = model.run_with_cache(
                        input_ids,
                        return_type="logits",
                        names_filter=lambda name: name == hook_name,
                    )
                    H = cache[hook_name].float()
                    del logits_model, cache

                    logits_probe = probe(H, lengths_t)
                    probs_batch = torch.sigmoid(logits_probe).cpu().numpy().astype(
                        np.float32
                    )
                    probs_all[batch_ids] = probs_batch

                    del H, logits_probe, input_ids, lengths_t, probs_batch
                    if device.type == "cuda":
                        torch.cuda.empty_cache()

            metadata = {
                "context_type": context_type,
                "task_name": task_name,
                "probe_type": "attn_pool",
                "layer": layer,
                "hook_type": hook_type,
                "feature_space": "resid",
            }
            save_probe_result(
                key, probs_all, metadata,
                probs_dict, meta_dict, completed_keys, additional_data
            )

            y_val = y_all[val_idx]
            val_probs = probs_all[val_idx]
            val_preds = (val_probs >= 0.5).astype(np.float32)
            val_acc, val_prec, val_rec, val_f1 = calculate_metrics(y_val, val_preds)
            print(
                f"[Attn]  {context_type:>9} | task={task_name:>20} | layer={layer:2d} | "
                f"VAL: acc={val_acc:.3f} | prec={val_prec:.3f} | "
                f"rec={val_rec:.3f} | f1={val_f1:.3f}"
            )


# -------------------------
#  Checkpointing
# -------------------------


def get_checkpoint_path() -> str:
    return os.path.join("trained_probes2", "checkpoint.pt")


def load_checkpoint() -> Tuple[Dict[str, np.ndarray], Dict[str, Dict[str, Any]], set]:
    checkpoint_path = get_checkpoint_path()
    if os.path.exists(checkpoint_path):
        print(f"Loading checkpoint from {checkpoint_path}...")
        checkpoint = torch.load(checkpoint_path, map_location="cpu")
        probs_dict = checkpoint.get("probs", {})
        meta_dict = checkpoint.get("meta", {})
        completed_keys = set(checkpoint.get("completed_keys", []))
        print(f"  Loaded {len(completed_keys)} completed probes")
        return probs_dict, meta_dict, completed_keys
    else:
        print("No checkpoint found, starting fresh")
        return {}, {}, set()


def save_checkpoint(
    probs_dict: Dict[str, np.ndarray],
    meta_dict: Dict[str, Dict[str, Any]],
    completed_keys: set,
    additional_data: Optional[Dict[str, Any]] = None,
) -> None:
    checkpoint_path = get_checkpoint_path()
    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)

    checkpoint: Dict[str, Any] = {
        "probs": probs_dict,
        "meta": meta_dict,
        "completed_keys": list(completed_keys),
    }
    if additional_data:
        checkpoint.update(additional_data)

    torch.save(checkpoint, checkpoint_path)
    print(f"  Checkpoint saved ({len(completed_keys)} probes completed)")


def save_probe_result(
    key: str,
    probs: np.ndarray,
    metadata: Dict[str, Any],
    probs_dict: Dict[str, np.ndarray],
    meta_dict: Dict[str, Dict[str, Any]],
    completed_keys: set,
    additional_data: Optional[Dict[str, Any]] = None,
) -> None:
    probs_dict[key] = probs
    meta_dict[key] = metadata
    completed_keys.add(key)
    save_checkpoint(probs_dict, meta_dict, completed_keys, additional_data)


# -------------------------
#  Main
# -------------------------


def main(
    mode: str,
    balance: bool = False,
    use_sae_probes: bool = False,
    use_attention_probes: bool = False,
    hook_type: str = "resid_post",
    restart: bool = False,
    token_pooling: str = "single",
    pool_k: int = 4,
    token_offset: int = 0,
    include_subanswer: bool = True,
) -> None:
    assert hook_type in ("resid_post", "resid_pre")
    assert token_pooling in ("single", "mean_last_k")
    full_run = mode != "test"
    print(
        f"Running mode={mode!r} (full_run={full_run}, balance={balance}, "
        f"use_sae_probes={use_sae_probes}, use_attention_probes={use_attention_probes}, "
        f"hook_type={hook_type}, restart={restart}, token_pooling={token_pooling}, "
        f"pool_k={pool_k}, token_offset={token_offset}, include_subanswer={include_subanswer})"
    )

    os.makedirs("trained_probes2", exist_ok=True)

    if restart:
        print("Restarting from scratch (ignoring any existing checkpoint)")
        probs_dict: Dict[str, np.ndarray] = {}
        meta_dict: Dict[str, Dict[str, Any]] = {}
        completed_keys: set = set()
    else:
        probs_dict, meta_dict, completed_keys = load_checkpoint()

    rng = np.random.default_rng(42)
    torch.manual_seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)

    # Load dataset
    (
        contexts_dict,
        y_correct,
        y_recall_full,
        y_subanswer_correct,
        y_subanswer_recall_full,
        question_to_subanswer_indices,
    ) = load_hotpot_decomp_dataset(JSON_DATASET_PATH)
    n_total = len(contexts_dict["planning"])
    n_subanswer_total = len(contexts_dict["subanswer"])
    print(f"Loaded {n_total} examples from dataset ({n_subanswer_total} subanswers).")

    # Subsample questions
    if full_run:
        max_examples = min(3000, n_total)
    else:
        max_examples = min(32, n_total)

    question_indices = np.arange(n_total)
    rng.shuffle(question_indices)
    question_indices = question_indices[:max_examples]
    question_indices_sorted = np.sort(question_indices)

    # Subsample contexts for planning and final (one per question)
    contexts_dict["planning"] = [contexts_dict["planning"][i] for i in question_indices_sorted]
    contexts_dict["final"] = [contexts_dict["final"][i] for i in question_indices_sorted]
    y_correct = y_correct[question_indices_sorted]
    y_recall_full = y_recall_full[question_indices_sorted]

    # Subsample subanswers
    subanswer_indices_list: List[int] = []
    question_to_subanswer_indices_subsampled: List[List[int]] = []
    for q_idx in question_indices_sorted:
        sa_indices = question_to_subanswer_indices[q_idx]
        new_sa_indices = []
        for old_sa_idx in sa_indices:
            new_sa_idx = len(subanswer_indices_list)
            subanswer_indices_list.append(old_sa_idx)
            new_sa_indices.append(new_sa_idx)
        question_to_subanswer_indices_subsampled.append(new_sa_indices)

    contexts_dict["subanswer"] = [contexts_dict["subanswer"][i] for i in subanswer_indices_list]
    y_subanswer_correct = y_subanswer_correct[subanswer_indices_list]
    y_subanswer_recall_full = y_subanswer_recall_full[subanswer_indices_list]

    n = len(contexts_dict["planning"])
    n_subanswer = len(contexts_dict["subanswer"])
    print(f"Using {n} examples after subsampling (max_examples={max_examples}, {n_subanswer} subanswers).")

    # Splits for questions
    train_idx, val_idx, test_idx = make_splits(n, rng)
    print(
        f"Question split sizes: train={len(train_idx)}, val={len(val_idx)}, "
        f"test={len(test_idx)}"
    )

    # Splits for subanswers
    subanswer_train_idx_list: List[int] = []
    subanswer_val_idx_list: List[int] = []
    subanswer_test_idx_list: List[int] = []
    for q_idx in train_idx:
        subanswer_train_idx_list.extend(question_to_subanswer_indices_subsampled[q_idx])
    for q_idx in val_idx:
        subanswer_val_idx_list.extend(question_to_subanswer_indices_subsampled[q_idx])
    for q_idx in test_idx:
        subanswer_test_idx_list.extend(question_to_subanswer_indices_subsampled[q_idx])
    subanswer_train_idx = np.array(subanswer_train_idx_list, dtype=np.int64)
    subanswer_val_idx = np.array(subanswer_val_idx_list, dtype=np.int64)
    subanswer_test_idx = np.array(subanswer_test_idx_list, dtype=np.int64)
    print(
        f"Subanswer split sizes: train={len(subanswer_train_idx)}, val={len(subanswer_val_idx)}, "
        f"test={len(subanswer_test_idx)}"
    )

    additional_data = {
        "y_correct": y_correct,
        "y_recall_full": y_recall_full,
        "train_idx": train_idx,
        "val_idx": val_idx,
        "test_idx": test_idx,
        "y_subanswer_correct": y_subanswer_correct,
        "y_subanswer_recall_full": y_subanswer_recall_full,
        "subanswer_train_idx": subanswer_train_idx,
        "subanswer_val_idx": subanswer_val_idx,
        "subanswer_test_idx": subanswer_test_idx,
        "token_pooling": token_pooling,
        "pool_k": pool_k,
        "token_offset": token_offset,
    }

    # Load model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading model 'meta-llama/Llama-3.1-8B-Instruct' on device={device}...")
    model = HookedTransformer.from_pretrained(
        "meta-llama/Llama-3.1-8B-Instruct",
        device=str(device),
        dtype=torch.float16,
    )

    # Decide layers
    preferred_layers = [4, 8, 12, 16, 20, 24, 28, 31]
    n_layers = model.cfg.n_layers
    layers_available = [l for l in preferred_layers if l < n_layers]
    if not layers_available:
        layers_available = list(range(n_layers))

    if full_run:
        layers_to_probe = layers_available
        layers_for_attn = (
            layers_available[-2:] if len(layers_available) >= 2 else layers_available
        )
        layers_for_sae = (
            layers_available[-4:] if len(layers_available) >= 4 else layers_available
        )
    else:
        layers_to_probe = [layers_available[-1]]
        layers_for_attn = layers_to_probe
        layers_for_sae = layers_to_probe

    print(f"Layers_to_probe = {layers_to_probe}")
    if use_attention_probes:
        print(f"Layers_for_attention = {layers_for_attn}")
    if use_sae_probes:
        print(f"Layers_for_SAE = {layers_for_sae}")

    # Per context type
    context_types = ["planning", "final"]
    if include_subanswer:
        context_types.insert(1, "subanswer")
    
    for context_type in context_types:
        print(f"\n{'='*70}\nProcessing context type: {context_type}\n{'='*70}")
        texts = contexts_dict[context_type]

        if context_type == "subanswer":
            y_ctx_correct = y_subanswer_correct
            y_ctx_recall_full = y_subanswer_recall_full
            ctx_train_idx = subanswer_train_idx
            ctx_val_idx = subanswer_val_idx
            ctx_test_idx = subanswer_test_idx
        else:
            y_ctx_correct = y_correct
            y_ctx_recall_full = y_recall_full
            ctx_train_idx = train_idx
            ctx_val_idx = val_idx
            ctx_test_idx = test_idx

        # Tokenize (no truncation)
        tokens_list, lengths = tokenize_contexts(model, texts)

        # Pooled activations
        final_acts = compute_token_activations(
            model,
            tokens_list,
            lengths,
            layers_to_probe,
            hook_type=hook_type,
            full_run=full_run,
            token_pooling=token_pooling,
            pool_k=pool_k,
            token_offset=token_offset,
        )

        # Dense / MassMean / MLP
        train_dense_mass_mlp_for_context(
            context_type,
            final_acts,
            y_ctx_correct,
            y_ctx_recall_full,
            ctx_train_idx,
            ctx_val_idx,
            ctx_test_idx,
            layers_to_probe,
            full_run=full_run,
            balance=balance,
            rng=rng,
            hook_type=hook_type,
            probs_dict=probs_dict,
            meta_dict=meta_dict,
            completed_keys=completed_keys,
            additional_data=additional_data,
        )

        # SAE probes
        if use_sae_probes:
            sae_latents = compute_sae_latents_per_layer(
                final_acts,
                layers_for_sae,
                device=device,
            )
            train_sae_dense_for_context(
                context_type,
                sae_latents,
                y_ctx_correct,
                y_ctx_recall_full,
                ctx_train_idx,
                ctx_val_idx,
                ctx_test_idx,
                layers_for_sae,
                full_run=full_run,
                balance=balance,
                rng=rng,
                hook_type=hook_type,
                probs_dict=probs_dict,
                meta_dict=meta_dict,
                completed_keys=completed_keys,
                additional_data=additional_data,
            )

        # Attention probes
        if use_attention_probes:
            train_attention_for_context_streaming(
                context_type,
                tokens_list,
                lengths,
                model,
                y_ctx_correct,
                y_ctx_recall_full,
                ctx_train_idx,
                ctx_val_idx,
                ctx_test_idx,
                layers_for_attn,
                full_run=full_run,
                balance=balance,
                rng=rng,
                hook_type=hook_type,
                probs_dict=probs_dict,
                meta_dict=meta_dict,
                completed_keys=completed_keys,
                additional_data=additional_data,
            )

    # Free model
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Save predictions + metadata
    payload = {
        "y_correct": y_correct,
        "y_recall_full": y_recall_full,
        "train_idx": train_idx,
        "val_idx": val_idx,
        "test_idx": test_idx,
        "y_subanswer_correct": y_subanswer_correct,
        "y_subanswer_recall_full": y_subanswer_recall_full,
        "subanswer_train_idx": subanswer_train_idx,
        "subanswer_val_idx": subanswer_val_idx,
        "subanswer_test_idx": subanswer_test_idx,
        "probs": probs_dict,
        "meta": meta_dict,
        "token_pooling": token_pooling,
        "pool_k": pool_k,
        "token_offset": token_offset,
    }
    out_path = os.path.join("trained_probes2", "probe_predictions.pt")
    torch.save(payload, out_path)
    print(f"\nSaved per-example probabilities + metadata to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Train probes on Llama-3.1-8B-Instruct activations for HotpotQA "
            "decomposition dataset, and save per-example probabilities."
        )
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["full", "test"],
        default="full",
        help="Run mode: 'full' (default) or 'test' for a tiny smoke test.",
    )
    parser.add_argument(
        "--balance",
        action="store_true",
        default=False,
        help="Balance the training split for each task (downsample positives/negatives).",
    )
    parser.add_argument(
        "--use_sae_probes",
        action="store_true",
        default=False,
        help="Also train SAE-based dense probes (requires sae_lens).",
    )
    parser.add_argument(
        "--use_attention_probes",
        action="store_true",
        default=False,
        help="Also train attention-style pooling probes over all tokens (streaming).",
    )
    parser.add_argument(
        "--hook_type",
        choices=["resid_post", "resid_pre"],
        default="resid_post",
        help="Which residual stream hook to use (default: resid_post).",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        default=False,
        help="Restart training from scratch, ignoring any existing checkpoint.",
    )
    parser.add_argument(
        "--token_pooling",
        choices=["single", "mean_last_k"],
        default="single",
        help=(
            "How to pool token activations before probing: "
            "'single' (a single token from the end, offset by --token_offset) or "
            "'mean_last_k' (mean over last --pool_k tokens)."
        ),
    )
    parser.add_argument(
        "--pool_k",
        type=int,
        default=3,
        help="Number of tokens to pool over for 'mean_last_k' token pooling.",
    )
    parser.add_argument(
        "--token_offset",
        type=int,
        default=0,
        help=(
            "Offset from the final token when token_pooling='single'. "
            "0 = last token, 1 = second-to-last, etc."
        ),
    )
    parser.add_argument(
        "--no_subanswer",
        action="store_true",
        default=False,
        help="Skip training probes on subanswer contexts (default: include subanswer training).",
    )

    args = parser.parse_args()
    main(
        args.mode,
        balance=args.balance,
        use_sae_probes=args.use_sae_probes,
        use_attention_probes=args.use_attention_probes,
        hook_type=args.hook_type,
        restart=args.restart,
        token_pooling=args.token_pooling,
        pool_k=args.pool_k,
        token_offset=args.token_offset,
        include_subanswer=not args.no_subanswer,
    )
