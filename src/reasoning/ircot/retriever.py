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
from typing import List, Optional, Protocol

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

