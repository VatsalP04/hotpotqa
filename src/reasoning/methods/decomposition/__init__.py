"""
Query Decomposition method for multi-hop QA.

Breaks complex questions into simpler sub-questions.
"""

from .config import DecompositionConfig
from .reasoner import DecompositionReasoner

__all__ = ["DecompositionConfig", "DecompositionReasoner"]

