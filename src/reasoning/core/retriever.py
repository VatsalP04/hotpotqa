"""
Document retrieval module.

Provides multiple retrieval strategies:
- BM25Retriever: Sparse retrieval using BM25 algorithm (default)
- DenseRetriever: Dense retrieval using embeddings and cosine similarity

Implements the IRCoT retrieval strategy with iterative retrieval.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Callable, Union, Protocol, runtime_checkable

import numpy as np

from .types import Context, EmbeddingsProtocol, Paragraph, RetrievalResult

logger = logging.getLogger(__name__)


# =============================================================================
# Retriever Protocol (Interface)
# =============================================================================

@runtime_checkable
class RetrieverProtocol(Protocol):
    """Protocol that any retriever must implement."""
    
    def index(self, context: Context) -> None:
        """Index context paragraphs for retrieval."""
        ...
    
    def retrieve(
        self,
        query: str,
        k: int = 2,
        exclude_indices: Optional[Set[int]] = None,
        min_score: float = 0.0
    ) -> List[RetrievalResult]:
        """Retrieve top-k most relevant paragraphs."""
        ...
    
    def get_paragraph(self, index: int) -> Optional[Paragraph]:
        """Get paragraph by index."""
        ...
    
    def get_all_paragraphs(self) -> List[Paragraph]:
        """Get all indexed paragraphs."""
        ...
    
    def clear(self) -> None:
        """Clear indexed paragraphs."""
        ...


# =============================================================================
# BM25 Retriever (Default - No API calls)
# =============================================================================

class BM25Retriever:
    """
    BM25 retriever using sparse lexical matching.
    
    BM25 (Best Matching 25) is a bag-of-words retrieval function that ranks
    documents based on the query terms appearing in each document.
    
    Advantages over dense retrieval:
    - No API calls required (faster, cheaper)
    - Works well for keyword matching
    - Interpretable scoring
    
    Parameters:
        k1: Term frequency saturation parameter (default: 1.5)
        b: Document length normalization parameter (default: 0.75)
    """
    
    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        include_title: bool = True,
        tokenizer: Optional[Callable[[str], List[str]]] = None,
    ):
        self._k1 = k1
        self._b = b
        self._include_title = include_title
        self._tokenizer = tokenizer or self._default_tokenizer
        
        self._paragraphs: List[Paragraph] = []
        self._doc_freqs: Counter = Counter()
        self._doc_lens: List[int] = []
        self._avg_doc_len: float = 0.0
        self._doc_term_freqs: List[Counter] = []
        self._indexed = False
        self._num_docs = 0
    
    @staticmethod
    def _default_tokenizer(text: str) -> List[str]:
        """Simple tokenizer: lowercase, split on non-alphanumeric, remove stopwords."""
        # Common English stopwords
        stopwords = {
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
            'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
            'we', 'they', 'what', 'which', 'who', 'whom', 'when', 'where', 'why',
            'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
            'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
            'too', 'very', 'as', 'if', 'then', 'because', 'while', 'although',
        }
        
        # Lowercase and split on non-alphanumeric
        tokens = re.findall(r'\b[a-z0-9]+\b', text.lower())
        
        # Remove stopwords and short tokens
        return [t for t in tokens if t not in stopwords and len(t) > 1]
    
    def index(self, context: Context) -> None:
        """Index context paragraphs for BM25 retrieval."""
        self._paragraphs = []
        self._doc_freqs = Counter()
        self._doc_lens = []
        self._doc_term_freqs = []
        
        for idx, (title, sentences) in enumerate(context):
            paragraph = Paragraph.from_context_item(title, sentences, idx)
            self._paragraphs.append(paragraph)
            
            # Get text and tokenize
            text = paragraph.full_text if self._include_title else paragraph.text
            tokens = self._tokenizer(text)
            
            # Count term frequencies for this document
            term_freqs = Counter(tokens)
            self._doc_term_freqs.append(term_freqs)
            self._doc_lens.append(len(tokens))
            
            # Update document frequencies
            for term in set(tokens):
                self._doc_freqs[term] += 1
        
        self._num_docs = len(self._paragraphs)
        self._avg_doc_len = sum(self._doc_lens) / self._num_docs if self._num_docs > 0 else 0
        self._indexed = self._num_docs > 0
        
        logger.debug(f"BM25 indexed {self._num_docs} paragraphs, vocab size: {len(self._doc_freqs)}")
    
    def retrieve(
        self,
        query: str,
        k: int = 2,
        exclude_indices: Optional[Set[int]] = None,
        min_score: float = 0.0
    ) -> List[RetrievalResult]:
        """Retrieve top-k most relevant paragraphs using BM25."""
        if not self._indexed or self._num_docs == 0:
            logger.warning("No paragraphs indexed for retrieval")
            return []
        
        # Tokenize query
        query_tokens = self._tokenizer(query)
        if not query_tokens:
            logger.debug("Empty query after tokenization")
            return []
        
        # Calculate BM25 scores for all documents
        scores = np.zeros(self._num_docs)
        
        for term in query_tokens:
            if term not in self._doc_freqs:
                continue
            
            # IDF component
            df = self._doc_freqs[term]
            idf = math.log((self._num_docs - df + 0.5) / (df + 0.5) + 1)
            
            # Score each document
            for doc_idx in range(self._num_docs):
                tf = self._doc_term_freqs[doc_idx].get(term, 0)
                if tf == 0:
                    continue
                
                doc_len = self._doc_lens[doc_idx]
                
                # BM25 term score
                numerator = tf * (self._k1 + 1)
                denominator = tf + self._k1 * (1 - self._b + self._b * doc_len / self._avg_doc_len)
                scores[doc_idx] += idf * (numerator / denominator)
        
        # Apply exclusion mask
        if exclude_indices:
            for idx in exclude_indices:
                if 0 <= idx < len(scores):
                    scores[idx] = -np.inf
        
        # Get top-k indices
        k = min(k, self._num_docs)
        top_indices = np.argsort(scores)[-k:][::-1]
        
        # Build results
        results = []
        for rank, idx in enumerate(top_indices):
            score = scores[idx]
            if score == -np.inf or score < min_score:
                continue
            
            results.append(RetrievalResult(
                paragraph=self._paragraphs[idx],
                score=float(score),
                rank=rank
            ))
        
        return results
    
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
        self._doc_freqs = Counter()
        self._doc_lens = []
        self._doc_term_freqs = []
        self._indexed = False
        self._num_docs = 0


# =============================================================================
# Dense Retriever (Embedding-based)
# =============================================================================

class DenseRetriever:
    """
    Dense retriever using embeddings and cosine similarity.
    
    Stores documents in memory and retrieves using vector similarity.
    Requires embedding API calls.
    """
    
    def __init__(
        self,
        embeddings: EmbeddingsProtocol,
        include_title: bool = True
    ):
        self._embeddings = embeddings
        self._include_title = include_title
        self._paragraphs: List[Paragraph] = []
        self._embeddings_matrix: Optional[np.ndarray] = None
        self._indexed = False
    
    def index(self, context: Context) -> None:
        """Index context paragraphs for retrieval."""
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
        """Retrieve top-k most similar paragraphs."""
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


# =============================================================================
# Retrieval History Tracking
# =============================================================================

@dataclass
class RetrievalHistoryEntry:
    """Records a single retrieval operation."""
    step: int
    query: str
    query_type: str  # "question" or "cot_sentence"
    paragraphs: List[str]  # Titles
    scores: List[float]


# Type alias for any base retriever
BaseRetriever = Union[BM25Retriever, DenseRetriever]


# =============================================================================
# IRCoT Retriever (Stateful wrapper)
# =============================================================================

class IRCoTRetriever:
    """
    IRCoT-style retriever with state tracking.
    
    Maintains retrieval state across reasoning steps to:
    - Track which paragraphs have been retrieved
    - Avoid duplicate retrievals
    - Build up context iteratively
    
    Works with any base retriever (BM25 or Dense).
    """
    
    def __init__(
        self,
        base_retriever: BaseRetriever,
        max_paragraphs: int = 10
    ):
        self._base = base_retriever
        self._max_paragraphs = max_paragraphs
        self._retrieved: List[Paragraph] = []
        self._retrieved_indices: Set[int] = set()
        self._history: List[RetrievalHistoryEntry] = []
        self._first_retrieval_titles: List[str] = []  # Track first retrieval for metrics
    
    def index(self, context: Context) -> None:
        """Index context and reset state."""
        self._base.index(context)
        self.reset()
    
    def reset(self) -> None:
        """Reset retrieval state for a new question."""
        self._retrieved = []
        self._retrieved_indices = set()
        self._history = []
        self._first_retrieval_titles = []
    
    def initial_retrieve(self, question: str, k: int = 2) -> List[Paragraph]:
        """Perform initial retrieval using the question."""
        results = self._base.retrieve(question, k)
        new_paragraphs = self._add_results(results)
        
        # Track first retrieval titles for metrics
        self._first_retrieval_titles = [p.title for p in new_paragraphs]
        
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
        """Retrieve additional paragraphs using a CoT sentence."""
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
    def first_retrieval_titles(self) -> List[str]:
        """Get titles from the first retrieval step (for metrics)."""
        return list(self._first_retrieval_titles)
    
    @property
    def count(self) -> int:
        """Get number of retrieved paragraphs."""
        return len(self._retrieved)
    
    @property
    def at_capacity(self) -> bool:
        """Check if retriever has reached max paragraphs."""
        return len(self._retrieved) >= self._max_paragraphs
    
    @property
    def history(self) -> List[RetrievalHistoryEntry]:
        """Get retrieval history."""
        return list(self._history)
    
    def get_summary(self) -> Dict:
        """Get summary of retrieval process."""
        return {
            "total_paragraphs": len(self._retrieved),
            "retrieval_steps": len(self._history),
            "titles": list(self.titles),
            "first_retrieval_titles": self._first_retrieval_titles,
        }


# =============================================================================
# Factory Function
# =============================================================================

def create_retriever(
    retriever_type: str = "bm25",
    embeddings: Optional[EmbeddingsProtocol] = None,
    **kwargs
) -> BaseRetriever:
    """
    Factory function to create a retriever.
    
    Args:
        retriever_type: "bm25" or "dense"
        embeddings: Required for dense retriever
        **kwargs: Additional arguments for the retriever
    
    Returns:
        Configured retriever instance
    """
    if retriever_type.lower() == "bm25":
        return BM25Retriever(**kwargs)
    elif retriever_type.lower() == "dense":
        if embeddings is None:
            raise ValueError("Embeddings required for dense retriever")
        return DenseRetriever(embeddings, **kwargs)
    else:
        raise ValueError(f"Unknown retriever type: {retriever_type}")
