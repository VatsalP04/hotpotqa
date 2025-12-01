from dataclasses import dataclass


@dataclass
class DecompositionConfig:
    # Retrieval
    k_retrieve: int = 2  # Paragraphs per sub-question retrieval
    max_sub_questions: int = 5  # Maximum sub-questions before stopping
    
    # LLM generation
    temperature: float = 0.2
    max_tokens_subq: int = 100  # For generating sub-questions
    max_tokens_suba: int = 50   # For generating sub-answers (short)
    max_tokens_final: int = 100  # For final answer