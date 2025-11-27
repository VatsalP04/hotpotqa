"""
Validation utilities for HotpotQA dataset.

This module provides functions to validate the structure and content
of HotpotQA examples, ensuring data quality and consistency.
"""

import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)


class ValidationError:
    """Represents a validation error found in the dataset."""

    def __init__(self, example_id: str, field: str, message: str, severity: str = "error"):
        """
        Initialize a validation error.

        Args:
            example_id: ID of the example with the error
            field: Field name that has the error
            message: Description of the error
            severity: Severity level ('error' or 'warning')
        """
        self.example_id = example_id
        self.field = field
        self.message = message
        self.severity = severity

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] Example {self.example_id}, field '{self.field}': {self.message}"


def validate_example(example: Dict[str, Any], split: str = "train") -> List[ValidationError]:
    """
    Validate a single HotpotQA example.

    Args:
        example: Example dictionary to validate
        split: Dataset split ('train' or 'dev')

    Returns:
        List of validation errors found (empty if valid)
    """
    errors = []
    example_id = example.get('_id', 'UNKNOWN')

    # Required fields for all splits
    required_fields = ['_id', 'question', 'answer', 'context', 'supporting_facts']

    # Check for required fields
    for field in required_fields:
        if field not in example:
            errors.append(ValidationError(
                example_id, field, f"Missing required field '{field}'"
            ))

    # Validate _id
    if '_id' in example:
        if not isinstance(example['_id'], str) or len(example['_id']) == 0:
            errors.append(ValidationError(
                example_id, '_id', "ID must be a non-empty string"
            ))

    # Validate question
    if 'question' in example:
        if not isinstance(example['question'], str):
            errors.append(ValidationError(
                example_id, 'question', "Question must be a string"
            ))
        elif len(example['question'].strip()) == 0:
            errors.append(ValidationError(
                example_id, 'question', "Question is empty", severity="warning"
            ))

    # Validate answer
    if 'answer' in example:
        if not isinstance(example['answer'], str):
            errors.append(ValidationError(
                example_id, 'answer', "Answer must be a string"
            ))
        elif len(example['answer'].strip()) == 0:
            errors.append(ValidationError(
                example_id, 'answer', "Answer is empty", severity="warning"
            ))

    # Validate context
    if 'context' in example:
        context = example['context']
        if not isinstance(context, list):
            errors.append(ValidationError(
                example_id, 'context', "Context must be a list"
            ))
        else:
            for i, paragraph in enumerate(context):
                if not isinstance(paragraph, list) or len(paragraph) != 2:
                    errors.append(ValidationError(
                        example_id,
                        f'context[{i}]',
                        "Context paragraph must be a list of [title, sentences]"
                    ))
                else:
                    title, sentences = paragraph
                    if not isinstance(title, str):
                        errors.append(ValidationError(
                            example_id,
                            f'context[{i}][0]',
                            "Paragraph title must be a string"
                        ))
                    if not isinstance(sentences, list):
                        errors.append(ValidationError(
                            example_id,
                            f'context[{i}][1]',
                            "Paragraph sentences must be a list"
                        ))
                    elif not all(isinstance(s, str) for s in sentences):
                        errors.append(ValidationError(
                            example_id,
                            f'context[{i}][1]',
                            "All sentences must be strings"
                        ))

            # Check for reasonable context length
            if len(context) == 0:
                errors.append(ValidationError(
                    example_id, 'context', "Context is empty", severity="warning"
                ))
            elif len(context) > 50:
                errors.append(ValidationError(
                    example_id,
                    'context',
                    f"Context has unusually many paragraphs ({len(context)})",
                    severity="warning"
                ))

    # Validate supporting_facts
    if 'supporting_facts' in example:
        supporting_facts = example['supporting_facts']
        if not isinstance(supporting_facts, list):
            errors.append(ValidationError(
                example_id, 'supporting_facts', "Supporting facts must be a list"
            ))
        else:
            for i, fact in enumerate(supporting_facts):
                if not isinstance(fact, list) or len(fact) != 2:
                    errors.append(ValidationError(
                        example_id,
                        f'supporting_facts[{i}]',
                        "Supporting fact must be a list of [title, sentence_id]"
                    ))
                else:
                    title, sent_id = fact
                    if not isinstance(title, str):
                        errors.append(ValidationError(
                            example_id,
                            f'supporting_facts[{i}][0]',
                            "Fact title must be a string"
                        ))
                    if not isinstance(sent_id, int):
                        errors.append(ValidationError(
                            example_id,
                            f'supporting_facts[{i}][1]',
                            "Fact sentence ID must be an integer"
                        ))

            # Check for reasonable number of supporting facts
            if len(supporting_facts) == 0:
                errors.append(ValidationError(
                    example_id,
                    'supporting_facts',
                    "No supporting facts provided",
                    severity="warning"
                ))

    # Validate optional fields
    if 'type' in example:
        valid_types = ['comparison', 'bridge']
        if example['type'] not in valid_types:
            errors.append(ValidationError(
                example_id,
                'type',
                f"Type must be one of {valid_types}, got '{example['type']}'",
                severity="warning"
            ))

    if 'level' in example:
        valid_levels = ['easy', 'medium', 'hard']
        if example['level'] not in valid_levels:
            errors.append(ValidationError(
                example_id,
                'level',
                f"Level must be one of {valid_levels}, got '{example['level']}'",
                severity="warning"
            ))

    return errors


def validate_examples(
    examples: List[Dict[str, Any]],
    split: str = "train",
    max_errors: Optional[int] = None
) -> Tuple[bool, List[ValidationError]]:
    """
    Validate a list of HotpotQA examples.

    Args:
        examples: List of examples to validate
        split: Dataset split ('train' or 'dev')
        max_errors: Maximum number of errors to collect (None for all)

    Returns:
        Tuple of (is_valid, list_of_errors)
        is_valid is True if no errors found, False otherwise
    """
    all_errors = []

    for example in examples:
        errors = validate_example(example, split=split)
        all_errors.extend(errors)

        if max_errors is not None and len(all_errors) >= max_errors:
            break

    is_valid = len(all_errors) == 0
    return is_valid, all_errors


def validate_and_report(
    examples: List[Dict[str, Any]],
    split: str = "train",
    verbose: bool = True
) -> bool:
    """
    Validate examples and print a detailed report.

    Args:
        examples: List of examples to validate
        split: Dataset split ('train' or 'dev')
        verbose: Whether to print detailed error messages

    Returns:
        True if validation passed, False otherwise
    """
    logger.info(f"Validating {len(examples)} examples from {split} split...")

    is_valid, errors = validate_examples(examples, split=split)

    # Count errors by severity
    error_count = sum(1 for e in errors if e.severity == "error")
    warning_count = sum(1 for e in errors if e.severity == "warning")

    if is_valid:
        logger.info("✅ All examples are valid!")
        return True
    else:
        logger.warning(f"❌ Validation failed!")
        logger.warning(f"   Found {error_count} errors and {warning_count} warnings")

        if verbose and len(errors) > 0:
            logger.warning("\nShowing first 10 issues:")
            for error in errors[:10]:
                logger.warning(f"  {error}")

            if len(errors) > 10:
                logger.warning(f"  ... and {len(errors) - 10} more issues")

        return False


def check_supporting_facts_coverage(example: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if supporting facts reference valid context paragraphs.

    Args:
        example: HotpotQA example

    Returns:
        Dictionary with coverage statistics
    """
    context_titles = {title for title, _ in example.get('context', [])}
    supporting_titles = {title for title, _ in example.get('supporting_facts', [])}

    missing_titles = supporting_titles - context_titles
    coverage = len(supporting_titles - missing_titles) / max(len(supporting_titles), 1)

    return {
        'coverage': coverage,
        'supporting_titles': len(supporting_titles),
        'missing_titles': len(missing_titles),
        'missing_title_list': list(missing_titles),
        'fully_covered': len(missing_titles) == 0
    }


def validate_supporting_facts_coverage(
    examples: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate that supporting facts reference valid context across all examples.

    Args:
        examples: List of examples to check

    Returns:
        Dictionary with aggregate statistics
    """
    total = len(examples)
    fully_covered = 0
    total_coverage = 0.0
    issues = []

    for example in examples:
        coverage = check_supporting_facts_coverage(example)
        total_coverage += coverage['coverage']

        if coverage['fully_covered']:
            fully_covered += 1
        elif coverage['missing_titles'] > 0:
            issues.append({
                'example_id': example.get('_id', 'UNKNOWN'),
                'missing_titles': coverage['missing_title_list']
            })

    return {
        'total_examples': total,
        'fully_covered_count': fully_covered,
        'fully_covered_percent': 100.0 * fully_covered / max(total, 1),
        'average_coverage': total_coverage / max(total, 1),
        'issues_count': len(issues),
        'sample_issues': issues[:5]  # First 5 issues
    }


if __name__ == "__main__":
    # Demo usage
    from .loader import load_hotpotqa
    from pathlib import Path
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )

    # Try to load and validate data
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data" / "raw"

    try:
        print("Loading data for validation...")
        data = load_hotpotqa(data_dir, split='train', max_examples=100, validate=False)

        print(f"\nValidating {len(data)} examples...")
        is_valid = validate_and_report(data, split='train', verbose=True)

        print("\n--- Checking Supporting Facts Coverage ---")
        coverage_stats = validate_supporting_facts_coverage(data)
        print(f"Total examples: {coverage_stats['total_examples']}")
        print(f"Fully covered: {coverage_stats['fully_covered_count']} "
              f"({coverage_stats['fully_covered_percent']:.1f}%)")
        print(f"Average coverage: {coverage_stats['average_coverage']:.2%}")

        if coverage_stats['issues_count'] > 0:
            print(f"\nFound {coverage_stats['issues_count']} examples with coverage issues")
            print("Sample issues:")
            for issue in coverage_stats['sample_issues']:
                print(f"  - {issue['example_id']}: missing {len(issue['missing_titles'])} titles")

    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
