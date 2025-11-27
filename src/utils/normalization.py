"""
Text normalization utilities for HotpotQA.

This module provides functions for normalizing text, including case folding,
punctuation normalization, number normalization, etc.
"""

import re
import string
from typing import Optional


def normalize_case(text: str, method: str = 'lower') -> str:
    """
    Normalize text case.

    Args:
        text: Input text
        method: Normalization method ('lower', 'upper', 'title', 'capitalize')

    Returns:
        Case-normalized text

    Example:
        >>> normalize_case("Hello WORLD", method='lower')
        'hello world'
    """
    if method == 'lower':
        return text.lower()
    elif method == 'upper':
        return text.upper()
    elif method == 'title':
        return text.title()
    elif method == 'capitalize':
        return text.capitalize()
    else:
        raise ValueError(f"Unknown normalization method: {method}")


def normalize_punctuation(text: str) -> str:
    """
    Normalize punctuation to standard forms.

    Args:
        text: Input text

    Returns:
        Text with normalized punctuation

    Example:
        >>> normalize_punctuation("Hello\u2019world")  # Smart quote
        "Hello'world"
    """
    # Normalize quotes
    text = text.replace('"', '"').replace('"', '"')  # Smart double quotes
    text = text.replace(''', "'").replace(''', "'")  # Smart single quotes
    text = text.replace('`', "'")  # Backticks

    # Normalize dashes
    text = text.replace('–', '-').replace('—', '-')  # En dash, em dash
    text = text.replace('‐', '-').replace('‑', '-')  # Various hyphens

    # Normalize ellipsis
    text = text.replace('…', '...')

    return text


def normalize_numbers(text: str, method: str = 'digit') -> str:
    """
    Normalize numbers in text.

    Args:
        text: Input text
        method: Normalization method:
               'digit' - keep as digits
               'word' - convert to words (not implemented)
               'mask' - replace with a token

    Returns:
        Text with normalized numbers

    Example:
        >>> normalize_numbers("I have 123 apples and 456 oranges", method='mask')
        'I have <NUM> apples and <NUM> oranges'
    """
    if method == 'digit':
        # Keep as is (already digits)
        return text
    elif method == 'mask':
        # Replace numbers with <NUM> token
        text = re.sub(r'\b\d+\.?\d*\b', '<NUM>', text)
        return text
    elif method == 'word':
        raise NotImplementedError("Number-to-word conversion not implemented")
    else:
        raise ValueError(f"Unknown method: {method}")


def normalize_whitespace(text: str, collapse: bool = True) -> str:
    """
    Normalize whitespace in text.

    Args:
        text: Input text
        collapse: Whether to collapse multiple spaces into one

    Returns:
        Text with normalized whitespace

    Example:
        >>> normalize_whitespace("Hello    world\\n\\n\\ntest")
        'Hello world\\ntest'
    """
    if collapse:
        # Collapse multiple spaces
        text = re.sub(r' +', ' ', text)
        # Collapse multiple newlines
        text = re.sub(r'\n+', '\n', text)
        # Remove leading/trailing whitespace on each line
        text = '\n'.join(line.strip() for line in text.split('\n'))
        # Remove empty lines
        text = '\n'.join(line for line in text.split('\n') if line)

    # Strip overall
    text = text.strip()
    return text


def remove_articles(text: str, articles: Optional[list] = None) -> str:
    """
    Remove articles from text (useful for answer matching).

    Args:
        text: Input text
        articles: List of articles to remove (defaults to ['a', 'an', 'the'])

    Returns:
        Text without articles

    Example:
        >>> remove_articles("The quick brown fox")
        'quick brown fox'
    """
    if articles is None:
        articles = ['a', 'an', 'the']

    # Create pattern to match articles as whole words
    pattern = r'\b(' + '|'.join(re.escape(art) for art in articles) + r')\b\s*'
    text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    return text.strip()


def remove_punctuation(text: str, keep: Optional[str] = None) -> str:
    """
    Remove punctuation from text.

    Args:
        text: Input text
        keep: Punctuation characters to keep (e.g., '.,!?')

    Returns:
        Text without punctuation

    Example:
        >>> remove_punctuation("Hello, world!")
        'Hello world'
        >>> remove_punctuation("Hello, world!", keep=',')
        'Hello, world'
    """
    if keep is None:
        # Remove all punctuation
        translator = str.maketrans('', '', string.punctuation)
    else:
        # Remove all except specified punctuation
        remove_chars = ''.join(c for c in string.punctuation if c not in keep)
        translator = str.maketrans('', '', remove_chars)

    return text.translate(translator)


def normalize_answer(answer: str) -> str:
    """
    Normalize an answer string for evaluation (HotpotQA style).

    This implements the normalization used in HotpotQA evaluation:
    - Lowercase
    - Remove articles (a, an, the)
    - Remove punctuation
    - Remove extra whitespace

    Args:
        answer: Answer string

    Returns:
        Normalized answer

    Example:
        >>> normalize_answer("The Capital City!")
        'capital city'
    """
    # Lowercase
    answer = answer.lower()

    # Remove articles
    answer = remove_articles(answer)

    # Remove punctuation
    answer = remove_punctuation(answer)

    # Normalize whitespace
    answer = normalize_whitespace(answer)

    return answer


def normalize_text(
    text: str,
    lowercase: bool = False,
    normalize_punct: bool = True,
    normalize_nums: bool = False,
    normalize_ws: bool = True,
    remove_articles: bool = False,
    remove_punct: bool = False,
    **kwargs
) -> str:
    """
    Apply multiple normalization operations to text.

    Args:
        text: Input text
        lowercase: Convert to lowercase
        normalize_punct: Normalize punctuation to standard forms
        normalize_nums: Normalize numbers (see normalize_numbers for methods)
        normalize_ws: Normalize whitespace
        remove_articles: Remove articles (a, an, the)
        remove_punct: Remove punctuation
        **kwargs: Additional arguments for specific normalization functions

    Returns:
        Normalized text

    Example:
        >>> normalize_text("The  café  costs  $5", lowercase=True, remove_articles=True)
        'café costs $5'
    """
    if not isinstance(text, str):
        return str(text)

    # Apply normalizations in order
    if normalize_punct:
        text = normalize_punctuation(text)

    if normalize_nums:
        text = normalize_numbers(text, method=kwargs.get('number_method', 'digit'))

    if remove_articles:
        text = globals()['remove_articles'](text, articles=kwargs.get('articles', None))

    if remove_punct:
        text = remove_punctuation(text, keep=kwargs.get('keep_punctuation', None))

    if normalize_ws:
        text = normalize_whitespace(text, collapse=kwargs.get('collapse_whitespace', True))

    if lowercase:
        text = text.lower()

    return text


if __name__ == "__main__":
    # Demo usage
    print("Testing text normalization utilities...\n")

    test_text = "The  café  costs  $5—really!"

    print(f"Original: '{test_text}'")
    print()

    print("--- Individual normalization operations ---")
    print(f"lowercase: '{normalize_case(test_text, 'lower')}'")
    print(f"normalize_punctuation: '{normalize_punctuation(test_text)}'")
    print(f"remove_articles: '{globals()['remove_articles'](test_text)}'")
    print(f"remove_punctuation: '{remove_punctuation(test_text)}'")
    print()

    print("--- Answer normalization ---")
    test_answer = "The Capital City!"
    print(f"Original answer: '{test_answer}'")
    print(f"Normalized answer: '{normalize_answer(test_answer)}'")
    print()

    print("--- Complete normalization ---")
    normalized = normalize_text(
        test_text,
        lowercase=True,
        normalize_punct=True,
        normalize_ws=True,
        remove_articles=True
    )
    print(f"Normalized: '{normalized}'")
    print()

    print("✅ Normalization module working!")
