"""
Configuration for Query Decomposition method.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DecompositionConfig:
    """Configuration for decomposition-based reasoning."""
    
    # Retrieval
    k_retrieve: int = 2  # Paragraphs per sub-question retrieval
    max_sub_questions: int = 5  # Maximum sub-questions
    
    # LLM generation
    temperature: float = 0.2
    max_tokens_subq: int = 100  # For generating sub-questions
    max_tokens_suba: int = 50   # For generating sub-answers
    max_tokens_final: int = 100  # For final answer

    # Fallback behavior (for ablation studies)
    enable_search_query_fallback: bool = True  # Generate new search query on NOT_FOUND
    enable_relaxed_prompt_fallback: bool = True  # Use relaxed prompt (no NOT_FOUND option) after reattempt fails
    
    # Self-consistency
    self_consistency_enabled: bool = False
    self_consistency_num_samples: int = 1
    self_consistency_temperatures: List[float] = field(default_factory=lambda: [0.6])
    
    @classmethod
    def full_pipeline(cls) -> "DecompositionConfig":
        """Full pipeline: search query fallback + relaxed prompt fallback."""
        return cls(
            enable_search_query_fallback=True,
            enable_relaxed_prompt_fallback=True,
            self_consistency_enabled=False,
        )
    
    @classmethod
    def relaxed_only(cls) -> "DecompositionConfig":
        """Relaxed prompt only: skip search query, directly use relaxed prompt on NOT_FOUND."""
        return cls(
            enable_search_query_fallback=False,
            enable_relaxed_prompt_fallback=True,
            self_consistency_enabled=False,
        )
    
    @classmethod
    def full_with_self_consistency(cls, num_samples: int = 5, temperature: float = 0.6) -> "DecompositionConfig":
        """Full pipeline + self-consistency."""
        return cls(
            enable_search_query_fallback=True,
            enable_relaxed_prompt_fallback=True,
            self_consistency_enabled=True,
            self_consistency_num_samples=num_samples,
            self_consistency_temperatures=[temperature],
        )
    
    @classmethod
    def no_fallback(cls) -> "DecompositionConfig":
        """No fallback: just use NOT_FOUND as answer if not found."""
        return cls(
            enable_search_query_fallback=False,
            enable_relaxed_prompt_fallback=False,
            self_consistency_enabled=False,
        )

