"""
Retriever module for IRCoT.

Provides document retrieval using dense embeddings and cosine similarity.
Implements the IRCoT retrieval strategy with iterative retrieval based on
Chain-of-Thought reasoning steps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from .types import Context, EmbeddingsProtocol, Paragraph, RetrievalResult

logger = logging.getLogger(__name__)


class DenseRetriever:
    """
    Dense retriever using embeddings and cosine similarity.
    
    Stores documents in memory and retrieves using vector similarity.
    Designed for the HotpotQA distractor setting where we search
    over provided context paragraphs.
    """
    
    def __init__(
        self,
        embeddings: EmbeddingsProtocol,
        include_title: bool = True
    ):
        """
        Initialize retriever.
        
        Args:
            embeddings: Embeddings implementation
            include_title: Whether to include title in embeddings
        """
        self._embeddings = embeddings
        self._include_title = include_title
        self._paragraphs: List[Paragraph] = []
        self._embeddings_matrix: Optional[np.ndarray] = None
        self._indexed = False
    
    def index(self, context: Context) -> None:
        """
        Index context paragraphs for retrieval.
        
        Args:
            context: List of (title, sentences) tuples
        """
        self._paragraphs = []
        texts = []
        
        for idx, (title, sentences) in enumerate(context):
            paragraph = Paragraph.from_context_item(title, sentences, idx)
            self._paragraphs.append(paragraph)
            
            text = paragraph.full_text if self._include_title else paragraph.text
            texts.append(text)
        
        if texts:
            self._embeddings_matrix = self._embeddings.embed_texts(texts)
            self._indexed = True
            logger.debug(f"Indexed {len(self._paragraphs)} paragraphs")
        else:
            self._embeddings_matrix = np.array([])
            self._indexed = False
            logger.warning("No paragraphs to index")
    
    def retrieve(
        self,
        query: str,
        k: int = 2,
        exclude_indices: Optional[Set[int]] = None,
        min_score: float = 0.0
    ) -> List[RetrievalResult]:
        """
        Retrieve top-k most similar paragraphs.
        
        Args:
            query: Query text
            k: Number of paragraphs to retrieve
            exclude_indices: Indices to exclude from results
            min_score: Minimum similarity threshold
            
        Returns:
            List of retrieval results
        """
        if not self._indexed or len(self._paragraphs) == 0:
            logger.warning("No paragraphs indexed for retrieval")
            return []
        
        # Get query embedding
        query_emb = self._embeddings.embed_text(query)
        
        # Calculate similarities
        similarities = self._cosine_similarity(query_emb, self._embeddings_matrix)
        
        # Apply exclusion mask
        if exclude_indices:
            for idx in exclude_indices:
                if 0 <= idx < len(similarities):
                    similarities[idx] = -np.inf
        
        # Get top-k indices
        k = min(k, len(self._paragraphs))
        top_indices = np.argsort(similarities)[-k:][::-1]
        
        # Build results
        results = []
        for rank, idx in enumerate(top_indices):
            score = similarities[idx]
            if score == -np.inf or score < min_score:
                continue
            
            results.append(RetrievalResult(
                paragraph=self._paragraphs[idx],
                score=float(score),
                rank=rank
            ))
        
        return results
    
    @staticmethod
    def _cosine_similarity(query_emb: np.ndarray, doc_embs: np.ndarray) -> np.ndarray:
        """Calculate cosine similarities."""
        if len(doc_embs) == 0:
            return np.array([])
        
        query_norm = np.linalg.norm(query_emb)
        if query_norm == 0:
            return np.zeros(len(doc_embs))
        
        query_normalized = query_emb / query_norm
        doc_norms = np.linalg.norm(doc_embs, axis=1, keepdims=True)
        doc_norms = np.where(doc_norms == 0, 1, doc_norms)
        doc_normalized = doc_embs / doc_norms
        
        return np.dot(doc_normalized, query_normalized)
    
    def get_paragraph(self, index: int) -> Optional[Paragraph]:
        """Get paragraph by index."""
        if 0 <= index < len(self._paragraphs):
            return self._paragraphs[index]
        return None
    
    def get_all_paragraphs(self) -> List[Paragraph]:
        """Get all indexed paragraphs."""
        return list(self._paragraphs)
    
    def clear(self) -> None:
        """Clear indexed paragraphs."""
        self._paragraphs = []
        self._embeddings_matrix = None
        self._indexed = False


@dataclass
class RetrievalHistoryEntry:
    """Records a single retrieval operation."""
    step: int
    query: str
    query_type: str  # "question" or "cot_sentence"
    paragraphs: List[str]  # Titles
    scores: List[float]


class IRCoTRetriever:
    """
    IRCoT-style retriever with state tracking.
    
    Maintains retrieval state across reasoning steps to:
    - Track which paragraphs have been retrieved
    - Avoid duplicate retrievals
    - Build up context iteratively
    
    This is the main retriever class used by the IRCoT system.
    """
    
    def __init__(
        self,
        base_retriever: DenseRetriever,
        max_paragraphs: int = 10
    ):
        """
        Initialize IRCoT retriever.
        
        Args:
            base_retriever: Underlying dense retriever
            max_paragraphs: Maximum paragraphs to accumulate
        """
        self._base = base_retriever
        self._max_paragraphs = max_paragraphs
        self._retrieved: List[Paragraph] = []
        self._retrieved_indices: Set[int] = set()
        self._history: List[RetrievalHistoryEntry] = []
    
    def index(self, context: Context) -> None:
        """Index context and reset state."""
        self._base.index(context)
        self.reset()
    
    def reset(self) -> None:
        """Reset retrieval state for a new question."""
        self._retrieved = []
        self._retrieved_indices = set()
        self._history = []
    
    def initial_retrieve(self, question: str, k: int = 2) -> List[Paragraph]:
        """
        Perform initial retrieval using the question.
        
        Args:
            question: The question to answer
            k: Number of paragraphs to retrieve
            
        Returns:
            List of retrieved paragraphs (cumulative)
        """
        results = self._base.retrieve(question, k)
        new_paragraphs = self._add_results(results)
        
        self._history.append(RetrievalHistoryEntry(
            step=0,
            query=question,
            query_type="question",
            paragraphs=[p.title for p in new_paragraphs],
            scores=[r.score for r in results[:len(new_paragraphs)]]
        ))
        
        logger.debug(f"Initial retrieval: {len(new_paragraphs)} paragraphs")
        return list(self._retrieved)
    
    def step_retrieve(
        self,
        cot_sentence: str,
        k: int = 1,
        step_number: Optional[int] = None
    ) -> List[Paragraph]:
        """
        Retrieve additional paragraphs using a CoT sentence.
        
        Args:
            cot_sentence: The latest CoT reasoning sentence
            k: Number of paragraphs to retrieve
            step_number: Current step number (for logging)
            
        Returns:
            Newly retrieved paragraphs only
        """
        # Check if we've reached max
        if len(self._retrieved) >= self._max_paragraphs:
            logger.debug("Max paragraphs reached, skipping retrieval")
            return []
        
        # Limit k to remaining capacity
        remaining = self._max_paragraphs - len(self._retrieved)
        k = min(k, remaining)
        
        # Retrieve excluding already-retrieved paragraphs
        results = self._base.retrieve(
            cot_sentence,
            k,
            exclude_indices=self._retrieved_indices
        )
        
        new_paragraphs = self._add_results(results)
        
        step = step_number if step_number is not None else len(self._history)
        self._history.append(RetrievalHistoryEntry(
            step=step,
            query=cot_sentence,
            query_type="cot_sentence",
            paragraphs=[p.title for p in new_paragraphs],
            scores=[r.score for r in results[:len(new_paragraphs)]]
        ))
        
        logger.debug(f"Step retrieval: {len(new_paragraphs)} new paragraphs")
        return new_paragraphs
    
    def _add_results(self, results: List[RetrievalResult]) -> List[Paragraph]:
        """Add results to retrieved set, return only new paragraphs."""
        new_paragraphs = []
        
        for result in results:
            if result.paragraph.index not in self._retrieved_indices:
                self._retrieved.append(result.paragraph)
                self._retrieved_indices.add(result.paragraph.index)
                new_paragraphs.append(result.paragraph)
        
        return new_paragraphs
    
    @property
    def paragraphs(self) -> List[Paragraph]:
        """Get all retrieved paragraphs."""
        return list(self._retrieved)
    
    @property
    def titles(self) -> Set[str]:
        """Get titles of all retrieved paragraphs."""
        return {p.title for p in self._retrieved}
    
    @property
    def count(self) -> int:
        """Get number of retrieved paragraphs."""
        return len(self._retrieved)
    
    @property
    def at_capacity(self) -> bool:
        """Check if retriever has reached max paragraphs."""
        return len(self._retrieved) >= self._max_paragraphs
    
    def get_summary(self) -> Dict:
        """Get summary of retrieval process."""
        return {
            "total_paragraphs": len(self._retrieved),
            "retrieval_steps": len(self._history),
            "titles": list(self.titles),
            "history": [
                {
                    "step": h.step,
                    "query_type": h.query_type,
                    "num_retrieved": len(h.paragraphs),
                    "paragraphs": h.paragraphs
                }
                for h in self._history
            ]
        }
    
    def format_context(self, numbered: bool = True) -> str:
        """
        Format retrieved paragraphs as context string.
        
        Args:
            numbered: Whether to number paragraphs
            
        Returns:
            Formatted context string
        """
        parts = []
        for i, para in enumerate(self._retrieved):
            if numbered:
                parts.append(f"[{i + 1}] {para.full_text}")
            else:
                parts.append(f"- {para.full_text}")
        return "\n\n".join(parts)
