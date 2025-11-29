"""
IRCoT Core Algorithm Implementation

This module implements the core IRCoT (Interleaving Retrieval with Chain-of-Thought) 
algorithm as described in the ACL 2023 paper. IRCoT addresses multi-hop question 
answering by iteratively retrieving documents and generating reasoning steps.

The Algorithm:
1. Initial Retrieval: Retrieve k documents based on the question
2. Reasoning Loop:
   a. Build prompt with few-shot demos + retrieved docs + partial reasoning
   b. Generate next reasoning step (single sentence)
   c. Check stopping conditions (answer trigger or limits reached)
   d. Retrieve additional documents based on the new reasoning step
   e. Add unique documents to context and repeat

Key Classes:
- IRCoTRetriever: Main class implementing the iterative retrieval loop
- IRCoTResult: Container for the final results (question, reasoning steps, documents)

The implementation follows the paper's methodology exactly:
- Single-sentence extraction per reasoning step
- Deduplication of retrieved documents
- Configurable stopping conditions
- Few-shot prompting with official demonstrations

This approach significantly outperforms standard retrieve-then-read methods on 
multi-hop questions by allowing the retrieval to be guided by intermediate reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set

from .config import IRCoTConfig
from .llm_client import LLMClient
from .prompts import CoTDemo, build_ircot_reason_prompt
from .retriever import Paragraph, Retriever


@dataclass
class IRCoTResult:
    """Result of running IRCoT on a single question."""

    question: str
    cot_steps: List[str]
    retrieved_paragraphs: List[Paragraph]


class IRCoTRetriever:
    """
    IRCoT: Interleaving Retrieval with Chain-of-Thought Reasoning.
    
    This class implements the core IRCoT algorithm that iteratively retrieves 
    documents and generates reasoning steps for multi-hop question answering.
    
    The algorithm works by:
    1. Starting with initial retrieval based on the question
    2. Generating reasoning steps one sentence at a time using few-shot prompts
    3. Using each reasoning step to retrieve additional relevant documents
    4. Continuing until a stopping condition is met (answer found or limits reached)
    
    This approach allows the retrieval to be dynamically guided by the evolving
    reasoning chain, leading to better performance on complex multi-hop questions.
    
    Args:
        retriever: Document retriever (e.g., FAISS-based dense retriever)
        llm: Language model for generating reasoning steps
        demos: Few-shot demonstrations for in-context learning
        config: Configuration parameters for the algorithm
    """

    def __init__(
        self,
        retriever: Retriever,
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

