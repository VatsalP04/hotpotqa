"""
Simple Chain-of-Thought reasoning method.

A baseline method that retrieves paragraphs once and generates
a complete chain-of-thought reasoning to answer the question.
"""

from .reasoner import SimpleCoTReasoner
from .config import SimpleCoTConfig

__all__ = ["SimpleCoTReasoner", "SimpleCoTConfig"]

