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

