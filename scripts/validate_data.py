#!/usr/bin/env python3
"""
Validate HotpotQA dataset files.

This script validates the structure and content of HotpotQA data files,
checking for missing fields, invalid references, and data quality issues.

Usage:
    python scripts/validate_data.py --split train
    python scripts/validate_data.py --split dev --verbose
    python scripts/validate_data.py --help
"""

import sys
import argparse
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.loader import load_hotpotqa
from src.data.validator import validate_and_report, validate_supporting_facts_coverage
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
        description="Validate HotpotQA dataset files",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--split",
        type=str,
        default="train",
        choices=["train", "dev"],
        help="Dataset split to validate (default: train)"
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
        help="Maximum number of examples to validate (default: all)"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed validation errors"
    )

    parser.add_argument(
        "--check-coverage",
        action="store_true",
        help="Check supporting facts coverage in context"
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
    """Main validation execution."""
    args = parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("HotpotQA Dataset Validation")
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

        # Load data (without validation to test validator)
        examples = load_hotpotqa(
            data_dir=data_dir,
            split=args.split,
            max_examples=args.max_examples,
            validate=False  # We'll validate manually
        )

        logger.info(f"Loaded {len(examples)} examples\n")

        # Run validation
        logger.info("Running structural validation...")
        is_valid = validate_and_report(
            examples,
            split=args.split,
            verbose=args.verbose
        )

        # Check supporting facts coverage if requested
        if args.check_coverage:
            logger.info("\n" + "=" * 60)
            logger.info("Checking supporting facts coverage...")
            logger.info("=" * 60)

            coverage_stats = validate_supporting_facts_coverage(examples)

            logger.info(f"Total examples: {coverage_stats['total_examples']}")
            logger.info(f"Fully covered: {coverage_stats['fully_covered_count']} "
                       f"({coverage_stats['fully_covered_percent']:.1f}%)")
            logger.info(f"Average coverage: {coverage_stats['average_coverage']:.1%}")

            if coverage_stats['issues_count'] > 0:
                logger.warning(f"\nFound {coverage_stats['issues_count']} "
                             f"examples with coverage issues")
                if args.verbose:
                    logger.warning("Sample issues:")
                    for issue in coverage_stats['sample_issues']:
                        logger.warning(f"  - {issue['example_id']}: "
                                     f"missing {len(issue['missing_titles'])} titles")

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 60)

        if is_valid:
            logger.info("✅ All validations passed!")
            return 0
        else:
            logger.warning("⚠️  Some validation issues found (see above)")
            logger.warning("Dataset may still be usable depending on the severity of issues")
            return 1

    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        logger.error("\nPlease ensure the HotpotQA dataset is downloaded to the data directory.")
        logger.error("Run the download script if needed: bash data/raw/download.sh")
        return 2

    except KeyboardInterrupt:
        logger.warning("\n⚠️  Validation interrupted by user")
        return 130

    except Exception as e:
        logger.error(f"❌ Error during validation: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
