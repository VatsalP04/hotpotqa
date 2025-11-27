"""
HotpotQA NLP Pipeline

A complete NLP pipeline for processing and analyzing the HotpotQA dataset,
including data loading, preprocessing, multi-hop reasoning analysis, and more.
"""

__version__ = "1.0.0"
__author__ = "HotpotQA Pipeline Team"

# Import main components for easy access
from .config.config_manager import ConfigManager, load_config
from .data import (
    load_hotpotqa,
    HotpotQADataset,
    HotpotQAContextDataset,
    validate_examples,
)
from .preprocessing import (
    HotpotQAPreprocessor,
    get_tokenizer,
    flatten_context,
    create_multihop_features,
)
from .utils import (
    clean_text,
    normalize_text,
    get_dataset_statistics,
)

__all__ = [
    # Config
    'ConfigManager',
    'load_config',
    # Data
    'load_hotpotqa',
    'HotpotQADataset',
    'HotpotQAContextDataset',
    'validate_examples',
    # Preprocessing
    'HotpotQAPreprocessor',
    'get_tokenizer',
    'flatten_context',
    'create_multihop_features',
    # Utils
    'clean_text',
    'normalize_text',
    'get_dataset_statistics',
]
