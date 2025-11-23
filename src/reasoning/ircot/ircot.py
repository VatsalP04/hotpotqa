from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set

from .config import IRCoTConfig
from .llm_client import LLMClient
from .prompts import CoTDemo, build_ircot_reason_prompt
from .retriever import Paragraph, TfidfRetriever


@dataclass
class IRCoTResult:
    """Result of running IRCoT on a single question."""

    question: str
    cot_steps: List[str]
    retrieved_paragraphs: List[Paragraph]


class IRCoTRetriever:
    """
    IRCoT: Interleaving Retrieval with Chain-of-Thought Reasoning.
    """

    def __init__(
        self,
        retriever: TfidfRetriever,
        llm: LLMClient,
        demos: List[CoTDemo],
        config: IRCoTConfig,
    ):
        self.retriever = retriever
        self.llm = llm
        self.demos = demos
        self.config = config

    def _get_first_sentence(self, text: str) -> str:
        """
        Only keep the first sentence from the LLM output for this step.
        """

        for delim in [".", "?", "!"]:
            idx = text.find(delim)
            if idx != -1:
                return text[: idx + 1].strip()
        return text.strip()

    def run(self, question: str) -> IRCoTResult:
        cfg = self.config

        retrieved: List[Paragraph] = self.retriever.retrieve(question, cfg.k_step)
        retrieved_ids: Set[int] = {p.pid for p in retrieved}
        cot_steps: List[str] = []
        step = 0

        while True:
            step += 1

            if len(retrieved) >= cfg.max_paragraphs:
                break
            if step > cfg.max_steps:
                break

            current_cot = " ".join(cot_steps)

            prompt = build_ircot_reason_prompt(
                demos=self.demos,
                retrieved_paragraphs=retrieved,
                question=question,
                current_cot=current_cot,
                config=cfg,
            )

            llm_out = self.llm.generate(
                prompt=prompt,
                max_new_tokens=cfg.max_new_tokens_reason,
                temperature=cfg.temperature,
                stop=None,
            )

            next_sentence = self._get_first_sentence(llm_out)
            if not next_sentence:
                break

            cot_steps.append(next_sentence)
            full_cot = " ".join(cot_steps)

            if cfg.answer_trigger in full_cot.lower():
                break

            new_paragraphs = self.retriever.retrieve(next_sentence, cfg.k_step)
            added_any = False

            for p in new_paragraphs:
                if p.pid not in retrieved_ids:
                    retrieved.append(p)
                    retrieved_ids.add(p.pid)
                    added_any = True

                    if len(retrieved) >= cfg.max_paragraphs:
                        break

            if not added_any:
                break

            if len(retrieved) >= cfg.max_paragraphs:
                break

        return IRCoTResult(
            question=question,
            cot_steps=cot_steps,
            retrieved_paragraphs=retrieved,
        )

