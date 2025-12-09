"""
Reasoning methods for multi-hop QA.

Available methods:
- IRCoT: Interleaved Retrieval Chain-of-Thought
- Decomposition: Query Decomposition
"""

from .ircot import IRCoTSystem, IRCoTConfig
from .decomposition import DecompositionReasoner, DecompositionConfig

__all__ = [
    "IRCoTSystem",
    "IRCoTConfig",
    "DecompositionReasoner",
    "DecompositionConfig",
]

