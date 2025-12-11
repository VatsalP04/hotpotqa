"""
sentence_retrieval.py - Complete Sentence-Level Retrieval Module

Add this file to your src/reasoning/ directory.
Then import and use in your main evaluation script.

Usage:
    from src.reasoning.sentence_retrieval import (
        OptimizedSentenceRetriever,
        CoreferenceResolver,
        SentenceChunk,
    )
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Protocol
from collections import defaultdict
import re
import math


# =============================================================================
# Data Models
# =============================================================================
@dataclass
class SentenceChunk:
    """A sentence with retrieval metadata."""
    title: str
    sentence_idx: int
    text: str
    
    # Scores
    score: float = 0.0
    bm25_score: float = 0.0
    dense_score: float = 0.0
    rerank_score: float = 0.0
    
    # Context expansion
    context_text: Optional[str] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    
    # Coreference resolved
    resolved_text: Optional[str] = None


@dataclass
class ParagraphWithSentences:
    """A paragraph split into sentences."""
    title: str
    sentences: List[str]
    resolved_sentences: Optional[List[str]] = None
    
    @property
    def full_text(self) -> str:
        return ' '.join(self.sentences)
    
    def get_sentence(self, idx: int, resolved: bool = False) -> str:
        """Get sentence by index, optionally resolved."""
        if resolved and self.resolved_sentences:
            return self.resolved_sentences[idx]
        return self.sentences[idx]


# =============================================================================
# Coreference Resolution
# =============================================================================
class CoreferenceResolver:
    """
    Resolve coreferences to make sentences self-contained.
    
    Implements two modes:
    1. Simple heuristic: Replace sentence-initial pronouns with title
    2. spaCy + coreferee: Full coreference resolution (requires installation)
    
    To use spaCy mode:
        pip install spacy coreferee
        python -m spacy download en_core_web_trf
        python -m coreferee install en
    """
    
    SUBJECT_PRONOUNS = {
        'he', 'she', 'they', 'it',
        'his', 'her', 'their', 'its', 
        'him', 'them',
        'himself', 'herself', 'itself', 'themselves'
    }
    
    def __init__(self, mode: str = 'heuristic'):
        """
        Args:
            mode: 'heuristic' (fast, simple) or 'spacy' (accurate, slow)
        """
        self.mode = mode
        self.nlp = None
        
        if mode == 'spacy':
            self._init_spacy()
    
    def _init_spacy(self):
        """Initialize spaCy with coreferee."""
        try:
            import spacy
            self.nlp = spacy.load('en_core_web_sm')
            self.nlp.add_pipe('coreferee')
            print("Loaded spaCy + coreferee for coreference resolution")
        except ImportError:
            print("WARNING: spaCy/coreferee not installed. Using heuristic mode.")
            print("Install with: pip install spacy coreferee")
            self.mode = 'heuristic'
        except Exception as e:
            print(f"WARNING: Could not load coreferee: {e}")
            self.mode = 'heuristic'
    
    def _is_person_title(self, title: str) -> bool:
        """Heuristic: check if title is likely a person's name."""
        words = title.split()
        # Person names are usually 2-4 words, all capitalized
        if len(words) < 1 or len(words) > 4:
            return False
        return all(w[0].isupper() for w in words if w)
    
    def resolve_sentence_heuristic(
        self, 
        sentence: str, 
        title: str, 
        sentence_idx: int
    ) -> str:
        """
        Simple heuristic resolution.
        Replace sentence-initial pronouns with the article title.
        """
        if sentence_idx == 0:
            # First sentence usually introduces the subject
            return sentence
        
        words = sentence.split()
        if not words:
            return sentence
        
        first_word = words[0].lower()
        
        if first_word in self.SUBJECT_PRONOUNS:
            words[0] = title
            return ' '.join(words)
        
        return sentence
    
    def resolve_paragraph(self, para: ParagraphWithSentences) -> ParagraphWithSentences:
        """
        Resolve coreferences in a paragraph.
        
        Updates para.resolved_sentences in place.
        """
        if self.mode == 'spacy' and self.nlp:
            para.resolved_sentences = self._resolve_spacy(para)
        else:
            para.resolved_sentences = [
                self.resolve_sentence_heuristic(sent, para.title, i)
                for i, sent in enumerate(para.sentences)
            ]
        
        return para
    
    def _resolve_spacy(self, para: ParagraphWithSentences) -> List[str]:
        """Use spaCy + coreferee for resolution."""
        full_text = para.full_text
        doc = self.nlp(full_text)
        
        # Get coreference chains
        resolved_text = full_text
        
        if hasattr(doc._, 'coref_chains') and doc._.coref_chains:
            # Replace pronouns with their referents
            replacements = []
            
            for chain in doc._.coref_chains:
                # Get the main mention (usually first or longest)
                main_mention = None
                for mention in chain:
                    text = doc[mention[0]:mention[-1]+1].text
                    if main_mention is None or len(text) > len(main_mention):
                        main_mention = text
                
                if main_mention:
                    for mention in chain[1:]:  # Skip the main mention
                        start = doc[mention[0]].idx
                        end = doc[mention[-1]].idx + len(doc[mention[-1]].text)
                        replacements.append((start, end, main_mention))
            
            # Apply replacements in reverse order
            for start, end, replacement in sorted(replacements, reverse=True):
                resolved_text = resolved_text[:start] + replacement + resolved_text[end:]
        
        # Re-split into sentences
        resolved_doc = self.nlp(resolved_text)
        return [sent.text for sent in resolved_doc.sents]
    
    def resolve_all(self, paragraphs: List[ParagraphWithSentences]) -> List[ParagraphWithSentences]:
        """Resolve coreferences in all paragraphs."""
        for para in paragraphs:
            self.resolve_paragraph(para)
        return paragraphs


# =============================================================================
# BM25 Index
# =============================================================================
class BM25SentenceIndex:
    """BM25 index for sentence-level retrieval."""
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.sentences: List[SentenceChunk] = []
        self.doc_freqs: Dict[str, int] = defaultdict(int)
        self.doc_lengths: List[int] = []
        self.tokenized: List[List[str]] = []
        self.avg_dl = 1.0
        self.N = 0
    
    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r'\w+', text.lower())
    
    def index(
        self, 
        sentences: List[SentenceChunk],
        use_context: bool = True,
        use_resolved: bool = False
    ):
        """
        Index sentences for BM25 search.
        
        Args:
            sentences: Sentences to index
            use_context: Index context_text (sentence + neighbors)
            use_resolved: Index resolved_text (after coref resolution)
        """
        self.sentences = sentences
        self.tokenized = []
        self.doc_lengths = []
        self.doc_freqs = defaultdict(int)
        
        for sent in sentences:
            # Select text to index
            if use_context and sent.context_text:
                text = f"{sent.title}: {sent.context_text}"
            elif use_resolved and sent.resolved_text:
                text = f"{sent.title}: {sent.resolved_text}"
            else:
                text = f"{sent.title}: {sent.text}"
            
            tokens = self._tokenize(text)
            self.tokenized.append(tokens)
            self.doc_lengths.append(len(tokens))
            
            for term in set(tokens):
                self.doc_freqs[term] += 1
        
        self.N = len(sentences)
        self.avg_dl = sum(self.doc_lengths) / self.N if self.N else 1
    
    def _idf(self, term: str) -> float:
        df = self.doc_freqs.get(term, 0)
        if df == 0:
            return 0
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)
    
    def _score(self, query_tokens: List[str], doc_idx: int) -> float:
        doc_tokens = self.tokenized[doc_idx]
        doc_len = self.doc_lengths[doc_idx]
        
        tf = defaultdict(int)
        for t in doc_tokens:
            tf[t] += 1
        
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            f = tf[term]
            idf = self._idf(term)
            num = f * (self.k1 + 1)
            denom = f + self.k1 * (1 - self.b + self.b * doc_len / self.avg_dl)
            score += idf * num / denom
        
        return score
    
    def search(self, query: str, top_k: int = 10) -> List[SentenceChunk]:
        """Search for top-k sentences."""
        query_tokens = self._tokenize(query)
        
        scores = [
            (self._score(query_tokens, i), i) 
            for i in range(self.N)
        ]
        scores.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for score, idx in scores[:top_k]:
            sent = self.sentences[idx]
            sent.bm25_score = score
            sent.score = score
            results.append(sent)
        
        return results


# =============================================================================
# Dense Index (with mock for testing)
# =============================================================================
class DenseSentenceIndex:
    """
    Dense retrieval index using embeddings.
    
    For production, pass your actual embedding function.
    """
    
    def __init__(self, embed_fn=None):
        """
        Args:
            embed_fn: Function that takes List[str] and returns List[List[float]]
                     If None, uses mock embeddings for testing.
        """
        self.embed_fn = embed_fn or self._mock_embed
        self.sentences: List[SentenceChunk] = []
        self.embeddings: List[List[float]] = []
    
    def _mock_embed(self, texts: List[str]) -> List[List[float]]:
        """Mock embedding for testing (deterministic hash-based)."""
        import hashlib
        result = []
        for text in texts:
            h = hashlib.md5(text.encode()).hexdigest()
            emb = [int(h[i:i+2], 16) / 255.0 for i in range(0, 32)]
            result.append(emb * 4)  # 128 dimensions
        return result
    
    def index(
        self,
        sentences: List[SentenceChunk],
        use_context: bool = True,
        use_resolved: bool = False
    ):
        """Index sentences using dense embeddings."""
        self.sentences = sentences
        
        texts = []
        for sent in sentences:
            if use_context and sent.context_text:
                texts.append(f"{sent.title}: {sent.context_text}")
            elif use_resolved and sent.resolved_text:
                texts.append(f"{sent.title}: {sent.resolved_text}")
            else:
                texts.append(f"{sent.title}: {sent.text}")
        
        self.embeddings = self.embed_fn(texts)
    
    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        dot = sum(x*y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x*x for x in a))
        norm_b = math.sqrt(sum(y*y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
    
    def search(self, query: str, top_k: int = 10) -> List[SentenceChunk]:
        """Search for top-k sentences using dense similarity."""
        query_emb = self.embed_fn([query])[0]
        
        scores = [
            (self._cosine_sim(query_emb, emb), i)
            for i, emb in enumerate(self.embeddings)
        ]
        scores.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for score, idx in scores[:top_k]:
            sent = self.sentences[idx]
            sent.dense_score = score
            sent.score = score
            results.append(sent)
        
        return results


# =============================================================================
# Cross-Encoder Reranker
# =============================================================================
class CrossEncoderReranker:
    """
    Rerank sentences using a cross-encoder model.
    
    For production, use sentence-transformers:
        pip install sentence-transformers
        model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    """
    
    def __init__(self, model_name: str = None):
        self.model = None
        self.model_name = model_name
        
        if model_name:
            self._load_model(model_name)
    
    def _load_model(self, model_name: str):
        """Load cross-encoder model."""
        try:
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(model_name)
            print(f"Loaded CrossEncoder: {model_name}")
        except ImportError:
            print("WARNING: sentence-transformers not installed.")
            print("Using mock reranking. Install with: pip install sentence-transformers")
    
    def rerank(
        self, 
        query: str, 
        sentences: List[SentenceChunk],
        use_resolved: bool = False
    ) -> List[SentenceChunk]:
        """
        Rerank sentences by relevance to query.
        
        Returns sentences sorted by rerank_score.
        """
        if self.model:
            return self._rerank_with_model(query, sentences, use_resolved)
        else:
            return self._rerank_mock(query, sentences, use_resolved)
    
    def _rerank_with_model(
        self,
        query: str,
        sentences: List[SentenceChunk],
        use_resolved: bool
    ) -> List[SentenceChunk]:
        """Rerank using actual cross-encoder model."""
        pairs = []
        for sent in sentences:
            text = sent.resolved_text if use_resolved and sent.resolved_text else sent.text
            pairs.append([query, text])
        
        scores = self.model.predict(pairs)
        
        for sent, score in zip(sentences, scores):
            sent.rerank_score = float(score)
        
        sentences.sort(key=lambda s: s.rerank_score, reverse=True)
        return sentences
    
    def _rerank_mock(
        self,
        query: str,
        sentences: List[SentenceChunk],
        use_resolved: bool
    ) -> List[SentenceChunk]:
        """Mock reranking using word overlap (Jaccard similarity)."""
        query_words = set(re.findall(r'\w+', query.lower()))
        
        for sent in sentences:
            text = sent.resolved_text if use_resolved and sent.resolved_text else sent.text
            sent_words = set(re.findall(r'\w+', text.lower()))
            
            intersection = len(query_words & sent_words)
            union = len(query_words | sent_words)
            sent.rerank_score = intersection / union if union > 0 else 0
        
        sentences.sort(key=lambda s: s.rerank_score, reverse=True)
        return sentences


# =============================================================================
# Main Optimized Retriever
# =============================================================================
class OptimizedSentenceRetriever:
    """
    Sentence-level retriever with multiple optimizations.
    
    Optimizations:
    1. Coreference resolution: Make sentences self-contained
    2. Context window: Embed sentences with surrounding context
    3. Hybrid retrieval: Combine BM25 + Dense
    4. Cross-encoder reranking: Rerank candidates
    
    Usage:
        retriever = OptimizedSentenceRetriever(
            paragraphs=paragraphs,
            use_coref=True,
            use_context_window=True,
            use_hybrid=True,
            use_reranking=True,
        )
        
        results = retriever.retrieve(question, top_k=10)
        supporting_facts = retriever.get_supporting_facts()
    """
    
    def __init__(
        self,
        paragraphs: List[ParagraphWithSentences],
        use_coref: bool = False,
        coref_mode: str = 'heuristic',
        use_context_window: bool = True,
        context_window_size: int = 1,
        use_hybrid: bool = False,
        bm25_weight: float = 0.3,
        dense_weight: float = 0.7,
        use_reranking: bool = False,
        reranker_model: str = None,
        embed_fn=None,
    ):
        """
        Args:
            paragraphs: List of ParagraphWithSentences
            use_coref: Enable coreference resolution
            coref_mode: 'heuristic' or 'spacy'
            use_context_window: Embed sentences with context
            context_window_size: Number of sentences before/after
            use_hybrid: Combine BM25 + Dense retrieval
            bm25_weight: Weight for BM25 in hybrid
            dense_weight: Weight for Dense in hybrid
            use_reranking: Apply cross-encoder reranking
            reranker_model: Model name for cross-encoder
            embed_fn: Custom embedding function for dense retrieval
        """
        self.paragraphs = paragraphs
        self.use_coref = use_coref
        self.use_context_window = use_context_window
        self.context_window_size = context_window_size
        self.use_hybrid = use_hybrid
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self.use_reranking = use_reranking
        
        # Internal state
        self._retrieved_sp: List[Tuple[str, int]] = []
        self._retrieved_metadata: List[Dict] = []
        
        # Apply coreference resolution
        if use_coref:
            coref = CoreferenceResolver(mode=coref_mode)
            coref.resolve_all(paragraphs)
        
        # Build sentence list
        self.sentences = self._build_sentences()
        
        # Build indices
        self.bm25_index = BM25SentenceIndex()
        self.bm25_index.index(
            self.sentences,
            use_context=use_context_window,
            use_resolved=use_coref
        )
        
        if use_hybrid:
            self.dense_index = DenseSentenceIndex(embed_fn)
            self.dense_index.index(
                self.sentences,
                use_context=use_context_window,
                use_resolved=use_coref
            )
        else:
            self.dense_index = None
        
        if use_reranking:
            self.reranker = CrossEncoderReranker(reranker_model)
        else:
            self.reranker = None
    
    def _build_sentences(self) -> List[SentenceChunk]:
        """Build SentenceChunk objects with context windows."""
        sentences = []
        
        for para in self.paragraphs:
            n = len(para.sentences)
            
            for idx, text in enumerate(para.sentences):
                # Get resolved text
                resolved = None
                if para.resolved_sentences:
                    resolved = para.resolved_sentences[idx]
                
                # Build context window
                context = None
                span_start = None
                span_end = None
                
                if self.use_context_window:
                    span_start = max(0, idx - self.context_window_size)
                    span_end = min(n, idx + self.context_window_size + 1)
                    context = ' '.join(para.sentences[span_start:span_end])
                
                sentences.append(SentenceChunk(
                    title=para.title,
                    sentence_idx=idx,
                    text=text,
                    resolved_text=resolved,
                    context_text=context,
                    span_start=span_start,
                    span_end=span_end,
                ))
        
        return sentences
    
    def retrieve(self, query: str, top_k: int = 10) -> List[SentenceChunk]:
        """
        Retrieve top-k sentences.
        
        Returns list of SentenceChunk with populated scores.
        Also updates internal supporting facts tracking.
        """
        if self.use_hybrid and self.dense_index:
            candidates = self._hybrid_retrieve(query, top_k * 3)
        else:
            candidates = self.bm25_index.search(query, top_k * 3)
        
        if self.use_reranking and self.reranker:
            candidates = self.reranker.rerank(query, candidates, use_resolved=self.use_coref)
            # Update main score to rerank score
            for sent in candidates:
                sent.score = sent.rerank_score
        
        # Take top-k
        final = candidates[:top_k]
        
        # Track supporting facts (Option 3: core sentences only)
        self._retrieved_sp = []
        self._retrieved_metadata = []
        seen = set()
        
        for sent in final:
            sp = (sent.title, sent.sentence_idx)
            if sp not in seen:
                seen.add(sp)
                self._retrieved_sp.append(sp)
                
                self._retrieved_metadata.append({
                    'title': sent.title,
                    'core_idx': sent.sentence_idx,
                    'span_start': sent.span_start,
                    'span_end': sent.span_end,
                    'text': sent.text,
                    'resolved_text': sent.resolved_text,
                    'context_text': sent.context_text,
                    'score': sent.score,
                    'bm25_score': sent.bm25_score,
                    'dense_score': sent.dense_score,
                    'rerank_score': sent.rerank_score,
                })
        
        return final
    
    def _hybrid_retrieve(self, query: str, n_candidates: int) -> List[SentenceChunk]:
        """Hybrid BM25 + Dense retrieval with score fusion."""
        bm25_results = self.bm25_index.search(query, n_candidates)
        dense_results = self.dense_index.search(query, n_candidates)
        
        # Score normalization and fusion
        scores: Dict[Tuple[str, int], Dict] = {}
        
        # Normalize BM25 scores
        bm25_scores = [s.bm25_score for s in bm25_results]
        if bm25_scores:
            bm25_max = max(bm25_scores) or 1
            bm25_min = min(bm25_scores)
            bm25_range = bm25_max - bm25_min or 1
            
            for sent in bm25_results:
                key = (sent.title, sent.sentence_idx)
                norm_score = (sent.bm25_score - bm25_min) / bm25_range
                scores[key] = {
                    'sent': sent,
                    'score': self.bm25_weight * norm_score
                }
        
        # Add dense scores (already 0-1 for cosine)
        for sent in dense_results:
            key = (sent.title, sent.sentence_idx)
            if key in scores:
                scores[key]['score'] += self.dense_weight * sent.dense_score
                scores[key]['sent'].dense_score = sent.dense_score
            else:
                scores[key] = {
                    'sent': sent,
                    'score': self.dense_weight * sent.dense_score
                }
        
        # Sort by combined score
        ranked = sorted(scores.values(), key=lambda x: x['score'], reverse=True)
        
        # Update scores and return
        results = []
        for item in ranked[:n_candidates]:
            item['sent'].score = item['score']
            results.append(item['sent'])
        
        return results
    
    def get_supporting_facts(self) -> List[Tuple[str, int]]:
        """Get predicted supporting facts (core sentences only)."""
        return self._retrieved_sp
    
    def get_metadata(self) -> List[Dict]:
        """Get detailed metadata for analysis."""
        return self._retrieved_metadata
    
    def get_context_for_llm(self) -> str:
        """Format retrieved content for LLM context."""
        parts = []
        
        # Group by title
        by_title: Dict[str, List[SentenceChunk]] = defaultdict(list)
        for meta in self._retrieved_metadata:
            title = meta['title']
            text = meta.get('context_text') or meta.get('text', '')
            by_title[title].append(text)
        
        for title, texts in by_title.items():
            # Deduplicate and join
            unique_texts = list(dict.fromkeys(texts))
            parts.append(f"[{title}]: {' '.join(unique_texts)}")
        
        return '\n\n'.join(parts)


# =============================================================================
# Convenience Function
# =============================================================================
def context_window_expand(
    sentences: List[SentenceChunk],
    paragraphs: List[ParagraphWithSentences],
    window: int = 1
) -> List[SentenceChunk]:
    """
    Expand retrieved sentences with context windows.
    
    Utility function for use with existing retrievers.
    """
    para_map = {p.title: p for p in paragraphs}
    
    for sent in sentences:
        para = para_map.get(sent.title)
        if not para:
            continue
        
        n = len(para.sentences)
        start = max(0, sent.sentence_idx - window)
        end = min(n, sent.sentence_idx + window + 1)
        
        sent.span_start = start
        sent.span_end = end - 1
        sent.context_text = ' '.join(para.sentences[start:end])
    
    return sentences
