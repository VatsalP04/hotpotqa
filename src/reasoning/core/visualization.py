"""
Visualization module for experiment results.

Generates comprehensive plots for:
- F1 vs Token usage
- Retrieval quality metrics
- Question type comparison
- Method comparison
- Efficiency analysis
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Try to import matplotlib, but allow running without it
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("matplotlib not available. Plotting disabled.")


# =============================================================================
# Color Schemes
# =============================================================================

# Professional color palette
COLORS = {
    "primary": "#2E86AB",      # Blue
    "secondary": "#A23B72",    # Magenta
    "tertiary": "#F18F01",     # Orange
    "quaternary": "#C73E1D",   # Red
    "success": "#3A7D44",      # Green
    "neutral": "#6B7280",      # Gray
}

METHOD_COLORS = {
    "IRCoT": "#2E86AB",
    "Decomposition": "#A23B72",
    "SimpleCoT": "#F18F01",
    "BM25": "#3A7D44",
    "Dense": "#C73E1D",
}

QUESTION_TYPE_COLORS = {
    "comparison": "#2E86AB",
    "bridge": "#A23B72",
}


# =============================================================================
# Plot Configuration
# =============================================================================

@dataclass
class PlotConfig:
    """Configuration for plots."""
    figsize: Tuple[int, int] = (10, 6)
    dpi: int = 150
    style: str = "seaborn-v0_8-whitegrid"
    font_size: int = 12
    title_size: int = 14
    label_size: int = 12
    legend_size: int = 10
    save_format: str = "png"


def setup_plot_style(config: PlotConfig):
    """Set up matplotlib style."""
    if not MATPLOTLIB_AVAILABLE:
        return
    
    try:
        plt.style.use(config.style)
    except:
        plt.style.use("seaborn-v0_8-white")
    
    plt.rcParams.update({
        'font.size': config.font_size,
        'axes.titlesize': config.title_size,
        'axes.labelsize': config.label_size,
        'legend.fontsize': config.legend_size,
        'figure.dpi': config.dpi,
    })


# =============================================================================
# Individual Plot Functions
# =============================================================================

def plot_f1_vs_tokens(
    results: Dict[str, List[Dict]],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Plot F1 score vs token usage for each method.
    
    Shows the trade-off between answer quality and computational cost.
    
    Args:
        results: Dict mapping method names to list of per-question results
        output_path: Path to save the plot
        config: Plot configuration
    
    Returns:
        Path to saved plot or None if matplotlib unavailable
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.warning("Cannot create plot: matplotlib not available")
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    fig, ax = plt.subplots(figsize=config.figsize)
    
    for method_name, method_results in results.items():
        f1_scores = [r.get("f1", 0) for r in method_results]
        tokens = [r.get("total_tokens", 0) for r in method_results]
        
        color = METHOD_COLORS.get(method_name, COLORS["neutral"])
        
        ax.scatter(tokens, f1_scores, label=method_name, color=color, alpha=0.6, s=50)
        
        # Add trend line
        if len(tokens) > 1:
            z = np.polyfit(tokens, f1_scores, 1)
            p = np.poly1d(z)
            x_line = np.linspace(min(tokens), max(tokens), 100)
            ax.plot(x_line, p(x_line), color=color, linestyle='--', alpha=0.5)
    
    ax.set_xlabel("Total Tokens")
    ax.set_ylabel("F1 Score")
    ax.set_title("F1 Score vs Token Usage")
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Set y-axis limits
    ax.set_ylim(0, 1.05)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format)
    plt.close()
    
    logger.info(f"Saved F1 vs Tokens plot to {output_path}")
    return output_path


def plot_retrieval_quality(
    results: Dict[str, List[Dict]],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Plot retrieval quality metrics for each method.
    
    Shows gold recall, first retrieval recall, and hit rates.
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    methods = list(results.keys())
    metrics = ["gold_recall", "gold_f1", "first_retrieval_recall", "first_retrieval_hit_rate"]
    metric_labels = ["Gold Recall", "Gold F1", "First Ret. Recall", "First Ret. Hit Rate"]
    
    # Calculate averages
    data = []
    for method in methods:
        method_results = results[method]
        method_data = []
        for metric in metrics:
            values = [r.get(metric, 0) for r in method_results]
            avg = sum(values) / len(values) if values else 0
            method_data.append(avg)
        data.append(method_data)
    
    data = np.array(data)
    
    x = np.arange(len(metric_labels))
    width = 0.8 / len(methods)
    
    fig, ax = plt.subplots(figsize=config.figsize)
    
    for i, method in enumerate(methods):
        offset = (i - len(methods) / 2 + 0.5) * width
        color = METHOD_COLORS.get(method, COLORS["neutral"])
        bars = ax.bar(x + offset, data[i], width, label=method, color=color, alpha=0.8)
        
        # Add value labels on bars
        for bar, val in zip(bars, data[i]):
            height = bar.get_height()
            ax.annotate(f'{val:.2f}',
                       xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3),
                       textcoords="offset points",
                       ha='center', va='bottom', fontsize=8)
    
    ax.set_xlabel("Metric")
    ax.set_ylabel("Score")
    ax.set_title("Retrieval Quality Metrics")
    ax.set_xticks(x)
    ax.set_xticklabels(metric_labels, rotation=15, ha='right')
    ax.legend()
    ax.set_ylim(0, 1.15)
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format)
    plt.close()
    
    logger.info(f"Saved retrieval quality plot to {output_path}")
    return output_path


def plot_question_type_comparison(
    results: Dict[str, List[Dict]],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Plot performance breakdown by question type (comparison vs bridge).
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    for method_name, method_results in results.items():
        comparison = [r for r in method_results if r.get("question_type") == "comparison"]
        bridge = [r for r in method_results if r.get("question_type") == "bridge"]
        
        color = METHOD_COLORS.get(method_name, COLORS["neutral"])
        
        # EM plot
        if comparison:
            comp_em = sum(r.get("em", 0) for r in comparison) / len(comparison)
            axes[0].bar(method_name + "\n(Comp)", comp_em, color=color, alpha=0.7)
        if bridge:
            bridge_em = sum(r.get("em", 0) for r in bridge) / len(bridge)
            axes[0].bar(method_name + "\n(Bridge)", bridge_em, color=color, alpha=0.4)
    
    # Create grouped bar chart
    methods = list(results.keys())
    x = np.arange(len(methods))
    width = 0.35
    
    comp_f1 = []
    bridge_f1 = []
    
    for method in methods:
        method_results = results[method]
        comparison = [r for r in method_results if r.get("question_type") == "comparison"]
        bridge = [r for r in method_results if r.get("question_type") == "bridge"]
        
        comp_f1.append(sum(r.get("f1", 0) for r in comparison) / len(comparison) if comparison else 0)
        bridge_f1.append(sum(r.get("f1", 0) for r in bridge) / len(bridge) if bridge else 0)
    
    axes[0].clear()
    bars1 = axes[0].bar(x - width/2, comp_f1, width, label='Comparison', color=QUESTION_TYPE_COLORS["comparison"])
    bars2 = axes[0].bar(x + width/2, bridge_f1, width, label='Bridge', color=QUESTION_TYPE_COLORS["bridge"])
    
    axes[0].set_xlabel("Method")
    axes[0].set_ylabel("F1 Score")
    axes[0].set_title("F1 by Question Type")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(methods)
    axes[0].legend()
    axes[0].set_ylim(0, 1.05)
    axes[0].grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for bar, val in zip(bars1, comp_f1):
        axes[0].annotate(f'{val:.2f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
    for bar, val in zip(bars2, bridge_f1):
        axes[0].annotate(f'{val:.2f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
    
    # Gold recall by question type
    comp_recall = []
    bridge_recall = []
    
    for method in methods:
        method_results = results[method]
        comparison = [r for r in method_results if r.get("question_type") == "comparison"]
        bridge = [r for r in method_results if r.get("question_type") == "bridge"]
        
        comp_recall.append(sum(r.get("gold_recall", 0) for r in comparison) / len(comparison) if comparison else 0)
        bridge_recall.append(sum(r.get("gold_recall", 0) for r in bridge) / len(bridge) if bridge else 0)
    
    bars3 = axes[1].bar(x - width/2, comp_recall, width, label='Comparison', color=QUESTION_TYPE_COLORS["comparison"])
    bars4 = axes[1].bar(x + width/2, bridge_recall, width, label='Bridge', color=QUESTION_TYPE_COLORS["bridge"])
    
    axes[1].set_xlabel("Method")
    axes[1].set_ylabel("Gold Paragraph Recall")
    axes[1].set_title("Retrieval Quality by Question Type")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(methods)
    axes[1].legend()
    axes[1].set_ylim(0, 1.05)
    axes[1].grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format)
    plt.close()
    
    logger.info(f"Saved question type comparison plot to {output_path}")
    return output_path


def plot_efficiency_comparison(
    results: Dict[str, List[Dict]],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Plot efficiency metrics: F1 per 1K tokens, time per question.
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    methods = list(results.keys())
    
    # Calculate aggregates
    avg_f1 = []
    avg_tokens = []
    avg_time = []
    f1_per_1k = []
    
    for method in methods:
        method_results = results[method]
        n = len(method_results)
        
        f1_vals = [r.get("f1", 0) for r in method_results]
        token_vals = [r.get("total_tokens", 0) for r in method_results]
        time_vals = [r.get("processing_time", 0) for r in method_results]
        
        avg_f1.append(sum(f1_vals) / n if n > 0 else 0)
        avg_tokens.append(sum(token_vals) / n if n > 0 else 0)
        avg_time.append(sum(time_vals) / n if n > 0 else 0)
        
        total_tokens = sum(token_vals)
        total_f1 = sum(f1_vals) / n if n > 0 else 0
        f1_per_1k.append((total_f1 * 1000) / (total_tokens / n) if total_tokens > 0 else 0)
    
    colors = [METHOD_COLORS.get(m, COLORS["neutral"]) for m in methods]
    
    # F1 Score comparison
    bars = axes[0].bar(methods, avg_f1, color=colors, alpha=0.8)
    axes[0].set_ylabel("Avg F1 Score")
    axes[0].set_title("Answer Quality")
    axes[0].set_ylim(0, 1.05)
    for bar, val in zip(bars, avg_f1):
        axes[0].annotate(f'{val:.3f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    # Tokens comparison
    bars = axes[1].bar(methods, avg_tokens, color=colors, alpha=0.8)
    axes[1].set_ylabel("Avg Tokens/Question")
    axes[1].set_title("Token Usage")
    for bar, val in zip(bars, avg_tokens):
        axes[1].annotate(f'{val:.0f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    # Efficiency (F1 per 1K tokens)
    bars = axes[2].bar(methods, f1_per_1k, color=colors, alpha=0.8)
    axes[2].set_ylabel("F1 per 1K Tokens")
    axes[2].set_title("Efficiency (Higher = Better)")
    for bar, val in zip(bars, f1_per_1k):
        axes[2].annotate(f'{val:.3f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    for ax in axes:
        ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format)
    plt.close()
    
    logger.info(f"Saved efficiency comparison plot to {output_path}")
    return output_path


def plot_answer_metrics(
    aggregates: Dict[str, Dict],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Plot comprehensive answer quality metrics (EM, F1, Precision, Recall).
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    methods = list(aggregates.keys())
    x = np.arange(len(methods))
    width = 0.2
    
    em_vals = [aggregates[m].get("answer_metrics", {}).get("avg_em", 0) for m in methods]
    f1_vals = [aggregates[m].get("answer_metrics", {}).get("avg_f1", 0) for m in methods]
    prec_vals = [aggregates[m].get("answer_metrics", {}).get("avg_precision", 0) for m in methods]
    recall_vals = [aggregates[m].get("answer_metrics", {}).get("avg_recall", 0) for m in methods]
    
    bars1 = ax.bar(x - 1.5*width, em_vals, width, label='EM', color=COLORS["primary"])
    bars2 = ax.bar(x - 0.5*width, f1_vals, width, label='F1', color=COLORS["secondary"])
    bars3 = ax.bar(x + 0.5*width, prec_vals, width, label='Precision', color=COLORS["tertiary"])
    bars4 = ax.bar(x + 1.5*width, recall_vals, width, label='Recall', color=COLORS["success"])
    
    ax.set_ylabel("Score")
    ax.set_title("Answer Quality Metrics (Comprehensive)")
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.legend()
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for bars in [bars1, bars2, bars3, bars4]:
        for bar in bars:
            height = bar.get_height()
            if height > 0.01:  # Only label if significant
                ax.annotate(f'{height:.2f}', xy=(bar.get_x() + bar.get_width() / 2, height),
                           xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format)
    plt.close()
    
    logger.info(f"Saved answer metrics plot to {output_path}")
    return output_path


def plot_supporting_facts_metrics(
    aggregates: Dict[str, Dict],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Plot Supporting Facts (SP) metrics: SP EM and SP F1.
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    methods = list(aggregates.keys())
    colors = [METHOD_COLORS.get(m, COLORS["neutral"]) for m in methods]
    x = np.arange(len(methods))
    width = 0.6
    
    # SP EM
    sp_em_vals = [aggregates[m].get("supporting_facts_metrics", {}).get("avg_sp_em", 0) for m in methods]
    bars1 = axes[0].bar(methods, sp_em_vals, width, color=colors, alpha=0.8)
    axes[0].set_ylabel("Score")
    axes[0].set_title("Supporting Facts Exact Match (SP EM)\n(All supporting fact paragraphs retrieved)")
    axes[0].set_ylim(0, 1.05)
    axes[0].grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars1, sp_em_vals):
        axes[0].annotate(f'{val:.3f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    # SP F1
    sp_f1_vals = [aggregates[m].get("supporting_facts_metrics", {}).get("avg_sp_f1", 0) for m in methods]
    bars2 = axes[1].bar(methods, sp_f1_vals, width, color=colors, alpha=0.8)
    axes[1].set_ylabel("Score")
    axes[1].set_title("Supporting Facts F1 (SP F1)\n(F1 of supporting fact paragraph retrieval)")
    axes[1].set_ylim(0, 1.05)
    axes[1].grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars2, sp_f1_vals):
        axes[1].annotate(f'{val:.3f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format)
    plt.close()
    
    logger.info(f"Saved supporting facts metrics plot to {output_path}")
    return output_path


def plot_joint_metrics(
    aggregates: Dict[str, Dict],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Plot Joint metrics: Joint EM and Joint F1.
    
    Joint EM = Answer EM × SP EM (both must be correct)
    Joint F1 = Answer F1 × SP F1
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    methods = list(aggregates.keys())
    colors = [METHOD_COLORS.get(m, COLORS["neutral"]) for m in methods]
    x = np.arange(len(methods))
    width = 0.6
    
    # Joint EM
    joint_em_vals = [aggregates[m].get("joint_metrics", {}).get("avg_joint_em", 0) for m in methods]
    bars1 = axes[0].bar(methods, joint_em_vals, width, color=colors, alpha=0.8)
    axes[0].set_ylabel("Score")
    axes[0].set_title("Joint Exact Match (Joint EM)\n(Answer EM AND SP EM both correct)")
    axes[0].set_ylim(0, 1.05)
    axes[0].grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars1, joint_em_vals):
        axes[0].annotate(f'{val:.3f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    # Joint F1
    joint_f1_vals = [aggregates[m].get("joint_metrics", {}).get("avg_joint_f1", 0) for m in methods]
    bars2 = axes[1].bar(methods, joint_f1_vals, width, color=colors, alpha=0.8)
    axes[1].set_ylabel("Score")
    axes[1].set_title("Joint F1 (Joint F1)\n(Answer F1 × SP F1)")
    axes[1].set_ylim(0, 1.05)
    axes[1].grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars2, joint_f1_vals):
        axes[1].annotate(f'{val:.3f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format)
    plt.close()
    
    logger.info(f"Saved joint metrics plot to {output_path}")
    return output_path


def plot_metrics_summary(
    aggregates: Dict[str, Dict],
    output_path: str,
    config: Optional[PlotConfig] = None,
) -> Optional[str]:
    """
    Create a comprehensive summary plot with all key metrics.
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    config = config or PlotConfig()
    setup_plot_style(config)
    
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    
    methods = list(aggregates.keys())
    colors = [METHOD_COLORS.get(m, COLORS["neutral"]) for m in methods]
    
    # 1. Answer Quality (EM and F1)
    ax = axes[0, 0]
    x = np.arange(len(methods))
    width = 0.35
    
    em_vals = [aggregates[m].get("answer_metrics", {}).get("avg_em", 0) for m in methods]
    f1_vals = [aggregates[m].get("answer_metrics", {}).get("avg_f1", 0) for m in methods]
    
    bars1 = ax.bar(x - width/2, em_vals, width, label='EM', color=COLORS["primary"])
    bars2 = ax.bar(x + width/2, f1_vals, width, label='F1', color=COLORS["secondary"])
    
    ax.set_ylabel("Score")
    ax.set_title("Answer Quality")
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.legend()
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.3f}', xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
    
    # 2. Supporting Facts (SP) Metrics
    ax = axes[0, 1]
    
    sp_em_vals = [aggregates[m].get("supporting_facts_metrics", {}).get("avg_sp_em", 0) for m in methods]
    sp_f1_vals = [aggregates[m].get("supporting_facts_metrics", {}).get("avg_sp_f1", 0) for m in methods]
    
    bars1 = ax.bar(x - width/2, sp_em_vals, width, label='SP EM', color=COLORS["success"])
    bars2 = ax.bar(x + width/2, sp_f1_vals, width, label='SP F1', color=COLORS["tertiary"])
    
    ax.set_ylabel("Score")
    ax.set_title("Supporting Facts (SP) Metrics")
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.legend()
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3, axis='y')
    
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.3f}', xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
    
    # 3. Joint Metrics (Answer AND SP both correct)
    ax = axes[0, 2]
    
    joint_em_vals = [aggregates[m].get("joint_metrics", {}).get("avg_joint_em", 0) for m in methods]
    joint_f1_vals = [aggregates[m].get("joint_metrics", {}).get("avg_joint_f1", 0) for m in methods]
    
    bars1 = ax.bar(x - width/2, joint_em_vals, width, label='Joint EM', color=COLORS["quaternary"])
    bars2 = ax.bar(x + width/2, joint_f1_vals, width, label='Joint F1', color="#8B4513")
    
    ax.set_ylabel("Score")
    ax.set_title("Joint Metrics (Answer + SP)")
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.legend()
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3, axis='y')
    
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.3f}', xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
    
    # 4. Retrieval Quality
    ax = axes[1, 0]
    
    gold_recall = [aggregates[m].get("retrieval_metrics", {}).get("avg_gold_recall", 0) for m in methods]
    first_recall = [aggregates[m].get("first_retrieval_metrics", {}).get("avg_recall", 0) for m in methods]
    
    bars1 = ax.bar(x - width/2, gold_recall, width, label='Overall Gold Recall', color=COLORS["success"])
    bars2 = ax.bar(x + width/2, first_recall, width, label='First Retrieval Recall', color=COLORS["tertiary"])
    
    ax.set_ylabel("Recall")
    ax.set_title("Retrieval Quality")
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.legend()
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3, axis='y')
    
    # 5. Token Usage
    ax = axes[1, 1]
    
    avg_tokens = [aggregates[m].get("token_usage", {}).get("avg_tokens_per_question", 0) for m in methods]
    
    bars = ax.bar(methods, avg_tokens, color=colors, alpha=0.8)
    ax.set_ylabel("Avg Tokens/Question")
    ax.set_title("Token Usage")
    ax.grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars, avg_tokens):
        ax.annotate(f'{val:.0f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                   xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    # 6. Efficiency
    ax = axes[1, 2]
    
    f1_per_1k = [aggregates[m].get("efficiency", {}).get("overall_f1_per_1k_tokens", 0) for m in methods]
    
    bars = ax.bar(methods, f1_per_1k, color=colors, alpha=0.8)
    ax.set_ylabel("F1 per 1K Tokens")
    ax.set_title("Efficiency (Higher = Better)")
    ax.grid(True, alpha=0.3, axis='y')
    
    for bar, val in zip(bars, f1_per_1k):
        ax.annotate(f'{val:.4f}', xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                   xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    plt.suptitle("Experiment Summary (Official HotpotQA Metrics)", fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.dpi, format=config.save_format, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Saved metrics summary plot to {output_path}")
    return output_path


# =============================================================================
# Main Visualization Generator
# =============================================================================

class VisualizationGenerator:
    """Generate all visualizations for experiment results."""
    
    def __init__(self, output_dir: str, config: Optional[PlotConfig] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or PlotConfig()
        self.plots_dir = self.output_dir / "plots"
        self.plots_dir.mkdir(exist_ok=True)
    
    def generate_all(
        self,
        per_question_results: Dict[str, List[Dict]],
        aggregate_results: Dict[str, Dict],
    ) -> Dict[str, str]:
        """
        Generate all visualization plots.
        
        Args:
            per_question_results: Dict mapping method names to per-question results
            aggregate_results: Dict mapping method names to aggregate metrics
        
        Returns:
            Dict mapping plot names to file paths
        """
        if not MATPLOTLIB_AVAILABLE:
            logger.warning("matplotlib not available, skipping visualization")
            return {}
        
        plots = {}
        
        # F1 vs Tokens
        path = str(self.plots_dir / "f1_vs_tokens.png")
        if plot_f1_vs_tokens(per_question_results, path, self.config):
            plots["f1_vs_tokens"] = path
        
        # Retrieval Quality
        path = str(self.plots_dir / "retrieval_quality.png")
        if plot_retrieval_quality(per_question_results, path, self.config):
            plots["retrieval_quality"] = path
        
        # Question Type Comparison
        path = str(self.plots_dir / "question_type_comparison.png")
        if plot_question_type_comparison(per_question_results, path, self.config):
            plots["question_type_comparison"] = path
        
        # Efficiency Comparison
        path = str(self.plots_dir / "efficiency_comparison.png")
        if plot_efficiency_comparison(per_question_results, path, self.config):
            plots["efficiency_comparison"] = path
        
        # Metrics Summary
        path = str(self.plots_dir / "metrics_summary.png")
        if plot_metrics_summary(aggregate_results, path, self.config):
            plots["metrics_summary"] = path
        
        # Answer Metrics (comprehensive)
        path = str(self.plots_dir / "answer_metrics.png")
        if plot_answer_metrics(aggregate_results, path, self.config):
            plots["answer_metrics"] = path
        
        # Supporting Facts Metrics
        path = str(self.plots_dir / "supporting_facts_metrics.png")
        if plot_supporting_facts_metrics(aggregate_results, path, self.config):
            plots["supporting_facts_metrics"] = path
        
        # Joint Metrics
        path = str(self.plots_dir / "joint_metrics.png")
        if plot_joint_metrics(aggregate_results, path, self.config):
            plots["joint_metrics"] = path
        
        logger.info(f"Generated {len(plots)} plots in {self.plots_dir}")
        return plots
    
    def generate_from_json(
        self,
        results_dir: str,
    ) -> Dict[str, str]:
        """
        Generate visualizations from saved JSON results.
        
        Looks for per_question.json and summary.json files in subdirectories.
        """
        results_path = Path(results_dir)
        
        per_question_results = {}
        aggregate_results = {}
        
        # Find all result directories
        for subdir in results_path.iterdir():
            if not subdir.is_dir():
                continue
            
            per_q_file = subdir / "per_question.json"
            summary_file = subdir / "summary.json"
            
            if per_q_file.exists():
                with open(per_q_file) as f:
                    method_name = subdir.name.split("_")[0]  # Extract method name
                    per_question_results[method_name] = json.load(f)
            
            if summary_file.exists():
                with open(summary_file) as f:
                    method_name = subdir.name.split("_")[0]
                    aggregate_results[method_name] = json.load(f)
        
        if not per_question_results:
            logger.warning(f"No results found in {results_dir}")
            return {}
        
        return self.generate_all(per_question_results, aggregate_results)

