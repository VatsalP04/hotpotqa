"""
Evaluation metrics for HotpotQA.

Implements Exact Match (EM) and F1 score following official HotpotQA evaluation.
"""

from __future__ import annotations

import re
import string
from collections import Counter
from typing import Dict, List, Optional


# =============================================================================
# Answer Normalization
# =============================================================================

def normalize_answer(text: str) -> str:
    """
    Normalize answer string for evaluation (HotpotQA/SQuAD style).
    
    Steps:
    - Lowercase
    - Remove articles (a, an, the)
    - Remove punctuation
    - Normalize whitespace
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
    """Calculate Exact Match score (1.0 if match, 0.0 otherwise)."""
    return float(normalize_answer(prediction) == normalize_answer(gold))


def precision_recall_f1(prediction: str, gold: str) -> Dict[str, float]:
    """
    Calculate token-level precision, recall, and F1 score.
    
    Matches official HotpotQA evaluation script:
    - Special handling for "yes", "no", "noanswer" (exact match only)
    - Token-level F1 for other answers
    """
    normalized_pred = normalize_answer(prediction)
    normalized_gold = normalize_answer(gold)
    
    # Special handling for yes/no/noanswer (exact match only)
    # If prediction is yes/no/noanswer and doesn't match gold, return 0
    if normalized_pred in ['yes', 'no', 'noanswer'] and normalized_pred != normalized_gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    # If gold is yes/no/noanswer and doesn't match prediction, return 0
    if normalized_gold in ['yes', 'no', 'noanswer'] and normalized_pred != normalized_gold:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    # Token-level F1 for other answers
    pred_tokens = normalized_pred.split()
    gold_tokens = normalized_gold.split()
    
    if not pred_tokens or not gold_tokens:
        match = float(pred_tokens == gold_tokens)
        return {"precision": match, "recall": match, "f1": match}
    
    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    
    if num_same == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {"precision": precision, "recall": recall, "f1": f1}


def f1_score(prediction: str, gold: str) -> float:
    """Calculate token-level F1 score."""
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

