"""
Evaluation metrics for HotpotQA.

Implements Exact Match (EM) and F1 score following official HotpotQA evaluation.
"""

from __future__ import annotations

import json
import logging
import re
import string
from collections import Counter
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# Answer Normalization
# =============================================================================

def normalize_answer(text: str) -> str:
    """
    Normalize answer string for evaluation.
    
    Following official HotpotQA/SQuAD normalization:
    - Lowercase
    - Remove articles (a, an, the)
    - Remove punctuation
    - Normalize whitespace
    
    Args:
        text: Answer string
        
    Returns:
        Normalized string
    """
    # Lowercase
    text = text.lower()
    
    # Remove articles
    text = re.sub(r'\b(a|an|the)\b', ' ', text)
    
    # Remove punctuation
    text = ''.join(ch for ch in text if ch not in string.punctuation)
    
    # Normalize whitespace
    text = ' '.join(text.split())
    
    return text


# =============================================================================
# Core Metrics
# =============================================================================

def exact_match(prediction: str, gold: str) -> float:
    """
    Calculate Exact Match score.
    
    Args:
        prediction: Predicted answer
        gold: Gold answer
        
    Returns:
        1.0 if exact match, 0.0 otherwise
    """
    return float(normalize_answer(prediction) == normalize_answer(gold))


def precision_recall_f1(prediction: str, gold: str) -> Dict[str, float]:
    """
    Calculate token-level precision, recall, and F1 score.
    
    Args:
        prediction: Predicted answer
        gold: Gold answer
        
    Returns:
        Dictionary with 'precision', 'recall', and 'f1' scores
    """
    pred_tokens = normalize_answer(prediction).split()
    gold_tokens = normalize_answer(gold).split()
    
    if not pred_tokens or not gold_tokens:
        match = float(pred_tokens == gold_tokens)
        return {
            "precision": match,
            "recall": match,
            "f1": match
        }
    
    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    
    if num_same == 0:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0
        }
    
    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1
    }


def f1_score(prediction: str, gold: str) -> float:
    """
    Calculate token-level F1 score (backward compatibility).
    
    Args:
        prediction: Predicted answer
        gold: Gold answer
        
    Returns:
        F1 score between 0 and 1
    """
    return precision_recall_f1(prediction, gold)["f1"]


# =============================================================================
# Evaluation Functions
# =============================================================================

def evaluate_single(prediction: str, gold: str) -> Dict[str, float]:
    """Evaluate a single prediction."""
    prf = precision_recall_f1(prediction, gold)
    return {
        "em": exact_match(prediction, gold),
        "precision": prf["precision"],
        "recall": prf["recall"],
        "f1": prf["f1"]
    }


def evaluate(
    predictions: List[Dict],
    gold_data: Optional[List[Dict]] = None
) -> Dict:
    """
    Evaluate predictions against gold answers.
    
    Args:
        predictions: List of predictions with 'answer' and '_id'
        gold_data: Optional gold data (if not in predictions)
        
    Returns:
        Evaluation results
    """
    # Build gold lookup
    gold_lookup = {}
    if gold_data:
        for item in gold_data:
            gold_lookup[item.get("_id", "")] = item.get("answer", "")
    
    em_scores = []
    precision_scores = []
    recall_scores = []
    f1_scores = []
    results_by_id = {}
    
    for pred in predictions:
        pred_id = pred.get("_id", "")
        pred_answer = pred.get("answer", "")
        
        # Get gold answer
        gold_answer = pred.get("gold_answer", "") or gold_lookup.get(pred_id, "")
        
        if not gold_answer:
            logger.warning(f"No gold answer for id: {pred_id}")
            continue
        
        em = exact_match(pred_answer, gold_answer)
        prf = precision_recall_f1(pred_answer, gold_answer)
        
        em_scores.append(em)
        precision_scores.append(prf["precision"])
        recall_scores.append(prf["recall"])
        f1_scores.append(prf["f1"])
        
        results_by_id[pred_id] = {
            "prediction": pred_answer,
            "gold": gold_answer,
            "em": em,
            "precision": prf["precision"],
            "recall": prf["recall"],
            "f1": prf["f1"]
        }
    
    n = len(em_scores)
    return {
        "exact_match": sum(em_scores) / n if n > 0 else 0.0,
        "precision": sum(precision_scores) / n if n > 0 else 0.0,
        "recall": sum(recall_scores) / n if n > 0 else 0.0,
        "f1": sum(f1_scores) / n if n > 0 else 0.0,
        "num_evaluated": n,
        "results_by_id": results_by_id
    }


def evaluate_retrieval(
    predictions: List[Dict],
    gold_data: List[Dict]
) -> Dict:
    """
    Evaluate retrieval quality.
    
    Args:
        predictions: Predictions with retrieved paragraphs
        gold_data: Gold data with supporting facts
        
    Returns:
        Retrieval metrics
    """
    # Build gold supporting paragraphs lookup
    gold_lookup = {}
    for item in gold_data:
        item_id = item.get("_id", "")
        supporting_facts = item.get("supporting_facts", [])
        gold_lookup[item_id] = {sf[0] for sf in supporting_facts}
    
    precision_scores = []
    recall_scores = []
    f1_scores = []
    
    for pred in predictions:
        pred_id = pred.get("_id", "")
        
        if pred_id not in gold_lookup:
            continue
        
        gold_paragraphs = gold_lookup[pred_id]
        
        # Get retrieved titles
        retrieved_titles = set()
        full_result = pred.get("full_result", {})
        
        if full_result:
            retrieved = full_result.get("retrieved_paragraphs", [])
            retrieved_titles = {p.get("title", "") for p in retrieved}
        
        if not retrieved_titles:
            retrieved = pred.get("retrieved_paragraphs", [])
            if retrieved:
                retrieved_titles = {p.get("title", "") for p in retrieved}
        
        if not retrieved_titles or not gold_paragraphs:
            precision_scores.append(0.0)
            recall_scores.append(0.0)
            f1_scores.append(0.0)
            continue
        
        # Calculate metrics
        tp = len(gold_paragraphs & retrieved_titles)
        precision = tp / len(retrieved_titles)
        recall = tp / len(gold_paragraphs)
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        precision_scores.append(precision)
        recall_scores.append(recall)
        f1_scores.append(f1)
    
    n = len(precision_scores)
    return {
        "retrieval_precision": sum(precision_scores) / n if n > 0 else 0.0,
        "retrieval_recall": sum(recall_scores) / n if n > 0 else 0.0,
        "retrieval_f1": sum(f1_scores) / n if n > 0 else 0.0,
        "num_evaluated": n
    }


def detailed_evaluation(
    predictions: List[Dict],
    gold_data: List[Dict],
    by_type: bool = True,
    by_level: bool = True
) -> Dict:
    """
    Detailed evaluation with breakdowns.
    
    Args:
        predictions: List of predictions
        gold_data: Gold data
        by_type: Include breakdown by question type
        by_level: Include breakdown by difficulty level
        
    Returns:
        Comprehensive evaluation results
    """
    gold_lookup = {item["_id"]: item for item in gold_data}
    
    results = {
        "overall": evaluate(predictions, gold_data),
        "retrieval": evaluate_retrieval(predictions, gold_data)
    }
    
    if by_type:
        by_type_groups: Dict[str, List[Dict]] = {}
        for pred in predictions:
            item = gold_lookup.get(pred.get("_id", ""), {})
            q_type = item.get("type", "unknown")
            by_type_groups.setdefault(q_type, []).append(pred)
        
        results["by_type"] = {}
        for q_type, preds in by_type_groups.items():
            gold_subset = [gold_lookup[p["_id"]] for p in preds if p["_id"] in gold_lookup]
            eval_result = evaluate(preds, gold_subset)
        results["by_type"][q_type] = {
            "exact_match": eval_result["exact_match"],
            "precision": eval_result.get("precision", 0.0),
            "recall": eval_result.get("recall", 0.0),
            "f1": eval_result["f1"],
            "num_evaluated": eval_result["num_evaluated"]
        }
    
    if by_level:
        by_level_groups: Dict[str, List[Dict]] = {}
        for pred in predictions:
            item = gold_lookup.get(pred.get("_id", ""), {})
            level = item.get("level", "unknown")
            by_level_groups.setdefault(level, []).append(pred)
        
        results["by_level"] = {}
        for level, preds in by_level_groups.items():
            gold_subset = [gold_lookup[p["_id"]] for p in preds if p["_id"] in gold_lookup]
            eval_result = evaluate(preds, gold_subset)
        results["by_level"][level] = {
            "exact_match": eval_result["exact_match"],
            "precision": eval_result.get("precision", 0.0),
            "recall": eval_result.get("recall", 0.0),
            "f1": eval_result["f1"],
            "num_evaluated": eval_result["num_evaluated"]
        }
    
    return results


# =============================================================================
# Reporting
# =============================================================================

def format_report(results: Dict) -> str:
    """
    Format evaluation results as readable report.
    
    Args:
        results: Evaluation results
        
    Returns:
        Formatted report string
    """
    lines = [
        "=" * 60,
        "EVALUATION REPORT",
        "=" * 60,
        ""
    ]
    
    # Overall
    overall = results.get("overall", {})
    lines.append("Overall Performance:")
    lines.append(f"  Exact Match: {overall.get('exact_match', 0):.4f} ({overall.get('exact_match', 0)*100:.2f}%)")
    lines.append(f"  Precision:   {overall.get('precision', 0):.4f} ({overall.get('precision', 0)*100:.2f}%)")
    lines.append(f"  Recall:      {overall.get('recall', 0):.4f} ({overall.get('recall', 0)*100:.2f}%)")
    lines.append(f"  F1 Score:    {overall.get('f1', 0):.4f} ({overall.get('f1', 0)*100:.2f}%)")
    lines.append(f"  Evaluated:   {overall.get('num_evaluated', 0)} instances")
    
    # Retrieval
    retrieval = results.get("retrieval", {})
    if retrieval and retrieval.get("num_evaluated", 0) > 0:
        lines.append("")
        lines.append("Retrieval Performance:")
        lines.append(f"  Precision: {retrieval.get('retrieval_precision', 0):.4f}")
        lines.append(f"  Recall:    {retrieval.get('retrieval_recall', 0):.4f}")
        lines.append(f"  F1 Score:  {retrieval.get('retrieval_f1', 0):.4f}")
    
    # By type
    by_type = results.get("by_type", {})
    if by_type:
        lines.append("")
        lines.append("By Question Type:")
        for q_type in sorted(by_type.keys()):
            m = by_type[q_type]
            lines.append(
                f"  {q_type}: EM={m.get('exact_match', 0):.4f}, "
                f"P={m.get('precision', 0):.4f}, R={m.get('recall', 0):.4f}, "
                f"F1={m.get('f1', 0):.4f}, N={m.get('num_evaluated', 0)}"
            )
    
    # By level
    by_level = results.get("by_level", {})
    if by_level:
        lines.append("")
        lines.append("By Difficulty:")
        for level in ["easy", "medium", "hard", "unknown"]:
            if level in by_level:
                m = by_level[level]
                lines.append(
                    f"  {level}: EM={m.get('exact_match', 0):.4f}, "
                    f"P={m.get('precision', 0):.4f}, R={m.get('recall', 0):.4f}, "
                    f"F1={m.get('f1', 0):.4f}, N={m.get('num_evaluated', 0)}"
                )
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def save_official_format(predictions: List[Dict], output_path: str) -> None:
    """
    Save predictions in official HotpotQA format.
    
    Args:
        predictions: List of predictions
        output_path: Output file path
    """
    output = {"answer": {}, "sp": {}}
    
    for pred in predictions:
        pred_id = pred.get("_id", "")
        output["answer"][pred_id] = pred.get("answer", "")
        
        if "supporting_facts" in pred:
            output["sp"][pred_id] = pred["supporting_facts"]
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"Saved predictions to {output_path}")


def error_analysis(
    predictions: List[Dict],
    gold_data: List[Dict],
    num_examples: int = 10
) -> Dict:
    """
    Analyze prediction errors.
    
    Args:
        predictions: List of predictions
        gold_data: Gold data
        num_examples: Number of examples to include
        
    Returns:
        Error analysis dictionary
    """
    gold_lookup = {item["_id"]: item for item in gold_data}
    
    errors = []
    correct = []
    
    for pred in predictions:
        pred_id = pred.get("_id", "")
        pred_answer = pred.get("answer", "")
        
        gold_item = gold_lookup.get(pred_id, {})
        gold_answer = gold_item.get("answer", "")
        
        em = exact_match(pred_answer, gold_answer)
        f1 = f1_score(pred_answer, gold_answer)
        
        entry = {
            "_id": pred_id,
            "question": gold_item.get("question", ""),
            "prediction": pred_answer,
            "gold": gold_answer,
            "em": em,
            "f1": f1,
            "type": gold_item.get("type", ""),
            "level": gold_item.get("level", "")
        }
        
        if em < 1.0:
            entry["reasoning"] = pred.get("reasoning", "")
            errors.append(entry)
        else:
            correct.append(entry)
    
    # Categorize errors
    categories = {
        "partial_match": [e for e in errors if e["f1"] > 0.5],
        "low_overlap": [e for e in errors if 0 < e["f1"] <= 0.5],
        "no_overlap": [e for e in errors if e["f1"] == 0]
    }
    
    total = len(errors) + len(correct)
    return {
        "total_errors": len(errors),
        "total_correct": len(correct),
        "error_rate": len(errors) / total if total > 0 else 0,
        "error_categories": {k: len(v) for k, v in categories.items()},
        "sample_errors": errors[:num_examples],
        "sample_correct": correct[:num_examples]
    }
