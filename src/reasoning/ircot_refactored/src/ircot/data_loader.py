"""
Data loader for HotpotQA dataset.

Handles loading, parsing, and preprocessing of HotpotQA data.
Supports both JSON and JSONL formats.
"""

from __future__ import annotations

import json
import logging
import os
import random
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set

from .types import HotpotQAInstance

logger = logging.getLogger(__name__)


# =============================================================================
# Data Loader
# =============================================================================

class HotpotQALoader:
    """
    Loader for HotpotQA dataset.
    
    Handles file discovery, loading, and conversion to HotpotQAInstance objects.
    """
    
    # Common file patterns
    FILE_PATTERNS = [
        "hotpot_{split}_{setting}_v1.json",
        "hotpot_{split}_v1.1.json",
        "{split}.json",
        "{split}.jsonl",
    ]
    
    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize loader.
        
        Args:
            data_dir: Directory containing data files (auto-detected if None)
        """
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
        filepath: Optional[str] = None
    ) -> List[HotpotQAInstance]:
        """
        Load HotpotQA dataset split.
        
        Args:
            split: Dataset split (train, dev, test)
            setting: Setting (distractor, fullwiki)
            filepath: Optional explicit filepath
            
        Returns:
            List of HotpotQAInstance objects
            
        Raises:
            FileNotFoundError: If data file not found
        """
        path = filepath or self._find_file(split, setting)
        
        if path is None:
            raise FileNotFoundError(
                f"Could not find {split} data. "
                f"Run download() first or specify filepath."
            )
        
        # Load based on extension
        if path.endswith(".jsonl"):
            raw_data = self._load_jsonl(path)
        else:
            raw_data = self._load_json(path)
        
        instances = [HotpotQAInstance.from_dict(d) for d in raw_data]
        logger.info(f"Loaded {len(instances)} instances from {path}")
        
        return instances
    
    def _find_file(self, split: str, setting: str) -> Optional[str]:
        """Find data file matching split and setting."""
        search_dirs = [self.data_dir, os.path.dirname(self.data_dir), "data", "."]
        
        for directory in search_dirs:
            if not directory:
                continue
            
            for pattern in self.FILE_PATTERNS:
                filename = pattern.format(split=split, setting=setting)
                filepath = os.path.join(directory, filename)
                
                if os.path.exists(filepath):
                    return filepath
        
        return None
    
    @staticmethod
    def _load_json(filepath: str) -> List[Dict]:
        """Load JSON file."""
        logger.info(f"Loading JSON from {filepath}")
        
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Handle both list format and dict with 'data' key
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data
    
    @staticmethod
    def _load_jsonl(filepath: str) -> List[Dict]:
        """Load JSONL file."""
        logger.info(f"Loading JSONL from {filepath}")
        
        data = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))
        return data
    
    def load_dev(self, setting: str = "distractor") -> List[HotpotQAInstance]:
        """Load development set."""
        return self.load("dev", setting)
    
    def load_train(self) -> List[HotpotQAInstance]:
        """Load training set."""
        return self.load("train", "distractor")


# =============================================================================
# Download Functions
# =============================================================================

DOWNLOAD_URLS = {
    ("train", "distractor"): "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_train_v1.1.json",
    ("dev", "distractor"): "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
    ("dev", "fullwiki"): "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_fullwiki_v1.json",
    ("test", "fullwiki"): "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_test_fullwiki_v1.json",
}


def download_hotpotqa(
    output_dir: str = "./data",
    split: str = "dev",
    setting: str = "distractor"
) -> str:
    """
    Download HotpotQA dataset.
    
    Args:
        output_dir: Directory to save file
        split: Dataset split
        setting: Dataset setting
        
    Returns:
        Path to downloaded file
        
    Raises:
        ValueError: If split/setting combination is invalid
    """
    key = (split, setting)
    if key not in DOWNLOAD_URLS:
        raise ValueError(f"Unknown split/setting: {split}/{setting}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    url = DOWNLOAD_URLS[key]
    filename = url.split("/")[-1]
    output_path = os.path.join(output_dir, filename)
    
    if os.path.exists(output_path):
        logger.info(f"File already exists: {output_path}")
        return output_path
    
    logger.info(f"Downloading from {url}")
    urllib.request.urlretrieve(url, output_path)
    logger.info(f"Downloaded to {output_path}")
    
    return output_path


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
    Subsample dataset with optional stratification.
    
    Args:
        instances: Full dataset
        n: Number of samples
        seed: Random seed
        stratify_by_type: Stratify by question type
        
    Returns:
        Subsampled list
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
    """
    Get dataset statistics.
    
    Args:
        instances: List of instances
        
    Returns:
        Statistics dictionary
    """
    if not instances:
        return {"total": 0}
    
    by_type: Dict[str, int] = {}
    by_level: Dict[str, int] = {}
    total_context = 0
    total_sf = 0
    
    for inst in instances:
        by_type[inst.question_type or "unknown"] = by_type.get(inst.question_type or "unknown", 0) + 1
        by_level[inst.level or "unknown"] = by_level.get(inst.level or "unknown", 0) + 1
        total_context += len(inst.context)
        total_sf += len(inst.supporting_facts)
    
    n = len(instances)
    return {
        "total": n,
        "by_type": by_type,
        "by_level": by_level,
        "avg_context_paragraphs": total_context / n,
        "avg_supporting_facts": total_sf / n,
    }


def format_for_prediction(instance: HotpotQAInstance) -> Dict:
    """
    Format instance for prediction pipeline.
    
    Args:
        instance: HotpotQA instance
        
    Returns:
        Dictionary ready for IRCoT
    """
    return {
        "_id": instance.id,
        "question": instance.question,
        "answer": instance.answer,
        "context": instance.context,
        "type": instance.question_type,
        "level": instance.level,
        "supporting_facts": instance.supporting_facts,
    }
