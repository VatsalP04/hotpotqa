"""
Enhanced experiment runner for reasoning methods.

Orchestrates experiments, collects comprehensive results, generates reports and visualizations.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

from src.reasoning.core.data import load_hotpotqa_json
from src.reasoning.core.metrics import (
    MetricsCalculator,
    QuestionMetrics,
    AggregateMetrics,
    generate_markdown_report,
    exact_match,
    f1_score,
)
from src.reasoning.core.visualization import VisualizationGenerator

logger = logging.getLogger(__name__)


@dataclass
class MethodResult:
    """Result from a single method run (returned by adapters)."""
    answer: str
    reasoning_chain: str = ""
    retrieved_titles: List[str] = field(default_factory=list)
    first_retrieved_titles: List[str] = field(default_factory=list)
    num_retrieval_steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    processing_time: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

class ExperimentRunner:
    """
    Enhanced experiment runner with comprehensive metrics and visualization.
    
    Features:
    - Runs experiments on multiple methods
    - Calculates comprehensive metrics (answer, retrieval, efficiency)
    - Generates markdown reports
    - Creates visualization plots automatically
    """
    
    def __init__(
        self,
        data_path: str,
        output_dir: str = "./outputs",
        num_samples: Optional[int] = None,
        seed: int = 42,
        generate_plots: bool = True,
        checkpoint_interval: int = 100,
    ):
        """
        Initialize experiment runner.
        
        Args:
            data_path: Path to HotpotQA JSON file
            output_dir: Directory for output files
            num_samples: Number of samples to use (None = all)
            seed: Random seed
            generate_plots: Whether to generate visualization plots
            checkpoint_interval: Save checkpoint every N questions (default: 100)
        """
        self.data_path = data_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.num_samples = num_samples
        self.seed = seed
        self.generate_plots = generate_plots
        self.checkpoint_interval = checkpoint_interval
        
        # Load data
        self.data = load_hotpotqa_json(
            data_path,
            max_examples=num_samples,
            shuffle=True,
            seed=seed
        )
        
        logger.info(f"Loaded {len(self.data)} examples")
        if checkpoint_interval > 0:
            logger.info(f"Checkpointing enabled: saving every {checkpoint_interval} questions")
    
    def _get_gold_titles(self, example: Dict) -> Set[str]:
        """Extract gold paragraph titles from supporting facts."""
        supporting_facts = example.get("supporting_facts", [])
        gold_titles = set()
        
        for sf in supporting_facts:
            if isinstance(sf, list) and len(sf) >= 1:
                gold_titles.add(sf[0])
            elif isinstance(sf, dict):
                gold_titles.add(sf.get("title", ""))
        
        return gold_titles
    
    def _get_checkpoint_path(self, method_name: str) -> Path:
        """Get path for checkpoint file."""
        checkpoint_dir = self.output_dir / "checkpoints"
        checkpoint_dir.mkdir(exist_ok=True)
        return checkpoint_dir / f"{method_name}_checkpoint.json"
    
    def _load_checkpoint(self, method_name: str) -> Optional[List[QuestionMetrics]]:
        """Load existing checkpoint if available."""
        checkpoint_path = self._get_checkpoint_path(method_name)
        if checkpoint_path.exists():
            try:
                with open(checkpoint_path) as f:
                    data = json.load(f)
                    results = []
                    for item in data:
                        if "gold_titles" in item and isinstance(item["gold_titles"], list):
                            item["gold_titles"] = set(item["gold_titles"])
                        results.append(QuestionMetrics(**item))
                    logger.info(f"📂 Loaded checkpoint: {len(results)} questions already processed")
                    return results
            except Exception as e:
                logger.warning(f"Failed to load checkpoint: {e}")
        return None
    
    def _save_checkpoint(self, method_name: str, results: List[QuestionMetrics]) -> None:
        """Save checkpoint."""
        checkpoint_path = self._get_checkpoint_path(method_name)
        try:
            with open(checkpoint_path, "w") as f:
                json.dump([r.to_dict() for r in results], f, indent=2)
            logger.info(f"💾 Checkpoint saved: {len(results)} questions ({checkpoint_path})")
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")
    
    def run_method(
        self,
        adapter,
        method_name: str,
        resume: bool = True,
    ) -> List[QuestionMetrics]:
        """
        Run a method on all questions with comprehensive metrics.
        
        Args:
            adapter: Method adapter with answer() method
            method_name: Name of the method
            resume: If True, resume from checkpoint if available
        
        Returns:
            List of QuestionMetrics objects
        """
        # Try to load checkpoint
        results = []
        start_idx = 0
        if resume:
            checkpoint_results = self._load_checkpoint(method_name)
            if checkpoint_results:
                results = checkpoint_results
                start_idx = len(results)
                logger.info(f"🔄 Resuming from question {start_idx + 1}/{len(self.data)}")
        
        for i, example in enumerate(self.data[start_idx:], start=start_idx):
            question_id = example.get("_id", str(i))
            question = example.get("question", "")
            gold_answer = example.get("answer", "")
            question_type = example.get("type", "unknown")
            context = example.get("context", [])
            gold_titles = self._get_gold_titles(example)
            
            logger.info(f"[{i+1}/{len(self.data)}] Processing: {question[:50]}...")
            
            error = None
            method_result = None
            
            try:
                start_time = time.time()
                method_result = adapter.answer(question, context)
                elapsed = time.time() - start_time
                method_result.processing_time = elapsed
                
            except Exception as e:
                logger.error(f"Error on question {i}: {e}")
                error = str(e)
                method_result = MethodResult(answer="")
            
            extra_info = method_result.extra if method_result else {}
            not_found_count = extra_info.get("not_found_count", 0)
            search_queries = extra_info.get("all_search_queries", [])
            sub_qas = extra_info.get("sub_qas", [])
            
            detailed_reasoning = method_result.reasoning_chain if method_result else ""
            if search_queries and detailed_reasoning:
                if "Search Queries:" not in detailed_reasoning:
                    detailed_reasoning += f"\n\nSearch Queries Used: {', '.join(search_queries)}"
            
            metrics = MetricsCalculator.calculate_question_metrics(
                    question_id=question_id,
                    question=question,
                question_type=question_type,
                    gold_answer=gold_answer,
                predicted_answer=method_result.answer if method_result else "",
                retrieved_titles=method_result.retrieved_titles if method_result else [],
                first_retrieved_titles=method_result.first_retrieved_titles if method_result else [],
                gold_titles=gold_titles,
                num_retrieval_steps=method_result.num_retrieval_steps if method_result else 0,
                input_tokens=method_result.input_tokens if method_result else 0,
                output_tokens=method_result.output_tokens if method_result else 0,
                processing_time=method_result.processing_time if method_result else 0.0,
                reasoning_chain=detailed_reasoning,
                error=error,
            )
            
            # Add extra info to metrics
            metrics.extra = {
                "not_found_count": not_found_count,
                "search_queries": search_queries,
                "sub_qas": sub_qas,
            }
            
            results.append(metrics)
            
            logger.info(f"  → Answer: {metrics.predicted_answer[:50]}... | "
                       f"EM: {metrics.em:.2f}, F1: {metrics.f1:.2f}, "
                       f"GoldRecall: {metrics.gold_recall:.2f}")
            
            if self.checkpoint_interval > 0 and (i + 1) % self.checkpoint_interval == 0:
                self._save_checkpoint(method_name, results)
                completed = len(results)
                total = len(self.data)
                pct = (completed / total) * 100
                logger.info(f"📊 Progress: {completed}/{total} ({pct:.1f}%) - Checkpoint saved")
        
        if self.checkpoint_interval > 0:
            self._save_checkpoint(method_name, results)
        
        return results
    
    def save_results(
        self,
        results: List[QuestionMetrics],
        aggregate: AggregateMetrics,
        method_name: str,
    ) -> Path:
        """Save results to output directory."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"{method_name}_{timestamp}"
        output_path.mkdir(parents=True, exist_ok=True)
        
        with open(output_path / "per_question.json", "w") as f:
            json.dump([r.to_dict() for r in results], f, indent=2)
        
        self._save_detailed_per_question_report(results, output_path / "detailed_per_question.md")
        
        with open(output_path / "summary.json", "w") as f:
            json.dump(aggregate.to_dict(), f, indent=2)
        
        generate_markdown_report(
            aggregate,
            results,
            str(output_path / "report.md")
        )
        
        logger.info(f"Results saved to {output_path}")
        return output_path
    
    def compare_methods(
        self,
        adapters: Dict[str, Any],
        resume: bool = True,
    ) -> Dict[str, AggregateMetrics]:
        """
        Compare multiple methods and generate comprehensive analysis.
        
        Args:
            adapters: Dict mapping method names to adapters
            resume: If True, resume from checkpoints if available
        
        Returns:
            Dict mapping method names to aggregate metrics
        """
        all_results: Dict[str, List[QuestionMetrics]] = {}
        all_aggregates: Dict[str, AggregateMetrics] = {}
        
        for method_name, adapter in adapters.items():
            logger.info(f"\n{'='*60}\nRunning {method_name}\n{'='*60}")
            
            results = self.run_method(adapter, method_name, resume=resume)
            aggregate = MetricsCalculator.aggregate_metrics(results, method_name)
            
            self.save_results(results, aggregate, method_name)
            
            all_results[method_name] = results
            all_aggregates[method_name] = aggregate
        
        self._print_comparison(all_aggregates)
        
        self._generate_comparison_outputs(all_results, all_aggregates)
        
        return all_aggregates
    
    def _print_comparison(self, aggregates: Dict[str, AggregateMetrics]) -> None:
        """Print comparison table."""
        print("\n" + "="*100)
        print("COMPARISON RESULTS")
        print("="*100)
        print(f"{'Method':<15} {'EM':>8} {'F1':>8} {'GoldRec':>8} {'1stRec':>8} "
              f"{'Tokens':>10} {'F1/1kT':>10} {'Time':>8} {'NOT_FOUND':>10}")
        print("-"*110)
        
        for name, agg in aggregates.items():
            not_found_str = f"{agg.not_found_count}" if agg.not_found_count > 0 else "-"
            print(f"{name:<15} {agg.avg_em:>8.4f} {agg.avg_f1:>8.4f} "
                  f"{agg.avg_gold_recall:>8.4f} {agg.avg_first_retrieval_recall:>8.4f} "
                  f"{agg.total_tokens:>10} {agg.overall_f1_per_1k_tokens:>10.4f} "
                  f"{agg.total_time:>8.2f}s {not_found_str:>10}")
        
        print("="*110)
        print("\nLegend: GoldRec = Gold Paragraph Recall, 1stRec = First Retrieval Recall, F1/1kT = F1 per 1000 tokens")
        print("NOT_FOUND = Number of questions using NOT_FOUND fallback (for decomposition)")
    
    def _generate_comparison_outputs(
        self,
        all_results: Dict[str, List[QuestionMetrics]],
        all_aggregates: Dict[str, AggregateMetrics],
    ) -> None:
        """Generate combined comparison outputs."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        comparison_dir = self.output_dir / f"comparison_{timestamp}"
        comparison_dir.mkdir(parents=True, exist_ok=True)
        
        per_question_dict = {
            method: [r.to_dict() for r in results]
            for method, results in all_results.items()
        }
        
        aggregate_dict = {
            method: agg.to_dict()
            for method, agg in all_aggregates.items()
        }
        
        with open(comparison_dir / "all_per_question.json", "w") as f:
            json.dump(per_question_dict, f, indent=2)
        
        with open(comparison_dir / "all_summaries.json", "w") as f:
            json.dump(aggregate_dict, f, indent=2)
        
        self._generate_comparison_report(all_aggregates, comparison_dir / "comparison_report.md")
        
        if self.generate_plots:
            logger.info("Generating visualization plots...")
            viz = VisualizationGenerator(str(comparison_dir))
            plots = viz.generate_all(per_question_dict, aggregate_dict)
            
            if plots:
                logger.info(f"Generated {len(plots)} plots:")
                for name, path in plots.items():
                    logger.info(f"  - {name}: {path}")
        
        logger.info(f"\n Comparison results saved to: {comparison_dir}")
    
    def _generate_comparison_report(
        self,
        aggregates: Dict[str, AggregateMetrics],
        output_path: Path,
    ) -> None:
        """Generate combined comparison markdown report."""
        lines = [
            "# Method Comparison Report",
            "",
            f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Methods Compared**: {', '.join(aggregates.keys())}",
            "",
            "---",
            "",
            "## Summary Table",
            "",
            "| Method | EM | F1 | Gold Recall | First Ret. Recall | Tokens | F1/1kT | Time |",
            "|--------|----|----|-------------|-------------------|--------|--------|------|",
        ]
        
        for name, agg in aggregates.items():
            lines.append(
                f"| {name} | {agg.avg_em:.4f} | {agg.avg_f1:.4f} | "
                f"{agg.avg_gold_recall:.4f} | {agg.avg_first_retrieval_recall:.4f} | "
                f"{agg.total_tokens:,} | {agg.overall_f1_per_1k_tokens:.4f} | {agg.total_time:.1f}s |"
            )
        
        lines.extend([
            "",
            "---",
            "",
            "## Detailed Metrics",
            "",
        ])
        
        for name, agg in aggregates.items():
            lines.extend([
                f"### {name}",
                "",
                "#### Answer Quality",
                f"- Exact Match: {agg.avg_em:.4f}",
                f"- F1 Score: {agg.avg_f1:.4f}",
                f"- Precision: {agg.avg_precision:.4f}",
                f"- Recall: {agg.avg_recall:.4f}",
                "",
                "#### Retrieval Quality",
                f"- Gold Paragraph Recall: {agg.avg_gold_recall:.4f}",
                f"- Gold Paragraph Precision: {agg.avg_gold_precision:.4f}",
                f"- Gold Paragraph F1: {agg.avg_gold_f1:.4f}",
                f"- Gold Hit Rate: {agg.avg_gold_hit_rate:.4f}",
                "",
                "#### First Retrieval Quality",
                f"- First Retrieval Recall: {agg.avg_first_retrieval_recall:.4f}",
                f"- First Retrieval Precision: {agg.avg_first_retrieval_precision:.4f}",
                f"- First Retrieval Hit Rate: {agg.avg_first_retrieval_hit_rate:.4f}",
                "",
                "#### Efficiency",
                f"- Avg Tokens/Question: {agg.avg_tokens_per_question:.1f}",
                f"- F1 per 1K Tokens: {agg.overall_f1_per_1k_tokens:.4f}",
                f"- Avg Time/Question: {agg.avg_time_per_question:.2f}s",
                "",
            ])
            
            if agg.comparison_metrics or agg.bridge_metrics:
                lines.append("#### By Question Type")
                if agg.comparison_metrics:
                    cm = agg.comparison_metrics
                    lines.append(f"- Comparison ({cm['count']}): EM={cm['avg_em']:.4f}, F1={cm['avg_f1']:.4f}")
                if agg.bridge_metrics:
                    bm = agg.bridge_metrics
                    lines.append(f"- Bridge ({bm['count']}): EM={bm['avg_em']:.4f}, F1={bm['avg_f1']:.4f}")
                lines.append("")
        
        with open(output_path, "w") as f:
            f.write("\n".join(lines))
        
        logger.info(f"Comparison report saved to {output_path}")
    
    def _save_detailed_per_question_report(
        self,
        results: List[QuestionMetrics],
        output_path: Path,
    ) -> None:
        """Generate detailed per-question report with full pipeline information."""
        lines = [
            "# Detailed Per-Question Report",
            "",
            f"**Total Questions**: {len(results)}",
            "",
            "---",
            "",
        ]
        
        for i, r in enumerate(results, 1):
            lines.extend([
                f"## Question {i}: {r.question_id}",
                "",
                f"**Question**: {r.question}",
                f"**Question Type**: {r.question_type}",
                "",
                "### Answers",
                f"- **Gold Answer**: {r.gold_answer}",
                f"- **Predicted Answer**: {r.predicted_answer}",
                f"- **Exact Match**: {'✅' if r.em > 0.5 else '❌'} ({r.em:.4f})",
                f"- **F1 Score**: {r.f1:.4f}",
                "",
                "### Retrieval",
                f"- **Retrieved Titles**: {', '.join(r.retrieved_titles) if r.retrieved_titles else 'None'}",
                f"- **First Retrieval Titles**: {', '.join(r.first_retrieved_titles) if r.first_retrieved_titles else 'None'}",
                f"- **Gold Titles**: {', '.join(sorted(r.gold_titles)) if r.gold_titles else 'None'}",
                f"- **Gold Recall**: {r.gold_recall:.4f}",
                f"- **First Retrieval Recall**: {r.first_retrieval_recall:.4f}",
                f"- **Number of Retrieval Steps**: {r.num_retrieval_steps}",
                "",
            ])
            
            # Add method-specific details
            extra = r.extra
            if extra.get("not_found_count", 0) > 0:
                lines.extend([
                    "### NOT_FOUND Fallback",
                    f"- **Used NOT_FOUND**: Yes ({extra['not_found_count']} sub-questions)",
                    "",
                ])
            
            if extra.get("search_queries"):
                lines.extend([
                    "### Search Queries",
                ])
                for j, query in enumerate(extra["search_queries"], 1):
                    lines.append(f"- Query {j}: {query}")
                lines.append("")
            
            if extra.get("sub_qas"):
                lines.extend([
                    "### Sub-Questions and Answers",
                ])
                for j, sub_qa in enumerate(extra["sub_qas"], 1):
                    lines.extend([
                        f"#### Sub-Q {j}",
                        f"- **Question**: {sub_qa['question']}",
                    ])
                    
                    # Show initial attempt
                    if sub_qa.get("initial_answer"):
                        lines.extend([
                            "",
                            "**Initial Attempt:**",
                            f"- **Query**: {sub_qa['search_queries'][0] if sub_qa.get('search_queries') else 'N/A'}",
                            f"- **Retrieved**: {', '.join(sub_qa.get('retrieved_titles', [])[:5])}",
                            f"- **Answer**: {sub_qa['initial_answer']}",
                            f"- **Status**: ⚠️ NOT_FOUND",
                        ])
                        
                        # Show re-attempt if it happened
                        if sub_qa.get("reattempt_query"):
                            lines.extend([
                                "",
                                "**Re-Attempt (Fallback):**",
                                f"- **Rewritten Query**: {sub_qa['reattempt_query']}",
                                f"- **Retrieved**: {', '.join(sub_qa.get('reattempt_retrieved_titles', [])[:5])}",
                                f"- **Re-Attempt Answer**: {sub_qa.get('reattempt_answer', 'N/A')}",
                            ])
                            if sub_qa.get('reattempt_answer') and sub_qa['reattempt_answer'].strip().upper() != "NOT_FOUND":
                                lines.append(f"- **Status**: Success (used as final answer)")
                            else:
                                lines.append(f"- **Status**:  Still NOT_FOUND")
                    else:
                        # No re-attempt needed
                        lines.extend([
                            f"- **Answer**: {sub_qa['answer']}",
                            f"- **Retrieved Titles**: {', '.join(sub_qa.get('retrieved_titles', []))}",
                        ])
                        if sub_qa.get("search_queries"):
                            lines.append(f"- **Search Query**: {sub_qa['search_queries'][0]}")
                    
                    lines.append("")
            
            lines.extend([
                "### Reasoning Chain",
                "```",
                r.reasoning_chain[:2000] if len(r.reasoning_chain) > 2000 else r.reasoning_chain,
                "```",
                "",
                "### Metrics Summary",
                f"- **EM**: {r.em:.4f} | **F1**: {r.f1:.4f} | **Precision**: {r.precision:.4f} | **Recall**: {r.recall:.4f}",
                f"- **Gold Recall**: {r.gold_recall:.4f} | **First Ret. Recall**: {r.first_retrieval_recall:.4f}",
                f"- **Tokens**: {r.total_tokens} (in: {r.input_tokens}, out: {r.output_tokens})",
                f"- **Time**: {r.processing_time:.2f}s",
                "",
                "---",
                "",
            ])
        
        with open(output_path, "w") as f:
            f.write("\n".join(lines))
        
        logger.info(f"Detailed per-question report saved to {output_path}")
