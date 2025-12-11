"""
Modular Retrieval Components for IRCoT & Decomposition
"""

from __future__ import annotations
import json
import os
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol, Tuple, Dict

try:
    import faiss
except ImportError:
    faiss = None

try:
    from mistralai import Mistral
except ImportError:
    Mistral = None


# -------------------------------------------------------------------
# DATA MODELS
# -------------------------------------------------------------------

@dataclass
class Paragraph:
    pid: int
    title: str
    text: str


@dataclass
class Sentence:
    title: str
    sent_idx: int
    text: str
    
    @property
    def sp_tuple(self):
        return (self.title, self.sent_idx)


@dataclass
class ParagraphWithSentences:
    title: str
    sentences: List[str]
    
    @property
    def full_text(self):
        return " ".join(self.sentences)

    def get_all_sentences(self):
        return [
            Sentence(self.title, idx, text)
            for idx, text in enumerate(self.sentences)
        ]


# -------------------------------------------------------------------
# RETRIEVER PROTOCOL
# -------------------------------------------------------------------

class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int) -> List[Paragraph]:
        ...


# -------------------------------------------------------------------
# PARAGRAPH-LEVEL RETRIEVER
# -------------------------------------------------------------------

class InMemoryRetriever:
    """
    Dense paragraph retriever using Mistral embeddings (local only).
    """

    def __init__(self, paragraphs: List[Paragraph], mistral_client, embedding_model="mistral-embed"):
        self.paragraphs = paragraphs
        self.client = mistral_client
        self.embedding_model = embedding_model

        texts = [p.text for p in paragraphs]
        resp = self.client.embeddings.create(model=self.embedding_model, inputs=texts)
        vecs = np.array([item.embedding for item in resp.data], dtype="float32")

        norm = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10
        self.embeddings = vecs / norm

    def retrieve(self, query: str, top_k: int):
        resp = self.client.embeddings.create(model=self.embedding_model, inputs=[query])
        qvec = np.array(resp.data[0].embedding, dtype="float32").reshape(1, -1)
        qvec = qvec / (np.linalg.norm(qvec) + 1e-10)

        scores = np.dot(self.embeddings, qvec.T).flatten()
        idxs = scores.argsort()[::-1][:top_k]

        return [self.paragraphs[i] for i in idxs]


class DistractorRetrieverAdapter:
    """
    Wrap paragraph retriever but also track supporting facts.
    """

    def __init__(self, retriever, paragraphs_with_sentences, top_k_paragraphs=2):
        self.retriever = retriever
        self.top_k_paragraphs = top_k_paragraphs
        self.paragraphs_with_sentences = {p.title: p for p in paragraphs_with_sentences}
        self.retrieved_sp = []
        self.retrieved_sentences = []

    def retrieve(self, query, top_k):
        paragraphs = self.retriever.retrieve(query, self.top_k_paragraphs)

        for p in paragraphs:
            para_obj = self.paragraphs_with_sentences.get(p.title)
            if para_obj:
                for s in para_obj.get_all_sentences():
                    if s.sp_tuple not in set(self.retrieved_sp):
                        self.retrieved_sp.append(s.sp_tuple)
                        self.retrieved_sentences.append(s)

        return paragraphs

    def get_supporting_facts(self):
        return [list(sp) for sp in self.retrieved_sp]

    def get_unique_retrieved_texts(self):
        seen = set()
        out = []
        for s in self.retrieved_sentences:
            if s.sp_tuple not in seen:
                seen.add(s.sp_tuple)
                out.append(s.text)
        return out


# -------------------------------------------------------------------
# SENTENCE-LEVEL RETRIEVER
# -------------------------------------------------------------------

class SentenceRetriever:
    """
    Dense sentence-level retriever.
    """

    def __init__(self, paragraphs_with_sentences, mistral_client, model="mistral-embed"):
        self.model = model
        self.client = mistral_client

        # Flatten sentences
        self.sentences = [
            s for p in paragraphs_with_sentences for s in p.get_all_sentences()
        ]

        texts = [s.text for s in self.sentences]
        resp = self.client.embeddings.create(model=self.model, inputs=texts)
        vecs = np.array([item.embedding for item in resp.data], dtype="float32")

        self.embeddings = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)

    def retrieve_sentences(self, query, top_k):
        resp = self.client.embeddings.create(model=self.model, inputs=[query])
        qvec = np.array(resp.data[0].embedding, dtype="float32").reshape(1, -1)
        qvec = qvec / (np.linalg.norm(qvec) + 1e-10)

        scores = np.dot(self.embeddings, qvec.T).flatten()
        idxs = scores.argsort()[::-1][:top_k]

        out = []
        for i in idxs:
            s = self.sentences[i]
            out.append({
                "title": s.title,
                "sentence": s.text,
                "sentence_idx": s.sent_idx,
                "score": float(scores[i])
            })
        return out


def context_window_expand(sentences, paragraphs_with_sentences, window=1):
    """
    Expand each retrieved sentence into a window.
    """
    title_map = {p.title: p for p in paragraphs_with_sentences}
    seen = set()
    chunks = []

    for s in sentences:
        title = s["title"]
        idx = s["sentence_idx"]

        para = title_map[title]
        all_s = para.sentences

        start = max(0, idx - window)
        end = min(len(all_s), idx + window + 1)
        key = (title, start, end)

        if key in seen:
            continue
        seen.add(key)

        chunks.append({
            "title": title,
            "text": " ".join(all_s[start:end]),
            "core_sentence_idx": idx,
            "score": s["score"]
        })

    return chunks


class SentenceWindowRetriever:
    """
    Plug-in retriever for sentence-window experiments.
    """

    def __init__(self, expanded_chunks):
        self.chunks = expanded_chunks

    def retrieve(self, query, top_k):
        out = []
        for i, c in enumerate(self.chunks[:top_k]):
            out.append(Paragraph(pid=i, title=c["title"], text=c["text"]))
        return out

    def get_supporting_facts(self):
        return [[c["title"], c["core_sentence_idx"]] for c in self.chunks]


