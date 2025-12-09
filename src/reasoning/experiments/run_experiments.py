#!/usr/bin/env python3
"""
Main script for running experiments with comprehensive metrics and visualization.

Features:
- BM25 retrieval by default (no embedding API calls)
- Comprehensive metrics (answer, retrieval, efficiency)
- Automatic plot generation
- Markdown reports

Usage:
    # Compare methods (default: BM25 retrieval)
    python -m src.reasoning.experiments.run_experiments compare \\
        --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \\
        --num_samples 50 \\
        --output_dir ./outputs
    
    # Use dense (embedding) retrieval
    python -m src.reasoning.experiments.run_experiments compare \\
        --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \\
        --use_dense \\
        --num_samples 50
    
    # Single method
    python -m src.reasoning.experiments.run_experiments single \\
        --method ircot \\
        --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \\
        --num_samples 20

Environment:
    MISTRAL_API_KEY: Your Mistral API key (required for LLM calls)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Load .env file and set up paths
# File is at: hotpotqa/src/reasoning/experiments/run_experiments.py
# Need to go up 3 levels to get to hotpotqa/
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent.parent  # hotpotqa/
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass

from src.reasoning.experiments.runner import ExperimentRunner
from src.reasoning.experiments.adapters import (
    IRCoTAdapter, DecompositionAdapter, SimpleCoTAdapter, create_adapter
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Run reasoning experiments with comprehensive metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare IRCoT and Decomposition using BM25 retrieval
  python run_experiments.py compare --data_path data.json --num_samples 50
  
  # Use dense (embedding) retrieval
  python run_experiments.py compare --data_path data.json --use_dense --num_samples 50
  
  # Run single method
  python run_experiments.py single --method ircot --data_path data.json --num_samples 20
  
  # Skip plot generation
  python run_experiments.py compare --data_path data.json --no_plots
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare multiple methods")
    compare_parser.add_argument("--data_path", type=str, required=True,
                               help="Path to HotpotQA JSON file")
    compare_parser.add_argument("--num_samples", type=int, default=None,
                               help="Number of samples (default: all)")
    compare_parser.add_argument("--output_dir", type=str, default="./outputs",
                               help="Output directory (default: ./outputs)")
    compare_parser.add_argument("--seed", type=int, default=42,
                               help="Random seed (default: 42)")
    compare_parser.add_argument("--methods", type=str, nargs="+",
                               default=["ircot", "decomposition", "simplecot"],
                               help="Methods to compare (default: ircot decomposition simplecot)")
    compare_parser.add_argument("--use_dense", action="store_true",
                               help="Use dense (embedding) retrieval instead of BM25")
    compare_parser.add_argument("--no_plots", action="store_true",
                               help="Skip plot generation")
    
    # Single method command
    single_parser = subparsers.add_parser("single", help="Run single method")
    single_parser.add_argument("--data_path", type=str, required=True,
                              help="Path to HotpotQA JSON file")
    single_parser.add_argument("--method", type=str, required=True,
                              choices=["ircot", "decomposition"],
                              help="Method to run")
    single_parser.add_argument("--num_samples", type=int, default=None,
                              help="Number of samples (default: all)")
    single_parser.add_argument("--output_dir", type=str, default="./outputs",
                              help="Output directory")
    single_parser.add_argument("--seed", type=int, default=42,
                              help="Random seed")
    single_parser.add_argument("--use_dense", action="store_true",
                              help="Use dense retrieval instead of BM25")
    single_parser.add_argument("--no_plots", action="store_true",
                              help="Skip plot generation")
    
    # Visualize command (from existing results)
    viz_parser = subparsers.add_parser("visualize", help="Generate plots from existing results")
    viz_parser.add_argument("--results_dir", type=str, required=True,
                           help="Directory containing result JSON files")
    viz_parser.add_argument("--output_dir", type=str, default=None,
                           help="Output directory for plots (default: results_dir)")
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    # Check API key
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        logger.error("MISTRAL_API_KEY environment variable not set")
        logger.info("Set it with: export MISTRAL_API_KEY=your_key")
        return
    
    if args.command == "compare":
        run_comparison(args)
    elif args.command == "single":
        run_single(args)
    elif args.command == "visualize":
        run_visualize(args)


def run_comparison(args):
    """Run method comparison."""
    logger.info("="*60)
    logger.info("RUNNING METHOD COMPARISON")
    logger.info("="*60)
    logger.info(f"Data: {args.data_path}")
    logger.info(f"Methods: {args.methods}")
    logger.info(f"Samples: {args.num_samples or 'all'}")
    logger.info(f"Retrieval: {'Dense (embeddings)' if args.use_dense else 'BM25 (lexical)'}")
    logger.info("="*60)
    
    # Create runner
    runner = ExperimentRunner(
        data_path=args.data_path,
        output_dir=args.output_dir,
        num_samples=args.num_samples,
        seed=args.seed,
        generate_plots=not args.no_plots,
    )
    
    # Create adapters (all use BM25 by default unless --use_dense is set)
    adapters = {}
    for method in args.methods:
        method_lower = method.lower()
        if method_lower == "ircot":
            adapters["IRCoT"] = IRCoTAdapter(use_dense=args.use_dense)
        elif method_lower in ("decomposition", "querydecomposition"):
            # Ensure self-consistency is disabled
            from src.reasoning.methods.decomposition import DecompositionConfig
            config = DecompositionConfig()
            config.self_consistency_enabled = False
            adapters["Decomposition"] = DecompositionAdapter(config=config, use_dense=args.use_dense)
        elif method_lower in ("simplecot", "simple_cot", "basiccot", "basic_cot"):
            adapters["SimpleCoT"] = SimpleCoTAdapter(use_dense=args.use_dense)
        else:
            logger.warning(f"Unknown method: {method}, skipping")
    
    if not adapters:
        logger.error("No valid methods specified")
        return
    
    # Run comparison
    runner.compare_methods(adapters)
    

def run_single(args):
    """Run single method."""
    logger.info("="*60)
    logger.info(f"RUNNING SINGLE METHOD: {args.method.upper()}")
    logger.info("="*60)
    
    # Create runner
    runner = ExperimentRunner(
        data_path=args.data_path,
        output_dir=args.output_dir,
        num_samples=args.num_samples,
        seed=args.seed,
        generate_plots=not args.no_plots,
    )
    
    # Create adapter
    adapter = create_adapter(args.method, use_dense=args.use_dense)
    method_lower = args.method.lower()
    if method_lower == "ircot":
            method_name = "IRCoT"
    elif method_lower in ("decomposition", "querydecomposition"):
        method_name = "Decomposition"
    else:
        method_name = "SimpleCoT"
        
    # Run
        results = runner.run_method(adapter, method_name)
    
    from src.reasoning.core.metrics import MetricsCalculator
    aggregate = MetricsCalculator.aggregate_metrics(results, method_name)
    
    runner.save_results(results, aggregate, method_name)
        
    # Print summary
    print(f"\n{'='*60}")
    print(f"RESULTS: {method_name}")
    print(f"{'='*60}")
    print(f"Questions: {aggregate.num_questions}")
    print(f"Errors: {aggregate.num_errors}")
    print(f"\nAnswer Quality:")
    print(f"  EM: {aggregate.avg_em:.4f}")
    print(f"  F1: {aggregate.avg_f1:.4f}")
    print(f"\nRetrieval Quality:")
    print(f"  Gold Recall: {aggregate.avg_gold_recall:.4f}")
    print(f"  First Retrieval Recall: {aggregate.avg_first_retrieval_recall:.4f}")
    print(f"\nEfficiency:")
    print(f"  Total Tokens: {aggregate.total_tokens:,}")
    print(f"  F1 per 1K Tokens: {aggregate.overall_f1_per_1k_tokens:.4f}")
    print(f"  Total Time: {aggregate.total_time:.2f}s")
    print(f"{'='*60}")


def run_visualize(args):
    """Generate visualizations from existing results."""
    from src.reasoning.core.visualization import VisualizationGenerator
    
    output_dir = args.output_dir or args.results_dir
    
    logger.info(f"Generating visualizations from {args.results_dir}")
    
    viz = VisualizationGenerator(output_dir)
    plots = viz.generate_from_json(args.results_dir)
    
    if plots:
        logger.info(f"Generated {len(plots)} plots:")
        for name, path in plots.items():
            logger.info(f"  - {name}: {path}")
    else:
        logger.warning("No plots generated (check if results exist)")


if __name__ == "__main__":
    main()
