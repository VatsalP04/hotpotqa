"""
IRCoT Retrieval Components

This module provides the retrieval infrastructure for the IRCoT algorithm.
It defines the retriever interface and implements a FAISS-based dense retriever
that integrates with the existing Wikipedia index.

Key Components:
- Paragraph: Data structure representing a document/paragraph
- Retriever: Protocol defining the retriever interface
- FAISSRetriever: Dense retrieval using pre-built FAISS index and Mistral embeddings

The retrieval system is designed to:
1. Provide a consistent interface for different retrieval methods
2. Integrate with existing FAISS infrastructure from the notebooks
3. Support dynamic retrieval based on reasoning steps
4. Handle embedding generation for queries using Mistral API

The FAISSRetriever loads:
- Pre-built FAISS index (wiki_faiss.index) containing document embeddings
- Metadata file (wiki_meta.jsonl) with document titles and text
- Uses Mistral embedding API for query encoding

This allows IRCoT to leverage the existing Wikipedia knowledge base built
in the notebooks while providing the iterative retrieval capabilities
required by the algorithm.

Usage:
    retriever = load_faiss_retriever_from_notebooks("notebooks")
    results = retriever.retrieve("your query", top_k=5)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol, Tuple, Dict

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None

try:
    from mistralai import Mistral
except ImportError:
    Mistral = None


@dataclass
class Paragraph:
    """Represents a paragraph in the corpus."""

    pid: int
    title: str
    text: str


class Retriever(Protocol):
    """Protocol for retrievers consumed by IRCoT."""

    def retrieve(self, query: str, top_k: int) -> List[Paragraph]:
        ...


class FAISSRetriever:
    """
    FAISS-based dense retriever using Mistral embeddings.
    
    This retriever integrates with the existing FAISS infrastructure built in
    the notebooks, providing dense semantic retrieval for the IRCoT algorithm.
    
    The retriever:
    1. Loads a pre-built FAISS index containing Wikipedia document embeddings
    2. Uses Mistral embedding API to encode queries into the same vector space
    3. Performs cosine similarity search to find relevant documents
    4. Returns results as Paragraph objects for use in IRCoT
    
    This approach leverages the existing Wikipedia knowledge base while providing
    the dynamic retrieval capabilities needed for iterative reasoning. The use
    of dense embeddings allows for semantic matching beyond keyword overlap.
    
    Args:
        index_path: Path to the FAISS index file (.index)
        metadata_path: Path to the metadata JSONL file with document info
        mistral_api_key: API key for Mistral embedding service
        embedding_model: Mistral model name for embeddings (default: mistral-embed)
    """

    def __init__(
        self,
        index_path: str,
        metadata_path: str,
        mistral_api_key: Optional[str] = None,
        embedding_model: str = "mistral-embed",
    ):
        """
        Initialize FAISS retriever.
        
        Args:
            index_path: Path to the FAISS index file (.index)
            metadata_path: Path to the metadata JSONL file
            mistral_api_key: Mistral API key for query embeddings
            embedding_model: Mistral embedding model name
        """
        if faiss is None:
            raise ImportError("faiss-cpu is required. Install with: pip install faiss-cpu")
        if Mistral is None:
            raise ImportError("mistralai is required. Install with: pip install mistralai")
        
        # Load FAISS index
        self.index = faiss.read_index(index_path)
        
        # Load metadata
        self.paragraphs: List[Paragraph] = []
        with open(metadata_path, 'r') as f:
            for i, line in enumerate(f):
                meta = json.loads(line)
                self.paragraphs.append(Paragraph(
                    pid=i,
                    title=meta['title'],
                    text=meta['text']
                ))
        
        # Initialize Mistral client for query embeddings
        api_key = mistral_api_key or os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY must be provided or set in environment")
        
        self.client = Mistral(api_key=api_key)
        self.embedding_model = embedding_model
        
        print(f"✅ FAISS retriever initialized with {len(self.paragraphs)} documents")

    def retrieve(self, query: str, top_k: int) -> List[Paragraph]:
        """Retrieve top_k most relevant paragraphs for the query."""
        if not query.strip():
            return []
        
        # Get query embedding
        try:
            resp = self.client.embeddings.create(
                model=self.embedding_model,
                inputs=[query]
            )
            q_vec = np.array(resp.data[0].embedding, dtype="float32").reshape(1, -1)
        except Exception as e:
            print(f"Error getting query embedding: {e}")
            return []
        
        # Normalize for cosine similarity
        faiss.normalize_L2(q_vec)
        
        # Search FAISS index
        scores, ids = self.index.search(q_vec, min(top_k, len(self.paragraphs)))
        
        # Return results
        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx >= 0 and idx < len(self.paragraphs):  # Valid index
                results.append(self.paragraphs[idx])
        
        return results


def load_faiss_retriever_from_notebooks(notebooks_dir: str = "notebooks") -> FAISSRetriever:
    """
    Convenience function to load FAISS retriever from the notebooks directory.
    
    Args:
        notebooks_dir: Path to notebooks directory containing FAISS files
        
    Returns:
        FAISSRetriever instance
    """
    base_path = Path(notebooks_dir)
    index_path = base_path / "wiki_faiss.index"
    metadata_path = base_path / "wiki_meta.jsonl"
    
    if not index_path.exists():
        raise FileNotFoundError(f"FAISS index not found at {index_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found at {metadata_path}")
    
    return FAISSRetriever(
        index_path=str(index_path),
        metadata_path=str(metadata_path)
    )

# For distractor setting

# Represents a single sentence with its source info for supporting fact tracking.
@dataclass
class Sentence:
    title: str
    sent_idx: int
    text: str
    
    @property
    def sp_tuple(self) -> Tuple[str, int]:
        return (self.title, self.sent_idx)


# Extended paragraph that tracks individual sentences for SP evaluation.
@dataclass
class ParagraphWithSentences:
    title: str
    sentences: List[str]
    
    @property
    def full_text(self) -> str:
        return " ".join(self.sentences)
    
    def get_all_sentences(self) -> List[Sentence]:
        return [
            Sentence(title=self.title, sent_idx=i, text=s)
            for i, s in enumerate(self.sentences)
        ]


class InMemoryRetriever:
    def __init__(
        self, 
        paragraphs: List[Paragraph], 
        mistral_client,
        embedding_model: str = "mistral-embed"
    ):
        self.paragraphs = paragraphs
        self.client = mistral_client
        self.embedding_model = embedding_model
        self.embeddings = np.array([])

        if not paragraphs:
            return

        # Batch embed all paragraphs
        texts = [p.text for p in paragraphs]
        try:
            resp = self.client.embeddings.create(
                model=self.embedding_model,
                inputs=texts
            )
            emb_list = [item.embedding for item in resp.data]
            self.embeddings = np.array(emb_list, dtype="float32")
            
            # Normalize for cosine similarity
            norm = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
            self.embeddings = self.embeddings / (norm + 1e-10)
        except Exception as e:
            print(f"Embedding error: {e}")
            self.embeddings = np.zeros((len(texts), 1024), dtype="float32")

    # Retrieve top_k most relevant paragraphs for the query.
    def retrieve(self, query: str, top_k: int) -> List[Paragraph]:
        if self.embeddings.size == 0:
            return []
            
        try:
            resp = self.client.embeddings.create(
                model=self.embedding_model,
                inputs=[query]
            )
            q_vec = np.array(resp.data[0].embedding, dtype="float32").reshape(1, -1)
            
            norm = np.linalg.norm(q_vec)
            q_vec = q_vec / (norm + 1e-10)
            
            scores = np.dot(self.embeddings, q_vec.T).flatten()
            top_indices = np.argsort(scores)[::-1][:top_k]
            
            return [self.paragraphs[i] for i in top_indices]
        except Exception as e:
            print(f"Retrieval error: {e}")
            return []

# Adapter that wraps InMemoryRetriever to track supporting facts at sentence level.
class DistractorRetrieverAdapter:
    def __init__(
        self, 
        retriever: InMemoryRetriever, 
        paragraphs_with_sentences: List[ParagraphWithSentences],
        top_k_paragraphs: int = 2
    ):
        self.retriever = retriever
        self.paragraphs_with_sentences = paragraphs_with_sentences
        self.top_k_paragraphs = top_k_paragraphs
        self.retrieved_sp: List[Tuple[str, int]] = []
        self.retrieved_sentences: List[Sentence] = []
        
        # Build title -> ParagraphWithSentences lookup
        self.title_to_para: Dict[str, ParagraphWithSentences] = {
            p.title: p for p in paragraphs_with_sentences
        }
    
    # Retrieve paragraphs and track all their sentences for SP evaluation.
    def retrieve(self, query: str, top_k: int) -> List[Paragraph]:
        paragraphs = self.retriever.retrieve(query, self.top_k_paragraphs)
        
        for para in paragraphs:
            # Look up the full sentence info
            para_with_sents = self.title_to_para.get(para.title)
            if para_with_sents:
                for sent in para_with_sents.get_all_sentences():
                    sp_tuple = sent.sp_tuple
                    if sp_tuple not in set(self.retrieved_sp):
                        self.retrieved_sp.append(sp_tuple)
                        self.retrieved_sentences.append(sent)
        
        return paragraphs
    
    # Get unique supporting facts as list of [title, sent_idx] pairs.
    def get_supporting_facts(self) -> List[List]:
        seen = set()
        unique_sp = []
        for sp in self.retrieved_sp:
            if sp not in seen:
                seen.add(sp)
                unique_sp.append(list(sp))
        return unique_sp
    
    # Get unique retrieved sentence texts.
    def get_unique_retrieved_texts(self) -> List[str]:
        seen = set()
        unique_texts = []
        for sent in self.retrieved_sentences:
            if sent.sp_tuple not in seen:
                seen.add(sent.sp_tuple)
                unique_texts.append(sent.text)
        return unique_texts