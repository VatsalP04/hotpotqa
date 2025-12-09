"""
Query Decomposition Reasoner.

Implements query decomposition for multi-hop QA.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Tuple, Protocol, Optional

from src.reasoning.core.types import SubQA, DecompositionResult
from src.reasoning.core.evaluation import normalize_answer
from src.reasoning.prompts import decomposition as decomp_prompts

from .config import DecompositionConfig


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int) -> List:
        ...


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float,
        stop: list | None = None,
    ) -> str:
        ...


class DecompositionReasoner:
    """Query decomposition for multi-hop QA."""
    
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        config: DecompositionConfig,
    ):
        self.retriever = retriever
        self.llm = llm
        self.config = config
    
    @staticmethod
    def _is_not_found(answer: str) -> bool:
        return answer.strip().upper() == "NOT_FOUND"
    
    def _plan_subquestions(self, main_question: str, temperature: Optional[float] = None) -> List[str]:
        """Generate sub-questions for the main question."""
        temp = temperature if temperature is not None else self.config.temperature
        prompt = decomp_prompts.build_planning_prompt(main_question)
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=300,
            temperature=temp,
            stop=None,
        )
        
        # Parse numbered questions from response
        questions = []
        lines = response.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Remove leading numbers/bullets
            cleaned = re.sub(r'^[\d]+[.\)]\s*', '', line)
            cleaned = re.sub(r'^[-•]\s*', '', cleaned)
            cleaned = cleaned.strip()
            
            # Skip labels like "Sub-questions:"
            if cleaned and not cleaned.endswith(':') and len(cleaned) > 5:
                questions.append(cleaned)
        
        return questions[:self.config.max_sub_questions]
    
    def _fill_placeholders(self, question: str, answers: List[str]) -> str:
        """Fill placeholders with previous answers."""
        result = question
        for i, answer in enumerate(answers, 1):
            placeholder = f"[ANSWER_{i}]"
            result = result.replace(placeholder, answer)
        return result
    
    def _answer_subquestion(
        self,
        sub_question: str,
        paragraphs: List,
        temperature: Optional[float] = None,
    ) -> str:
        """Answer a sub-question using retrieved paragraphs."""
        temp = temperature if temperature is not None else self.config.temperature
        para_texts = []
        for p in paragraphs:
            para_texts.append(f"{p.title}: {p.text}")
        
        prompt = decomp_prompts.build_subanswer_prompt(sub_question, para_texts)
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_suba,
            temperature=temp,
            stop=["\n"],
        )
        
        # Clean up
        answer = response.strip()
        for prefix in ["Answer:", "A:"]:
            if answer.lower().startswith(prefix.lower()):
                answer = answer[len(prefix):].strip()
        
        return answer
    
    def _generate_final_answer(
        self,
        main_question: str,
        sub_qa_history: List[Tuple[str, str]],
        temperature: Optional[float] = None,
    ) -> str:
        """Generate final answer from sub-QA history."""
        temp = temperature if temperature is not None else self.config.temperature
        prompt = decomp_prompts.build_final_answer_prompt(main_question, sub_qa_history)
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_final,
            temperature=temp,
            stop=["\n"],
        )
        
        answer = response.strip()
        for prefix in ["Answer:", "A:"]:
            if answer.lower().startswith(prefix.lower()):
                answer = answer[len(prefix):].strip()
        
        return answer
    
    def _generate_search_query(
        self,
        main_question: str,
        failed_sub_question: str,
        previous_answers: List[Tuple[str, str]],
    ) -> str:
        """Generate a search query for fallback retrieval."""
        prompt = decomp_prompts.build_query_rewrite_prompt(main_question, failed_sub_question, previous_answers)
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=64,
            temperature=0.3,
            stop=["\n"],
        )
        return response.strip()
    
    def _run_single(self, question: str, temperature: Optional[float] = None) -> DecompositionResult:
        """Run decomposition for a single question."""
        cfg = self.config
        temp = temperature if temperature is not None else cfg.temperature
        planned_questions = self._plan_subquestions(question, temperature=temp)
        
        if not planned_questions:
            planned_questions = [question]
        
        sub_qas: List[SubQA] = []
        sub_qa_history: List[Tuple[str, str]] = []
        all_retrieved_titles: List[str] = []
        answers_so_far: List[str] = []
        
        for template in planned_questions:
            filled_question = self._fill_placeholders(template, answers_so_far)
            
            query_history: List[str] = [filled_question]
            paragraphs = self.retriever.retrieve(filled_question, cfg.k_retrieve)
            retrieved_titles = [p.title for p in paragraphs]
            all_retrieved_titles.extend(retrieved_titles)
            
            sub_answer = self._answer_subquestion(filled_question, paragraphs, temperature=temp)
            
            # Fallback if not found
            if self._is_not_found(sub_answer):
                rewrite_query = self._generate_search_query(question, filled_question, sub_qa_history)
                if rewrite_query:
                    query_history.append(rewrite_query)
                    fallback_paragraphs = self.retriever.retrieve(
                        rewrite_query,
                        max(cfg.k_retrieve + 1, cfg.k_retrieve)
                    )
                    if fallback_paragraphs:
                        fallback_titles = [p.title for p in fallback_paragraphs]
                        all_retrieved_titles.extend(fallback_titles)
                        alt_answer = self._answer_subquestion(filled_question, fallback_paragraphs, temperature=temp)
                        if not self._is_not_found(alt_answer):
                            paragraphs = fallback_paragraphs
                            retrieved_titles = fallback_titles
                            sub_answer = alt_answer
            
            answers_so_far.append(sub_answer)
            
            paragraphs_texts = [f"{p.title}: {p.text}" for p in paragraphs]
            
            sub_qa = SubQA(
                question=filled_question,
                answer=sub_answer,
                retrieved_titles=retrieved_titles,
                retrieved_paragraphs=paragraphs_texts,
                search_queries=query_history,
            )
            sub_qas.append(sub_qa)
            sub_qa_history.append((filled_question, sub_answer))
        
        final_answer = self._generate_final_answer(question, sub_qa_history, temperature=temp)
        
        return DecompositionResult(
            main_question=question,
            planned_questions=planned_questions,
            sub_qas=sub_qas,
            final_answer=final_answer,
            all_retrieved_titles=list(set(all_retrieved_titles)),
        )
    
    def _run_with_self_consistency(self, question: str) -> DecompositionResult:
        """Run with self-consistency voting."""
        cfg = self.config
        allowed_samples = {1, 3, 5}
        num_samples = cfg.self_consistency_num_samples
        if num_samples not in allowed_samples:
            raise ValueError("self_consistency_num_samples must be one of {1, 3, 5}")
        
        temperatures = cfg.self_consistency_temperatures or [cfg.temperature]
        allowed_temps = {0.5, 0.6, 0.7}
        for temp in temperatures:
            if temp not in allowed_temps:
                raise ValueError("self_consistency_temperatures must be drawn from {0.5, 0.6, 0.7}")
        
        runs: List[Tuple[DecompositionResult, str]] = []
        for idx in range(num_samples):
            temp = temperatures[idx % len(temperatures)]
            result = self._run_single(question, temperature=temp)
            runs.append((result, normalize_answer(result.final_answer)))
        
        counts = Counter(norm for _, norm in runs)
        winning_norm, _ = counts.most_common(1)[0]
        
        for result, norm in runs:
            if norm == winning_norm:
                return result
        
        return runs[0][0]
    
    def run(self, question: str) -> DecompositionResult:
        """Run decomposition reasoning."""
        if self.config.self_consistency_enabled and self.config.self_consistency_num_samples > 1:
            return self._run_with_self_consistency(question)
        
        return self._run_single(question)

