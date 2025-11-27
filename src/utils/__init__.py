"""
Utility functions for the HotpotQA NLP pipeline.

This module provides various utility functions for text processing,
data analysis, and helper operations.
"""

from .cleaning import (
    remove_extra_whitespace,
    normalize_unicode,
    remove_html_tags,
    remove_urls,
    remove_special_characters,
    fix_spacing_around_punctuation,
    remove_repeated_punctuation,
    clean_text,
    clean_paragraph,
)

from .normalization import (
    normalize_case,
    normalize_punctuation,
    normalize_numbers,
    normalize_whitespace,
    remove_articles,
    remove_punctuation,
    normalize_answer,
    normalize_text,
)

from .analysis import (
    count_examples,
    analyze_questions,
    analyze_answers,
    analyze_context,
    analyze_reasoning_types,
    analyze_supporting_facts,
    get_dataset_statistics,
    print_statistics,
    save_statistics,
    compare_statistics,
)

__all__ = [
    # Cleaning
    'remove_extra_whitespace',
    'normalize_unicode',
    'remove_html_tags',
    'remove_urls',
    'remove_special_characters',
    'fix_spacing_around_punctuation',
    'remove_repeated_punctuation',
    'clean_text',
    'clean_paragraph',
    # Normalization
    'normalize_case',
    'normalize_punctuation',
    'normalize_numbers',
    'normalize_whitespace',
    'remove_articles',
    'remove_punctuation',
    'normalize_answer',
    'normalize_text',
    # Analysis
    'count_examples',
    'analyze_questions',
    'analyze_answers',
    'analyze_context',
    'analyze_reasoning_types',
    'analyze_supporting_facts',
    'get_dataset_statistics',
    'print_statistics',
    'save_statistics',
    'compare_statistics',
]
