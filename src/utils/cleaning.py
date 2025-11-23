"""
Text cleaning utilities for HotpotQA.

This module provides functions for cleaning and sanitizing text data,
including removing unwanted characters, fixing encoding issues, etc.
"""

import re
import html
import unicodedata
from typing import Optional


def remove_extra_whitespace(text: str) -> str:
    """
    Remove extra whitespace from text.

    Args:
        text: Input text

    Returns:
        Text with normalized whitespace

    Example:
        >>> remove_extra_whitespace("Hello    world  \\n\\n  test")
        'Hello world test'
    """
    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)
    # Replace multiple newlines with single newline
    text = re.sub(r'\n+', '\n', text)
    # Replace tabs with spaces
    text = text.replace('\t', ' ')
    # Strip leading/trailing whitespace
    text = text.strip()
    return text


def normalize_unicode(text: str, form: str = 'NFKC') -> str:
    """
    Normalize Unicode characters.

    Args:
        text: Input text
        form: Normalization form ('NFC', 'NFKC', 'NFD', 'NFKD')

    Returns:
        Normalized text

    Example:
        >>> normalize_unicode("café")  # Different representations of é
        'café'
    """
    return unicodedata.normalize(form, text)


def remove_html_tags(text: str) -> str:
    """
    Remove HTML tags and unescape HTML entities.

    Args:
        text: Input text that may contain HTML

    Returns:
        Text with HTML removed

    Example:
        >>> remove_html_tags("<p>Hello &amp; world</p>")
        'Hello & world'
    """
    # Unescape HTML entities first
    text = html.unescape(text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    return text


def remove_urls(text: str, replacement: str = '') -> str:
    """
    Remove URLs from text.

    Args:
        text: Input text
        replacement: String to replace URLs with

    Returns:
        Text with URLs removed

    Example:
        >>> remove_urls("Check out https://example.com for more info")
        'Check out  for more info'
    """
    # Pattern to match URLs
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    text = re.sub(url_pattern, replacement, text)
    return text


def remove_special_characters(
    text: str,
    keep_chars: Optional[str] = None,
    replacement: str = ' '
) -> str:
    """
    Remove special characters, keeping only alphanumeric and specified characters.

    Args:
        text: Input text
        keep_chars: Additional characters to keep (e.g., '.,!?')
        replacement: String to replace removed characters with

    Returns:
        Text with special characters removed

    Example:
        >>> remove_special_characters("Hello@world!", keep_chars='!')
        'Hello world!'
    """
    if keep_chars is None:
        keep_chars = ''

    # Create pattern to match characters to keep
    pattern = f'[^a-zA-Z0-9\\s{re.escape(keep_chars)}]'
    text = re.sub(pattern, replacement, text)

    return text


def fix_spacing_around_punctuation(text: str) -> str:
    """
    Fix spacing around punctuation marks.

    Args:
        text: Input text

    Returns:
        Text with corrected punctuation spacing

    Example:
        >>> fix_spacing_around_punctuation("Hello , world !")
        'Hello, world!'
    """
    # Remove space before punctuation
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    # Add space after punctuation if missing
    text = re.sub(r'([.,!?;:])([A-Za-z])', r'\1 \2', text)
    return text


def remove_repeated_punctuation(text: str) -> str:
    """
    Remove repeated punctuation marks.

    Args:
        text: Input text

    Returns:
        Text with single punctuation marks

    Example:
        >>> remove_repeated_punctuation("What???? Really!!!")
        'What? Really!'
    """
    # Replace multiple occurrences of the same punctuation
    text = re.sub(r'([.,!?;:])+', r'\1', text)
    return text


def clean_text(
    text: str,
    lowercase: bool = False,
    remove_extra_whitespace: bool = True,
    normalize_unicode: bool = True,
    remove_html: bool = False,
    remove_urls: bool = False,
    remove_special_chars: bool = False,
    fix_punctuation_spacing: bool = False,
    remove_repeated_punct: bool = False,
    **kwargs
) -> str:
    """
    Apply multiple cleaning operations to text.

    Args:
        text: Input text
        lowercase: Convert to lowercase
        remove_extra_whitespace: Remove extra whitespace
        normalize_unicode: Normalize Unicode characters
        remove_html: Remove HTML tags and unescape entities
        remove_urls: Remove URLs
        remove_special_chars: Remove special characters
        fix_punctuation_spacing: Fix spacing around punctuation
        remove_repeated_punct: Remove repeated punctuation
        **kwargs: Additional arguments for specific cleaning functions

    Returns:
        Cleaned text

    Example:
        >>> clean_text("  Hello   <b>World</b>!!!  ", remove_html=True, remove_repeated_punct=True)
        'Hello World!'
    """
    if not isinstance(text, str):
        return str(text)

    # Apply cleaning operations in order
    if normalize_unicode:
        text = globals()['normalize_unicode'](text, form=kwargs.get('unicode_form', 'NFKC'))

    if remove_html:
        text = remove_html_tags(text)

    if remove_urls:
        text = globals()['remove_urls'](text, replacement=kwargs.get('url_replacement', ' '))

    if remove_special_chars:
        text = remove_special_characters(
            text,
            keep_chars=kwargs.get('keep_chars', None),
            replacement=kwargs.get('special_char_replacement', ' ')
        )

    if remove_repeated_punct:
        text = remove_repeated_punctuation(text)

    if fix_punctuation_spacing:
        text = fix_spacing_around_punctuation(text)

    if remove_extra_whitespace:
        text = globals()['remove_extra_whitespace'](text)

    if lowercase:
        text = text.lower()

    return text


def clean_paragraph(
    title: str,
    sentences: list,
    **cleaning_kwargs
) -> tuple:
    """
    Clean a HotpotQA paragraph (title and sentences).

    Args:
        title: Paragraph title
        sentences: List of sentences
        **cleaning_kwargs: Arguments passed to clean_text

    Returns:
        Tuple of (cleaned_title, cleaned_sentences)

    Example:
        >>> title, sentences = clean_paragraph(
        ...     "  Paris  ",
        ...     ["Paris is capital.", "  It's nice.  "]
        ... )
        >>> title
        'Paris'
    """
    cleaned_title = clean_text(title, **cleaning_kwargs)
    cleaned_sentences = [clean_text(sent, **cleaning_kwargs) for sent in sentences]
    return cleaned_title, cleaned_sentences


if __name__ == "__main__":
    # Demo usage
    print("Testing text cleaning utilities...\n")

    test_text = "  Hello   <b>World</b>!!!  Check  https://example.com  "

    print(f"Original: '{test_text}'")
    print()

    print("--- Individual cleaning operations ---")
    print(f"remove_extra_whitespace: '{remove_extra_whitespace(test_text)}'")
    print(f"remove_html_tags: '{remove_html_tags(test_text)}'")
    print(f"remove_urls: '{globals()['remove_urls'](test_text)}'")
    print(f"remove_repeated_punctuation: '{remove_repeated_punctuation(test_text)}'")
    print()

    print("--- Complete cleaning ---")
    cleaned = clean_text(
        test_text,
        remove_html=True,
        remove_urls=True,
        remove_repeated_punct=True,
        remove_extra_whitespace=True
    )
    print(f"Cleaned: '{cleaned}'")
    print()

    print("✅ Cleaning module working!")
