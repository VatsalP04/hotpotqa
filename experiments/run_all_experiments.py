#!/usr/bin/env python3
"""
run_all_experiments.py - Master Script to Run All Experiments

This script runs all three experiments in sequence:
1. Retriever comparison (BM25 vs Dense vs Hybrid)
2. Sentence vs Paragraph level comparison
3. Sentence-level optimizations

Usage:
    python scripts/run_all_experiments.py --max_examples 100 --seed 42

Output:
    experiments/
    ├── retriever_comparison/
    │   ├── retriever_bm25_*.csv
    │   ├── retriever_dense_*.csv
    │   ├── retriever_hybrid_*.csv
    │   └── retriever_comparison_*.json
    ├── sentence_vs_paragraph/
    │   ├── <timestamp>/
    │   │   ├── paragraph_results.csv
    │   │   ├── sentence_results.csv
    │   │   └── comparison.json
    └── sentence_optimizations/
        └── <timestamp>/
            ├── baseline_results.csv
            ├── context_window_results.csv
            ├── coref_resolution_results.csv
            ├── hybrid_retrieval_results.csv
            ├── full_optimization_results.csv
            └── comparison_summary.json
"""

import subprocess
import sys
import argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_experiment(script_name: str, args: list) -> bool:
    """Run an experiment script and return success status."""
    script_path = PROJECT_ROOT / "experiments" / script_name
    
    if not script_path.exists():
        print(f"ERROR: Script not found: {script_path}")
        return False
    
    cmd = [sys.executable, str(script_path)] + args
    print(f"\n{'='*80}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*80}\n")
    
    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT)
        return result.returncode == 0
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run all experiments")
    parser.add_argument("--max_examples", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top_k", type=int, default=5)
    parser.add_argument("--skip_retriever", action="store_true",
                        help="Skip retriever comparison experiment")
    parser.add_argument("--skip_sentence_para", action="store_true",
                        help="Skip sentence vs paragraph experiment")
    parser.add_argument("--skip_optimizations", action="store_true",
                        help="Skip sentence optimizations experiment")
    parser.add_argument("--use_mock", action="store_true",
                        help="Use mock embeddings (for testing)")
    parser.add_argument("--data_path", type=str, default=None,
                        help="Path to HotpotQA dev data")
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("HOTPOTQA SENTENCE-LEVEL RETRIEVAL EXPERIMENTS")
    print("="*80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Max Examples: {args.max_examples}")
    print(f"Seed: {args.seed}")
    print(f"Top-K: {args.top_k}")
    print("="*80)
    
    common_args = [
        "--max_examples", str(args.max_examples),
        "--seed", str(args.seed),
        "--top_k", str(args.top_k),
    ]
    
    if args.data_path:
        common_args.extend(["--data_path", args.data_path])
    
    results = {}
    
    # Experiment 1: Retriever Comparison
    if not args.skip_retriever:
        print("\n" + "🔬 "*20)
        print("EXPERIMENT 1: RETRIEVER COMPARISON (BM25 vs Dense vs Hybrid)")
        print("🔬 "*20)
        
        exp1_args = common_args.copy()
        if args.use_mock:
            exp1_args.append("--use_mock")
        
        results['retriever_comparison'] = run_experiment(
            "01_compare_retrievers.py", 
            exp1_args
        )
    
    # Experiment 2: Sentence vs Paragraph
    if not args.skip_sentence_para:
        print("\n" + "🔬 "*20)
        print("EXPERIMENT 2: SENTENCE vs PARAGRAPH RETRIEVAL")
        print("🔬 "*20)
        
        results['sentence_vs_paragraph'] = run_experiment(
            "02_sentence_vs_paragraph.py",
            common_args
        )
    
    # Experiment 3: Sentence Optimizations
    if not args.skip_optimizations:
        print("\n" + "🔬 "*20)
        print("EXPERIMENT 3: SENTENCE-LEVEL OPTIMIZATIONS")
        print("🔬 "*20)
        
        results['sentence_optimizations'] = run_experiment(
            "03_sentence_optimizations.py",
            common_args
        )
    
    # Summary
    print("\n" + "="*80)
    print("EXPERIMENT SUMMARY")
    print("="*80)
    
    for exp_name, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"  {exp_name}: {status}")
    
    print("\n📁 Results saved in: experiments/")
    print("="*80)
    
    # Return non-zero if any experiment failed
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
