"""
Multi-hop reasoning preprocessing for HotpotQA.

This module provides utilities for extracting and processing multi-hop
reasoning chains from HotpotQA examples, including supporting facts analysis
and reasoning path construction.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict

logger = logging.getLogger(__name__)


def extract_supporting_facts(
    example: Dict[str, Any],
    return_sentences: bool = False
) -> List[Tuple[str, int]]:
    """
    Extract supporting facts from an example.

    Args:
        example: HotpotQA example
        return_sentences: If True, also return the actual sentence text

    Returns:
        List of (title, sentence_id) tuples, or list of (title, sentence_id, text) if return_sentences=True

    Example:
        >>> example = {
        ...     'supporting_facts': [['Paris', 0], ['France', 1]],
        ...     'context': [['Paris', ['Paris is capital.', 'It is nice.']], ['France', ['X', 'France exists.']]]
        ... }
        >>> extract_supporting_facts(example, return_sentences=True)
        [('Paris', 0, 'Paris is capital.'), ('France', 1, 'France exists.')]
    """
    supporting_facts = example.get('supporting_facts', [])

    if not return_sentences:
        return [(title, sent_id) for title, sent_id in supporting_facts]

    # Build context lookup
    context_dict = {title: sentences for title, sentences in example.get('context', [])}

    result = []
    for title, sent_id in supporting_facts:
        if title in context_dict:
            sentences = context_dict[title]
            if 0 <= sent_id < len(sentences):
                sentence_text = sentences[sent_id]
                result.append((title, sent_id, sentence_text))
            else:
                logger.warning(
                    f"Supporting fact references invalid sentence: {title}[{sent_id}] "
                    f"(only {len(sentences)} sentences available)"
                )
        else:
            logger.warning(f"Supporting fact references missing paragraph: {title}")

    return result


def group_supporting_facts_by_paragraph(
    supporting_facts: List[Tuple[str, int]]
) -> Dict[str, List[int]]:
    """
    Group supporting facts by paragraph title.

    Args:
        supporting_facts: List of (title, sentence_id) tuples

    Returns:
        Dictionary mapping title to list of sentence IDs

    Example:
        >>> facts = [('Paris', 0), ('Paris', 2), ('France', 1)]
        >>> group_supporting_facts_by_paragraph(facts)
        {'Paris': [0, 2], 'France': [1]}
    """
    grouped = defaultdict(list)
    for title, sent_id in supporting_facts:
        grouped[title].append(sent_id)
    return dict(grouped)


def identify_reasoning_type(example: Dict[str, Any]) -> str:
    """
    Identify the type of multi-hop reasoning required.

    Args:
        example: HotpotQA example

    Returns:
        Reasoning type ('comparison', 'bridge', or 'unknown')

    Example:
        >>> example = {'type': 'bridge'}
        >>> identify_reasoning_type(example)
        'bridge'
    """
    reasoning_type = example.get('type', 'unknown')

    # Validate type
    if reasoning_type not in ['comparison', 'bridge', 'unknown']:
        logger.warning(f"Unknown reasoning type: {reasoning_type}")
        return 'unknown'

    return reasoning_type


def extract_reasoning_chain(
    example: Dict[str, Any],
    max_hops: int = 4
) -> List[Dict[str, Any]]:
    """
    Extract the reasoning chain from supporting facts.

    A reasoning chain represents the sequence of facts needed to answer the question.

    Args:
        example: HotpotQA example
        max_hops: Maximum number of reasoning hops

    Returns:
        List of reasoning steps, each containing paragraph title and relevant sentences

    Example:
        >>> example = {
        ...     'supporting_facts': [['Paris', 0], ['France', 1]],
        ...     'context': [['Paris', ['Paris is in France.']], ['France', ['France is in Europe.']]]
        ... }
        >>> chain = extract_reasoning_chain(example)
        >>> len(chain)
        2
    """
    supporting_facts = extract_supporting_facts(example, return_sentences=True)

    if not supporting_facts:
        return []

    # Group by paragraph to create reasoning steps
    grouped = defaultdict(list)
    for title, sent_id, text in supporting_facts:
        grouped[title].append({'sentence_id': sent_id, 'text': text})

    # Create chain (each paragraph is a hop)
    chain = []
    for title, sentences in grouped.items():
        chain.append({
            'hop': len(chain) + 1,
            'paragraph_title': title,
            'sentences': sentences,
            'num_sentences': len(sentences)
        })

        if len(chain) >= max_hops:
            break

    return chain


def count_reasoning_hops(example: Dict[str, Any]) -> int:
    """
    Count the number of reasoning hops (distinct paragraphs in supporting facts).

    Args:
        example: HotpotQA example

    Returns:
        Number of hops

    Example:
        >>> example = {'supporting_facts': [['A', 0], ['A', 1], ['B', 0]]}
        >>> count_reasoning_hops(example)
        2
    """
    supporting_facts = example.get('supporting_facts', [])
    unique_titles = {title for title, _ in supporting_facts}
    return len(unique_titles)


def is_multihop(example: Dict[str, Any], min_hops: int = 2) -> bool:
    """
    Check if an example requires multi-hop reasoning.

    Args:
        example: HotpotQA example
        min_hops: Minimum number of hops to be considered multi-hop

    Returns:
        True if example requires min_hops or more reasoning hops

    Example:
        >>> example = {'supporting_facts': [['A', 0], ['B', 0]]}
        >>> is_multihop(example, min_hops=2)
        True
    """
    return count_reasoning_hops(example) >= min_hops


def get_bridge_entities(example: Dict[str, Any]) -> Set[str]:
    """
    Extract potential bridge entities from a bridge question.

    Bridge questions typically connect two entities through a shared property.

    Args:
        example: HotpotQA example

    Returns:
        Set of potential bridge entities (paragraph titles from supporting facts)

    Example:
        >>> example = {'type': 'bridge', 'supporting_facts': [['Paris', 0], ['France', 0]]}
        >>> get_bridge_entities(example)
        {'Paris', 'France'}
    """
    if example.get('type') != 'bridge':
        logger.warning("get_bridge_entities called on non-bridge question")

    supporting_facts = example.get('supporting_facts', [])
    return {title for title, _ in supporting_facts}


def create_multihop_features(example: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create comprehensive multi-hop reasoning features for an example.

    Args:
        example: HotpotQA example

    Returns:
        Dictionary of multi-hop features

    Example:
        >>> example = {
        ...     'type': 'bridge',
        ...     'supporting_facts': [['A', 0], ['A', 1], ['B', 0]],
        ...     'context': [['A', ['x', 'y']], ['B', ['z']]]
        ... }
        >>> features = create_multihop_features(example)
        >>> features['num_hops']
        2
    """
    features = {
        'reasoning_type': identify_reasoning_type(example),
        'num_hops': count_reasoning_hops(example),
        'is_multihop': is_multihop(example),
        'num_supporting_facts': len(example.get('supporting_facts', [])),
        'supporting_paragraphs': list(get_bridge_entities(example)),
        'reasoning_chain': extract_reasoning_chain(example),
    }

    # Add type-specific features
    if features['reasoning_type'] == 'bridge':
        features['bridge_entities'] = list(get_bridge_entities(example))

    return features


def filter_multihop_examples(
    examples: List[Dict[str, Any]],
    min_hops: int = 2,
    max_hops: Optional[int] = None,
    reasoning_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Filter examples based on multi-hop criteria.

    Args:
        examples: List of HotpotQA examples
        min_hops: Minimum number of hops
        max_hops: Maximum number of hops (None for no limit)
        reasoning_type: Filter by reasoning type ('comparison', 'bridge', or None)

    Returns:
        Filtered list of examples

    Example:
        >>> examples = [
        ...     {'supporting_facts': [['A', 0], ['B', 0]], 'type': 'bridge'},
        ...     {'supporting_facts': [['A', 0]], 'type': 'bridge'},
        ... ]
        >>> filtered = filter_multihop_examples(examples, min_hops=2)
        >>> len(filtered)
        1
    """
    filtered = []

    for example in examples:
        # Check hop count
        num_hops = count_reasoning_hops(example)
        if num_hops < min_hops:
            continue
        if max_hops is not None and num_hops > max_hops:
            continue

        # Check reasoning type
        if reasoning_type is not None:
            if example.get('type') != reasoning_type:
                continue

        filtered.append(example)

    logger.info(f"Filtered from {len(examples)} to {len(filtered)} multi-hop examples")
    return filtered


def analyze_multihop_distribution(
    examples: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze the distribution of multi-hop characteristics in a dataset.

    Args:
        examples: List of HotpotQA examples

    Returns:
        Dictionary with distribution statistics

    Example:
        >>> examples = [...]  # List of examples
        >>> stats = analyze_multihop_distribution(examples)
        >>> print(f"Average hops: {stats['avg_hops']:.2f}")
    """
    if not examples:
        return {}

    hop_counts = []
    reasoning_types = defaultdict(int)
    supporting_fact_counts = []

    for example in examples:
        hop_counts.append(count_reasoning_hops(example))
        reasoning_types[example.get('type', 'unknown')] += 1
        supporting_fact_counts.append(len(example.get('supporting_facts', [])))

    return {
        'total_examples': len(examples),
        'avg_hops': sum(hop_counts) / len(hop_counts),
        'min_hops': min(hop_counts),
        'max_hops': max(hop_counts),
        'hop_distribution': dict(
            zip(*zip(*[(h, hop_counts.count(h)) for h in set(hop_counts)]))
        ) if hop_counts else {},
        'reasoning_type_distribution': dict(reasoning_types),
        'avg_supporting_facts': sum(supporting_fact_counts) / len(supporting_fact_counts),
        'multihop_percentage': 100.0 * sum(1 for h in hop_counts if h >= 2) / len(hop_counts),
    }


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)

    # Sample example
    example = {
        '_id': 'test_001',
        'type': 'bridge',
        'question': 'What country is the capital Paris located in?',
        'answer': 'France',
        'context': [
            ['Paris', ['Paris is the capital of France.', 'It has 2.2 million people.']],
            ['France', ['France is located in Europe.', 'It is known for wine.']],
        ],
        'supporting_facts': [
            ['Paris', 0],
            ['France', 0]
        ]
    }

    print("--- Testing extract_supporting_facts ---")
    facts = extract_supporting_facts(example, return_sentences=True)
    for title, sent_id, text in facts:
        print(f"  {title}[{sent_id}]: {text}")

    print("\n--- Testing extract_reasoning_chain ---")
    chain = extract_reasoning_chain(example)
    for step in chain:
        print(f"  Hop {step['hop']}: {step['paragraph_title']} ({step['num_sentences']} sentences)")

    print("\n--- Testing create_multihop_features ---")
    features = create_multihop_features(example)
    print(f"  Reasoning type: {features['reasoning_type']}")
    print(f"  Number of hops: {features['num_hops']}")
    print(f"  Is multihop: {features['is_multihop']}")

    print("\n✅ Multi-hop preprocessing module working!")
