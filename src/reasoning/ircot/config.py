"""
IRCoT Configuration Module

This module defines the configuration parameters for the IRCoT (Interleaving Retrieval 
with Chain-of-Thought) algorithm. The hyperparameters are based on the optimal settings 
reported in the ACL 2023 paper.

The configuration controls:
- Retrieval behavior (how many documents to retrieve per step)
- LLM generation parameters (temperature, token limits)
- Stopping conditions and loop limits
- Few-shot demonstration settings

These parameters were tuned on HotpotQA and can be adjusted for other datasets.
"""

from dataclasses import dataclass


@dataclass
class IRCoTConfig:
    """
    Configuration for IRCoT-style retrieval and QA.

    This class contains all hyperparameters for the IRCoT algorithm, mirroring 
    the settings described in the ACL'23 paper. These parameters control the 
    iterative retrieval loop, LLM generation, and stopping conditions.
    
    Attributes:
        k_step: Number of paragraphs to retrieve at each step
        max_paragraphs: Maximum total paragraphs allowed across all steps
        max_steps: Maximum number of reasoning steps before stopping
        temperature: LLM sampling temperature (lower = more deterministic)
        max_new_tokens_reason: Token limit for each reasoning step
        max_new_tokens_reader: Token limit for final answer generation
        max_demos: Number of few-shot demonstrations to include in prompts
        use_cot_reader: Whether to use chain-of-thought for final answer
        answer_trigger: Text pattern that signals the final answer
    """

    # Retrieval
    k_step: int = 4  # K paragraphs per retrieval step
    max_paragraphs: int = 15  # Total paragraphs allowed across steps
    max_steps: int = 8  # Maximum reasoning steps

    # LLM generation
    temperature: float = 0.2
    max_new_tokens_reason: int = 128
    max_new_tokens_reader: int = 256

    # Prompting / demos
    max_demos: int = 3
    use_cot_reader: bool = True

    # Misc
    answer_trigger: str = "answer is"

