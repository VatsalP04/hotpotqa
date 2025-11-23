"""
Data loading and processing module for HotpotQA.

This module provides utilities for loading, validating, and creating
PyTorch datasets from HotpotQA data files.
"""

from .loader import (
    HotpotQALoader,
    load_hotpotqa,
    load_splits,
    get_example_by_id,
    filter_examples,
)

from .validator import (
    ValidationError,
    validate_example,
    validate_examples,
    validate_and_report,
    check_supporting_facts_coverage,
    validate_supporting_facts_coverage,
)

from .dataset import (
    HotpotQADataset,
    HotpotQAContextDataset,
    HotpotQASupportingFactsDataset,
    collate_fn,
)

__all__ = [
    # Loader
    'HotpotQALoader',
    'load_hotpotqa',
    'load_splits',
    'get_example_by_id',
    'filter_examples',
    # Validator
    'ValidationError',
    'validate_example',
    'validate_examples',
    'validate_and_report',
    'check_supporting_facts_coverage',
    'validate_supporting_facts_coverage',
    # Dataset
    'HotpotQADataset',
    'HotpotQAContextDataset',
    'HotpotQASupportingFactsDataset',
    'collate_fn',
]
