"""
IRCoT System - Core Implementation.

Implements the IRCoT (Interleaved Retrieval with Chain-of-Thought)
algorithm from Trivedi et al. (2023).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.reasoning.core.types import (
    Context,
    CoTDemo,
    IRCoTResult,
    Paragraph,
    ReasoningStep,
)
from src.reasoning.core.llm import LLMClient, create_llm_client
from src.reasoning.core.embeddings import MistralEmbeddings, CachedEmbeddings
from src.reasoning.core.retriever import DenseRetriever, IRCoTRetriever
from src.reasoning.prompts import ircot as ircot_prompts

from .config import IRCoTConfig
from .answer_extraction import AnswerExtractor, SentenceExtractor

logger = logging.getLogger(__name__)


@dataclass
class SystemStats:
    """Tracks API usage statistics."""
    llm_calls: int = 0
    embedding_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.embedding_tokens
    
    def to_dict(self) -> Dict:
        return {
            "llm_calls": self.llm_calls,
            "embedding_calls": self.embedding_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "embedding_tokens": self.embedding_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class QAResult:
    """Result from QA Reader."""
    answer: str
    cot: str


class IRCoTSystem:
    """
    IRCoT System for multi-hop question answering.
    
    Algorithm:
    1. Initial retrieval: Use question to retrieve K paragraphs
    2. Loop:
        a. Generate next CoT sentence
        b. Check if answer is found (termination)
        c. If not terminated, use CoT sentence to retrieve more paragraphs
    3. Return answer extracted from CoT
    """
    
    def __init__(
        self,
        config: IRCoTConfig,
        demos: List[CoTDemo],
        llm: Optional[LLMClient] = None,
        retriever: Optional[IRCoTRetriever] = None,
    ):
        self.config = config
        self.demos = demos[:config.num_few_shot_examples]
        
        # Initialize LLM
        if llm is not None:
            self.llm = llm
        else:
            system_instruction = ircot_prompts.get_system_instruction() if config.use_system_instruction else None
            self.llm = create_llm_client(
                api_key=config.mistral_api_key,
                model=config.mistral_model,
                system_instruction=system_instruction
            )
        
        # Initialize retriever
        if retriever is not None:
            self.retriever = retriever
        else:
            embeddings = MistralEmbeddings(
                api_key=config.mistral_api_key,
                model=config.mistral_embed_model
            )
            cached_embeddings = CachedEmbeddings(embeddings)
            base_retriever = DenseRetriever(cached_embeddings)
            self.retriever = IRCoTRetriever(base_retriever, config.max_total_paragraphs)
        
        # Initialize QA Reader with separate LLM client
        qa_system_instruction = ircot_prompts.get_qa_reader_system_instruction() if config.use_system_instruction else None
        qa_llm = create_llm_client(
            api_key=config.mistral_api_key,
            model=config.mistral_model,
            system_instruction=qa_system_instruction
        )
        self.qa_reader = QAReader(config, self.demos, qa_llm)
        
        self._stats = SystemStats()
        
        logger.info(f"IRCoT system initialized with {len(self.demos)} demonstrations")
    
    def answer(
        self,
        question: str,
        context: Context,
        use_interleaved: bool = True
    ) -> IRCoTResult:
        """
        Answer a question using IRCoT.
        
        Args:
            question: The question to answer
            context: HotpotQA context [(title, sentences), ...]
            use_interleaved: Use interleaved retrieval (True) or one-step (False)
        
        Returns:
            IRCoTResult with answer and reasoning trace
        """
        start_time = time.time()
        
        # Index context for retrieval
        self.retriever.index(context)
        
        # Run appropriate algorithm
        if use_interleaved:
            result = self._answer_interleaved(question)
        else:
            result = self._answer_one_step(question)
        
        result.processing_time = time.time() - start_time
        return result
    
    def _answer_interleaved(self, question: str) -> IRCoTResult:
        """Answer using interleaved retrieval and CoT."""
        reasoning_steps = []
        cumulative_cot = ""
        
        # Step 1: Initial retrieval using question
        initial_paragraphs = self.retriever.initial_retrieve(
            question,
            k=self.config.paragraphs_per_retrieval
        )
        
        logger.debug(f"Initial retrieval: {len(initial_paragraphs)} paragraphs")
        
        reasoning_steps.append(ReasoningStep(
            step_number=0,
            cot_sentence="[Initial retrieval]",
            retrieved_paragraphs=list(initial_paragraphs),
            cumulative_cot="",
            retrieval_query=question
        ))
        
        # Iterative reasoning and retrieval
        terminated = False
        extracted_answer = ""
        
        for step in range(1, self.config.max_reasoning_steps + 1):
            current_paragraphs = self.retriever.paragraphs
            
            if self.retriever.at_capacity:
                logger.debug("Max paragraphs reached")
                break
            
            # Generate next CoT sentence
            cot_sentence = self._generate_cot_step(
                question=question,
                paragraphs=current_paragraphs,
                previous_cot=cumulative_cot
            )
            
            if not cot_sentence:
                logger.debug("Empty CoT sentence, stopping")
                break
            
            cumulative_cot = f"{cumulative_cot} {cot_sentence}".strip()
            
            logger.debug(f"Step {step} CoT: {cot_sentence[:100]}...")
            
            # Check for answer
            if not extracted_answer:
                result = AnswerExtractor.extract(cumulative_cot)
                if result.found:
                    extracted_answer = result.answer
            
            # Check termination
            if AnswerExtractor.contains_answer_marker(cumulative_cot):
                terminated = True
                reasoning_steps.append(ReasoningStep(
                    step_number=step,
                    cot_sentence=cot_sentence,
                    retrieved_paragraphs=[],
                    cumulative_cot=cumulative_cot,
                    retrieval_query=""
                ))
                logger.debug(f"Terminated at step {step}")
                break
            
            # Retrieve more paragraphs
            new_paragraphs = self.retriever.step_retrieve(
                cot_sentence,
                k=1,
                step_number=step
            )
            
            logger.debug(f"Step {step}: {len(new_paragraphs)} new paragraphs")
            
            reasoning_steps.append(ReasoningStep(
                step_number=step,
                cot_sentence=cot_sentence,
                retrieved_paragraphs=new_paragraphs,
                cumulative_cot=cumulative_cot,
                retrieval_query=cot_sentence
            ))
            
            if not new_paragraphs:
                logger.debug("No new paragraphs, stopping")
                break
        
        # Stage 2: Use QA Reader for final answer
        all_paragraphs = self.retriever.paragraphs
        qa_result = self.qa_reader.answer(
            question=question,
            paragraphs=all_paragraphs,
            interleaved_cot=cumulative_cot if cumulative_cot.strip() else None
        )
        
        final_answer = qa_result.answer
        final_cot = qa_result.cot
        
        # Fallback to extraction from interleaved CoT
        if not final_answer:
            if not extracted_answer:
                result = AnswerExtractor.extract(cumulative_cot)
                extracted_answer = result.answer
            final_answer = extracted_answer
            final_cot = cumulative_cot
        
        return IRCoTResult(
            question=question,
            answer=final_answer,
            reasoning_chain=final_cot,
            reasoning_steps=reasoning_steps,
            retrieved_paragraphs=all_paragraphs,
            num_steps=len(reasoning_steps),
            terminated_by_answer=terminated
        )
    
    def _answer_one_step(self, question: str) -> IRCoTResult:
        """Answer using one-step retrieval (baseline)."""
        paragraphs = self.retriever.initial_retrieve(
            question,
            k=self.config.max_total_paragraphs
        )
        
        qa_result = self.qa_reader.answer(question=question, paragraphs=paragraphs)
        
        final_answer = qa_result.answer
        final_cot = qa_result.cot
        
        if not final_answer:
            cot = self._generate_full_cot(question, paragraphs)
            result = AnswerExtractor.extract(cot)
            final_answer = result.answer
            final_cot = cot
        
        reasoning_step = ReasoningStep(
            step_number=1,
            cot_sentence=final_cot,
            retrieved_paragraphs=paragraphs,
            cumulative_cot=final_cot,
            retrieval_query=question
        )
        
        return IRCoTResult(
            question=question,
            answer=final_answer,
            reasoning_chain=final_cot,
            reasoning_steps=[reasoning_step],
            retrieved_paragraphs=paragraphs,
            num_steps=1,
            terminated_by_answer=AnswerExtractor.contains_answer_marker(final_cot)
        )
    
    def _generate_cot_step(
        self,
        question: str,
        paragraphs: List[Paragraph],
        previous_cot: str
    ) -> str:
        """Generate the next CoT reasoning sentence."""
        prompt = ircot_prompts.build_reason_prompt(
            demos=self.demos,
            paragraphs=paragraphs,
            question=question,
            current_cot=previous_cot,
            num_examples=self.config.num_few_shot_examples,
            include_instruction=self.config.use_system_instruction
        )
        
        response = self._generate(prompt, self.config.max_tokens_step)
        
        return SentenceExtractor.get_next_sentence(response, previous_cot)
    
    def _generate_full_cot(
        self,
        question: str,
        paragraphs: List[Paragraph]
    ) -> str:
        """Generate complete CoT at once."""
        prompt = ircot_prompts.build_reason_prompt(
            demos=self.demos,
            paragraphs=paragraphs,
            question=question,
            current_cot="",
            num_examples=self.config.num_few_shot_examples,
            include_instruction=self.config.use_system_instruction
        )
        
        return self._generate(prompt, self.config.max_tokens_qa)
    
    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Generate text using LLM."""
        self._stats.llm_calls += 1
        
        result = self.llm.generate(
            prompt=prompt,
            max_new_tokens=max_tokens,
            temperature=self.config.temperature
        )
        
        return result
    
    @property
    def stats(self) -> Dict:
        """Get system statistics."""
        qa_stats = {"call_count": self.qa_reader.call_count}
        
        main_llm_usage = {}
        qa_llm_usage = {}
        
        if hasattr(self.llm, 'get_usage_stats'):
            main_llm_usage = self.llm.get_usage_stats()
        if hasattr(self.qa_reader.llm, 'get_usage_stats'):
            qa_llm_usage = self.qa_reader.llm.get_usage_stats()
        
        combined_input = main_llm_usage.get('input_tokens', 0) + qa_llm_usage.get('input_tokens', 0)
        combined_output = main_llm_usage.get('output_tokens', 0) + qa_llm_usage.get('output_tokens', 0)
        
        stats_dict = self._stats.to_dict()
        stats_dict['input_tokens'] = combined_input
        stats_dict['output_tokens'] = combined_output
        stats_dict['total_tokens'] = combined_input + combined_output + stats_dict.get('embedding_tokens', 0)
        
        return {
            **stats_dict,
            "qa_reader_calls": qa_stats["call_count"]
        }
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = SystemStats()


class QAReader:
    """QA Reader for final answer generation."""
    
    def __init__(
        self,
        config: IRCoTConfig,
        demos: List[CoTDemo],
        llm: LLMClient
    ):
        self.config = config
        self.demos = demos[:config.num_few_shot_examples]
        self.llm = llm
        self._call_count = 0
    
    def answer(
        self,
        question: str,
        paragraphs: List[Paragraph],
        interleaved_cot: Optional[str] = None
    ) -> QAResult:
        """Generate final answer from paragraphs.
        
        Args:
            question: The question to answer
            paragraphs: Retrieved paragraphs
            interleaved_cot: Optional CoT from interleaved reasoning steps.
                           If provided, the reader will extract answer from it
                           if found, otherwise generate new reasoning.
        """
        max_paras = self.config.max_total_paragraphs
        if len(paragraphs) > max_paras:
            logger.warning(f"Limiting paragraphs from {len(paragraphs)} to {max_paras}")
            paragraphs = paragraphs[:max_paras]
        
        prompt = ircot_prompts.build_qa_prompt(
            demos=self.demos,
            paragraphs=paragraphs,
            question=question,
            num_examples=self.config.num_few_shot_examples,
            include_instruction=self.config.use_system_instruction,
            interleaved_cot=interleaved_cot
        )
        
        self._call_count += 1
        
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens_qa,
            temperature=self.config.temperature
        )
        
        result = AnswerExtractor.extract(response)
        
        return QAResult(
            answer=result.answer,
            cot=result.full_cot
        )
    
    @property
    def call_count(self) -> int:
        return self._call_count

