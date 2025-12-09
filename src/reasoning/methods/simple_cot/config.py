"""
Configuration for SimpleCoT method.
"""

from dataclasses import dataclass


@dataclass
class SimpleCoTConfig:
    """Configuration for Simple Chain-of-Thought reasoning."""
    
    # Retrieval
    k_retrieve: int = 3  # Number of paragraphs to retrieve
    
    # LLM generation
    temperature: float = 0.0
    max_tokens_cot: int = 300  # Max tokens for CoT generation
    max_tokens_answer: int = 50  # Max tokens for answer generation

