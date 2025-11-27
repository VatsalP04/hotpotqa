"""
PyTorch Dataset classes for HotpotQA.

This module provides Dataset implementations that can be used with
PyTorch DataLoader or HuggingFace Trainer for efficient batching and iteration.
"""

import torch
from torch.utils.data import Dataset
from typing import List, Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class HotpotQADataset(Dataset):
    """
    PyTorch Dataset for HotpotQA.

    This dataset wraps the loaded HotpotQA examples and can optionally apply
    transformations (e.g., tokenization, preprocessing) on-the-fly.
    """

    def __init__(
        self,
        examples: List[Dict[str, Any]],
        transform: Optional[Callable] = None,
        return_tensors: bool = False
    ):
        """
        Initialize the dataset.

        Args:
            examples: List of HotpotQA examples
            transform: Optional transform function to apply to each example
            return_tensors: Whether to convert outputs to tensors
        """
        self.examples = examples
        self.transform = transform
        self.return_tensors = return_tensors

    def __len__(self) -> int:
        """Return the number of examples in the dataset."""
        return len(self.examples)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        """
        Get an example by index.

        Args:
            idx: Index of the example

        Returns:
            Example dictionary, optionally transformed
        """
        if isinstance(idx, slice):
            # Handle slicing
            return [self[i] for i in range(*idx.indices(len(self)))]

        example = self.examples[idx].copy()

        # Apply transform if provided
        if self.transform is not None:
            example = self.transform(example)

        # Convert to tensors if requested
        if self.return_tensors:
            example = self._to_tensors(example)

        return example

    def _to_tensors(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert numeric values in the example to PyTorch tensors.

        Args:
            example: Example dictionary

        Returns:
            Example with tensors
        """
        result = {}
        for key, value in example.items():
            if isinstance(value, (list, tuple)):
                # Try to convert lists to tensors
                try:
                    result[key] = torch.tensor(value)
                except (ValueError, TypeError):
                    # If conversion fails, keep original
                    result[key] = value
            elif isinstance(value, (int, float)):
                result[key] = torch.tensor(value)
            else:
                result[key] = value
        return result

    def get_subset(self, indices: List[int]) -> 'HotpotQADataset':
        """
        Create a subset of the dataset.

        Args:
            indices: List of indices to include

        Returns:
            New HotpotQADataset with selected examples
        """
        subset_examples = [self.examples[i] for i in indices]
        return HotpotQADataset(
            subset_examples,
            transform=self.transform,
            return_tensors=self.return_tensors
        )

    def filter(self, predicate: Callable[[Dict[str, Any]], bool]) -> 'HotpotQADataset':
        """
        Filter examples based on a predicate function.

        Args:
            predicate: Function that takes an example and returns True to keep it

        Returns:
            New HotpotQADataset with filtered examples
        """
        filtered_examples = [ex for ex in self.examples if predicate(ex)]
        logger.info(f"Filtered from {len(self.examples)} to {len(filtered_examples)} examples")
        return HotpotQADataset(
            filtered_examples,
            transform=self.transform,
            return_tensors=self.return_tensors
        )


class HotpotQAContextDataset(Dataset):
    """
    Dataset that flattens context for each example.

    This dataset returns the question with flattened context,
    useful for models that take a single text input.
    """

    def __init__(
        self,
        examples: List[Dict[str, Any]],
        max_context_paragraphs: Optional[int] = None,
        include_titles: bool = True,
        separator: str = "\n\n"
    ):
        """
        Initialize the context dataset.

        Args:
            examples: List of HotpotQA examples
            max_context_paragraphs: Maximum number of context paragraphs to include
            include_titles: Whether to include paragraph titles
            separator: Separator between context paragraphs
        """
        self.examples = examples
        self.max_context_paragraphs = max_context_paragraphs
        self.include_titles = include_titles
        self.separator = separator

    def __len__(self) -> int:
        """Return the number of examples in the dataset."""
        return len(self.examples)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        """
        Get an example with flattened context.

        Args:
            idx: Index of the example

        Returns:
            Dictionary with 'question', 'context', 'answer', and metadata
        """
        example = self.examples[idx]

        # Flatten context
        context_parts = []
        context_paragraphs = example.get('context', [])

        # Limit paragraphs if specified
        if self.max_context_paragraphs is not None:
            context_paragraphs = context_paragraphs[:self.max_context_paragraphs]

        for title, sentences in context_paragraphs:
            if self.include_titles:
                context_parts.append(f"Title: {title}")

            # Join sentences
            paragraph_text = " ".join(sentences)
            context_parts.append(paragraph_text)

        context_text = self.separator.join(context_parts)

        return {
            '_id': example.get('_id'),
            'question': example.get('question'),
            'context': context_text,
            'answer': example.get('answer'),
            'type': example.get('type'),
            'level': example.get('level'),
            'supporting_facts': example.get('supporting_facts', []),
            'num_context_paragraphs': len(context_paragraphs)
        }


class HotpotQASupportingFactsDataset(Dataset):
    """
    Dataset that only includes supporting fact paragraphs in context.

    This dataset creates a focused context containing only the paragraphs
    mentioned in supporting_facts, useful for training models on relevant context.
    """

    def __init__(
        self,
        examples: List[Dict[str, Any]],
        include_titles: bool = True,
        separator: str = "\n\n"
    ):
        """
        Initialize the supporting facts dataset.

        Args:
            examples: List of HotpotQA examples
            include_titles: Whether to include paragraph titles
            separator: Separator between context paragraphs
        """
        self.examples = examples
        self.include_titles = include_titles
        self.separator = separator

    def __len__(self) -> int:
        """Return the number of examples in the dataset."""
        return len(self.examples)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        """
        Get an example with only supporting fact context.

        Args:
            idx: Index of the example

        Returns:
            Dictionary with focused context
        """
        example = self.examples[idx]

        # Get supporting fact titles
        supporting_titles = {title for title, _ in example.get('supporting_facts', [])}

        # Filter context to only supporting paragraphs
        context_parts = []
        for title, sentences in example.get('context', []):
            if title in supporting_titles:
                if self.include_titles:
                    context_parts.append(f"Title: {title}")
                paragraph_text = " ".join(sentences)
                context_parts.append(paragraph_text)

        context_text = self.separator.join(context_parts)

        return {
            '_id': example.get('_id'),
            'question': example.get('question'),
            'context': context_text,
            'answer': example.get('answer'),
            'type': example.get('type'),
            'level': example.get('level'),
            'supporting_facts': example.get('supporting_facts', []),
            'num_supporting_paragraphs': len(supporting_titles)
        }


def collate_fn(batch: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Custom collate function for batching HotpotQA examples.

    Args:
        batch: List of examples from the dataset

    Returns:
        Batched dictionary with lists of values
    """
    if len(batch) == 0:
        return {}

    # Get all keys from the first example
    keys = batch[0].keys()

    # Collate each key
    collated = {}
    for key in keys:
        values = [example[key] for example in batch]

        # Try to stack tensors if all values are tensors
        if all(isinstance(v, torch.Tensor) for v in values):
            try:
                collated[key] = torch.stack(values)
            except (RuntimeError, TypeError):
                # If stacking fails (e.g., different shapes), keep as list
                collated[key] = values
        else:
            collated[key] = values

    return collated


if __name__ == "__main__":
    # Demo usage
    from .loader import load_hotpotqa
    from torch.utils.data import DataLoader
    from pathlib import Path
    import sys

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Load data
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data" / "raw"

    try:
        print("Loading data...")
        examples = load_hotpotqa(data_dir, split='train', max_examples=10, validate=False)

        # Test basic dataset
        print("\n--- Testing HotpotQADataset ---")
        dataset = HotpotQADataset(examples)
        print(f"Dataset length: {len(dataset)}")
        print(f"First example ID: {dataset[0]['_id']}")

        # Test context dataset
        print("\n--- Testing HotpotQAContextDataset ---")
        context_dataset = HotpotQAContextDataset(examples, max_context_paragraphs=3)
        example = context_dataset[0]
        print(f"Question: {example['question']}")
        print(f"Context length: {len(example['context'])} characters")
        print(f"Context preview: {example['context'][:200]}...")

        # Test supporting facts dataset
        print("\n--- Testing HotpotQASupportingFactsDataset ---")
        sf_dataset = HotpotQASupportingFactsDataset(examples)
        example = sf_dataset[0]
        print(f"Question: {example['question']}")
        print(f"Supporting paragraphs: {example['num_supporting_paragraphs']}")
        print(f"Context preview: {example['context'][:200]}...")

        # Test DataLoader
        print("\n--- Testing DataLoader ---")
        dataloader = DataLoader(dataset, batch_size=2, collate_fn=collate_fn)
        batch = next(iter(dataloader))
        print(f"Batch keys: {batch.keys()}")
        print(f"Batch size: {len(batch['_id'])}")

        print("\n✅ All dataset tests passed!")

    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
