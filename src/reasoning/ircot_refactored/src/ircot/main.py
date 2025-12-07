#!/usr/bin/env python3
"""
Main script for running IRCoT experiments on HotpotQA.

Usage:
    # Run IRCoT on dev set
    python -m ircot.main run --num_samples 100
    
    # Run baseline comparison
    python -m ircot.main run --num_samples 100 --baseline
    
    # Run ablation study
    python -m ircot.main ablation --num_samples 50
    
    # Download data
    python -m ircot.main download
    
    # Evaluate predictions
    python -m ircot.main evaluate --predictions pred.json --gold gold.json

Environment:
    MISTRAL_API_KEY: Your Mistral API key (required)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import (
    IRCoTConfig,
    IRCoTQA,
    HotpotQALoader,
    download_hotpotqa,
    subsample,
    get_statistics,
    format_for_prediction,
    detailed_evaluation,
    format_report,
    save_official_format,
    error_analysis,
    get_config_for_ablation,
    ABLATION_CONFIGS,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Experiment Runner
# =============================================================================

class ExperimentRunner:
    """Runs IRCoT experiments with proper output management."""
    
    def __init__(self, output_dir: str = "./outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def create_run_dir(self, name: str) -> Path:
        """Create timestamped run directory."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.output_dir / f"{name}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir
    
    def run(
        self,
        data_path: str,
        num_samples: Optional[int] = None,
        use_ircot: bool = True,
        seed: int = 42,
        config: Optional[IRCoTConfig] = None,
        name: str = "experiment"
    ) -> Dict:
        """
        Run experiment and save all outputs.
        
        Args:
            data_path: Path to data file
            num_samples: Number of samples (None for all)
            use_ircot: Use IRCoT (True) or baseline
            seed: Random seed
            config: Configuration
            name: Experiment name
            
        Returns:
            Evaluation results
        """
        # Setup
        run_dir = self.create_run_dir(name)
        logger.info(f"Output directory: {run_dir}")
        
        config = config or IRCoTConfig()
        self._save_json(run_dir / "config.json", config.to_dict())
        
        # Load data
        loader = HotpotQALoader()
        instances = loader.load(filepath=data_path)
        logger.info(f"Loaded {len(instances)} instances")
        
        # Log statistics
        stats = get_statistics(instances)
        logger.info(f"Dataset stats: {json.dumps(stats, indent=2)}")
        
        # Subsample
        if num_samples and num_samples < len(instances):
            instances = subsample(instances, num_samples, seed=seed)
            logger.info(f"Subsampled to {len(instances)} instances")
        
        # Prepare data
        questions = [format_for_prediction(inst) for inst in instances]
        
        # Run predictions
        method = "IRCoT" if use_ircot else "Baseline"
        logger.info(f"Running {method} predictions...")
        
        qa = IRCoTQA(config)
        predictions = qa.batch_answer(questions, use_ircot=use_ircot)
        
        # Log stats
        api_stats = qa.stats
        logger.info(f"API stats: {json.dumps(api_stats, indent=2)}")
        
        # Save predictions
        self._save_json(run_dir / "predictions.json", predictions)
        save_official_format(predictions, str(run_dir / "pred_official.json"))
        
        # Evaluate
        gold_data = [inst.to_dict() for inst in instances]
        results = detailed_evaluation(predictions, gold_data)
        
        # Add metadata
        results["metadata"] = {
            "experiment_name": name,
            "method": method,
            "num_samples": len(instances),
            "use_ircot": use_ircot,
            "config": config.to_dict(),
            "api_stats": api_stats
        }
        
        # Save results
        self._save_json(run_dir / "evaluation.json", results)
        
        # Save report
        report = format_report(results)
        print("\n" + report)
        (run_dir / "report.txt").write_text(report)
        
        # Error analysis
        errors = error_analysis(predictions, gold_data)
        self._save_json(run_dir / "error_analysis.json", errors)
        
        logger.info(f"All outputs saved to {run_dir}")
        return results
    
    def run_ablation(
        self,
        data_path: str,
        num_samples: int = 100,
        seed: int = 42,
        configs: Optional[List[str]] = None
    ) -> Dict:
        """
        Run ablation study.
        
        Args:
            data_path: Path to data file
            num_samples: Samples per config
            seed: Random seed
            configs: Config names to run (default: all)
            
        Returns:
            All results
        """
        ablation_dir = self.create_run_dir("ablation")
        configs = configs or list(ABLATION_CONFIGS.keys())
        
        all_results = {}
        
        for config_name in configs:
            logger.info(f"\n{'='*60}")
            logger.info(f"Running: {config_name}")
            logger.info(f"{'='*60}")
            
            config = get_config_for_ablation(config_name)
            use_ircot = config_name != "one_step"
            
            try:
                results = self.run(
                    data_path=data_path,
                    num_samples=num_samples,
                    use_ircot=use_ircot,
                    seed=seed,
                    config=config,
                    name=config_name
                )
                all_results[config_name] = results
            except Exception as e:
                logger.error(f"Error in {config_name}: {e}")
                all_results[config_name] = {"error": str(e)}
        
        # Save summary
        summary = {}
        for name, results in all_results.items():
            if "error" not in results:
                summary[name] = {
                    "exact_match": results["overall"]["exact_match"],
                    "f1": results["overall"]["f1"],
                }
            else:
                summary[name] = {"error": results["error"]}
        
        self._save_json(ablation_dir / "summary.json", summary)
        
        # Print comparison
        print("\n" + "=" * 60)
        print("ABLATION SUMMARY")
        print("=" * 60)
        for name, metrics in summary.items():
            if "error" not in metrics:
                print(f"{name:20s}: EM={metrics['exact_match']:.4f}, F1={metrics['f1']:.4f}")
            else:
                print(f"{name:20s}: ERROR - {metrics['error']}")
        
        return all_results
    
    @staticmethod
    def _save_json(path: Path, data: Dict) -> None:
        """Save JSON with numpy handling."""
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=lambda x: float(x) if hasattr(x, 'item') else str(x))


# =============================================================================
# CLI Commands
# =============================================================================

def find_data_path() -> Optional[str]:
    """Find data file automatically."""
    candidates = [
        "data/hotpotqa/hotpot_dev_distractor_v1.json",
        "data/hotpot_dev_distractor_v1.json",
        "./data/hotpotqa/hotpot_dev_distractor_v1.json",
    ]
    
    for path in candidates:
        if os.path.exists(path):
            return path
    
    return None


def cmd_run(args: argparse.Namespace) -> None:
    """Run experiment command."""
    data_path = args.data_path or find_data_path()
    
    if not data_path or not os.path.exists(data_path):
        logger.error("Data file not found. Run 'download' first or specify --data_path")
        sys.exit(1)
    
    # Build config
    config = IRCoTConfig(
        initial_retrieval_k=args.initial_k,
        step_retrieval_k=args.step_k,
        max_reasoning_steps=args.max_steps,
        max_total_paragraphs=args.max_paragraphs,
        num_few_shot_examples=args.num_few_shot,
    )
    
    runner = ExperimentRunner(args.output_dir)
    runner.run(
        data_path=data_path,
        num_samples=args.num_samples,
        use_ircot=not args.baseline,
        seed=args.seed,
        config=config,
        name="ircot" if not args.baseline else "baseline"
    )


def cmd_ablation(args: argparse.Namespace) -> None:
    """Run ablation command."""
    data_path = args.data_path or find_data_path()
    
    if not data_path or not os.path.exists(data_path):
        logger.error("Data file not found")
        sys.exit(1)
    
    runner = ExperimentRunner(args.output_dir)
    runner.run_ablation(
        data_path=data_path,
        num_samples=args.num_samples or 100,
        seed=args.seed,
        configs=args.configs
    )


def cmd_download(args: argparse.Namespace) -> None:
    """Download data command."""
    output_dir = "data/hotpotqa"
    os.makedirs(output_dir, exist_ok=True)
    
    path = download_hotpotqa(output_dir, args.split, args.setting)
    logger.info(f"Downloaded to: {path}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Evaluate predictions command."""
    with open(args.predictions) as f:
        predictions = json.load(f)
    
    loader = HotpotQALoader()
    instances = loader.load(filepath=args.gold)
    gold_data = [inst.to_dict() for inst in instances]
    
    results = detailed_evaluation(predictions, gold_data)
    print(format_report(results))
    
    errors = error_analysis(predictions, gold_data)
    print(f"\nErrors: {errors['total_errors']}, Rate: {errors['error_rate']:.2%}")


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="IRCoT for HotpotQA",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Run command
    run_parser = subparsers.add_parser("run", help="Run experiment")
    run_parser.add_argument("--data_path", help="Path to data file")
    run_parser.add_argument("--output_dir", default="./outputs", help="Output directory")
    run_parser.add_argument("--num_samples", type=int, help="Number of samples")
    run_parser.add_argument("--seed", type=int, default=42, help="Random seed")
    run_parser.add_argument("--baseline", action="store_true", help="Use baseline")
    run_parser.add_argument("--initial_k", type=int, default=2)
    run_parser.add_argument("--step_k", type=int, default=1)
    run_parser.add_argument("--max_steps", type=int, default=4)
    run_parser.add_argument("--max_paragraphs", type=int, default=5)
    run_parser.add_argument("--num_few_shot", type=int, default=3)
    
    # Ablation command
    abl_parser = subparsers.add_parser("ablation", help="Run ablation study")
    abl_parser.add_argument("--data_path", help="Path to data file")
    abl_parser.add_argument("--output_dir", default="./outputs")
    abl_parser.add_argument("--num_samples", type=int, default=100)
    abl_parser.add_argument("--seed", type=int, default=42)
    abl_parser.add_argument("--configs", nargs="+", help="Specific configs")
    
    # Download command
    dl_parser = subparsers.add_parser("download", help="Download data")
    dl_parser.add_argument("--split", default="dev", choices=["train", "dev", "test"])
    dl_parser.add_argument("--setting", default="distractor", choices=["distractor", "fullwiki"])
    
    # Evaluate command
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate predictions")
    eval_parser.add_argument("--predictions", required=True, help="Predictions file")
    eval_parser.add_argument("--gold", required=True, help="Gold data file")
    
    args = parser.parse_args()
    
    if args.command == "run":
        cmd_run(args)
    elif args.command == "ablation":
        cmd_ablation(args)
    elif args.command == "download":
        cmd_download(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
