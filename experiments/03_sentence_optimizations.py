#!/usr/bin/env python3
"""
Experiment 3: Sentence-Level Retrieval Optimizations

After establishing that sentence-level is promising, this script tests optimizations:
1. Coreference resolution preprocessing
2. Context window embedding (embed with context, retrieve sentence)
3. Cross-encoder reranking
4. Hybrid BM25 + Dense retrieval

Usage:
    python experiments/03_sentence_optimizations.py --max_examples 100 --seed 42
"""

import sys
import json
import csv
import argparse
import random
import re
import math
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from collections import defaultdict
import os

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Import from existing modules
from src.data.loader import load_hotpotqa
from src.models.mistral_client import MistralClient
from src.reasoning.sentence_retrieval import OptimizedSentenceRetriever, ParagraphWithSentences


# =============================================================================
# Evaluation Metrics
# =============================================================================
def sp_metrics(pred_sp, gold_sp) -> Dict:
    """Compute supporting facts metrics."""
    pred_set = set(map(tuple, pred_sp))
    gold_set = set(map(tuple, gold_sp))
    
    tp = len(pred_set & gold_set)
    precision = tp / len(pred_set) if pred_set else 0
    recall = tp / len(gold_set) if gold_set else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    # Soft recall - allow tolerance in sentence index
    def soft_recall(tol):
        matches = 0
        for gt, gi in gold_set:
            for pt, pi in pred_set:
                if gt == pt and abs(gi - pi) <= tol:
                    matches += 1
                    break
        return matches / len(gold_set) if gold_set else 0
    
    # Title recall
    pred_titles = set(t for t, _ in pred_set)
    gold_titles = set(t for t, _ in gold_set)
    title_recall = len(pred_titles & gold_titles) / len(gold_titles) if gold_titles else 0
    
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'soft_recall_1': soft_recall(1),
        'soft_recall_2': soft_recall(2),
        'title_recall': title_recall,
    }


# =============================================================================
# Experiment Runner
# =============================================================================
def run_optimization_experiment(
    dev_data: List[Dict],
    config_name: str,
    config: Dict,
    embed_fn=None,
) -> Tuple[List[Dict], Dict]:
    """Run experiment with specific optimization config."""
    
    rows = []
    all_metrics = []
    
    for i, example in enumerate(dev_data):
        question = example['question']
        gold_sp = example.get('supporting_facts', [])
        context = example['context']
        
        # Build paragraphs
        paragraphs = [
            ParagraphWithSentences(title, sentences)
            for title, sentences in context
        ]
        
        # Build retriever with config
        retriever = OptimizedSentenceRetriever(
            paragraphs=paragraphs,
            use_coref=config.get('use_coref', False),
            use_context_window=config.get('use_context_window', True),
            use_hybrid=config.get('use_hybrid', False),
            use_reranking=config.get('use_reranking', False),
            context_window_size=config.get('context_window_size', 1),
            embed_fn=embed_fn,
        )
        
        # Retrieve
        top_k = config.get('top_k', 10)
        retrieved = retriever.retrieve(question, top_k)
        pred_sp = retriever.get_supporting_facts()
        
        # Metrics
        metrics = sp_metrics(pred_sp, gold_sp)
        all_metrics.append(metrics)
        
        rows.append({
            'qid': example.get('_id', str(i)),
            'question': question,
            'precision': metrics['precision'],
            'recall': metrics['recall'],
            'f1': metrics['f1'],
            'soft_recall_1': metrics['soft_recall_1'],
            'title_recall': metrics['title_recall'],
            'num_pred': len(pred_sp),
            'num_gold': len(gold_sp),
        })
        
        if (i + 1) % 25 == 0:
            avg_f1 = sum(m['f1'] for m in all_metrics) / len(all_metrics)
            print(f"    [{i+1}/{len(dev_data)}] {config_name}: F1={avg_f1:.3f}")
    
    # Aggregate
    n = len(all_metrics)
    agg = {
        'config_name': config_name,
        'n': n,
        'avg_precision': sum(m['precision'] for m in all_metrics) / n,
        'avg_recall': sum(m['recall'] for m in all_metrics) / n,
        'avg_f1': sum(m['f1'] for m in all_metrics) / n,
        'avg_soft_recall_1': sum(m['soft_recall_1'] for m in all_metrics) / n,
        'avg_title_recall': sum(m['title_recall'] for m in all_metrics) / n,
    }
    
    return rows, agg


# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_examples", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top_k", type=int, default=8)
    parser.add_argument("--data_path", type=str, default=None)
    parser.add_argument("--use_mock", action="store_true",
                        help="Use mock embeddings (for testing without API)")
    args = parser.parse_args()
    
    random.seed(args.seed)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "experiments" / "sentence_optimizations" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*80)
    print("EXPERIMENT 3: SENTENCE-LEVEL RETRIEVAL OPTIMIZATIONS")
    print("="*80)
    print(f"Max Examples: {args.max_examples}")
    print(f"Top-K: {args.top_k}")
    print(f"Seed: {args.seed}")
    print(f"Output: {output_dir}")
    print("="*80 + "\n")
    
    # Load data
    if args.data_path:
        print(f"Loading data from: {args.data_path}")
        with open(args.data_path) as f:
            dev_data = json.load(f)
    else:
        # Use the project's data loader
        print(f"Loading data from: {PROJECT_ROOT / 'data' / 'hotpotqa'}")
        dev_data = load_hotpotqa(
            data_dir=PROJECT_ROOT / "data" / "hotpotqa",
            split="dev",
            max_examples=None,
            shuffle=False,
            seed=args.seed
        )
    
    random.seed(args.seed)
    random.shuffle(dev_data)
    dev_data = dev_data[:args.max_examples]
    print(f"Loaded {len(dev_data)} examples\n")
    
    # Initialize embedding function
    embed_fn = None
    if not args.use_mock:
        try:
            print("Initializing Mistral client for embeddings...")
            mistral_client = MistralClient()
            embed_fn = mistral_client.embed
            print("✅ Using Mistral embeddings\n")
        except Exception as e:
            print(f"WARNING: Could not initialize Mistral client: {e}")
            print("Using mock embeddings (deterministic but not semantic)\n")
            # embed_fn will remain None, OptimizedSentenceRetriever will use mock
    else:
        print("Using mock embeddings (for testing)\n")
    
    # Define configurations to test
    configs = {
        'baseline': {
            'use_coref': False,
            'use_context_window': False,
            'use_hybrid': False,
            'use_reranking': False,
            'top_k': args.top_k,
        },
        'context_window': {
            'use_coref': False,
            'use_context_window': True,
            'use_hybrid': False,
            'use_reranking': False,
            'context_window_size': 1,
            'top_k': args.top_k,
        },
        'coref_resolution': {
            'use_coref': True,
            'use_context_window': False,
            'use_hybrid': False,
            'use_reranking': False,
            'top_k': args.top_k,
        },
        'coref_plus_context': {
            'use_coref': True,
            'use_context_window': True,
            'use_hybrid': False,
            'use_reranking': False,
            'context_window_size': 1,
            'top_k': args.top_k,
        },
        'hybrid_retrieval': {
            'use_coref': False,
            'use_context_window': True,
            'use_hybrid': True,
            'use_reranking': False,
            'context_window_size': 1,
            'top_k': args.top_k,
        },
        'full_optimization': {
            'use_coref': True,
            'use_context_window': True,
            'use_hybrid': True,
            'use_reranking': False,  # Set to True if you have cross-encoder
            'context_window_size': 1,
            'top_k': args.top_k,
        },
    }
    
    results = {}
    
    for config_name, config in configs.items():
        print(f"\n🔬 Running: {config_name}")
        print(f"   Config: {config}")
        rows, agg = run_optimization_experiment(dev_data, config_name, config, embed_fn)
        results[config_name] = agg
        
        # Save CSV
        csv_path = output_dir / f"{config_name}_results.csv"
        with open(csv_path, 'w', newline='') as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
        print(f"   Saved: {csv_path}")
    
    # Print comparison
    print("\n" + "="*80)
    print("OPTIMIZATION COMPARISON")
    print("="*80)
    
    print(f"\n{'Configuration':<25} {'Precision':<12} {'Recall':<12} {'F1':<12} {'Soft R@1':<12} {'Title R':<12}")
    print("-"*85)
    
    for name, agg in results.items():
        print(f"{name:<25} {agg['avg_precision']:<12.4f} {agg['avg_recall']:<12.4f} {agg['avg_f1']:<12.4f} {agg['avg_soft_recall_1']:<12.4f} {agg['avg_title_recall']:<12.4f}")
    
    # Find best
    best = max(results.items(), key=lambda x: x[1]['avg_f1'])
    print(f"\n🏆 Best Configuration: {best[0]} (F1: {best[1]['avg_f1']:.4f})")
    
    # Save summary
    with open(output_dir / "comparison_summary.json", 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📁 Results saved to: {output_dir}")
    print("="*80)


if __name__ == "__main__":
    main()
