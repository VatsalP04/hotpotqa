"""
Prompt formatting for IRCoT.

This module handles all prompt construction for the IRCoT system.
Prompts follow the official IRCoT format from Trivedi et al. (2023).
"""

from __future__ import annotations

from typing import List, Optional

from .types import CoTDemo, Paragraph
from .config import IRCoTConfig


# =============================================================================
# System Instructions
# =============================================================================

IRCOT_SYSTEM_INSTRUCTION = """You are a helpful assistant that answers questions using step-by-step reasoning.

IMPORTANT: Follow the exact format and style of the examples provided:
1. Provide clear, step-by-step reasoning that connects information from the given paragraphs
2. Use the same writing style and structure as the examples
3. End your reasoning with "So the answer is: [ANSWER]." (exactly as shown in examples)
4. Be concise but thorough in your reasoning steps
5. If the answer is incomplete ('so the answer is' not there) generate the next step of the reasoning 

The examples show the expected format - follow them closely."""


QA_READER_SYSTEM_INSTRUCTION = """You are a helpful assistant that answers questions using complete Chain-of-Thought reasoning.

IMPORTANT: Follow the exact format and style of the examples provided:
1. Review all the provided paragraphs carefully
2. Generate complete step-by-step reasoning that connects information from the paragraphs
3. Work through the logic systematically to arrive at the answer
4. End your reasoning with "So the answer is: [ANSWER]." (exactly as shown in examples)
5. Provide a comprehensive reasoning chain that fully explains how you arrived at the answer

The examples show the expected format - generate a complete Chain-of-Thought following their style."""


def get_system_instruction() -> str:
    """Get the system instruction for IRCoT reasoning prompts."""
    return IRCOT_SYSTEM_INSTRUCTION


def get_qa_reader_system_instruction() -> str:
    """Get the system instruction for QA Reader prompts."""
    return QA_READER_SYSTEM_INSTRUCTION


# =============================================================================
# Formatting Helpers
# =============================================================================

def format_paragraph(paragraph: Paragraph) -> str:
    """
    Format a single paragraph in IRCoT style.
    
    Args:
        paragraph: Paragraph to format
        
    Returns:
        Formatted string with "Wikipedia Title:" header
    """
    return f"Wikipedia Title: {paragraph.title}\n{paragraph.text}"


def format_paragraphs(paragraphs: List[Paragraph]) -> str:
    """
    Format multiple paragraphs in IRCoT style.
    
    Args:
        paragraphs: List of paragraphs to format
        
    Returns:
        Formatted string with all paragraphs
    """
    return "\n\n".join(format_paragraph(p) for p in paragraphs)


def format_demo(demo: CoTDemo) -> str:
    """
    Format a single few-shot demonstration.
    
    Args:
        demo: CoTDemo to format
        
    Returns:
        Formatted demonstration string
    """
    parts = [
        format_paragraphs(demo.paragraphs),
        f"Q: {demo.question}",
        f"A: {demo.cot_answer}"
    ]
    return "\n\n".join(parts)


# =============================================================================
# Main Prompt Builders
# =============================================================================

def build_reason_prompt(
    demos: List[CoTDemo],
    paragraphs: List[Paragraph],
    question: str,
    current_cot: str = "",
    num_examples: int = 3,
    include_instruction: bool = True
) -> str:
    """
    Build prompt for a single IRCoT reasoning step.
    
    This follows the official IRCoT prompt format:
    - Optional format instruction
    - Few-shot demonstrations
    - Retrieved paragraphs
    - Question with partial CoT continuation
    
    Args:
        demos: Few-shot demonstrations
        paragraphs: Retrieved paragraphs for this question
        question: The question being answered
        current_cot: Current partial CoT reasoning
        num_examples: Number of demonstrations to include
        include_instruction: Whether to add format instruction
        
    Returns:
        Complete prompt string
    """
    parts = []
    
    # Optional instruction
    if include_instruction:
        parts.append("Follow the format of the examples below. Continue the reasoning step-by-step.")
        parts.append("")
    
    # Few-shot demonstrations
    for demo in demos[:num_examples]:
        parts.append(format_demo(demo))
    
    # Current instance
    parts.append(format_paragraphs(paragraphs))
    parts.append(f"Q: {question}")
    
    # Answer prompt with optional continuation
    if current_cot.strip():
        parts.append(f"A: {current_cot} ")
    else:
        parts.append("A: ")
    
    return "\n\n".join(parts)


def build_qa_prompt(
    demos: List[CoTDemo],
    paragraphs: List[Paragraph],
    question: str,
    num_examples: int = 3,
    include_instruction: bool = True
) -> str:
    """
    Build prompt for QA Reader (final answer generation).
    
    Similar to reason prompt but starts fresh without partial CoT,
    allowing the reader to generate complete reasoning.
    
    Args:
        demos: Few-shot demonstrations
        paragraphs: All accumulated paragraphs
        question: The question to answer
        num_examples: Number of demonstrations to include
        include_instruction: Whether to add format instruction
        
    Returns:
        Complete prompt string
    """
    parts = []
    
    if include_instruction:
        parts.append(
            "Follow the format of the examples below. "
            "Provide step-by-step reasoning and end with 'So the answer is: [ANSWER].'"
        )
        parts.append("")
    
    # Few-shot demonstrations
    for demo in demos[:num_examples]:
        parts.append(format_demo(demo))
        parts.append("")  # Extra spacing between demos
    
    # Current instance
    parts.append(format_paragraphs(paragraphs))
    parts.append(f"Q: {question}")
    parts.append("A: Let's reason step by step. ")
    
    return "\n\n".join(parts)


def build_direct_qa_prompt(
    demos: List[CoTDemo],
    paragraphs: List[Paragraph],
    question: str,
    num_examples: int = 3
) -> str:
    """
    Build prompt for direct QA without CoT (baseline).
    
    Args:
        demos: Few-shot demonstrations
        paragraphs: Retrieved paragraphs
        question: The question to answer
        num_examples: Number of demonstrations to include
        
    Returns:
        Complete prompt string
    """
    from .answer_extraction import AnswerExtractor
    
    parts = []
    
    # Demonstrations with extracted answers (not full CoT)
    for demo in demos[:num_examples]:
        parts.append(format_paragraphs(demo.paragraphs))
        parts.append(f"Q: {demo.question}")
        
        # Extract just the answer from the CoT
        result = AnswerExtractor.extract(demo.cot_answer)
        parts.append(f"A: {result.answer}")
    
    # Current instance
    parts.append(format_paragraphs(paragraphs))
    parts.append(f"Q: {question}")
    parts.append("A: ")
    
    return "\n\n".join(parts)


# =============================================================================
# Specialized Prompts
# =============================================================================

REFLECTION_TEMPLATE = """Based on your previous reasoning, evaluate whether the answer is well-supported by the evidence.

Question: {question}
Previous reasoning: {cot}
Extracted answer: {answer}

Is this answer correct and well-supported? If not, what additional information would help?
Provide a brief reflection:"""


def build_reflection_prompt(question: str, cot: str, answer: str) -> str:
    """
    Build prompt for self-reflective reasoning.
    
    Inspired by Takeda et al. (2023) on self-evaluative prompting.
    
    Args:
        question: The question being answered
        cot: Current CoT reasoning
        answer: Extracted answer
        
    Returns:
        Reflection prompt string
    """
    return REFLECTION_TEMPLATE.format(
        question=question,
        cot=cot,
        answer=answer
    )
