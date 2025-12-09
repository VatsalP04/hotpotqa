"""
IRCoT (Interleaved Retrieval Chain-of-Thought) method.

Implementation of the IRCoT algorithm from Trivedi et al. (2023).
"""

from .config import IRCoTConfig
from .system import IRCoTSystem, QAReader
from .answer_extraction import AnswerExtractor, SentenceExtractor, ExtractedAnswer
from .demo_loader import load_default_demos, load_demos_from_file

__all__ = [
    "IRCoTConfig",
    "IRCoTSystem",
    "QAReader",
    "AnswerExtractor",
    "SentenceExtractor",
    "ExtractedAnswer",
    "load_default_demos",
    "load_demos_from_file",
]

