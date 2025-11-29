"""
IRCoT Prompt Engineering Module

This module handles prompt construction for the IRCoT algorithm. It defines the data
structures for few-shot demonstrations and provides functions to build prompts for
different stages of the IRCoT pipeline.

Key Components:
- CoTDemo: Data structure for few-shot demonstrations
- format_paragraphs(): Formats Wikipedia paragraphs in the IRCoT style
- build_ircot_reason_prompt(): Builds prompts for iterative reasoning steps
- build_reader_prompt_*(): Builds prompts for final answer generation

Prompt Structure:
IRCoT uses a specific prompt format that includes:
1. Few-shot demonstrations showing multi-hop reasoning
2. Retrieved Wikipedia paragraphs formatted consistently
3. The current question and any partial reasoning
4. Appropriate continuation prompts

The prompt engineering is critical for IRCoT performance as it:
- Teaches the model the expected reasoning format through examples
- Provides consistent document formatting
- Guides the model to generate single reasoning steps
- Ensures proper answer extraction patterns

Format Example:
    Wikipedia Title: Document 1
    [Document text]
    
    Wikipedia Title: Document 2  
    [Document text]
    
    Q: [Question]
    A: [Reasoning step 1. Reasoning step 2. So the answer is: Final Answer.]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .config import IRCoTConfig
from .retriever import Paragraph


@dataclass
class CoTDemo:
    """
    One in-context demonstration: docs + question + full CoT answer.
    """

    paragraphs: List[Paragraph]
    question: str
    cot_answer: str  # includes reasoning + "answer is: <final>"


def format_paragraphs(paragraphs: List[Paragraph]) -> str:
    """
    Format paragraphs similar to the structure used in IRCoT.
    """

    blocks = []
    for p in paragraphs:
        blocks.append(f"Wikipedia Title: {p.title}\n{p.text}")
    return "\n\n".join(blocks)


def build_ircot_reason_prompt(
    demos: List[CoTDemo],
    retrieved_paragraphs: List[Paragraph],
    question: str,
    current_cot: str,
    config: IRCoTConfig,
) -> str:
    """
    Build the prompt for a single IRCoT 'Reason' step.
    """

    parts = []

    # Add demos
    for demo in demos[: config.max_demos]:
        parts.append(format_paragraphs(demo.paragraphs))
        parts.append(f"Q: {demo.question}")
        parts.append(f"A: {demo.cot_answer}")

    # Add current instance: docs + question + partial CoT
    parts.append(format_paragraphs(retrieved_paragraphs))
    parts.append(f"Q: {question}")

    if current_cot.strip():
        parts.append(f"A: {current_cot} ")
    else:
        parts.append("A: ")

    return "\n\n".join(parts)


def build_reader_prompt_cot(
    demos: List[CoTDemo],
    retrieved_paragraphs: List[Paragraph],
    question: str,
    config: IRCoTConfig,
) -> str:
    """
    Build a CoT-style reader prompt, similar to the paper.
    """

    parts = []

    for demo in demos[: config.max_demos]:
        parts.append(format_paragraphs(demo.paragraphs))
        parts.append(f"Q: {demo.question}")
        parts.append(f"A: {demo.cot_answer}")

    parts.append(format_paragraphs(retrieved_paragraphs))
    parts.append(f"Q: {question}")
    parts.append("A: Let's reason step by step. ")

    return "\n\n".join(parts)


def build_reader_prompt_direct(
    demos: List[CoTDemo],
    retrieved_paragraphs: List[Paragraph],
    question: str,
    config: IRCoTConfig,
) -> str:
    """
    Direct answering reader: demos contain only final answer text in cot_answer.
    """

    parts = []

    for demo in demos[: config.max_demos]:
        parts.append(format_paragraphs(demo.paragraphs))
        parts.append(f"Q: {demo.question}")
        parts.append(f"A: {demo.cot_answer}")

    parts.append(format_paragraphs(retrieved_paragraphs))
    parts.append(f"Q: {question}")
    parts.append("A: ")

    return "\n\n".join(parts)

