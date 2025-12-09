"""
Simple Chain-of-Thought Reasoner.

Baseline method: retrieve paragraphs once, then generate complete CoT reasoning.
"""

from __future__ import annotations

from typing import List, Protocol, Optional
from dataclasses import dataclass

from src.reasoning.core.types import Paragraph
from src.reasoning.prompts import simple_cot as simple_cot_prompts

from .config import SimpleCoTConfig


class Retriever(Protocol):
    def retrieve(self, query: str, k: int) -> List[Paragraph]:
        ...


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float,
        stop: Optional[List[str]] = None,
    ) -> str:
        ...


@dataclass
class SimpleCoTResult:
    """Result from SimpleCoT reasoning."""
    question: str
    answer: str
    reasoning_chain: str
    retrieved_paragraphs: List[Paragraph]
    retrieved_titles: List[str]


class SimpleCoTReasoner:
    """Simple Chain-of-Thought reasoning for multi-hop QA."""
    
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        config: SimpleCoTConfig,
    ):
        self.retriever = retriever
        self.llm = llm
        self.config = config
    
    def run(self, question: str) -> SimpleCoTResult:
        """
        Run SimpleCoT reasoning (two-step process).
        
        Steps:
        1. Retrieve paragraphs using the question
        2. Generate chain of thought from paragraphs and question
        3. Generate final answer from chain of thought
        """
        # Step 1: Retrieve paragraphs
        paragraphs = self.retriever.retrieve(question, self.config.k_retrieve)
        retrieved_titles = [p.title for p in paragraphs]
        
        # Step 2: Generate chain of thought
        cot_prompt = simple_cot_prompts.build_cot_prompt(paragraphs, question)
        
        chain_of_thought = self.llm.generate(
            prompt=cot_prompt,
            max_new_tokens=self.config.max_tokens_cot,
            temperature=self.config.temperature,
            stop=None,
        )
        chain_of_thought = chain_of_thought.strip()
        
        # Step 3: Generate final answer from chain of thought
        answer_prompt = simple_cot_prompts.build_answer_prompt(
            paragraphs, question, chain_of_thought
        )
        
        answer = self.llm.generate(
            prompt=answer_prompt,
            max_new_tokens=self.config.max_tokens_answer,
            temperature=self.config.temperature,
            stop=["\n"],
        )
        answer = answer.strip()
        
        # Clean up answer (remove prefixes if present)
        for prefix in ["Answer:", "A:"]:
            if answer.lower().startswith(prefix.lower()):
                answer = answer[len(prefix):].strip()
        
        # Build full reasoning chain (CoT + Answer)
        reasoning_chain = f"{chain_of_thought}\n\nAnswer: {answer}"
        
        return SimpleCoTResult(
            question=question,
            answer=answer,
            reasoning_chain=reasoning_chain,
            retrieved_paragraphs=paragraphs,
            retrieved_titles=retrieved_titles,
        )

