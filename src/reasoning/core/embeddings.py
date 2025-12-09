"""
Embeddings module with Mistral API and caching.

Provides embedding generation using Mistral API with optional caching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np
from mistralai import Mistral

from .types import EmbeddingsProtocol

logger = logging.getLogger(__name__)


class MistralEmbeddings:
    """Generates embeddings using Mistral API."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "mistral-embed"):
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not self._api_key:
            raise ValueError("API key is required for MistralEmbeddings")
        
        self.client = Mistral(api_key=self._api_key)
        self.model = model
        self.embedding_dim = 1024
    
    def embed_text(self, text: str) -> np.ndarray:
        """Generate embedding for a single text."""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                inputs=[text]
            )
            return np.array(response.data[0].embedding)
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise
    
    def embed_texts(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings for multiple texts with batching."""
        if not texts:
            return np.array([])
        
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    inputs=batch
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                logger.error(f"Error generating embeddings for batch {i}: {e}")
                raise
        
        return np.array(all_embeddings)
    
    # Aliases for compatibility
    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_text(query)
    
    def embed_documents(self, documents: List[str]) -> np.ndarray:
        return self.embed_texts(documents)


class CachedEmbeddings:
    """Decorator that adds caching to any embeddings implementation."""
    
    def __init__(
        self,
        embeddings: EmbeddingsProtocol,
        cache_dir: Optional[str] = None
    ):
        self._embeddings = embeddings
        self._cache: Dict[str, np.ndarray] = {}
        self._cache_dir = cache_dir
        self._hits = 0
        self._misses = 0
        
        if cache_dir:
            self._load_cache()
    
    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension from underlying embeddings."""
        return getattr(self._embeddings, 'embedding_dim', 1024)
    
    def embed_text(self, text: str) -> np.ndarray:
        """Generate embedding with caching."""
        key = self._get_cache_key(text)
        
        if key in self._cache:
            self._hits += 1
            return self._cache[key].copy()
        
        self._misses += 1
        embedding = self._embeddings.embed_text(text)
        self._cache[key] = embedding
        return embedding
    
    def embed_texts(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings with caching."""
        if not texts:
            return np.array([])
        
        results = [None] * len(texts)
        texts_to_embed = []
        indices_to_embed = []
        
        # Check cache for each text
        for i, text in enumerate(texts):
            key = self._get_cache_key(text)
            if key in self._cache:
                self._hits += 1
                results[i] = self._cache[key]
            else:
                self._misses += 1
                texts_to_embed.append(text)
                indices_to_embed.append(i)
        
        # Embed uncached texts
        if texts_to_embed:
            new_embeddings = self._embeddings.embed_texts(texts_to_embed, batch_size)
            for idx, text, emb in zip(indices_to_embed, texts_to_embed, new_embeddings):
                key = self._get_cache_key(text)
                self._cache[key] = emb
                results[idx] = emb
        
        return np.array(results)
    
    # Aliases
    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_text(query)
    
    def embed_documents(self, documents: List[str]) -> np.ndarray:
        return self.embed_texts(documents)
    
    @staticmethod
    def _get_cache_key(text: str) -> str:
        """Generate cache key from text."""
        return hashlib.md5(text.encode()).hexdigest()
    
    def _load_cache(self) -> None:
        """Load cache from disk."""
        if not self._cache_dir:
            return
        
        cache_file = os.path.join(self._cache_dir, "embeddings_cache.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                self._cache = {k: np.array(v) for k, v in data.items()}
                logger.info(f"Loaded {len(self._cache)} cached embeddings")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
    
    def save_cache(self) -> None:
        """Save cache to disk."""
        if not self._cache_dir:
            return
        
        os.makedirs(self._cache_dir, exist_ok=True)
        cache_file = os.path.join(self._cache_dir, "embeddings_cache.json")
        try:
            data = {k: v.tolist() for k, v in self._cache.items()}
            with open(cache_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def clear_cache(self) -> None:
        """Clear the cache."""
        self._cache = {}
        self._hits = 0
        self._misses = 0
    
    @property
    def cache_stats(self) -> Dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0
        }


# =============================================================================
# Factory & Utility Functions
# =============================================================================

def create_embeddings(
    api_key: Optional[str] = None,
    model: str = "mistral-embed",
    use_cache: bool = True,
    cache_dir: Optional[str] = None
) -> EmbeddingsProtocol:
    """Create an embeddings instance with optional caching."""
    base = MistralEmbeddings(api_key, model)
    
    if use_cache:
        return CachedEmbeddings(base, cache_dir)
    
    return base


def cosine_similarity(query_emb: np.ndarray, doc_embs: np.ndarray) -> np.ndarray:
    """Calculate cosine similarity between query and documents."""
    if len(doc_embs) == 0:
        return np.array([])
    
    # Normalize query
    query_norm = np.linalg.norm(query_emb)
    if query_norm == 0:
        return np.zeros(len(doc_embs))
    query_normalized = query_emb / query_norm
    
    # Normalize documents
    doc_norms = np.linalg.norm(doc_embs, axis=1, keepdims=True)
    doc_norms = np.where(doc_norms == 0, 1, doc_norms)
    doc_normalized = doc_embs / doc_norms
    
    return np.dot(doc_normalized, query_normalized)

