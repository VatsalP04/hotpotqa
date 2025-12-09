"""
Adapters for reasoning methods.

Provides a unified interface for different reasoning methods.
Uses BM25 retrieval by default (no embedding API calls required).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from src.reasoning.core.types import Context, Paragraph
from src.reasoning.core.llm import create_llm_client
from src.reasoning.core.retriever import BM25Retriever, DenseRetriever, IRCoTRetriever

from src.reasoning.methods.ircot import IRCoTSystem, IRCoTConfig, load_default_demos
from src.reasoning.methods.decomposition import DecompositionReasoner, DecompositionConfig
from src.reasoning.methods.simple_cot import SimpleCoTReasoner, SimpleCoTConfig

from .runner import MethodResult

logger = logging.getLogger(__name__)


# =============================================================================
# IRCoT Adapter (BM25 by default)
# =============================================================================

class IRCoTAdapter:
    """
    Adapter for IRCoT method.
    
    Uses BM25 retrieval by default for efficiency (no embedding API calls).
    Set use_dense=True to use embedding-based retrieval.
    """
    
    def __init__(
        self,
        config: Optional[IRCoTConfig] = None,
        use_dense: bool = False,
    ):
        self.config = config or IRCoTConfig()
        self.use_dense = use_dense
        self._system = None
        self._demos = None
        self._base_retriever = None
    
    def _init_system(self, context: Context):
        """Initialize IRCoT system with retriever for this context."""
        # Load demos once
        if self._demos is None:
            self._demos = load_default_demos(self.config.num_few_shot_examples)
        
        # Create retriever based on preference
        if self.use_dense:
            # Dense retrieval requires embeddings (API calls)
            from src.reasoning.core.embeddings import MistralEmbeddings, CachedEmbeddings
            embeddings = CachedEmbeddings(MistralEmbeddings(api_key=self.config.mistral_api_key))
            base_retriever = DenseRetriever(embeddings)
        else:
            # BM25 - no API calls, faster
            base_retriever = BM25Retriever()
        
        # Wrap in IRCoTRetriever for state tracking
        retriever = IRCoTRetriever(base_retriever, self.config.max_total_paragraphs)
        
        # Create system
        self._system = IRCoTSystem(
            self.config,
            self._demos,
            retriever=retriever,
        )
    
    def answer(self, question: str, context: Context) -> MethodResult:
        """Answer a question using IRCoT."""
        # Initialize system with fresh retriever for this context
        self._init_system(context)
        
        # Reset usage stats
        if hasattr(self._system.llm, 'reset_usage_stats'):
            self._system.llm.reset_usage_stats()
        if hasattr(self._system.qa_reader.llm, 'reset_usage_stats'):
            self._system.qa_reader.llm.reset_usage_stats()
        
        # Run IRCoT
        result = self._system.answer(question, context, use_interleaved=True)
        
        # Get token usage
        stats = self._system.stats
        
        # Get retrieval info from the retriever
        retriever = self._system.retriever
        first_titles = retriever.first_retrieval_titles if hasattr(retriever, 'first_retrieval_titles') else []
        num_steps = len(retriever.history) if hasattr(retriever, 'history') else result.num_steps
        
        return MethodResult(
            answer=result.answer,
            reasoning_chain=result.reasoning_chain,
            retrieved_titles=[p.title for p in result.retrieved_paragraphs],
            first_retrieved_titles=first_titles,
            num_retrieval_steps=num_steps,
            input_tokens=stats.get('input_tokens', 0),
            output_tokens=stats.get('output_tokens', 0),
            embedding_tokens=stats.get('embedding_tokens', 0),
            processing_time=result.processing_time,
        )


# =============================================================================
# Decomposition Adapter (BM25 by default)
# =============================================================================

class DecompositionAdapter:
    """
    Adapter for Query Decomposition method.
    
    Uses BM25 retrieval by default for efficiency.
    """
    
    def __init__(
        self,
        config: Optional[DecompositionConfig] = None,
        use_dense: bool = False,
    ):
        self.config = config or DecompositionConfig()
        self.use_dense = use_dense
        self._llm = None
        self._embeddings = None
    
    def _init_components(self):
        """Lazy initialization of LLM."""
        if self._llm is None:
            self._llm = create_llm_client()
    
    def _create_retriever(self, context: Context):
        """Create and index a retriever for the given context."""
        if self.use_dense:
            from src.reasoning.core.embeddings import MistralEmbeddings, CachedEmbeddings
            if self._embeddings is None:
                self._embeddings = CachedEmbeddings(MistralEmbeddings())
            retriever = DenseRetriever(self._embeddings)
        else:
            retriever = BM25Retriever()
        
        retriever.index(context)
        return retriever
    
    def answer(self, question: str, context: Context) -> MethodResult:
        """Answer a question using decomposition."""
        self._init_components()
        
        # Reset usage stats
        if hasattr(self._llm, 'reset_usage_stats'):
            self._llm.reset_usage_stats()
        
        # Create retriever
        base_retriever = self._create_retriever(context)
        
        # Track retrieval info
        retrieval_tracker = RetrievalTracker()
        
        class RetrieverWrapper:
            """Wrapper to match expected interface and track retrievals."""
            def __init__(self, retriever, tracker):
                self._retriever = retriever
                self._tracker = tracker
                self._first_retrieval_done = False
            
            def retrieve(self, query: str, top_k: int) -> List[Paragraph]:
                results = self._retriever.retrieve(query, k=top_k)
                paragraphs = [r.paragraph for r in results]
                
                # Track retrieval
                self._tracker.add_retrieval([p.title for p in paragraphs])
                if not self._first_retrieval_done:
                    self._tracker.set_first_retrieval([p.title for p in paragraphs])
                    self._first_retrieval_done = True
                
                return paragraphs
        
        retriever = RetrieverWrapper(base_retriever, retrieval_tracker)
        
        # Create reasoner and run
        reasoner = DecompositionReasoner(retriever, self._llm, self.config)
        result = reasoner.run(question)
        
        # Get token usage
        usage = {}
        if hasattr(self._llm, 'get_usage_stats'):
            usage = self._llm.get_usage_stats()
        
        # Build reasoning chain from sub-QAs with search queries
        reasoning_parts = []
        all_search_queries = []
        not_found_count = 0
        
        for sub_qa in result.sub_qas:
            reasoning_parts.append(f"Q: {sub_qa.question}")
            if sub_qa.search_queries:
                reasoning_parts.append(f"  Search Queries: {', '.join(sub_qa.search_queries)}")
                all_search_queries.extend(sub_qa.search_queries)
            reasoning_parts.append(f"A: {sub_qa.answer}")
            if sub_qa.answer.strip().upper() == "NOT_FOUND":
                not_found_count += 1
        reasoning_chain = "\n".join(reasoning_parts)
        
        return MethodResult(
            answer=result.final_answer,
            reasoning_chain=reasoning_chain,
            retrieved_titles=result.all_retrieved_titles,
            first_retrieved_titles=retrieval_tracker.first_retrieval,
            num_retrieval_steps=retrieval_tracker.num_retrievals,
            input_tokens=usage.get('input_tokens', 0),
            output_tokens=usage.get('output_tokens', 0),
            embedding_tokens=usage.get('embedding_tokens', 0),
            extra={
                "sub_qas": [
                    {
                        "question": sqa.question,
                        "answer": sqa.answer,
                        "retrieved_titles": sqa.retrieved_titles,
                        "search_queries": sqa.search_queries,
                        "is_not_found": sqa.answer.strip().upper() == "NOT_FOUND",
                    }
                    for sqa in result.sub_qas
                ],
                "not_found_count": not_found_count,
                "all_search_queries": all_search_queries,
            },
        )


# =============================================================================
# SimpleCoT Adapter (BM25 by default)
# =============================================================================

class SimpleCoTAdapter:
    """
    Adapter for Simple Chain-of-Thought method.
    
    Uses BM25 retrieval by default for efficiency.
    """
    
    def __init__(
        self,
        config: Optional[SimpleCoTConfig] = None,
        use_dense: bool = False,
    ):
        self.config = config or SimpleCoTConfig()
        self.use_dense = use_dense
        self._llm = None
        self._embeddings = None
    
    def _init_components(self):
        """Lazy initialization of LLM."""
        if self._llm is None:
            self._llm = create_llm_client()
    
    def _create_retriever(self, context: Context):
        """Create and index a retriever for the given context."""
        if self.use_dense:
            from src.reasoning.core.embeddings import MistralEmbeddings, CachedEmbeddings
            if self._embeddings is None:
                self._embeddings = CachedEmbeddings(MistralEmbeddings())
            retriever = DenseRetriever(self._embeddings)
        else:
            retriever = BM25Retriever()
        
        retriever.index(context)
        return retriever
    
    def answer(self, question: str, context: Context) -> MethodResult:
        """Answer a question using SimpleCoT."""
        self._init_components()
        
        # Reset usage stats
        if hasattr(self._llm, 'reset_usage_stats'):
            self._llm.reset_usage_stats()
        
        # Create retriever
        base_retriever = self._create_retriever(context)
        
        # Wrap retriever
        class RetrieverWrapper:
            def __init__(self, retriever):
                self._retriever = retriever
            
            def retrieve(self, query: str, k: int) -> List[Paragraph]:
                results = self._retriever.retrieve(query, k=k)
                return [r.paragraph for r in results]
        
        retriever = RetrieverWrapper(base_retriever)
        
        # Create reasoner and run
        reasoner = SimpleCoTReasoner(retriever, self._llm, self.config)
        result = reasoner.run(question)
        
        # Get token usage
        usage = {}
        if hasattr(self._llm, 'get_usage_stats'):
            usage = self._llm.get_usage_stats()
        
        return MethodResult(
            answer=result.answer,
            reasoning_chain=result.reasoning_chain,
            retrieved_titles=result.retrieved_titles,
            first_retrieved_titles=result.retrieved_titles,  # SimpleCoT only has one retrieval
            num_retrieval_steps=1,
            input_tokens=usage.get('input_tokens', 0),
            output_tokens=usage.get('output_tokens', 0),
            embedding_tokens=usage.get('embedding_tokens', 0),
        )


# =============================================================================
# Helper Classes
# =============================================================================

class RetrievalTracker:
    """Track retrieval operations for metrics."""
    
    def __init__(self):
        self.all_titles: List[str] = []
        self.first_retrieval: List[str] = []
        self.num_retrievals: int = 0
    
    def add_retrieval(self, titles: List[str]):
        """Record a retrieval operation."""
        self.all_titles.extend(titles)
        self.num_retrievals += 1
    
    def set_first_retrieval(self, titles: List[str]):
        """Set the first retrieval titles."""
        self.first_retrieval = list(titles)


# =============================================================================
# Factory Functions
# =============================================================================

def create_adapter(
    method: str,
    use_dense: bool = False,
    **kwargs
):
    """
    Factory function to create method adapters.
    
    Args:
        method: "ircot", "decomposition", or "simplecot"
        use_dense: Use dense (embedding) retrieval instead of BM25
        **kwargs: Additional config arguments
    
    Returns:
        Configured adapter instance
    """
    method = method.lower()
    
    if method == "ircot":
        config = IRCoTConfig(**{k: v for k, v in kwargs.items() if hasattr(IRCoTConfig, k)})
        return IRCoTAdapter(config=config, use_dense=use_dense)
    
    elif method in ("decomposition", "querydecomposition"):
        config = DecompositionConfig(**{k: v for k, v in kwargs.items() if hasattr(DecompositionConfig, k)})
        # Ensure self-consistency is disabled
        config.self_consistency_enabled = False
        return DecompositionAdapter(config=config, use_dense=use_dense)
    
    elif method in ("simplecot", "simple_cot", "basiccot", "basic_cot"):
        config = SimpleCoTConfig(**{k: v for k, v in kwargs.items() if hasattr(SimpleCoTConfig, k)})
        return SimpleCoTAdapter(config=config, use_dense=use_dense)
    
    else:
        raise ValueError(f"Unknown method: {method}. Choose 'ircot', 'decomposition', or 'simplecot'")
