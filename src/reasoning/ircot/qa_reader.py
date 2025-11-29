"""
IRCoT QA Reader Module

This module implements the final answer generation component of the IRCoT pipeline.
After the iterative retrieval loop completes, the QA Reader takes all retrieved
documents and generates a comprehensive final answer.

Key Classes:
- QAReader: Generates final answers from retrieved context
- QAResult: Container for the final answer and reasoning chain

The QA Reader is a separate component from the iterative retrieval loop, following
the two-stage design from the IRCoT paper:
1. IRCoT Retriever: Iteratively builds up relevant context through reasoning
2. QA Reader: Generates the final answer from all collected context

This separation allows for:
- Different prompting strategies for retrieval vs. answer generation
- Longer, more comprehensive final answers
- Better answer extraction and formatting
- Flexibility in reader implementation (CoT vs. direct answering)

The reader supports both chain-of-thought and direct answering modes, with
configurable few-shot demonstrations and answer extraction patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .config import IRCoTConfig
from .llm_client import LLMClient
from .prompts import CoTDemo, build_reader_prompt_cot, build_reader_prompt_direct
from .retriever import Paragraph


@dataclass
class QAResult:
    """Reader result: final answer + (optional) reasoning chain."""

    answer: str
    cot: str


class QAReader:
    """
    Separate reader module for final answer generation, as described in the IRCoT paper.
    
    The QA Reader takes the documents retrieved by the IRCoT loop and generates
    a comprehensive final answer. This two-stage approach (retrieve then read)
    allows for different optimization strategies and prompt designs.
    
    The reader can operate in two modes:
    1. Chain-of-Thought: Generates step-by-step reasoning before the final answer
    2. Direct: Generates the answer directly from the context
    
    The reader uses the same few-shot demonstrations as the retrieval loop but
    with different prompting to focus on answer generation rather than retrieval.
    
    Args:
        llm: Language model for answer generation
        demos: Few-shot demonstrations for in-context learning
        config: Configuration parameters including reader mode and token limits
    """

    def __init__(
        self,
        llm: LLMClient,
        demos: List[CoTDemo],
        config: IRCoTConfig,
    ):
        self.llm = llm
        self.demos = demos
        self.config = config

    def _extract_answer_from_text(self, text: str) -> Tuple[str, str]:
        """
        Parse 'answer is: ...' substrings; fallback to returning the entire text.
        """

        lower = text.lower()
        trigger = self.config.answer_trigger
        idx = lower.rfind(trigger)

        if idx != -1:
            after = text[idx + len(trigger) :].strip(" :\n")
            newline_idx = after.find("\n")
            if newline_idx != -1:
                after = after[:newline_idx].strip()
            return after, text.strip()

        return text.strip(), text.strip()

    def answer(self, question: str, paragraphs: List[Paragraph]) -> QAResult:
        cfg = self.config

        if cfg.use_cot_reader:
            prompt = build_reader_prompt_cot(
                demos=self.demos,
                retrieved_paragraphs=paragraphs,
                question=question,
                config=cfg,
            )
        else:
            prompt = build_reader_prompt_direct(
                demos=self.demos,
                retrieved_paragraphs=paragraphs,
                question=question,
                config=cfg,
            )

        llm_out = self.llm.generate(
            prompt=prompt,
            max_new_tokens=cfg.max_new_tokens_reader,
            temperature=cfg.temperature,
            stop=None,
        )
        ans, cot = self._extract_answer_from_text(llm_out)
        return QAResult(answer=ans, cot=cot)

