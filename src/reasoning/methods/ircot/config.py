"""
Configuration for IRCoT method.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


class ModelDefaults:
    """Default model settings."""
    MISTRAL_MODEL = "mistral-small-latest"
    MISTRAL_EMBED_MODEL = "mistral-embed"


class ReasoningDefaults:
    """Default reasoning parameters from IRCoT paper."""
    MAX_REASONING_STEPS = 7
    PARAGRAPHS_PER_RETRIEVAL = 2
    MAX_TOTAL_PARAGRAPHS = 10
    NUM_FEW_SHOT_EXAMPLES = 2


class GenerationDefaults:
    """Default generation parameters."""
    MAX_TOKENS_STEP = 150
    MAX_TOKENS_QA = 300
    TEMPERATURE = 0.0


class AnswerMarkers:
    """Answer extraction markers."""
    SO_THE_ANSWER = "so the answer is"
    THE_ANSWER_IS = "the answer is"
    THEREFORE = "therefore"


@dataclass
class IRCoTConfig:
    """
    Configuration for IRCoT system.
    
    Contains all hyperparameters for the IRCoT algorithm.
    """
    # Model settings
    mistral_api_key: str = field(default_factory=lambda: os.environ.get("MISTRAL_API_KEY", ""))
    mistral_model: str = ModelDefaults.MISTRAL_MODEL
    mistral_embed_model: str = ModelDefaults.MISTRAL_EMBED_MODEL
    
    # Reasoning parameters
    max_reasoning_steps: int = ReasoningDefaults.MAX_REASONING_STEPS
    paragraphs_per_retrieval: int = ReasoningDefaults.PARAGRAPHS_PER_RETRIEVAL
    max_total_paragraphs: int = ReasoningDefaults.MAX_TOTAL_PARAGRAPHS
    num_few_shot_examples: int = ReasoningDefaults.NUM_FEW_SHOT_EXAMPLES
    
    # Generation parameters
    max_tokens_step: int = GenerationDefaults.MAX_TOKENS_STEP
    max_tokens_qa: int = GenerationDefaults.MAX_TOKENS_QA
    temperature: float = GenerationDefaults.TEMPERATURE
    
    # System instruction
    use_system_instruction: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding API key)."""
        return {
            "mistral_model": self.mistral_model,
            "mistral_embed_model": self.mistral_embed_model,
            "max_reasoning_steps": self.max_reasoning_steps,
            "paragraphs_per_retrieval": self.paragraphs_per_retrieval,
            "max_total_paragraphs": self.max_total_paragraphs,
            "num_few_shot_examples": self.num_few_shot_examples,
            "max_tokens_step": self.max_tokens_step,
            "max_tokens_qa": self.max_tokens_qa,
            "temperature": self.temperature,
            "use_system_instruction": self.use_system_instruction,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IRCoTConfig":
        """Create config from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def get_default_config() -> IRCoTConfig:
    """Get default IRCoT configuration."""
    return IRCoTConfig()

