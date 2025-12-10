#!/usr/bin/env python3
"""
Ablation studies for Query Decomposition method.

Compares different fallback strategies:
1. Full Pipeline: search query fallback + relaxed prompt fallback
2. Relaxed Only: skip search query, directly use relaxed prompt on NOT_FOUND
3. Full + Self-Consistency: full pipeline + self-consistency (5 samples @ 0.6 temp)
4. No Fallback: keep NOT_FOUND as answer (baseline)

Usage:
    uv run python src/reasoning/experiments/run_ablation.py \
        --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
        --num_samples 100 \
        --output_dir ./outputs/ablation
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Load .env file and set up paths
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

from src.reasoning.experiments.runner import ExperimentRunner, MethodResult
from src.reasoning.experiments.adapters import DecompositionAdapter
from src.reasoning.methods.decomposition import DecompositionConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_ablation_configs():
    """Create configurations for each ablation variant."""
    return {
        "Decomp_Full": DecompositionConfig.full_pipeline(),
        "Decomp_RelaxedOnly": DecompositionConfig.relaxed_only(),
        "Decomp_Full+SC": DecompositionConfig.full_with_self_consistency(num_samples=5, temperature=0.6),
        "Decomp_NoFallback": DecompositionConfig.no_fallback(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run ablation studies for Query Decomposition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ablation Variants:
  Decomp_Full       - Full pipeline: search query fallback + relaxed prompt
  Decomp_RelaxedOnly - Skip search query, directly use relaxed prompt on NOT_FOUND
  Decomp_Full+SC    - Full pipeline + self-consistency (5 samples @ 0.6 temp)
  Decomp_NoFallback - No fallback, keep NOT_FOUND as answer (baseline)

Examples:
  # Run all ablation variants
  uv run python src/reasoning/experiments/run_ablation.py \\
      --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \\
      --num_samples 100
  
  # Run specific variants
  uv run python src/reasoning/experiments/run_ablation.py \\
      --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \\
      --variants Decomp_Full Decomp_RelaxedOnly \\
      --num_samples 50
        """
    )
    
    parser.add_argument("--data_path", type=str, required=True,
                       help="Path to HotpotQA JSON file")
    parser.add_argument("--num_samples", type=int, default=100,
                       help="Number of samples (default: 100)")
    parser.add_argument("--output_dir", type=str, default="./outputs/ablation",
                       help="Output directory (default: ./outputs/ablation)")
    parser.add_argument("--seed", type=int, default=42,
                       help="Random seed (default: 42)")
    parser.add_argument("--variants", type=str, nargs="+", default=None,
                       help="Specific variants to run (default: all)")
    parser.add_argument("--no_plots", action="store_true",
                       help="Skip plot generation")
    
    args = parser.parse_args()
    
    # Check API key
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        logger.error("MISTRAL_API_KEY environment variable not set")
        logger.info("Set it with: export MISTRAL_API_KEY=your_key")
        return
    
    run_ablation(args)


def run_ablation(args):
    """Run ablation study."""
    logger.info("=" * 60)
    logger.info("QUERY DECOMPOSITION ABLATION STUDY")
    logger.info("=" * 60)
    logger.info(f"Data: {args.data_path}")
    logger.info(f"Samples: {args.num_samples}")
    logger.info(f"Output: {args.output_dir}")
    logger.info("=" * 60)
    
    # Create runner
    runner = ExperimentRunner(
        data_path=args.data_path,
        output_dir=args.output_dir,
        num_samples=args.num_samples,
        seed=args.seed,
        generate_plots=not args.no_plots,
    )
    
    # Get ablation configs
    all_configs = create_ablation_configs()
    
    # Filter to requested variants
    if args.variants:
        configs = {k: v for k, v in all_configs.items() if k in args.variants}
        if not configs:
            logger.error(f"No valid variants specified. Choose from: {list(all_configs.keys())}")
            return
    else:
        configs = all_configs
    
    logger.info(f"Running {len(configs)} ablation variants:")
    for name, config in configs.items():
        logger.info(f"  - {name}:")
        logger.info(f"      search_query_fallback: {config.enable_search_query_fallback}")
        logger.info(f"      relaxed_prompt_fallback: {config.enable_relaxed_prompt_fallback}")
        logger.info(f"      self_consistency: {config.self_consistency_enabled} (n={config.self_consistency_num_samples})")
    logger.info("")
    
    # Create adapters
    adapters = {}
    for name, config in configs.items():
        adapters[name] = DecompositionAdapter(config=config, use_dense=False)
        logger.info(f"✓ Created adapter: {name}")
    
    # Run comparison
    runner.compare_methods(adapters)
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("ABLATION STUDY COMPLETE")
    logger.info(f"Results saved to: {args.output_dir}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

