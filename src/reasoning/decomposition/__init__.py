"""
Decomposition-based Multi-hop Question Answering

This module implements a decomposition approach to multi-hop QA where:
1. The main question is broken down into sub-questions
2. Each sub-question is answered using retrieved context
3. The final answer is generated from sub-question/answer pairs only

This differs from IRCoT which uses chain-of-thought reasoning sentences
to guide retrieval. The decomposition approach explicitly generates
questions and their answers at each step.
"""

from .decomposition import (
    DecompositionReasoner,
    DecompositionResult,
    SubQA,
)
from .prompts import (
    build_planning_prompt,
    build_subanswer_prompt,
    build_final_answer_prompt,
)
from .config import DecompositionConfig

__all__ = [
    "DecompositionReasoner",
    "DecompositionResult",
    "SubQA",
    "DecompositionConfig",
]

