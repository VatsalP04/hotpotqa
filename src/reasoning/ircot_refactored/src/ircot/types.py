"""
Core types and protocols for IRCoT system.

This module defines all data classes, protocols (interfaces), and type aliases
used throughout the IRCoT implementation. Centralizing types here ensures
consistency and makes the codebase easier to understand and maintain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set, Sequence, Protocol, runtime_checkable
import numpy as np


# =============================================================================
# Type Aliases
# =============================================================================

Context = List[Tuple[str, List[str]]]  # HotpotQA context format: [(title, sentences), ...]
SupportingFacts = List[Tuple[str, int]]  # [(title, sentence_idx), ...]


# =============================================================================
# Protocols (Interfaces)
# =============================================================================

@runtime_checkable
class LLMProtocol(Protocol):
    """Protocol for language model clients."""
    
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        """Generate text completion from a prompt."""
        ...


@runtime_checkable
class EmbeddingsProtocol(Protocol):
    """Protocol for embedding generators."""
    
    def embed_text(self, text: str) -> np.ndarray:
        """Generate embedding for a single text."""
        ...
    
    def embed_texts(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings for multiple texts."""
        ...


@runtime_checkable
class RetrieverProtocol(Protocol):
    """Protocol for document retrievers."""
    
    def index(self, context: Context) -> None:
        """Index documents for retrieval."""
        ...
    
    def retrieve(self, query: str, k: int = 2) -> List["RetrievalResult"]:
        """Retrieve top-k relevant documents."""
        ...


# =============================================================================
# Data Classes - Documents
# =============================================================================

@dataclass(frozen=True)
class Paragraph:
    """
    Represents a paragraph from the HotpotQA context.
    
    Immutable to prevent accidental modification after creation.
    Uses frozen=True for hashability in sets.
    """
    title: str
    text: str
    sentences: Tuple[str, ...]  # Tuple for immutability
    index: int
    
    @classmethod
    def from_context_item(cls, title: str, sentences: List[str], index: int) -> "Paragraph":
        """Factory method to create Paragraph from HotpotQA context item."""
        return cls(
            title=title,
            text=" ".join(sentences),
            sentences=tuple(sentences),
            index=index
        )
    
    @property
    def full_text(self) -> str:
        """Get the full paragraph text with title prefix."""
        return f"{self.title}: {self.text}"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "title": self.title,
            "text": self.text,
            "sentences": list(self.sentences),
            "index": self.index
        }


@dataclass
class RetrievalResult:
    """Result from a retrieval operation."""
    paragraph: Paragraph
    score: float
    rank: int
    
    def to_dict(self) -> Dict:
        return {
            "paragraph": self.paragraph.to_dict(),
            "score": self.score,
            "rank": self.rank
        }


# =============================================================================
# Data Classes - Reasoning
# =============================================================================

@dataclass
class ReasoningStep:
    """Represents a single step in the IRCoT reasoning process."""
    step_number: int
    cot_sentence: str
    retrieved_paragraphs: List[Paragraph]
    cumulative_cot: str
    retrieval_query: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "step_number": self.step_number,
            "cot_sentence": self.cot_sentence,
            "retrieved_paragraphs": [p.to_dict() for p in self.retrieved_paragraphs],
            "cumulative_cot": self.cumulative_cot,
            "retrieval_query": self.retrieval_query
        }


@dataclass
class IRCoTResult:
    """Complete result from IRCoT processing."""
    question: str
    answer: str
    reasoning_chain: str
    reasoning_steps: List[ReasoningStep]
    retrieved_paragraphs: List[Paragraph]
    num_steps: int
    terminated_by_answer: bool
    processing_time: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "reasoning_chain": self.reasoning_chain,
            "reasoning_steps": [s.to_dict() for s in self.reasoning_steps],
            "retrieved_paragraphs": [p.to_dict() for p in self.retrieved_paragraphs],
            "num_steps": self.num_steps,
            "terminated_by_answer": self.terminated_by_answer,
            "processing_time": self.processing_time
        }


@dataclass
class QAResult:
    """Result from the QA Reader."""
    answer: str
    cot: str  # Complete chain-of-thought reasoning
    
    def to_dict(self) -> Dict:
        return {"answer": self.answer, "cot": self.cot}


# =============================================================================
# Data Classes - Dataset
# =============================================================================

@dataclass
class HotpotQAInstance:
    """Represents a single HotpotQA instance."""
    id: str
    question: str
    answer: str
    context: Context
    supporting_facts: SupportingFacts
    question_type: str  # "comparison" or "bridge"
    level: str  # "easy", "medium", "hard"
    
    @classmethod
    def from_dict(cls, data: Dict) -> "HotpotQAInstance":
        """Create instance from dictionary (handles various formats)."""
        context = cls._parse_context(data.get("context", []))
        supporting_facts = cls._parse_supporting_facts(data.get("supporting_facts", []))
        
        return cls(
            id=data.get("_id", ""),
            question=data.get("question", ""),
            answer=data.get("answer", ""),
            context=context,
            supporting_facts=supporting_facts,
            question_type=data.get("type", ""),
            level=data.get("level", "")
        )
    
    @staticmethod
    def _parse_context(raw_context: List) -> Context:
        """Parse context from various formats."""
        context = []
        for item in raw_context:
            if isinstance(item, list) and len(item) >= 2:
                title = item[0]
                sentences = item[1] if isinstance(item[1], list) else [item[1]]
                context.append((title, sentences))
            elif isinstance(item, dict):
                context.append((item.get("title", ""), item.get("sentences", [])))
        return context
    
    @staticmethod
    def _parse_supporting_facts(raw_sf: List) -> SupportingFacts:
        """Parse supporting facts from various formats."""
        facts = []
        for sf in raw_sf:
            if isinstance(sf, list) and len(sf) >= 2:
                facts.append((sf[0], sf[1]))
            elif isinstance(sf, dict):
                facts.append((sf.get("title", ""), sf.get("sent_id", 0)))
        return facts
    
    def to_dict(self) -> Dict:
        """Convert to dictionary format."""
        return {
            "_id": self.id,
            "question": self.question,
            "answer": self.answer,
            "context": self.context,
            "supporting_facts": self.supporting_facts,
            "type": self.question_type,
            "level": self.level
        }
    
    @property
    def gold_paragraph_titles(self) -> Set[str]:
        """Get titles of paragraphs containing supporting facts."""
        return {sf[0] for sf in self.supporting_facts}


# =============================================================================
# Data Classes - Few-Shot Demonstrations
# =============================================================================

@dataclass
class CoTDemo:
    """
    A few-shot demonstration for Chain-of-Thought reasoning.
    
    Contains example paragraphs, question, and the expected CoT answer
    used to teach the model the reasoning format.
    """
    paragraphs: List[Paragraph]
    question: str
    cot_answer: str  # Full CoT including "So the answer is: X"
    
    def to_dict(self) -> Dict:
        return {
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "question": self.question,
            "cot_answer": self.cot_answer
        }
