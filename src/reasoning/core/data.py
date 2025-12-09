"""
Data loading utilities for HotpotQA.

Handles loading, parsing, and preprocessing of HotpotQA data.
"""

from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Dict, List, Optional

from .types import HotpotQAInstance

logger = logging.getLogger(__name__)


# =============================================================================
# Simple JSON Loading
# =============================================================================

def load_hotpotqa_json(
    filepath: str,
    max_examples: Optional[int] = None,
    shuffle: bool = False,
    seed: int = 42
) -> List[Dict]:
    """
    Load HotpotQA dataset from JSON file.
    
    Args:
        filepath: Path to JSON file
        max_examples: Optional limit on examples
        shuffle: Whether to shuffle before limiting
        seed: Random seed for shuffling
    
    Returns:
        List of example dictionaries
    """
    logger.info(f"Loading data from {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle both list format and dict with 'data' key
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    
    if shuffle:
        random.seed(seed)
        random.shuffle(data)
    
    if max_examples:
        data = data[:max_examples]
    
    logger.info(f"Loaded {len(data)} examples")
    return data


# =============================================================================
# HotpotQA Loader Class
# =============================================================================

class HotpotQALoader:
    """Loader for HotpotQA dataset with automatic file discovery."""
    
    FILE_PATTERNS = [
        "hotpot_{split}_{setting}_v1.json",
        "hotpot_{split}_v1.1.json",
        "{split}.json",
    ]
    
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or self._find_data_dir()
    
    @staticmethod
    def _find_data_dir() -> str:
        """Find data directory automatically."""
        candidates = [
            Path("data/hotpotqa"),
            Path("data"),
            Path(__file__).parent.parent.parent.parent / "data" / "hotpotqa",
        ]
        
        for path in candidates:
            if path.exists():
                return str(path)
        
        return "data/hotpotqa"
    
    def load(
        self,
        split: str = "dev",
        setting: str = "distractor",
        filepath: Optional[str] = None,
        max_examples: Optional[int] = None
    ) -> List[HotpotQAInstance]:
        """
        Load HotpotQA dataset split.
        
        Args:
            split: Dataset split (train, dev, test)
            setting: Setting (distractor, fullwiki)
            filepath: Optional explicit filepath
            max_examples: Optional limit on examples
        
        Returns:
            List of HotpotQAInstance objects
        """
        path = filepath or self._find_file(split, setting)
        
        if path is None:
            raise FileNotFoundError(
                f"Could not find {split} data. Specify filepath or check data directory."
            )
        
        raw_data = load_hotpotqa_json(path, max_examples)
        instances = [HotpotQAInstance.from_dict(d) for d in raw_data]
        
        logger.info(f"Loaded {len(instances)} instances from {path}")
        return instances
    
    def _find_file(self, split: str, setting: str) -> Optional[str]:
        """Find data file matching split and setting."""
        search_dirs = [self.data_dir, "data", "."]
        
        for directory in search_dirs:
            if not directory:
                continue
            
            for pattern in self.FILE_PATTERNS:
                filename = pattern.format(split=split, setting=setting)
                filepath = os.path.join(directory, filename)
                
                if os.path.exists(filepath):
                    return filepath
        
        return None
    
    def load_dev(self, setting: str = "distractor", max_examples: Optional[int] = None) -> List[HotpotQAInstance]:
        """Load development set."""
        return self.load("dev", setting, max_examples=max_examples)
    
    def load_train(self, max_examples: Optional[int] = None) -> List[HotpotQAInstance]:
        """Load training set."""
        return self.load("train", "distractor", max_examples=max_examples)


# =============================================================================
# Dataset Utilities
# =============================================================================

def subsample(
    instances: List[HotpotQAInstance],
    n: int,
    seed: int = 42,
    stratify_by_type: bool = True
) -> List[HotpotQAInstance]:
    """
    Subsample dataset with optional stratification by question type.
    """
    if n >= len(instances):
        return instances
    
    random.seed(seed)
    
    if not stratify_by_type:
        return random.sample(instances, n)
    
    # Group by type
    by_type: Dict[str, List[HotpotQAInstance]] = {}
    for inst in instances:
        key = inst.question_type or "unknown"
        by_type.setdefault(key, []).append(inst)
    
    # Sample proportionally
    sampled = []
    for group in by_type.values():
        proportion = len(group) / len(instances)
        n_sample = max(1, int(n * proportion))
        n_sample = min(n_sample, len(group))
        sampled.extend(random.sample(group, n_sample))
    
    # Adjust to exact n
    if len(sampled) > n:
        sampled = random.sample(sampled, n)
    elif len(sampled) < n:
        remaining = [inst for inst in instances if inst not in sampled]
        additional = min(n - len(sampled), len(remaining))
        sampled.extend(random.sample(remaining, additional))
    
    random.shuffle(sampled)
    return sampled


def get_statistics(instances: List[HotpotQAInstance]) -> Dict:
    """Get dataset statistics."""
    if not instances:
        return {"total": 0}
    
    by_type: Dict[str, int] = {}
    by_level: Dict[str, int] = {}
    
    for inst in instances:
        by_type[inst.question_type or "unknown"] = by_type.get(inst.question_type or "unknown", 0) + 1
        by_level[inst.level or "unknown"] = by_level.get(inst.level or "unknown", 0) + 1
    
    return {
        "total": len(instances),
        "by_type": by_type,
        "by_level": by_level,
    }

