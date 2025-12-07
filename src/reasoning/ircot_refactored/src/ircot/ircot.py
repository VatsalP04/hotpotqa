"""
IRCoT System - Core Implementation.

This module implements the IRCoT (Interleaved Retrieval with Chain-of-Thought)
algorithm from Trivedi et al. (2023).

The system alternates between:
1. Generating Chain-of-Thought reasoning steps
2. Retrieving relevant documents based on reasoning

This interleaving allows the model to discover new information needed for
multi-hop questions, rather than retrieving all documents upfront.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .answer_extraction import AnswerExtractor, SentenceExtractor
from .config import IRCoTConfig, AnswerMarkers
from .embeddings import CachedEmbeddings, MistralEmbeddings
from .llm_client import LLMClient, MistralLLMClient, create_llm_client
from .prompts import build_reason_prompt, build_qa_prompt, get_system_instruction, get_qa_reader_system_instruction
from .retriever import DenseRetriever, IRCoTRetriever
from .types import (
    Context,
    CoTDemo,
    IRCoTResult,
    Paragraph,
    QAResult,
    ReasoningStep,
)

logger = logging.getLogger(__name__)


@dataclass
class SystemStats:
    """Tracks API usage statistics."""
    llm_calls: int = 0
    embedding_calls: int = 0
    total_tokens: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "llm_calls": self.llm_calls,
            "embedding_calls": self.embedding_calls,
            "total_tokens": self.total_tokens,
        }


class IRCoTSystem:
    """
    IRCoT System for multi-hop question answering.
    
    Implements the interleaved retrieval with Chain-of-Thought reasoning
    approach for answering complex questions.
    
    Algorithm:
    1. Initial retrieval: Use question to retrieve K paragraphs
    2. Loop:
        a. Generate next CoT sentence using question + paragraphs + previous CoT
        b. Check if answer is found (termination)
        c. If not terminated, use CoT sentence to retrieve more paragraphs
    3. Return answer extracted from CoT
    
    Example:
        system = IRCoTSystem(config, demos)
        result = system.answer(question, context)
        print(result.answer)
    """
    
    def __init__(
        self,
        config: IRCoTConfig,
        demos: List[CoTDemo],
        llm: Optional[LLMClient] = None,
        retriever: Optional[IRCoTRetriever] = None,
    ):
        """
        Initialize IRCoT system.
        
        Args:
            config: System configuration
            demos: Few-shot demonstrations
            llm: Optional LLM client (creates default if not provided)
            retriever: Optional retriever (creates default if not provided)
        """
        self.config = config
        self.demos = demos[:config.num_few_shot_examples]
        
        # Initialize LLM
        if llm is not None:
            self.llm = llm
        else:
            system_instruction = get_system_instruction() if config.use_system_instruction else None
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
        
        # Initialize QA Reader with separate LLM client (different system instruction)
        qa_system_instruction = get_qa_reader_system_instruction() if config.use_system_instruction else None
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
        """
        Answer using interleaved retrieval and CoT.
        
        This is the main IRCoT algorithm.
        """
        reasoning_steps = []
        cumulative_cot = ""
        
        # Step 1: Initial retrieval using question
        initial_paragraphs = self.retriever.initial_retrieve(
            question,
            k=self.config.initial_retrieval_k
        )
        
        logger.debug(f"Initial retrieval: {len(initial_paragraphs)} paragraphs")
        
        # Record initial step
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
            
            # Check capacity
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
            
            # Update cumulative CoT
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
                k=self.config.step_retrieval_k,
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
        
        # Stage 2: Use QA Reader to generate final answer from all retrieved paragraphs
        # QA Reader sees: demos, all retrieved paragraphs, question
        # QA Reader does NOT see: the interleaved CoT (generates its own)
        all_paragraphs = self.retriever.paragraphs
        qa_result = self.qa_reader.answer(question=question, paragraphs=all_paragraphs)
        
        # Use QA Reader's answer and CoT as the final result
        final_answer = qa_result.answer
        final_cot = qa_result.cot
        
        # If QA Reader didn't produce an answer, fallback to extraction from interleaved CoT
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
        """
        Answer using one-step retrieval (baseline).
        
        Retrieves all paragraphs at once, then uses QA Reader to generate complete CoT.
        """
        # Single retrieval step
        paragraphs = self.retriever.initial_retrieve(
            question,
            k=self.config.max_total_paragraphs
        )
        
        # Stage 2: Use QA Reader to generate final answer from all paragraphs
        # QA Reader sees: demos, all paragraphs, question
        # QA Reader does NOT see: any previous CoT (generates its own)
        qa_result = self.qa_reader.answer(question=question, paragraphs=paragraphs)
        
        # Use QA Reader's answer and CoT
        final_answer = qa_result.answer
        final_cot = qa_result.cot
        
        # If QA Reader didn't produce an answer, fallback to direct generation
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
        """
        Generate the next CoT reasoning sentence.
        
        Args:
            question: The question
            paragraphs: Current retrieved paragraphs
            previous_cot: Previously generated CoT
            
        Returns:
            Next CoT sentence (new, not repeated)
        """
        prompt = build_reason_prompt(
            demos=self.demos,
            paragraphs=paragraphs,
            question=question,
            current_cot=previous_cot,
            num_examples=self.config.num_few_shot_examples,
            include_instruction=self.config.use_system_instruction
        )
        
        response = self._generate(prompt, self.config.step_max_tokens)
        
        # Extract next NEW sentence
        return SentenceExtractor.get_next_sentence(response, previous_cot)
    
    def _generate_full_cot(
        self,
        question: str,
        paragraphs: List[Paragraph]
    ) -> str:
        """Generate complete CoT at once."""
        prompt = build_reason_prompt(
            demos=self.demos,
            paragraphs=paragraphs,
            question=question,
            current_cot="",
            num_examples=self.config.num_few_shot_examples,
            include_instruction=self.config.use_system_instruction
        )
        
        return self._generate(prompt, self.config.max_tokens)
    
    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Generate text using LLM."""
        self._stats.llm_calls += 1
        
        return self.llm.generate(
            prompt=prompt,
            max_new_tokens=max_tokens,
            temperature=self.config.temperature
        )
    
    @property
    def stats(self) -> Dict:
        """Get system statistics."""
        qa_stats = {"call_count": self.qa_reader.call_count}
        return {
            **self._stats.to_dict(),
            "qa_reader_calls": qa_stats["call_count"]
        }
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = SystemStats()


class QAReader:
    """
    QA Reader for final answer generation.
    
    Takes all retrieved paragraphs and generates a comprehensive
    final answer using Chain-of-Thought reasoning.
    """
    
    def __init__(
        self,
        config: IRCoTConfig,
        demos: List[CoTDemo],
        llm: LLMClient
    ):
        """
        Initialize QA Reader.
        
        Args:
            config: Configuration
            demos: Few-shot demonstrations
            llm: LLM client
        """
        self.config = config
        self.demos = demos[:config.num_few_shot_examples]
        self.llm = llm
        self._call_count = 0
    
    def answer(
        self,
        question: str,
        paragraphs: List[Paragraph]
    ) -> QAResult:
        """
        Generate final answer from paragraphs.
        
        Args:
            question: The question
            paragraphs: All retrieved paragraphs
            
        Returns:
            QAResult with answer and CoT
        """
        # Limit paragraphs
        max_paras = self.config.max_total_paragraphs
        if len(paragraphs) > max_paras:
            logger.warning(f"Limiting paragraphs from {len(paragraphs)} to {max_paras}")
            paragraphs = paragraphs[:max_paras]
        
        # Build prompt
        prompt = build_qa_prompt(
            demos=self.demos,
            paragraphs=paragraphs,
            question=question,
            num_examples=self.config.num_few_shot_examples,
            include_instruction=self.config.use_system_instruction
        )
        
        # Generate
        self._call_count += 1
        response = self.llm.generate(
            prompt=prompt,
            max_new_tokens=self.config.max_tokens,
            temperature=self.config.temperature
        )
        
        # Extract answer
        result = AnswerExtractor.extract(response)
        
        return QAResult(
            answer=result.answer,
            cot=result.full_cot
        )
    
    @property
    def call_count(self) -> int:
        return self._call_count


class IRCoTQA:
    """
    High-level IRCoT Question Answering pipeline.
    
    Provides a simple interface for answering questions with
    optional batch processing and result formatting.
    """
    
    def __init__(
        self,
        config: Optional[IRCoTConfig] = None,
        demos: Optional[List[CoTDemo]] = None
    ):
        """
        Initialize QA pipeline.
        
        Args:
            config: Configuration (uses defaults if not provided)
            demos: Few-shot demonstrations (loads defaults if not provided)
        """
        from .demo_loader import load_default_demos
        
        self.config = config or IRCoTConfig()
        
        if demos is None:
            demos = load_default_demos(self.config.num_few_shot_examples)
        
        self.system = IRCoTSystem(self.config, demos)
    
    def answer(
        self,
        question: str,
        context: Context,
        use_ircot: bool = True
    ) -> Dict:
        """
        Answer a question.
        
        Args:
            question: Question to answer
            context: HotpotQA context
            use_ircot: Use IRCoT (True) or baseline (False)
            
        Returns:
            Dictionary with answer and metadata
        """
        result = self.system.answer(
            question=question,
            context=context,
            use_interleaved=use_ircot
        )
        
        return {
            "answer": result.answer,
            "reasoning": result.reasoning_chain,
            "num_steps": result.num_steps,
            "num_paragraphs": len(result.retrieved_paragraphs),
            "terminated_by_answer": result.terminated_by_answer,
            "processing_time": result.processing_time,
            "full_result": result.to_dict()
        }
    
    def batch_answer(
        self,
        questions: List[Dict],
        use_ircot: bool = True,
        verbose: bool = True
    ) -> List[Dict]:
        """
        Answer multiple questions.
        
        Args:
            questions: List of dicts with 'question' and 'context'
            use_ircot: Use IRCoT or baseline
            verbose: Log progress
            
        Returns:
            List of answer dictionaries
        """
        results = []
        total = len(questions)
        
        for i, q in enumerate(questions):
            if verbose:
                logger.info(f"Processing question {i + 1}/{total}")
            
            try:
                result = self.answer(
                    question=q["question"],
                    context=q["context"],
                    use_ircot=use_ircot
                )
                result["_id"] = q.get("_id", str(i))
                result["gold_answer"] = q.get("answer", "")
                results.append(result)
                
            except Exception as e:
                logger.error(f"Error processing question {i}: {e}")
                results.append({
                    "_id": q.get("_id", str(i)),
                    "answer": "",
                    "error": str(e),
                    "gold_answer": q.get("answer", "")
                })
        
        return results
    
    @property
    def stats(self) -> Dict:
        """Get system statistics."""
        return self.system.stats
