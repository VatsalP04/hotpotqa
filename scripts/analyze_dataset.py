#!/usr/bin/env python3
"""
Analyze HotpotQA dataset and generate statistics.

This script loads HotpotQA data and generates comprehensive statistics
about questions, answers, context, reasoning types, and supporting facts.

Usage:
    python scripts/analyze_dataset.py --split train
    python scripts/analyze_dataset.py --split dev --save-stats
    python scripts/analyze_dataset.py --help
"""

import sys
import argparse
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.loader import load_hotpotqa
from src.utils.analysis import get_dataset_statistics, print_statistics, save_statistics
from src.config.config_manager import ConfigManager


def setup_logging(log_level: str = "INFO") -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(levelname)s - %(message)s"
    )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze HotpotQA dataset and generate statistics",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--split",
        type=str,
        default="train",
        choices=["train", "dev"],
        help="Dataset split to analyze (default: train)"
    )

    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Directory containing dataset files (default: data/raw)"
    )

    parser.add_argument(
        "--max-examples",
        type=int,
        default=None,
        help="Maximum number of examples to analyze (default: all)"
    )

    parser.add_argument(
        "--save-stats",
        action="store_true",
        help="Save statistics to JSON file"
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for statistics JSON (default: data/processed/<split>_stats.json)"
    )

    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed statistics"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )

    return parser.parse_args()


def main():
    """Main analysis execution."""
    args = parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("HotpotQA Dataset Analysis")
    logger.info("=" * 60)
    logger.info(f"Split: {args.split}")
    if args.max_examples:
        logger.info(f"Max examples: {args.max_examples}")
    logger.info("=" * 60)

    try:
        # Determine data directory
        if args.data_dir:
            data_dir = Path(args.data_dir)
        else:
            config = ConfigManager()
            data_dir = PROJECT_ROOT / config.get('data.raw_dir', 'data/raw')

        logger.info(f"\nLoading data from: {data_dir}")

        # Load data
        examples = load_hotpotqa(
            data_dir=data_dir,
            split=args.split,
            max_examples=args.max_examples,
            validate=False  # Skip validation for speed
        )

        logger.info(f"Loaded {len(examples)} examples\n")

        # Analyze dataset
        logger.info("Analyzing dataset...\n")
        stats = get_dataset_statistics(examples)

        # Print statistics
        print()  # Blank line before stats
        print_statistics(stats, detailed=args.detailed)

        # Save statistics if requested
        if args.save_stats:
            if args.output:
                output_path = Path(args.output)
            else:
                config = ConfigManager()
                processed_dir = PROJECT_ROOT / config.get('data.processed_dir', 'data/processed')
                processed_dir.mkdir(parents=True, exist_ok=True)
                output_path = processed_dir / f"{args.split}_stats.json"

            logger.info(f"\nSaving statistics to: {output_path}")
            save_statistics(stats, str(output_path), pretty=True)
            logger.info("✅ Statistics saved!")

        return 0

    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        logger.error("\nPlease ensure the HotpotQA dataset is downloaded to the data directory.")
        return 2

    except KeyboardInterrupt:
        logger.warning("\n⚠️  Analysis interrupted by user")
        return 130

    except Exception as e:
        logger.error(f"❌ Error during analysis: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
