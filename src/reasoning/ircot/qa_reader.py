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
    Separate reader module, as in the IRCoT paper.
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

