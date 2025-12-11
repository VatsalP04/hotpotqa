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
        
        metadata = {"step": "planning", "main_question": main_question[:100]}
        tags = ["decomposition", "planning"]
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=300,
            temperature=temp,
            stop=None,
            run_name="decomposition_planning",
            metadata=metadata,
            tags=tags,
        )
        
        questions = []
        lines = response.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            cleaned = re.sub(r'^[\d]+[.\)]\s*', '', line)
            cleaned = re.sub(r'^[-•]\s*', '', cleaned)
            cleaned = cleaned.strip()
            
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
        is_reattempt: bool = False,
    ) -> str:
        """Answer a sub-question using retrieved paragraphs."""
        temp = temperature if temperature is not None else self.config.temperature
        para_texts = []
        for p in paragraphs:
            para_texts.append(f"{p.title}: {p.text}")
        
        prompt = decomp_prompts.build_subanswer_prompt(sub_question, para_texts)
        
        metadata = {
            "step": "sub_answer",
            "sub_question": sub_question[:100],
            "num_paragraphs": len(paragraphs),
            "is_reattempt": is_reattempt,
        }
        tags = ["decomposition", "sub_answer"]
        if is_reattempt:
            tags.append("reattempt")
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_suba,
            temperature=temp,
            stop=["\n"],
            run_name="decomposition_sub_answer",
            metadata=metadata,
            tags=tags,
        )
        
        answer = response.strip()
        for prefix in ["Answer:", "A:"]:
            if answer.lower().startswith(prefix.lower()):
                answer = answer[len(prefix):].strip()
        
        return answer
    
    def _answer_subquestion_forced(
        self,
        sub_question: str,
        paragraphs: List,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Answer a sub-question but force an answer (no NOT_FOUND escape).
        Used after a reattempt still returns NOT_FOUND.
        """
        temp = temperature if temperature is not None else self.config.temperature
        para_texts = []
        for p in paragraphs:
            para_texts.append(f"{p.title}: {p.text}")
        
        prompt = decomp_prompts.build_forced_subanswer_prompt(sub_question, para_texts)
        
        metadata = {
            "step": "sub_answer_forced",
            "sub_question": sub_question[:100],
            "num_paragraphs": len(paragraphs),
        }
        tags = ["decomposition", "sub_answer", "forced"]
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_suba,
            temperature=temp,
            stop=["\n"],
            run_name="decomposition_sub_answer_forced",
            metadata=metadata,
            tags=tags,
        )
        
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
        
        metadata = {
            "step": "final_answer",
            "main_question": main_question[:100],
            "num_sub_questions": len(sub_qa_history),
        }
        tags = ["decomposition", "final_answer"]
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_final,
            temperature=temp,
            stop=["\n"],
            run_name="decomposition_final_answer",
            metadata=metadata,
            tags=tags,
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
        
        metadata = {
            "step": "query_rewrite",
            "main_question": main_question[:100],
            "failed_sub_question": failed_sub_question[:100],
            "num_previous_answers": len(previous_answers),
        }
        tags = ["decomposition", "query_rewrite", "fallback"]
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=64,
            temperature=0.3,
            stop=["\n"],
            run_name="decomposition_query_rewrite",
            metadata=metadata,
            tags=tags,
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
            
            if cfg.use_relaxed_prompt_initial:
                sub_answer = self._answer_subquestion_forced(filled_question, paragraphs, temperature=temp)
            else:
                sub_answer = self._answer_subquestion(filled_question, paragraphs, temperature=temp, is_reattempt=False)
            
            initial_answer = sub_answer
            initial_retrieved = retrieved_titles.copy()
            
            reattempt_query = None
            reattempt_answer = None
            reattempt_retrieved = []
            
            if not cfg.use_relaxed_prompt_initial and self._is_not_found(sub_answer):
                if cfg.enable_search_query_fallback:
                    rewrite_query = self._generate_search_query(question, filled_question, sub_qa_history)
                    if rewrite_query:
                        query_history.append(rewrite_query)
                        reattempt_query = rewrite_query
                        fallback_paragraphs = self.retriever.retrieve(
                            rewrite_query,
                            max(cfg.k_retrieve + 1, cfg.k_retrieve)
                        )
                        if fallback_paragraphs:
                            fallback_titles = [p.title for p in fallback_paragraphs]
                            all_retrieved_titles.extend(fallback_titles)
                            reattempt_retrieved = fallback_titles.copy()
                            alt_answer = self._answer_subquestion(filled_question, fallback_paragraphs, temperature=temp, is_reattempt=True)
                            reattempt_answer = alt_answer
                            if not self._is_not_found(alt_answer):
                                paragraphs = fallback_paragraphs
                                retrieved_titles = fallback_titles
                                sub_answer = alt_answer
                            elif cfg.enable_relaxed_prompt_fallback:
                                forced_answer = self._answer_subquestion_forced(filled_question, fallback_paragraphs, temperature=temp)
                                reattempt_answer = forced_answer
                                paragraphs = fallback_paragraphs
                                retrieved_titles = fallback_titles
                                sub_answer = forced_answer
                elif cfg.enable_relaxed_prompt_fallback:
                    forced_answer = self._answer_subquestion_forced(filled_question, paragraphs, temperature=temp)
                    reattempt_answer = forced_answer
                    sub_answer = forced_answer
            
            answers_so_far.append(sub_answer)
            
            paragraphs_texts = [f"{p.title}: {p.text}" for p in paragraphs]
            
            sub_qa = SubQA(
                question=filled_question,
                answer=sub_answer,
                retrieved_titles=retrieved_titles,
                retrieved_paragraphs=paragraphs_texts,
                search_queries=query_history,
                initial_answer=initial_answer if self._is_not_found(initial_answer) else None,
                reattempt_query=reattempt_query,
                reattempt_answer=reattempt_answer,
                reattempt_retrieved_titles=reattempt_retrieved,
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
        """Run with self-consistency voting.
        
        Runs the decomposition multiple times with different temperatures
        and returns the most common answer (majority voting).
        """
        cfg = self.config
        num_samples = cfg.self_consistency_num_samples
        
        if num_samples < 1:
            raise ValueError("self_consistency_num_samples must be at least 1")
        
        temperatures = cfg.self_consistency_temperatures or [cfg.temperature]
        
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

