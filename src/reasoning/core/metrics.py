"""
Enhanced metrics for HotpotQA evaluation.

Provides comprehensive metrics for:
- Answer quality (EM, F1, precision, recall)
- Retrieval quality (gold paragraph recall, precision, F1)
- First retrieval quality (initial retrieval effectiveness)
- Token efficiency (F1 per token, answer quality vs cost)
- Supporting facts coverage

All metrics follow official HotpotQA evaluation methodology.
"""

from __future__ import annotations

import re
import string
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import json


# =============================================================================
# Answer Normalization (Official HotpotQA style)
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
    if not text:
        return ""
    
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
# Core Answer Metrics
# =============================================================================

def exact_match(prediction: str, gold: str) -> float:
    """Calculate Exact Match score (1.0 if match, 0.0 otherwise)."""
    return float(normalize_answer(prediction) == normalize_answer(gold))


def token_precision_recall_f1(prediction: str, gold: str) -> Dict[str, float]:
    """Calculate token-level precision, recall, and F1 score."""
    pred_tokens = normalize_answer(prediction).split()
    gold_tokens = normalize_answer(gold).split()
    
    if not pred_tokens and not gold_tokens:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred_tokens or not gold_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
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
    return token_precision_recall_f1(prediction, gold)["f1"]


# =============================================================================
# Retrieval Quality Metrics
# =============================================================================

def retrieval_precision_recall_f1(
    retrieved_titles: List[str],
    gold_titles: Set[str]
) -> Dict[str, float]:
    """
    Calculate retrieval precision, recall, and F1.
    
    Args:
        retrieved_titles: List of retrieved paragraph titles
        gold_titles: Set of gold (supporting fact) paragraph titles
    
    Returns:
        Dict with precision, recall, f1
    """
    if not retrieved_titles and not gold_titles:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not retrieved_titles or not gold_titles:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    retrieved_set = set(retrieved_titles)
    
    true_positives = len(retrieved_set & gold_titles)
    
    precision = true_positives / len(retrieved_set) if retrieved_set else 0.0
    recall = true_positives / len(gold_titles) if gold_titles else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {"precision": precision, "recall": recall, "f1": f1}


def gold_paragraph_recall(
    retrieved_titles: List[str],
    gold_titles: Set[str]
) -> float:
    """Calculate recall of gold paragraphs (how many gold paragraphs were retrieved)."""
    if not gold_titles:
        return 1.0
    if not retrieved_titles:
        return 0.0
    
    retrieved_set = set(retrieved_titles)
    return len(retrieved_set & gold_titles) / len(gold_titles)


def gold_paragraph_hit_rate(
    retrieved_titles: List[str],
    gold_titles: Set[str]
) -> float:
    """Calculate hit rate (1.0 if at least one gold paragraph retrieved, 0.0 otherwise)."""
    if not gold_titles:
        return 1.0
    if not retrieved_titles:
        return 0.0
    
    retrieved_set = set(retrieved_titles)
    return 1.0 if (retrieved_set & gold_titles) else 0.0


def first_retrieval_metrics(
    first_retrieved_titles: List[str],
    gold_titles: Set[str]
) -> Dict[str, float]:
    """
    Evaluate the quality of the FIRST retrieval step.
    
    This is important because the first retrieval often determines
    if the model can find the right path to the answer.
    
    Returns:
        Dict with recall, precision, f1, hit_rate for first retrieval
    """
    prf = retrieval_precision_recall_f1(first_retrieved_titles, gold_titles)
    hit_rate = gold_paragraph_hit_rate(first_retrieved_titles, gold_titles)
    
    return {
        "first_retrieval_recall": prf["recall"],
        "first_retrieval_precision": prf["precision"],
        "first_retrieval_f1": prf["f1"],
        "first_retrieval_hit_rate": hit_rate,
    }


# =============================================================================
# Supporting Facts Metrics
# =============================================================================

def supporting_facts_metrics(
    retrieved_titles: List[str],
    supporting_facts: List[Tuple[str, int]]
) -> Dict[str, float]:
    """
    Calculate metrics for supporting facts coverage.
    
    Args:
        retrieved_titles: List of retrieved paragraph titles
        supporting_facts: List of (title, sentence_idx) tuples
    
    Returns:
        Dict with coverage metrics
    """
    if not supporting_facts:
        return {
            "sf_title_recall": 1.0,
            "sf_title_precision": 1.0 if not retrieved_titles else 0.0,
            "sf_title_f1": 1.0 if not retrieved_titles else 0.0,
        }
    
    gold_titles = {sf[0] for sf in supporting_facts}
    prf = retrieval_precision_recall_f1(retrieved_titles, gold_titles)
    
    return {
        "sf_title_recall": prf["recall"],
        "sf_title_precision": prf["precision"],
        "sf_title_f1": prf["f1"],
    }


# =============================================================================
# Token Efficiency Metrics
# =============================================================================

def token_efficiency_metrics(
    f1: float,
    em: float,
    input_tokens: int,
    output_tokens: int,
) -> Dict[str, float]:
    """
    Calculate token efficiency metrics.
    
    Higher values = better (more quality per token spent).
    
    Returns:
        Dict with efficiency metrics
    """
    total_tokens = input_tokens + output_tokens
    
    # Avoid division by zero
    if total_tokens == 0:
        return {
            "f1_per_1k_tokens": 0.0,
            "em_per_1k_tokens": 0.0,
            "tokens_per_correct": 0.0,
        }
    
    return {
        "f1_per_1k_tokens": (f1 * 1000) / total_tokens,
        "em_per_1k_tokens": (em * 1000) / total_tokens,
        "tokens_per_correct": total_tokens / em if em > 0 else float('inf'),
    }


# =============================================================================
# Data Classes for Results
# =============================================================================

@dataclass
class QuestionMetrics:
    """Complete metrics for a single question."""
    question_id: str
    question: str
    question_type: str  # "comparison" or "bridge"
    
    # Answers
    gold_answer: str
    predicted_answer: str
    
    # Core answer metrics
    em: float
    f1: float
    precision: float
    recall: float
    
    # Retrieval info
    retrieved_titles: List[str]
    first_retrieved_titles: List[str]
    gold_titles: Set[str]
    num_retrieval_steps: int
    num_paragraphs_retrieved: int
    
    # Retrieval metrics
    gold_recall: float
    gold_precision: float
    gold_f1: float
    gold_hit_rate: float
    
    # First retrieval metrics
    first_retrieval_recall: float
    first_retrieval_precision: float
    first_retrieval_f1: float
    first_retrieval_hit_rate: float
    
    # Token usage
    input_tokens: int
    output_tokens: int
    total_tokens: int
    
    # Efficiency
    f1_per_1k_tokens: float
    em_per_1k_tokens: float
    
    # Timing
    processing_time: float
    
    # Extra info
    reasoning_chain: str = ""
    error: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)  # For method-specific details
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "question_id": self.question_id,
            "question": self.question,
            "question_type": self.question_type,
            "gold_answer": self.gold_answer,
            "predicted_answer": self.predicted_answer,
            "em": self.em,
            "f1": self.f1,
            "precision": self.precision,
            "recall": self.recall,
            "retrieved_titles": self.retrieved_titles,
            "first_retrieved_titles": self.first_retrieved_titles,
            "gold_titles": list(self.gold_titles),
            "num_retrieval_steps": self.num_retrieval_steps,
            "num_paragraphs_retrieved": self.num_paragraphs_retrieved,
            "gold_recall": self.gold_recall,
            "gold_precision": self.gold_precision,
            "gold_f1": self.gold_f1,
            "gold_hit_rate": self.gold_hit_rate,
            "first_retrieval_recall": self.first_retrieval_recall,
            "first_retrieval_precision": self.first_retrieval_precision,
            "first_retrieval_f1": self.first_retrieval_f1,
            "first_retrieval_hit_rate": self.first_retrieval_hit_rate,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "f1_per_1k_tokens": self.f1_per_1k_tokens,
            "em_per_1k_tokens": self.em_per_1k_tokens,
            "processing_time": self.processing_time,
            "reasoning_chain": self.reasoning_chain,
            "error": self.error,
            "extra": self.extra,  # Include method-specific details (NOT_FOUND, search queries, etc.)
        }


@dataclass
class AggregateMetrics:
    """Aggregated metrics across all questions."""
    method: str
    num_questions: int
    num_errors: int
    
    # Answer metrics (macro averaged)
    avg_em: float
    avg_f1: float
    avg_precision: float
    avg_recall: float
    
    # Retrieval metrics (macro averaged)
    avg_gold_recall: float
    avg_gold_precision: float
    avg_gold_f1: float
    avg_gold_hit_rate: float
    
    # First retrieval metrics
    avg_first_retrieval_recall: float
    avg_first_retrieval_precision: float
    avg_first_retrieval_f1: float
    avg_first_retrieval_hit_rate: float
    
    # Retrieval stats
    avg_retrieval_steps: float
    avg_paragraphs_retrieved: float
    
    # Token usage
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    avg_tokens_per_question: float
    
    # Efficiency
    avg_f1_per_1k_tokens: float
    avg_em_per_1k_tokens: float
    overall_f1_per_1k_tokens: float  # F1 / (total_tokens / 1000)
    
    # Timing
    total_time: float
    avg_time_per_question: float
    
    # Optional fields (with defaults)
    not_found_count: int = 0  # For decomposition: questions using NOT_FOUND fallback
    comparison_metrics: Optional[Dict[str, float]] = None
    bridge_metrics: Optional[Dict[str, float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "method": self.method,
            "num_questions": self.num_questions,
            "num_errors": self.num_errors,
            "not_found_count": self.not_found_count,
            
            "answer_metrics": {
                "avg_em": self.avg_em,
                "avg_f1": self.avg_f1,
                "avg_precision": self.avg_precision,
                "avg_recall": self.avg_recall,
            },
            
            "retrieval_metrics": {
                "avg_gold_recall": self.avg_gold_recall,
                "avg_gold_precision": self.avg_gold_precision,
                "avg_gold_f1": self.avg_gold_f1,
                "avg_gold_hit_rate": self.avg_gold_hit_rate,
            },
            
            "first_retrieval_metrics": {
                "avg_recall": self.avg_first_retrieval_recall,
                "avg_precision": self.avg_first_retrieval_precision,
                "avg_f1": self.avg_first_retrieval_f1,
                "avg_hit_rate": self.avg_first_retrieval_hit_rate,
            },
            
            "retrieval_stats": {
                "avg_retrieval_steps": self.avg_retrieval_steps,
                "avg_paragraphs_retrieved": self.avg_paragraphs_retrieved,
            },
            
            "token_usage": {
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_tokens,
                "avg_tokens_per_question": self.avg_tokens_per_question,
            },
            
            "efficiency": {
                "avg_f1_per_1k_tokens": self.avg_f1_per_1k_tokens,
                "avg_em_per_1k_tokens": self.avg_em_per_1k_tokens,
                "overall_f1_per_1k_tokens": self.overall_f1_per_1k_tokens,
            },
            
            "timing": {
                "total_time": self.total_time,
                "avg_time_per_question": self.avg_time_per_question,
            },
        }
        
        if self.comparison_metrics:
            result["by_question_type"] = {
                "comparison": self.comparison_metrics,
                "bridge": self.bridge_metrics,
            }
        
        return result


# =============================================================================
# Metrics Calculator
# =============================================================================

class MetricsCalculator:
    """Calculate comprehensive metrics from method results."""
    
    @staticmethod
    def calculate_question_metrics(
        question_id: str,
        question: str,
        question_type: str,
        gold_answer: str,
        predicted_answer: str,
        retrieved_titles: List[str],
        first_retrieved_titles: List[str],
        gold_titles: Set[str],
        num_retrieval_steps: int,
        input_tokens: int,
        output_tokens: int,
        processing_time: float,
        reasoning_chain: str = "",
        error: Optional[str] = None,
    ) -> QuestionMetrics:
        """Calculate all metrics for a single question."""
        
        # Answer metrics
        em = exact_match(predicted_answer, gold_answer)
        prf = token_precision_recall_f1(predicted_answer, gold_answer)
        
        # Retrieval metrics
        retrieval_prf = retrieval_precision_recall_f1(retrieved_titles, gold_titles)
        hit_rate = gold_paragraph_hit_rate(retrieved_titles, gold_titles)
        
        # First retrieval metrics
        first_prf = retrieval_precision_recall_f1(first_retrieved_titles, gold_titles)
        first_hit_rate = gold_paragraph_hit_rate(first_retrieved_titles, gold_titles)
        
        # Token efficiency
        total_tokens = input_tokens + output_tokens
        efficiency = token_efficiency_metrics(prf["f1"], em, input_tokens, output_tokens)
        
        return QuestionMetrics(
            question_id=question_id,
            question=question,
            question_type=question_type,
            gold_answer=gold_answer,
            predicted_answer=predicted_answer,
            em=em,
            f1=prf["f1"],
            precision=prf["precision"],
            recall=prf["recall"],
            retrieved_titles=retrieved_titles,
            first_retrieved_titles=first_retrieved_titles,
            gold_titles=gold_titles,
            num_retrieval_steps=num_retrieval_steps,
            num_paragraphs_retrieved=len(retrieved_titles),
            gold_recall=retrieval_prf["recall"],
            gold_precision=retrieval_prf["precision"],
            gold_f1=retrieval_prf["f1"],
            gold_hit_rate=hit_rate,
            first_retrieval_recall=first_prf["recall"],
            first_retrieval_precision=first_prf["precision"],
            first_retrieval_f1=first_prf["f1"],
            first_retrieval_hit_rate=first_hit_rate,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            f1_per_1k_tokens=efficiency["f1_per_1k_tokens"],
            em_per_1k_tokens=efficiency["em_per_1k_tokens"],
            processing_time=processing_time,
            reasoning_chain=reasoning_chain,
            error=error,
        )
    
    @staticmethod
    def aggregate_metrics(
        results: List[QuestionMetrics],
        method_name: str
    ) -> AggregateMetrics:
        """Aggregate metrics across all questions."""
        n = len(results)
        if n == 0:
            return AggregateMetrics(
                method=method_name,
                num_questions=0,
                num_errors=0,
                not_found_count=0,
                avg_em=0.0, avg_f1=0.0, avg_precision=0.0, avg_recall=0.0,
                avg_gold_recall=0.0, avg_gold_precision=0.0, avg_gold_f1=0.0, avg_gold_hit_rate=0.0,
                avg_first_retrieval_recall=0.0, avg_first_retrieval_precision=0.0,
                avg_first_retrieval_f1=0.0, avg_first_retrieval_hit_rate=0.0,
                avg_retrieval_steps=0.0, avg_paragraphs_retrieved=0.0,
                total_input_tokens=0, total_output_tokens=0, total_tokens=0,
                avg_tokens_per_question=0.0,
                avg_f1_per_1k_tokens=0.0, avg_em_per_1k_tokens=0.0, overall_f1_per_1k_tokens=0.0,
                total_time=0.0, avg_time_per_question=0.0,
            )
        
        num_errors = sum(1 for r in results if r.error)
        
        # Track NOT_FOUND for decomposition
        not_found_count = sum(1 for r in results if r.extra.get("not_found_count", 0) > 0)
        
        # Averages
        avg_em = sum(r.em for r in results) / n
        avg_f1 = sum(r.f1 for r in results) / n
        avg_precision = sum(r.precision for r in results) / n
        avg_recall = sum(r.recall for r in results) / n
        
        avg_gold_recall = sum(r.gold_recall for r in results) / n
        avg_gold_precision = sum(r.gold_precision for r in results) / n
        avg_gold_f1 = sum(r.gold_f1 for r in results) / n
        avg_gold_hit_rate = sum(r.gold_hit_rate for r in results) / n
        
        avg_first_recall = sum(r.first_retrieval_recall for r in results) / n
        avg_first_precision = sum(r.first_retrieval_precision for r in results) / n
        avg_first_f1 = sum(r.first_retrieval_f1 for r in results) / n
        avg_first_hit_rate = sum(r.first_retrieval_hit_rate for r in results) / n
        
        avg_retrieval_steps = sum(r.num_retrieval_steps for r in results) / n
        avg_paragraphs = sum(r.num_paragraphs_retrieved for r in results) / n
        
        # Tokens
        total_input = sum(r.input_tokens for r in results)
        total_output = sum(r.output_tokens for r in results)
        total_tokens = total_input + total_output
        avg_tokens = total_tokens / n
        
        # Efficiency
        avg_f1_per_1k = sum(r.f1_per_1k_tokens for r in results) / n
        avg_em_per_1k = sum(r.em_per_1k_tokens for r in results) / n
        overall_f1_per_1k = (avg_f1 * 1000) / avg_tokens if avg_tokens > 0 else 0.0
        
        # Timing
        total_time = sum(r.processing_time for r in results)
        avg_time = total_time / n
        
        # By question type
        comparison_results = [r for r in results if r.question_type == "comparison"]
        bridge_results = [r for r in results if r.question_type == "bridge"]
        
        comparison_metrics = None
        bridge_metrics = None
        
        if comparison_results:
            nc = len(comparison_results)
            comparison_metrics = {
                "count": nc,
                "avg_em": sum(r.em for r in comparison_results) / nc,
                "avg_f1": sum(r.f1 for r in comparison_results) / nc,
                "avg_gold_recall": sum(r.gold_recall for r in comparison_results) / nc,
            }
        
        if bridge_results:
            nb = len(bridge_results)
            bridge_metrics = {
                "count": nb,
                "avg_em": sum(r.em for r in bridge_results) / nb,
                "avg_f1": sum(r.f1 for r in bridge_results) / nb,
                "avg_gold_recall": sum(r.gold_recall for r in bridge_results) / nb,
            }
        
        return AggregateMetrics(
            method=method_name,
            num_questions=n,
            num_errors=num_errors,
            not_found_count=not_found_count,
            avg_em=avg_em,
            avg_f1=avg_f1,
            avg_precision=avg_precision,
            avg_recall=avg_recall,
            avg_gold_recall=avg_gold_recall,
            avg_gold_precision=avg_gold_precision,
            avg_gold_f1=avg_gold_f1,
            avg_gold_hit_rate=avg_gold_hit_rate,
            avg_first_retrieval_recall=avg_first_recall,
            avg_first_retrieval_precision=avg_first_precision,
            avg_first_retrieval_f1=avg_first_f1,
            avg_first_retrieval_hit_rate=avg_first_hit_rate,
            avg_retrieval_steps=avg_retrieval_steps,
            avg_paragraphs_retrieved=avg_paragraphs,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_tokens,
            avg_tokens_per_question=avg_tokens,
            avg_f1_per_1k_tokens=avg_f1_per_1k,
            avg_em_per_1k_tokens=avg_em_per_1k,
            overall_f1_per_1k_tokens=overall_f1_per_1k,
            total_time=total_time,
            avg_time_per_question=avg_time,
            comparison_metrics=comparison_metrics,
            bridge_metrics=bridge_metrics,
        )


# =============================================================================
# Report Generation
# =============================================================================

def generate_markdown_report(
    aggregate: AggregateMetrics,
    per_question: List[QuestionMetrics],
    output_path: str,
) -> str:
    """Generate a comprehensive markdown report."""
    from datetime import datetime as dt
    date_str = dt.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        f"# Evaluation Report: {aggregate.method}",
        "",
        f"**Date**: {date_str}",
        f"**Questions Evaluated**: {aggregate.num_questions}",
        f"**Errors**: {aggregate.num_errors}",
    ]
    
    # Add NOT_FOUND count for decomposition
    if aggregate.not_found_count > 0:
        pct = (aggregate.not_found_count / aggregate.num_questions * 100) if aggregate.num_questions > 0 else 0.0
        lines.append(f"**NOT_FOUND Fallback Used**: {aggregate.not_found_count} questions ({pct:.1f}%)")
    
    lines.extend([
        "",
        "---",
        "",
        "## Summary",
        "",
        "### Answer Quality",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Exact Match (EM) | {aggregate.avg_em:.4f} |",
        f"| F1 Score | {aggregate.avg_f1:.4f} |",
        f"| Precision | {aggregate.avg_precision:.4f} |",
        f"| Recall | {aggregate.avg_recall:.4f} |",
        "",
        "### Retrieval Quality",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Gold Paragraph Recall | {aggregate.avg_gold_recall:.4f} |",
        f"| Gold Paragraph Precision | {aggregate.avg_gold_precision:.4f} |",
        f"| Gold Paragraph F1 | {aggregate.avg_gold_f1:.4f} |",
        f"| Gold Hit Rate | {aggregate.avg_gold_hit_rate:.4f} |",
        "",
        "### First Retrieval Quality",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| First Retrieval Recall | {aggregate.avg_first_retrieval_recall:.4f} |",
        f"| First Retrieval Precision | {aggregate.avg_first_retrieval_precision:.4f} |",
        f"| First Retrieval F1 | {aggregate.avg_first_retrieval_f1:.4f} |",
        f"| First Retrieval Hit Rate | {aggregate.avg_first_retrieval_hit_rate:.4f} |",
        "",
        "### Token Efficiency",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Tokens | {aggregate.total_tokens:,} |",
        f"| Avg Tokens/Question | {aggregate.avg_tokens_per_question:.1f} |",
        f"| F1 per 1K Tokens | {aggregate.overall_f1_per_1k_tokens:.4f} |",
        f"| EM per 1K Tokens | {aggregate.avg_em_per_1k_tokens:.4f} |",
        "",
        "### Timing",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Time | {aggregate.total_time:.2f}s |",
        f"| Avg Time/Question | {aggregate.avg_time_per_question:.2f}s |",
        "",
    ])
    
    # By question type
    if aggregate.comparison_metrics or aggregate.bridge_metrics:
        lines.extend([
            "---",
            "",
            "## By Question Type",
            "",
            "| Type | Count | EM | F1 | Gold Recall |",
            "|------|-------|----|----|-------------|",
        ])
        
        if aggregate.comparison_metrics:
            cm = aggregate.comparison_metrics
            lines.append(f"| Comparison | {cm['count']} | {cm['avg_em']:.4f} | {cm['avg_f1']:.4f} | {cm['avg_gold_recall']:.4f} |")
        
        if aggregate.bridge_metrics:
            bm = aggregate.bridge_metrics
            lines.append(f"| Bridge | {bm['count']} | {bm['avg_em']:.4f} | {bm['avg_f1']:.4f} | {bm['avg_gold_recall']:.4f} |")
        
        lines.append("")
    
    # Error analysis
    errors = [r for r in per_question if r.error]
    if errors:
        lines.extend([
            "---",
            "",
            "## Errors",
            "",
            f"**Total Errors**: {len(errors)}",
            "",
        ])
        for i, e in enumerate(errors[:5]):
            lines.append(f"{i+1}. **Q**: {e.question[:100]}...")
            lines.append(f"   **Error**: {e.error}")
            lines.append("")
    
    report = "\n".join(lines)
    
    # Save report
    with open(output_path, "w") as f:
        f.write(report)
    
    return report

