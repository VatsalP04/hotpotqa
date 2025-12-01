from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Protocol

from .config import DecompositionConfig
from .prompts import (
    build_planning_prompt,
    build_subanswer_prompt,
    build_final_answer_prompt,
)


@dataclass
class SubQA:
    question: str
    answer: str
    retrieved_titles: List[str] = field(default_factory=list)


@dataclass
class DecompositionResult:
    main_question: str
    planned_questions: List[str]  # Original templates with placeholders
    sub_qas: List[SubQA]          # Executed questions with answers
    final_answer: str
    all_retrieved_titles: List[str] = field(default_factory=list)


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
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        config: DecompositionConfig,
    ):
        self.retriever = retriever
        self.llm = llm
        self.config = config
    
    def _plan_subquestions(self, main_question: str) -> List[str]:
        prompt = build_planning_prompt(main_question)
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=300,
            temperature=self.config.temperature,
            stop=None,
        )
        
        # Parse numbered questions from response
        questions = []
        lines = response.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Match patterns like "1. Question?" or "1) Question?" or just "Question?"
            # Remove leading numbers/bullets
            cleaned = re.sub(r'^[\d]+[.\)]\s*', '', line)
            cleaned = re.sub(r'^[-•]\s*', '', cleaned)
            cleaned = cleaned.strip()
            
            # Skip if it's a label like "Sub-questions:" or empty after cleaning
            if cleaned and not cleaned.endswith(':') and len(cleaned) > 5:
                questions.append(cleaned)
        
        # Limit to max_sub_questions
        return questions[:self.config.max_sub_questions]
    
    def _fill_placeholders(self, question: str, answers: List[str]) -> str:
        result = question
        for i, answer in enumerate(answers, 1):
            placeholder = f"[ANSWER_{i}]"
            result = result.replace(placeholder, answer)
        return result
    
    def _answer_subquestion(
        self,
        sub_question: str,
        paragraphs: List,
    ) -> str:
        para_texts = []
        for p in paragraphs:
            para_texts.append(f"{p.title}: {p.text}")
        
        prompt = build_subanswer_prompt(sub_question, para_texts)
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_suba,
            temperature=self.config.temperature,
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
    ) -> str:
        prompt = build_final_answer_prompt(main_question, sub_qa_history)
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_final,
            temperature=self.config.temperature,
            stop=["\n"],
        )
        
        answer = response.strip()
        for prefix in ["Answer:", "A:"]:
            if answer.lower().startswith(prefix.lower()):
                answer = answer[len(prefix):].strip()
        
        return answer
    
    def run(self, question: str) -> DecompositionResult:
        cfg = self.config
        
        # Stage 1: Plan
        planned_questions = self._plan_subquestions(question)
        
        if not planned_questions:
            # Fallback: treat the main question as the only sub-question
            planned_questions = [question]
        
        # Stage 2: Execute
        sub_qas: List[SubQA] = []
        sub_qa_history: List[Tuple[str, str]] = []
        all_retrieved_titles: List[str] = []
        answers_so_far: List[str] = []
        
        for template in planned_questions:
            # Fill in placeholders from previous answers
            filled_question = self._fill_placeholders(template, answers_so_far)
            
            # Retrieve
            paragraphs = self.retriever.retrieve(filled_question, cfg.k_retrieve)
            retrieved_titles = [p.title for p in paragraphs]
            all_retrieved_titles.extend(retrieved_titles)
            
            # Answer
            sub_answer = self._answer_subquestion(filled_question, paragraphs)
            answers_so_far.append(sub_answer)
            
            # Store
            sub_qa = SubQA(
                question=filled_question,
                answer=sub_answer,
                retrieved_titles=retrieved_titles,
            )
            sub_qas.append(sub_qa)
            sub_qa_history.append((filled_question, sub_answer))
        
        # Final answer from sub-QA pairs only
        final_answer = self._generate_final_answer(question, sub_qa_history)
        
        return DecompositionResult(
            main_question=question,
            planned_questions=planned_questions,
            sub_qas=sub_qas,
            final_answer=final_answer,
            all_retrieved_titles=list(set(all_retrieved_titles)),
        )
