# mateo/sweep_thresholds.py

from __future__ import annotations

import argparse
import os
from typing import Dict, Any, List

import numpy as np
import torch


def calculate_metrics_for_class_0(
    y_true: np.ndarray, y_pred: np.ndarray
) -> tuple[float, float, float, float]:
    """Calculate precision, recall, F1 for class 0 (negative class).
    
    For class 0:
    - precision = correctly predicted 0 / total predicted 0
    - recall = correctly predicted 0 / total 0s
    """
    y_true = y_true.astype(np.float32)
    y_pred = y_pred.astype(np.float32)

    accuracy = float((y_pred == y_true).mean())
    # For class 0: tp = predicted 0 and true 0, fp = predicted 0 and true 1, fn = predicted 1 and true 0
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


def main(pred_path: str, split: str = "val") -> None:
    if not os.path.exists(pred_path):
        raise FileNotFoundError(f"Prediction file not found at: {pred_path}")

    print(f"Loading predictions from {pred_path}...")
    payload = torch.load(pred_path, map_location="cpu", weights_only=False)

    y_correct = np.asarray(payload["y_correct"], dtype=np.float32)
    y_recall_full = np.asarray(payload["y_recall_full"], dtype=np.float32)
    train_idx = np.asarray(payload["train_idx"], dtype=np.int64)
    val_idx = np.asarray(payload["val_idx"], dtype=np.int64)
    test_idx = np.asarray(payload["test_idx"], dtype=np.int64)
    
    # Load subanswer labels and indices (if present)
    y_subanswer_correct = np.asarray(
        payload.get("y_subanswer_correct", payload["y_correct"]), dtype=np.float32
    )
    y_subanswer_recall_full = np.asarray(
        payload.get("y_subanswer_recall_full", payload["y_recall_full"]), dtype=np.float32
    )
    subanswer_train_idx = np.asarray(
        payload.get("subanswer_train_idx", payload["train_idx"]), dtype=np.int64
    )
    subanswer_val_idx = np.asarray(
        payload.get("subanswer_val_idx", payload["val_idx"]), dtype=np.int64
    )
    subanswer_test_idx = np.asarray(
        payload.get("subanswer_test_idx", payload["test_idx"]), dtype=np.int64
    )
    
    probs_dict: Dict[str, np.ndarray] = {
        k: np.asarray(v, dtype=np.float32) for k, v in payload["probs"].items()
    }
    meta_dict: Dict[str, Dict[str, Any]] = dict(payload["meta"])

    if split == "val":
        idx = val_idx
        subanswer_idx = subanswer_val_idx
        split_name = "val"
    elif split == "test":
        idx = test_idx
        subanswer_idx = subanswer_test_idx
        split_name = "test"
    elif split == "train":
        idx = train_idx
        subanswer_idx = subanswer_train_idx
        split_name = "train"
    else:
        raise ValueError("split must be one of {'train','val','test'}")

    print(f"Running threshold sweeps on split={split_name} (size={len(idx)} for questions, {len(subanswer_idx)} for subanswers)...")

    rows: List[str] = []
    header = "threshold,stage_probe,answer_or_retrieval,precision,recall,f1"
    rows.append(header)

    for key, probs_all in probs_dict.items():
        meta = meta_dict[key]
        context_type = meta["context_type"]
        task_name = meta["task_name"]
        probe_type = meta["probe_type"]
        layer = meta["layer"]

        # Use subanswer-specific labels and indices for subanswer probes
        if context_type == "subanswer":
            if task_name in ("correct", "correct_given_recall1"):
                y_full = y_subanswer_correct
                task_kind = "answer"
            elif task_name == "recall_full":
                y_full = y_subanswer_recall_full
                task_kind = "retrieval"
            else:
                # Unknown / unsupported task
                continue
            split_idx = subanswer_idx
        else:
            if task_name in ("correct", "correct_given_recall1"):
                y_full = y_correct
                task_kind = "answer"
            elif task_name == "recall_full":
                y_full = y_recall_full
                task_kind = "retrieval"
            else:
                # Unknown / unsupported task
                continue
            split_idx = idx

        y_split = y_full[split_idx]
        p_split = probs_all[split_idx]

        # Need both classes present to make F1 meaningful
        if len(np.unique(y_split)) < 2:
            print(
                f"[WARN] Skipping probe {key}: only one label present on split={split_name}."
            )
            continue

        # Candidate thresholds: 0.1, 0.2, 0.3, ..., 0.9
        thresholds = np.arange(0.1, 1.0, 0.1)

        # Get pooling info from metadata (for backward compatibility, use defaults if not present)
        token_pooling = meta.get("token_pooling", "single")
        pool_k = meta.get("pool_k", 4)
        token_offset = meta.get("token_offset", 0)
        
        # Create pooling suffix
        if token_pooling == "single":
            pool_suffix = f"__offset{token_offset}"
        else:  # mean_last_k
            pool_suffix = f"__pool{pool_k}"
        
        stage_probe = f"{context_type}_L{layer}_{probe_type}_{task_name}{pool_suffix}"

        for t in thresholds:
            preds = (p_split >= t).astype(np.float32)
            # Calculate metrics for class 0 (negative class)
            # For answer: precision = correctly predicted 0 / total predicted 0, recall = correctly predicted 0 / total 0s
            # For retrieval: precision = correctly predicted 0 (recall<1) / total predicted 0, recall = correctly predicted 0 / total 0s
            # Note: For retrieval, y_full is already y_recall_full, so y_full == 0 means recall < 1
            _, prec, rec, f1 = calculate_metrics_for_class_0(y_split, preds)
            row = f"{t:.6f},{stage_probe},{task_kind},{prec:.6f},{rec:.6f},{f1:.6f}"
            rows.append(row)

    out_csv = os.path.join(
        os.path.dirname(pred_path), f"threshold_sweep_{split_name}.csv"
    )
    with open(out_csv, "w", encoding="utf-8") as f:
        for line in rows:
            f.write(line + "\n")

    print(f"Saved threshold sweep results to {out_csv}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run threshold sweeps over all trained probes and output CSV "
            "with precision/recall/F1 vs threshold."
        )
    )
    parser.add_argument(
        "--pred_path",
        type=str,
        default=os.path.join("trained_probes2", "probe_predictions.pt"),
        help="Path to probe_predictions.pt saved by train_probes.py.",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "test"],
        default="val",
        help="Dataset split to evaluate thresholds on (default: val).",
    )
    args = parser.parse_args()
    main(args.pred_path, split=args.split)
