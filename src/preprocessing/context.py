"""
Context processing utilities for HotpotQA.

This module provides functions for flattening, chunking, and manipulating
context paragraphs from HotpotQA examples.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


def flatten_context(
    context: List[List[Any]],
    include_titles: bool = True,
    title_template: str = "Title: {title}\n",
    paragraph_separator: str = "\n\n",
    sentence_separator: str = " ",
    max_paragraphs: Optional[int] = None
) -> str:
    """
    Flatten HotpotQA context into a single string.

    Args:
        context: List of [title, sentences] pairs
        include_titles: Whether to include paragraph titles
        title_template: Template for formatting titles (must contain {title})
        paragraph_separator: Separator between paragraphs
        sentence_separator: Separator between sentences within a paragraph
        max_paragraphs: Maximum number of paragraphs to include (None for all)

    Returns:
        Flattened context string

    Example:
        >>> context = [
        ...     ["Paris", ["Paris is the capital of France.", "It has 2.2M people."]],
        ...     ["France", ["France is in Europe."]]
        ... ]
        >>> flatten_context(context, include_titles=True)
        'Title: Paris\nParis is the capital of France. It has 2.2M people.\n\nTitle: France\nFrance is in Europe.'
    """
    if max_paragraphs is not None:
        context = context[:max_paragraphs]

    paragraphs = []

    for title, sentences in context:
        parts = []

        # Add title if requested
        if include_titles:
            parts.append(title_template.format(title=title))

        # Join sentences
        if isinstance(sentences, list):
            paragraph_text = sentence_separator.join(sentences)
        else:
            paragraph_text = str(sentences)

        parts.append(paragraph_text)

        paragraphs.append("".join(parts))

    return paragraph_separator.join(paragraphs)


def extract_supporting_context(
    example: Dict[str, Any],
    include_titles: bool = True,
    title_template: str = "Title: {title}\n",
    paragraph_separator: str = "\n\n",
    sentence_separator: str = " "
) -> str:
    """
    Extract only the supporting fact paragraphs from context.

    Args:
        example: HotpotQA example with 'context' and 'supporting_facts'
        include_titles: Whether to include paragraph titles
        title_template: Template for formatting titles
        paragraph_separator: Separator between paragraphs
        sentence_separator: Separator between sentences

    Returns:
        Context string with only supporting paragraphs

    Example:
        >>> example = {
        ...     'context': [["Paris", ["Paris is capital."]], ["London", ["London exists."]]],
        ...     'supporting_facts': [["Paris", 0]]
        ... }
        >>> extract_supporting_context(example)
        'Title: Paris\nParis is capital.'
    """
    # Get supporting titles
    supporting_titles = {title for title, _ in example.get('supporting_facts', [])}

    # Filter context
    supporting_context = [
        [title, sentences]
        for title, sentences in example.get('context', [])
        if title in supporting_titles
    ]

    return flatten_context(
        supporting_context,
        include_titles=include_titles,
        title_template=title_template,
        paragraph_separator=paragraph_separator,
        sentence_separator=sentence_separator
    )


def chunk_context(
    context: List[List[Any]],
    max_chunk_paragraphs: int = 5,
    overlap: int = 1
) -> List[List[List[Any]]]:
    """
    Split context into overlapping chunks.

    Useful for handling long contexts that exceed model limits.

    Args:
        context: List of [title, sentences] pairs
        max_chunk_paragraphs: Maximum paragraphs per chunk
        overlap: Number of paragraphs to overlap between chunks

    Returns:
        List of context chunks

    Example:
        >>> context = [["A", ["a"]], ["B", ["b"]], ["C", ["c"]], ["D", ["d"]]]
        >>> chunks = chunk_context(context, max_chunk_paragraphs=2, overlap=1)
        >>> len(chunks)
        2
    """
    if len(context) <= max_chunk_paragraphs:
        return [context]

    chunks = []
    start = 0

    while start < len(context):
        end = min(start + max_chunk_paragraphs, len(context))
        chunks.append(context[start:end])

        # Move to next chunk with overlap
        start = end - overlap
        if start >= len(context):
            break

    return chunks


def get_paragraph_by_title(
    context: List[List[Any]],
    title: str
) -> Optional[List[Any]]:
    """
    Find a paragraph in context by its title.

    Args:
        context: List of [title, sentences] pairs
        title: Title to search for

    Returns:
        [title, sentences] pair if found, None otherwise
    """
    for para_title, sentences in context:
        if para_title == title:
            return [para_title, sentences]
    return None


def filter_context_by_titles(
    context: List[List[Any]],
    titles: List[str],
    preserve_order: bool = True
) -> List[List[Any]]:
    """
    Filter context to only include paragraphs with specified titles.

    Args:
        context: List of [title, sentences] pairs
        titles: List of titles to keep
        preserve_order: Whether to preserve original context order (vs. titles order)

    Returns:
        Filtered context

    Example:
        >>> context = [["A", ["a"]], ["B", ["b"]], ["C", ["c"]]]
        >>> filter_context_by_titles(context, ["C", "A"])
        [['A', ['a']], ['C', ['c']]]
    """
    title_set = set(titles)

    if preserve_order:
        # Keep original context order
        return [
            [title, sentences]
            for title, sentences in context
            if title in title_set
        ]
    else:
        # Follow titles order
        context_dict = {title: sentences for title, sentences in context}
        return [
            [title, context_dict[title]]
            for title in titles
            if title in context_dict
        ]


def count_tokens_approximate(text: str, method: str = "whitespace") -> int:
    """
    Approximate token count for text.

    Args:
        text: Input text
        method: Counting method ('whitespace', 'chars')

    Returns:
        Approximate token count
    """
    if method == "whitespace":
        return len(text.split())
    elif method == "chars":
        # Rough approximation: 4 chars per token (common for English)
        return len(text) // 4
    else:
        raise ValueError(f"Unknown method: {method}")


def truncate_context_to_length(
    context: List[List[Any]],
    max_tokens: int,
    method: str = "whitespace",
    prioritize_supporting: bool = False,
    supporting_titles: Optional[List[str]] = None
) -> List[List[Any]]:
    """
    Truncate context to fit within a maximum token budget.

    Args:
        context: List of [title, sentences] pairs
        max_tokens: Maximum number of tokens
        method: Token counting method ('whitespace', 'chars')
        prioritize_supporting: Whether to prioritize supporting paragraphs
        supporting_titles: List of supporting paragraph titles (if prioritize_supporting=True)

    Returns:
        Truncated context

    Example:
        >>> context = [["A", ["Long text"*100]], ["B", ["Short"]]]
        >>> truncated = truncate_context_to_length(context, max_tokens=50)
    """
    if prioritize_supporting and supporting_titles:
        # First include all supporting paragraphs
        supporting_set = set(supporting_titles)
        supporting_paras = []
        other_paras = []

        for title, sentences in context:
            if title in supporting_set:
                supporting_paras.append([title, sentences])
            else:
                other_paras.append([title, sentences])

        # Start with supporting paragraphs
        result = []
        total_tokens = 0

        for para in supporting_paras:
            para_text = " ".join(para[1]) if isinstance(para[1], list) else str(para[1])
            para_tokens = count_tokens_approximate(para_text, method)

            if total_tokens + para_tokens <= max_tokens:
                result.append(para)
                total_tokens += para_tokens

        # Add other paragraphs if there's room
        for para in other_paras:
            para_text = " ".join(para[1]) if isinstance(para[1], list) else str(para[1])
            para_tokens = count_tokens_approximate(para_text, method)

            if total_tokens + para_tokens <= max_tokens:
                result.append(para)
                total_tokens += para_tokens
            else:
                break

        return result
    else:
        # Simple truncation from the start
        result = []
        total_tokens = 0

        for title, sentences in context:
            para_text = " ".join(sentences) if isinstance(sentences, list) else str(sentences)
            para_tokens = count_tokens_approximate(para_text, method)

            if total_tokens + para_tokens <= max_tokens:
                result.append([title, sentences])
                total_tokens += para_tokens
            else:
                break

        return result


def format_context_for_qa(
    example: Dict[str, Any],
    include_question: bool = True,
    question_template: str = "Question: {question}\n\n",
    context_template: str = "Context:\n{context}\n\n",
    answer_template: Optional[str] = "Answer: {answer}",
    **context_kwargs
) -> str:
    """
    Format an example as a complete QA prompt.

    Args:
        example: HotpotQA example
        include_question: Whether to include the question
        question_template: Template for question formatting
        context_template: Template for context formatting
        answer_template: Template for answer formatting (None to exclude answer)
        **context_kwargs: Additional arguments passed to flatten_context

    Returns:
        Formatted QA string

    Example:
        >>> example = {'question': 'What is Paris?', 'context': [...], 'answer': 'Capital'}
        >>> formatted = format_context_for_qa(example)
    """
    parts = []

    # Add question
    if include_question and 'question' in example:
        parts.append(question_template.format(question=example['question']))

    # Add context
    if 'context' in example:
        context_str = flatten_context(example['context'], **context_kwargs)
        parts.append(context_template.format(context=context_str))

    # Add answer if requested and available
    if answer_template is not None and 'answer' in example:
        parts.append(answer_template.format(answer=example['answer']))

    return "".join(parts)


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)

    # Sample context
    context = [
        ["Paris", ["Paris is the capital of France.", "It has a population of 2.2 million."]],
        ["France", ["France is a country in Europe.", "It is known for wine and cheese."]],
        ["Europe", ["Europe is a continent."]]
    ]

    print("--- Testing flatten_context ---")
    flat = flatten_context(context, include_titles=True, max_paragraphs=2)
    print(flat)
    print()

    print("--- Testing chunk_context ---")
    chunks = chunk_context(context, max_chunk_paragraphs=2, overlap=1)
    print(f"Number of chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i+1}: {[title for title, _ in chunk]}")
    print()

    print("--- Testing truncate_context_to_length ---")
    truncated = truncate_context_to_length(context, max_tokens=30, method="whitespace")
    print(f"Truncated to {len(truncated)} paragraphs")
    print()

    print("✅ Context processing module working!")
