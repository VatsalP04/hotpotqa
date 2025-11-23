"""
Dataset analysis utilities for HotpotQA.

This module provides functions for analyzing and getting statistics about
the HotpotQA dataset, including question types, answer distributions, etc.
"""

import logging
from typing import List, Dict, Any, Optional
from collections import Counter, defaultdict
import json

logger = logging.getLogger(__name__)


def count_examples(examples: List[Dict[str, Any]]) -> int:
    """Return the number of examples."""
    return len(examples)


def analyze_questions(examples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze question characteristics.

    Args:
        examples: List of HotpotQA examples

    Returns:
        Dictionary with question statistics
    """
    question_lengths = []
    question_words = []
    question_starters = Counter()

    for example in examples:
        question = example.get('question', '')
        question_lengths.append(len(question))

        words = question.split()
        question_words.append(len(words))

        # Get first word (question starter)
        if words:
            first_word = words[0].lower().rstrip('.,!?')
            question_starters[first_word] += 1

    return {
        'total_questions': len(examples),
        'avg_length_chars': sum(question_lengths) / max(len(question_lengths), 1),
        'avg_length_words': sum(question_words) / max(len(question_words), 1),
        'min_length_chars': min(question_lengths) if question_lengths else 0,
        'max_length_chars': max(question_lengths) if question_lengths else 0,
        'min_length_words': min(question_words) if question_words else 0,
        'max_length_words': max(question_words) if question_words else 0,
        'question_starters': dict(question_starters.most_common(10)),
    }


def analyze_answers(examples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze answer characteristics.

    Args:
        examples: List of HotpotQA examples

    Returns:
        Dictionary with answer statistics
    """
    answer_lengths = []
    answer_words = []
    answer_types = Counter()
    yes_no_count = 0

    for example in examples:
        answer = example.get('answer', '')
        answer_lengths.append(len(answer))

        words = answer.split()
        answer_words.append(len(words))

        # Classify answer type
        answer_lower = answer.lower().strip()
        if answer_lower in ['yes', 'no']:
            answer_types['yes/no'] += 1
            yes_no_count += 1
        elif len(words) == 1:
            answer_types['single_word'] += 1
        elif len(words) <= 3:
            answer_types['short_phrase'] += 1
        else:
            answer_types['long_phrase'] += 1

    return {
        'total_answers': len(examples),
        'avg_length_chars': sum(answer_lengths) / max(len(answer_lengths), 1),
        'avg_length_words': sum(answer_words) / max(len(answer_words), 1),
        'min_length_chars': min(answer_lengths) if answer_lengths else 0,
        'max_length_chars': max(answer_lengths) if answer_lengths else 0,
        'min_length_words': min(answer_words) if answer_words else 0,
        'max_length_words': max(answer_words) if answer_words else 0,
        'answer_type_distribution': dict(answer_types),
        'yes_no_percentage': 100.0 * yes_no_count / max(len(examples), 1),
    }


def analyze_context(examples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze context characteristics.

    Args:
        examples: List of HotpotQA examples

    Returns:
        Dictionary with context statistics
    """
    num_paragraphs = []
    total_sentences = []
    paragraph_lengths = []

    for example in examples:
        context = example.get('context', [])
        num_paragraphs.append(len(context))

        example_sentences = 0
        for title, sentences in context:
            example_sentences += len(sentences)
            paragraph_text = ' '.join(sentences)
            paragraph_lengths.append(len(paragraph_text))

        total_sentences.append(example_sentences)

    return {
        'total_examples': len(examples),
        'avg_paragraphs_per_example': sum(num_paragraphs) / max(len(num_paragraphs), 1),
        'min_paragraphs': min(num_paragraphs) if num_paragraphs else 0,
        'max_paragraphs': max(num_paragraphs) if num_paragraphs else 0,
        'avg_sentences_per_example': sum(total_sentences) / max(len(total_sentences), 1),
        'avg_paragraph_length_chars': sum(paragraph_lengths) / max(len(paragraph_lengths), 1),
    }


def analyze_reasoning_types(examples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze reasoning type distribution.

    Args:
        examples: List of HotpotQA examples

    Returns:
        Dictionary with reasoning type statistics
    """
    type_counter = Counter()
    level_counter = Counter()

    for example in examples:
        reasoning_type = example.get('type', 'unknown')
        type_counter[reasoning_type] += 1

        level = example.get('level', 'unknown')
        level_counter[level] += 1

    return {
        'total_examples': len(examples),
        'type_distribution': dict(type_counter),
        'type_percentages': {
            t: 100.0 * count / len(examples)
            for t, count in type_counter.items()
        },
        'level_distribution': dict(level_counter),
        'level_percentages': {
            l: 100.0 * count / len(examples)
            for l, count in level_counter.items()
        },
    }


def analyze_supporting_facts(examples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze supporting facts characteristics.

    Args:
        examples: List of HotpotQA examples

    Returns:
        Dictionary with supporting facts statistics
    """
    num_facts = []
    num_paragraphs_with_facts = []

    for example in examples:
        supporting_facts = example.get('supporting_facts', [])
        num_facts.append(len(supporting_facts))

        # Count unique paragraphs
        unique_paragraphs = {title for title, _ in supporting_facts}
        num_paragraphs_with_facts.append(len(unique_paragraphs))

    return {
        'total_examples': len(examples),
        'avg_supporting_facts': sum(num_facts) / max(len(num_facts), 1),
        'min_supporting_facts': min(num_facts) if num_facts else 0,
        'max_supporting_facts': max(num_facts) if num_facts else 0,
        'avg_paragraphs_with_facts': sum(num_paragraphs_with_facts) / max(len(num_paragraphs_with_facts), 1),
        'multihop_percentage': 100.0 * sum(1 for n in num_paragraphs_with_facts if n >= 2) / max(len(examples), 1),
    }


def get_dataset_statistics(examples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get comprehensive statistics about the dataset.

    Args:
        examples: List of HotpotQA examples

    Returns:
        Dictionary with all statistics

    Example:
        >>> from src.data.loader import load_hotpotqa
        >>> data = load_hotpotqa('data/raw', 'train', max_examples=100)
        >>> stats = get_dataset_statistics(data)
        >>> print(f"Average question length: {stats['questions']['avg_length_words']:.1f} words")
    """
    logger.info(f"Analyzing {len(examples)} examples...")

    stats = {
        'dataset_size': len(examples),
        'questions': analyze_questions(examples),
        'answers': analyze_answers(examples),
        'context': analyze_context(examples),
        'reasoning_types': analyze_reasoning_types(examples),
        'supporting_facts': analyze_supporting_facts(examples),
    }

    logger.info("Analysis complete")
    return stats


def print_statistics(stats: Dict[str, Any], detailed: bool = True) -> None:
    """
    Print statistics in a readable format.

    Args:
        stats: Statistics dictionary from get_dataset_statistics
        detailed: Whether to print detailed statistics
    """
    print("=" * 60)
    print("DATASET STATISTICS")
    print("=" * 60)

    print(f"\n📊 Dataset Size: {stats['dataset_size']:,} examples")

    # Questions
    print("\n❓ QUESTIONS")
    q_stats = stats['questions']
    print(f"  Average length: {q_stats['avg_length_words']:.1f} words ({q_stats['avg_length_chars']:.1f} chars)")
    print(f"  Range: {q_stats['min_length_words']}-{q_stats['max_length_words']} words")
    if detailed and 'question_starters' in q_stats:
        print("  Top question starters:")
        for starter, count in list(q_stats['question_starters'].items())[:5]:
            print(f"    - {starter}: {count}")

    # Answers
    print("\n💬 ANSWERS")
    a_stats = stats['answers']
    print(f"  Average length: {a_stats['avg_length_words']:.1f} words ({a_stats['avg_length_chars']:.1f} chars)")
    print(f"  Range: {a_stats['min_length_words']}-{a_stats['max_length_words']} words")
    print(f"  Yes/No answers: {a_stats['yes_no_percentage']:.1f}%")
    if detailed and 'answer_type_distribution' in a_stats:
        print("  Answer type distribution:")
        for atype, count in a_stats['answer_type_distribution'].items():
            pct = 100.0 * count / stats['dataset_size']
            print(f"    - {atype}: {count} ({pct:.1f}%)")

    # Context
    print("\n📝 CONTEXT")
    c_stats = stats['context']
    print(f"  Average paragraphs per example: {c_stats['avg_paragraphs_per_example']:.1f}")
    print(f"  Range: {c_stats['min_paragraphs']}-{c_stats['max_paragraphs']} paragraphs")
    print(f"  Average sentences per example: {c_stats['avg_sentences_per_example']:.1f}")

    # Reasoning Types
    print("\n🧠 REASONING TYPES")
    r_stats = stats['reasoning_types']
    for rtype, percentage in r_stats['type_percentages'].items():
        count = r_stats['type_distribution'][rtype]
        print(f"  {rtype}: {count} ({percentage:.1f}%)")

    # Difficulty Levels
    if r_stats['level_distribution']:
        print("\n📈 DIFFICULTY LEVELS")
        for level, percentage in r_stats['level_percentages'].items():
            count = r_stats['level_distribution'][level]
            print(f"  {level}: {count} ({percentage:.1f}%)")

    # Supporting Facts
    print("\n🔗 SUPPORTING FACTS")
    sf_stats = stats['supporting_facts']
    print(f"  Average supporting facts per example: {sf_stats['avg_supporting_facts']:.1f}")
    print(f"  Range: {sf_stats['min_supporting_facts']}-{sf_stats['max_supporting_facts']} facts")
    print(f"  Average paragraphs with facts: {sf_stats['avg_paragraphs_with_facts']:.1f}")
    print(f"  Multi-hop examples (≥2 paragraphs): {sf_stats['multihop_percentage']:.1f}%")

    print("\n" + "=" * 60)


def save_statistics(
    stats: Dict[str, Any],
    output_path: str,
    pretty: bool = True
) -> None:
    """
    Save statistics to a JSON file.

    Args:
        stats: Statistics dictionary
        output_path: Path to save the statistics
        pretty: Whether to pretty-print the JSON
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        if pretty:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        else:
            json.dump(stats, f, ensure_ascii=False)

    logger.info(f"Statistics saved to {output_path}")


def compare_statistics(
    stats1: Dict[str, Any],
    stats2: Dict[str, Any],
    label1: str = "Dataset 1",
    label2: str = "Dataset 2"
) -> None:
    """
    Compare statistics between two datasets.

    Args:
        stats1: Statistics for first dataset
        stats2: Statistics for second dataset
        label1: Label for first dataset
        label2: Label for second dataset
    """
    print("=" * 80)
    print(f"COMPARING: {label1} vs {label2}")
    print("=" * 80)

    print(f"\n📊 Dataset Sizes:")
    print(f"  {label1}: {stats1['dataset_size']:,}")
    print(f"  {label2}: {stats2['dataset_size']:,}")

    print(f"\n❓ Average Question Length (words):")
    print(f"  {label1}: {stats1['questions']['avg_length_words']:.1f}")
    print(f"  {label2}: {stats2['questions']['avg_length_words']:.1f}")

    print(f"\n💬 Average Answer Length (words):")
    print(f"  {label1}: {stats1['answers']['avg_length_words']:.1f}")
    print(f"  {label2}: {stats2['answers']['avg_length_words']:.1f}")

    print(f"\n🧠 Reasoning Type Distribution:")
    for rtype in set(list(stats1['reasoning_types']['type_percentages'].keys()) +
                     list(stats2['reasoning_types']['type_percentages'].keys())):
        pct1 = stats1['reasoning_types']['type_percentages'].get(rtype, 0)
        pct2 = stats2['reasoning_types']['type_percentages'].get(rtype, 0)
        print(f"  {rtype}: {pct1:.1f}% vs {pct2:.1f}%")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    # Demo usage
    from pathlib import Path
    import sys

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data" / "raw"

    try:
        from ..data.loader import load_hotpotqa

        print("Loading data for analysis...")
        data = load_hotpotqa(data_dir, split='train', max_examples=100, validate=False)

        print("\nAnalyzing dataset...")
        stats = get_dataset_statistics(data)

        print("\n")
        print_statistics(stats, detailed=True)

        # Save statistics
        output_path = project_root / "data" / "processed" / "train_stats.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_statistics(stats, str(output_path))

        print(f"\n✅ Analysis complete! Statistics saved to {output_path}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
