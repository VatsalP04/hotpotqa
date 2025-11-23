from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Paragraph:
    """Represents a paragraph in the corpus."""

    pid: int
    title: str
    text: str


class TfidfRetriever:
    """
    Retrieval module with fit() + retrieve() API, approximating BM25 via TF-IDF.
    """

    def __init__(self, paragraphs: List[Paragraph]):
        self.paragraphs = paragraphs
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=50000)
        self._doc_matrix = None
        self._fit()

    def _fit(self) -> None:
        texts = [p.text for p in self.paragraphs]
        self._doc_matrix = self._vectorizer.fit_transform(texts)

    def retrieve(self, query: str, top_k: int) -> List[Paragraph]:
        """Return top_k paragraphs most similar to the query."""
        if not query.strip():
            return []

        q_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self._doc_matrix)[0]
        top_idx = np.argsort(-sims)[:top_k]
        return [self.paragraphs[i] for i in top_idx]


def build_corpus_from_texts(
    texts: List[str], titles: Optional[List[str]] = None
) -> List[Paragraph]:
    """Convenience helper to build a tiny corpus from raw texts."""
    if titles is None:
        titles = [f"Doc-{i}" for i in range(len(texts))]
    return [
        Paragraph(pid=i, title=titles[i], text=texts[i])
        for i in range(len(texts))
    ]

