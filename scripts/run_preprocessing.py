#!/usr/bin/env python3
"""
Run the complete preprocessing pipeline on HotpotQA data.

This script loads raw HotpotQA data, applies all preprocessing steps
(cleaning, tokenization, context processing, multi-hop feature extraction),
and saves the processed data for downstream tasks.

Usage:
    python scripts/run_preprocessing.py --split train --preset quick
    python scripts/run_preprocessing.py --split dev --config configs/custom.yaml
    python scripts/run_preprocessing.py --help
"""

import sys
import argparse
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.config_manager import load_config
from src.preprocessing.pipeline import HotpotQAPreprocessor


def setup_logging(log_level: str = "INFO", log_file: str = None) -> None:
    """Setup logging configuration."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=handlers
    )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run preprocessing pipeline on HotpotQA data",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--split",
        type=str,
        default="train",
        choices=["train", "dev"],
        help="Dataset split to process (default: train)"
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to configuration file (default: configs/default.yaml)"
    )

    parser.add_argument(
        "--preset",
        type=str,
        default=None,
        choices=["quick", "full", "rag", "baseline"],
        help="Preprocessing preset to use (overrides config)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for processed data (default: auto-generated)"
    )

    parser.add_argument(
        "--max-examples",
        type=int,
        default=None,
        help="Maximum number of examples to process (default: all)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )

    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to log file (default: logs/preprocessing.log)"
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save processed data (useful for testing)"
    )

    return parser.parse_args()


def main():
    """Main preprocessing pipeline execution."""
    args = parse_args()

    # Setup logging
    if args.log_file is None and not args.no_save:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        args.log_file = str(log_dir / f"preprocessing_{args.split}.log")

    setup_logging(args.log_level, args.log_file)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("HotpotQA Preprocessing Pipeline")
    logger.info("=" * 60)
    logger.info(f"Split: {args.split}")
    logger.info(f"Preset: {args.preset or 'None'}")
    logger.info(f"Config: {args.config or 'default'}")
    if args.max_examples:
        logger.info(f"Max examples: {args.max_examples}")
    logger.info("=" * 60)

    try:
        # Load configuration
        logger.info("Loading configuration...")
        overrides = {}
        if args.max_examples:
            overrides['data.max_examples'] = args.max_examples

        config = load_config(
            config_file=args.config,
            preset=args.preset,
            overrides=overrides if overrides else None
        )

        # Initialize preprocessor
        logger.info("Initializing preprocessor...")
        preprocessor = HotpotQAPreprocessor(config)

        # Determine output path
        output_path = args.output
        if not args.no_save and output_path is None:
            processed_dir = PROJECT_ROOT / config.get('data.processed_dir', 'data/processed')
            processed_dir.mkdir(parents=True, exist_ok=True)

            preset_suffix = f"_{args.preset}" if args.preset else ""
            output_format = config.get('preprocessing.output.save_format', 'json')
            output_path = processed_dir / f"{args.split}_processed{preset_suffix}.{output_format}"

        # Run preprocessing
        logger.info(f"Running preprocessing on {args.split} split...")
        processed_examples = preprocessor.run(
            split=args.split,
            output_path=output_path if not args.no_save else None
        )

        # Print summary
        logger.info("=" * 60)
        logger.info("PREPROCESSING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Processed examples: {len(processed_examples)}")
        if not args.no_save:
            logger.info(f"Output saved to: {output_path}")
        logger.info("=" * 60)

        # Print sample output
        if processed_examples:
            logger.info("\nSample processed example:")
            example = processed_examples[0]
            logger.info(f"  ID: {example.get('_id', 'N/A')}")
            logger.info(f"  Question: {example.get('question', 'N/A')[:100]}...")
            logger.info(f"  Answer: {example.get('answer', 'N/A')}")
            logger.info(f"  Context length: {len(example.get('context_flat', ''))} chars")
            logger.info(f"  Reasoning type: {example.get('multihop', {}).get('reasoning_type', 'N/A')}")
            logger.info(f"  Number of hops: {example.get('multihop', {}).get('num_hops', 'N/A')}")

        return 0

    except KeyboardInterrupt:
        logger.warning("\n⚠️  Preprocessing interrupted by user")
        return 130

    except Exception as e:
        logger.error(f"❌ Error during preprocessing: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
