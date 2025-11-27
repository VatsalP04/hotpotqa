"""
Preprocessing module for HotpotQA dataset.

This module provides comprehensive preprocessing capabilities including:
- Tokenization (HuggingFace, spaCy, NLTK)
- Context processing (flattening, chunking, truncation)
- Multi-hop reasoning feature extraction
- Complete end-to-end preprocessing pipeline
"""

from .tokenizer import (
    BaseTokenizer,
    HuggingFaceTokenizer,
    SpacyTokenizer,
    NLTKTokenizer,
    get_tokenizer,
)

from .context import (
    flatten_context,
    extract_supporting_context,
    chunk_context,
    get_paragraph_by_title,
    filter_context_by_titles,
    count_tokens_approximate,
    truncate_context_to_length,
    format_context_for_qa,
)

from .multihop import (
    extract_supporting_facts,
    group_supporting_facts_by_paragraph,
    identify_reasoning_type,
    extract_reasoning_chain,
    count_reasoning_hops,
    is_multihop,
    get_bridge_entities,
    create_multihop_features,
    filter_multihop_examples,
    analyze_multihop_distribution,
)

from .pipeline import (
    HotpotQAPreprocessor,
)

__all__ = [
    # Tokenizer
    'BaseTokenizer',
    'HuggingFaceTokenizer',
    'SpacyTokenizer',
    'NLTKTokenizer',
    'get_tokenizer',
    # Context
    'flatten_context',
    'extract_supporting_context',
    'chunk_context',
    'get_paragraph_by_title',
    'filter_context_by_titles',
    'count_tokens_approximate',
    'truncate_context_to_length',
    'format_context_for_qa',
    # Multi-hop
    'extract_supporting_facts',
    'group_supporting_facts_by_paragraph',
    'identify_reasoning_type',
    'extract_reasoning_chain',
    'count_reasoning_hops',
    'is_multihop',
    'get_bridge_entities',
    'create_multihop_features',
    'filter_multihop_examples',
    'analyze_multihop_distribution',
    # Pipeline
    'HotpotQAPreprocessor',
]
