"""
Configuration for Query Decomposition method.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DecompositionConfig:
    """Configuration for decomposition-based reasoning."""
    
    k_retrieve: int = 2
    max_sub_questions: int = 5
    
    temperature: float = 0.2
    max_tokens_subq: int = 100
    max_tokens_suba: int = 50
    max_tokens_final: int = 100

    use_relaxed_prompt_initial: bool = False
    
    enable_search_query_fallback: bool = True
    enable_relaxed_prompt_fallback: bool = True
    
    self_consistency_enabled: bool = False
    self_consistency_num_samples: int = 1
    self_consistency_temperatures: List[float] = field(default_factory=lambda: [0.6])
    
    @classmethod
    def relaxed_initial(cls) -> "DecompositionConfig":
        """
        Ablation: Use relaxed prompt (no NOT_FOUND option) as initial answering.
        No fallbacks needed since we always get an answer.
        """
        return cls(
            use_relaxed_prompt_initial=True,
            enable_search_query_fallback=False,
            enable_relaxed_prompt_fallback=False,
            self_consistency_enabled=False,
        )
    
    @classmethod
    def notfound_no_fallback(cls) -> "DecompositionConfig":
        """
        Ablation: Use NOT_FOUND prompt, no fallbacks.
        If NOT_FOUND is returned, keep it as the answer.
        """
        return cls(
            use_relaxed_prompt_initial=False,
            enable_search_query_fallback=False,
            enable_relaxed_prompt_fallback=False,
            self_consistency_enabled=False,
        )
    
    @classmethod
    def notfound_direct_relaxed(cls) -> "DecompositionConfig":
        """
        Ablation: Use NOT_FOUND prompt, directly fallback to relaxed prompt.
        If NOT_FOUND -> use relaxed prompt (no search query in between).
        """
        return cls(
            use_relaxed_prompt_initial=False,
            enable_search_query_fallback=False,
            enable_relaxed_prompt_fallback=True,
            self_consistency_enabled=False,
        )
    
    @classmethod
    def notfound_with_search_fallback(cls) -> "DecompositionConfig":
        """
        Ablation: Use NOT_FOUND prompt, fallback with search query rewrite only.
        If NOT_FOUND -> generate search query -> reattempt with NOT_FOUND prompt.
        No relaxed prompt fallback.
        """
        return cls(
            use_relaxed_prompt_initial=False,
            enable_search_query_fallback=True,
            enable_relaxed_prompt_fallback=False,
            self_consistency_enabled=False,
        )
    
    @classmethod
    def full_pipeline(cls) -> "DecompositionConfig":
        """
        Ablation: Full pipeline with all fallbacks.
        NOT_FOUND prompt -> search query fallback -> relaxed prompt fallback.
        """
        return cls(
            use_relaxed_prompt_initial=False,
            enable_search_query_fallback=True,
            enable_relaxed_prompt_fallback=True,
            self_consistency_enabled=False,
        )
    
    @classmethod
    def full_with_self_consistency(cls, num_samples: int = 5, temperature: float = 0.6) -> "DecompositionConfig":
        """Full pipeline + self-consistency."""
        return cls(
            use_relaxed_prompt_initial=False,
            enable_search_query_fallback=True,
            enable_relaxed_prompt_fallback=True,
            self_consistency_enabled=True,
            self_consistency_num_samples=num_samples,
            self_consistency_temperatures=[temperature],
        )

