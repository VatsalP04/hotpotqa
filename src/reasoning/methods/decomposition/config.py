"""
Configuration for Query Decomposition method.
"""

from dataclasses import dataclass, field
from typing import List


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

    # Self-consistency
    self_consistency_enabled: bool = False
    self_consistency_num_samples: int = 1
    self_consistency_temperatures: List[float] = field(default_factory=lambda: [0.5, 0.6, 0.7])

