"""
Data loading utilities for HotpotQA dataset.

This module provides functions to load and parse HotpotQA JSON files,
with support for filtering, sampling, and validation.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import random

logger = logging.getLogger(__name__)


class HotpotQALoader:
    """
    Loader for HotpotQA dataset files.

    Handles loading JSON files, validation, and optional filtering/sampling.
    """

    def __init__(
        self,
        data_dir: Union[str, Path],
        split: str = "train",
        max_examples: Optional[int] = None,
        shuffle: bool = False,
        seed: int = 42
    ):
        """
        Initialize the HotpotQA loader.

        Args:
            data_dir: Directory containing HotpotQA JSON files
            split: Dataset split to load ('train' or 'dev')
            max_examples: Maximum number of examples to load (None for all)
            shuffle: Whether to shuffle the examples before truncating
            seed: Random seed for shuffling
        """
        self.data_dir = Path(data_dir)
        self.split = split
        self.max_examples = max_examples
        self.shuffle = shuffle
        self.seed = seed

        # Map split names to file names
        self.file_mapping = {
            "train": "hotpot_train_v1.1.json",
            "dev": "hotpot_dev_distractor_v1.json",
            "development": "hotpot_dev_distractor_v1.json",
        }

        if split not in self.file_mapping:
            raise ValueError(
                f"Unknown split '{split}'. Available splits: {list(self.file_mapping.keys())}"
            )

        self.file_path = self.data_dir / self.file_mapping[split]
        self.data: List[Dict[str, Any]] = []

    def load(self) -> List[Dict[str, Any]]:
        """
        Load the dataset from disk.

        Returns:
            List of dataset examples as dictionaries

        Raises:
            FileNotFoundError: If the dataset file doesn't exist
            json.JSONDecodeError: If the file is not valid JSON
        """
        logger.info(f"Loading HotpotQA {self.split} split from {self.file_path}")

        if not self.file_path.exists():
            raise FileNotFoundError(
                f"Dataset file not found: {self.file_path}\n"
                f"Please ensure the HotpotQA dataset is downloaded to {self.data_dir}"
            )

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Check if file contains an error message (e.g., "404: Not Found")
                # Only check the first 20 characters to avoid false positives from data content
                content_start = content.strip()[:20]
                if content_start.startswith("404") or content_start == "404: Not Found":
                    raise FileNotFoundError(
                        f"Dataset file appears to be an error response, not valid data: {self.file_path}\n"
                        f"File contents: {content[:100]}\n"
                        f"Please download the HotpotQA dataset using the download script in data/hotpotqa/download.sh"
                    )
                self.data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON file: {e}")
            # Read first few lines to help debug
            with open(self.file_path, 'r', encoding='utf-8') as f:
                preview = f.read(200)
            raise json.JSONDecodeError(
                f"Invalid JSON format in {self.file_path}. "
                f"File preview: {preview}...\n"
                f"Please ensure the dataset file is properly downloaded.",
                e.doc, e.pos
            )

        logger.info(f"Loaded {len(self.data)} examples from {self.split} split")

        # Shuffle if requested
        if self.shuffle:
            random.seed(self.seed)
            random.shuffle(self.data)
            logger.info(f"Shuffled examples with seed {self.seed}")

        # Truncate if max_examples is specified
        if self.max_examples is not None and self.max_examples < len(self.data):
            self.data = self.data[:self.max_examples]
            logger.info(f"Truncated to {self.max_examples} examples")

        return self.data

    def __len__(self) -> int:
        """Return the number of loaded examples."""
        return len(self.data)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        """Get a specific example by index."""
        return self.data[idx]

    def __iter__(self):
        """Iterate over all examples."""
        return iter(self.data)


def load_hotpotqa(
    data_dir: Union[str, Path],
    split: str = "train",
    max_examples: Optional[int] = None,
    shuffle: bool = False,
    seed: int = 42,
    validate: bool = True
) -> List[Dict[str, Any]]:
    """
    Convenience function to load HotpotQA dataset.

    Args:
        data_dir: Directory containing HotpotQA JSON files
        split: Dataset split to load ('train' or 'dev')
        max_examples: Maximum number of examples to load (None for all)
        shuffle: Whether to shuffle the examples
        seed: Random seed for shuffling
        validate: Whether to validate examples after loading

    Returns:
        List of dataset examples

    Example:
        >>> data = load_hotpotqa('data/raw', split='train', max_examples=100)
        >>> print(f"Loaded {len(data)} examples")
        >>> print(f"First question: {data[0]['question']}")
    """
    loader = HotpotQALoader(
        data_dir=data_dir,
        split=split,
        max_examples=max_examples,
        shuffle=shuffle,
        seed=seed
    )

    data = loader.load()

    if validate:
        from .validator import validate_examples
        is_valid, errors = validate_examples(data, split=split)
        if not is_valid:
            logger.warning(f"Validation found {len(errors)} issues")
            for error in errors[:5]:  # Show first 5 errors
                logger.warning(f"  - {error}")
            if len(errors) > 5:
                logger.warning(f"  ... and {len(errors) - 5} more errors")

    return data


def load_splits(
    data_dir: Union[str, Path],
    splits: List[str] = ["train", "dev"],
    **kwargs
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load multiple dataset splits at once.

    Args:
        data_dir: Directory containing HotpotQA JSON files
        splits: List of splits to load
        **kwargs: Additional arguments passed to load_hotpotqa

    Returns:
        Dictionary mapping split names to data lists

    Example:
        >>> data = load_splits('data/raw', splits=['train', 'dev'], max_examples=100)
        >>> print(f"Train: {len(data['train'])} examples")
        >>> print(f"Dev: {len(data['dev'])} examples")
    """
    result = {}
    for split in splits:
        logger.info(f"Loading {split} split...")
        result[split] = load_hotpotqa(data_dir, split=split, **kwargs)

    return result


def get_example_by_id(
    data: List[Dict[str, Any]],
    example_id: str
) -> Optional[Dict[str, Any]]:
    """
    Find an example by its ID.

    Args:
        data: List of examples
        example_id: ID of the example to find

    Returns:
        The example dict if found, None otherwise
    """
    for example in data:
        if example.get('_id') == example_id:
            return example
    return None


def filter_examples(
    data: List[Dict[str, Any]],
    answer_type: Optional[str] = None,
    level: Optional[str] = None,
    min_context_length: Optional[int] = None,
    max_context_length: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Filter examples based on various criteria.

    Args:
        data: List of examples
        answer_type: Filter by answer type ('yes', 'no', or span answer)
        level: Filter by difficulty level ('easy', 'medium', 'hard')
        min_context_length: Minimum number of context paragraphs
        max_context_length: Maximum number of context paragraphs

    Returns:
        Filtered list of examples
    """
    filtered = data

    if answer_type is not None:
        if answer_type.lower() in ['yes', 'no']:
            filtered = [ex for ex in filtered if ex.get('answer', '').lower() == answer_type.lower()]
        else:
            filtered = [ex for ex in filtered if ex.get('answer', '').lower() not in ['yes', 'no']]

    if level is not None:
        filtered = [ex for ex in filtered if ex.get('level', '') == level]

    if min_context_length is not None:
        filtered = [ex for ex in filtered if len(ex.get('context', [])) >= min_context_length]

    if max_context_length is not None:
        filtered = [ex for ex in filtered if len(ex.get('context', [])) <= max_context_length]

    logger.info(f"Filtered from {len(data)} to {len(filtered)} examples")
    return filtered


if __name__ == "__main__":
    # Demo usage
    import sys
    from pathlib import Path

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Try to load data
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data" / "raw"

    try:
        print(f"Loading data from {data_dir}...")
        train_data = load_hotpotqa(data_dir, split='train', max_examples=10)

        print(f"\n✅ Successfully loaded {len(train_data)} training examples")
        print(f"\nFirst example:")
        example = train_data[0]
        print(f"  ID: {example['_id']}")
        print(f"  Question: {example['question']}")
        print(f"  Answer: {example['answer']}")
        print(f"  Type: {example.get('type', 'N/A')}")
        print(f"  Level: {example.get('level', 'N/A')}")
        print(f"  Context paragraphs: {len(example.get('context', []))}")
        print(f"  Supporting facts: {len(example.get('supporting_facts', []))}")

    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("Please download the HotpotQA dataset first.")
        sys.exit(1)
