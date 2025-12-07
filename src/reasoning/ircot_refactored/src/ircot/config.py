"""
Configuration settings for IRCoT implementation.

This module provides a clean, validated configuration system with:
- Sensible defaults based on Trivedi et al. (2023)
- Validation on construction
- Predefined ablation configurations
- Clear separation of concerns (model, retrieval, generation, etc.)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from enum import Enum


# =============================================================================
# Constants - Centralized magic strings and numbers
# =============================================================================

class ModelDefaults:
    """Default model identifiers."""
    MISTRAL_CHAT = "mistral-small-latest"
    MISTRAL_EMBED = "mistral-embed"
    EMBEDDING_DIM = 1024


class ReasoningDefaults:
    """Default reasoning parameters from IRCoT paper."""
    INITIAL_RETRIEVAL_K = 2
    STEP_RETRIEVAL_K = 1
    MAX_TOTAL_PARAGRAPHS = 5
    MAX_REASONING_STEPS = 4
    NUM_FEW_SHOT_EXAMPLES = 3


class GenerationDefaults:
    """Default generation parameters."""
    TEMPERATURE = 0.0
    MAX_TOKENS = 256
    STEP_MAX_TOKENS = 100


class AnswerMarkers:
    """Markers used to detect answer in CoT."""
    PRIMARY = "So the answer is"
    ALTERNATIVES = [
        "so the answer is",
        "the answer is:",
        "the answer is",
        "answer:",
    ]


# =============================================================================
# Configuration Classes
# =============================================================================

@dataclass
class IRCoTConfig:
    """
    Configuration for the IRCoT system.
    
    All parameters are validated on construction. Invalid configurations
    raise ValueError with descriptive messages.
    
    Attributes:
        mistral_api_key: API key for Mistral (optional, can use env var)
        mistral_model: Model for text generation
        mistral_embed_model: Model for embeddings
        initial_retrieval_k: Paragraphs to retrieve initially
        step_retrieval_k: Paragraphs to retrieve per reasoning step
        max_total_paragraphs: Maximum paragraphs to accumulate
        max_reasoning_steps: Maximum CoT reasoning steps
        temperature: LLM sampling temperature
        max_tokens: Max tokens for final answer generation
        step_max_tokens: Max tokens per reasoning step
        num_few_shot_examples: Number of demonstrations in prompt
        early_stopping: Stop when answer marker is found
        use_system_instruction: Include system instruction in prompts
    """
    
    # API Settings
    mistral_api_key: str = field(
        default_factory=lambda: os.environ.get("MISTRAL_API_KEY", "")
    )
    mistral_model: str = ModelDefaults.MISTRAL_CHAT
    mistral_embed_model: str = ModelDefaults.MISTRAL_EMBED
    
    # Retrieval Settings
    initial_retrieval_k: int = ReasoningDefaults.INITIAL_RETRIEVAL_K
    step_retrieval_k: int = ReasoningDefaults.STEP_RETRIEVAL_K
    max_total_paragraphs: int = ReasoningDefaults.MAX_TOTAL_PARAGRAPHS
    
    # Reasoning Settings
    max_reasoning_steps: int = ReasoningDefaults.MAX_REASONING_STEPS
    early_stopping: bool = True
    
    # Generation Settings
    temperature: float = GenerationDefaults.TEMPERATURE
    max_tokens: int = GenerationDefaults.MAX_TOKENS
    step_max_tokens: int = GenerationDefaults.STEP_MAX_TOKENS
    
    # Few-shot Settings
    num_few_shot_examples: int = ReasoningDefaults.NUM_FEW_SHOT_EXAMPLES
    use_system_instruction: bool = True
    
    # Paths
    data_dir: str = "./data"
    output_dir: str = "./outputs"
    
    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        self._validate()
    
    def _validate(self) -> None:
        """Validate all configuration parameters."""
        if self.initial_retrieval_k < 1:
            raise ValueError("initial_retrieval_k must be at least 1")
        if self.step_retrieval_k < 0:
            raise ValueError("step_retrieval_k cannot be negative")
        if self.max_total_paragraphs < 1:
            raise ValueError("max_total_paragraphs must be at least 1")
        if self.max_reasoning_steps < 1:
            raise ValueError("max_reasoning_steps must be at least 1")
        if self.num_few_shot_examples < 0:
            raise ValueError("num_few_shot_examples cannot be negative")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary (excludes API key)."""
        return {
            "mistral_model": self.mistral_model,
            "mistral_embed_model": self.mistral_embed_model,
            "initial_retrieval_k": self.initial_retrieval_k,
            "step_retrieval_k": self.step_retrieval_k,
            "max_total_paragraphs": self.max_total_paragraphs,
            "max_reasoning_steps": self.max_reasoning_steps,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "step_max_tokens": self.step_max_tokens,
            "num_few_shot_examples": self.num_few_shot_examples,
            "early_stopping": self.early_stopping,
            "use_system_instruction": self.use_system_instruction,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IRCoTConfig":
        """Create configuration from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# =============================================================================
# Predefined Configurations
# =============================================================================

class AblationPresets(Enum):
    """Predefined configurations for ablation studies."""
    
    IRCOT_FULL = "ircot_full"
    IRCOT_K1 = "ircot_k1"
    IRCOT_K3 = "ircot_k3"
    IRCOT_STEPS2 = "ircot_steps2"
    IRCOT_STEPS6 = "ircot_steps6"
    ONE_STEP = "one_step"


ABLATION_CONFIGS: Dict[str, Dict[str, Any]] = {
    AblationPresets.IRCOT_FULL.value: {
        "initial_retrieval_k": 2,
        "step_retrieval_k": 1,
        "max_reasoning_steps": 4,
        "max_total_paragraphs": 5,
    },
    AblationPresets.IRCOT_K1.value: {
        "initial_retrieval_k": 1,
        "step_retrieval_k": 1,
        "max_reasoning_steps": 4,
        "max_total_paragraphs": 4,
    },
    AblationPresets.IRCOT_K3.value: {
        "initial_retrieval_k": 3,
        "step_retrieval_k": 1,
        "max_reasoning_steps": 4,
        "max_total_paragraphs": 6,
    },
    AblationPresets.IRCOT_STEPS2.value: {
        "initial_retrieval_k": 2,
        "step_retrieval_k": 1,
        "max_reasoning_steps": 2,
        "max_total_paragraphs": 4,
    },
    AblationPresets.IRCOT_STEPS6.value: {
        "initial_retrieval_k": 2,
        "step_retrieval_k": 1,
        "max_reasoning_steps": 6,
        "max_total_paragraphs": 8,
    },
    AblationPresets.ONE_STEP.value: {
        "initial_retrieval_k": 5,
        "step_retrieval_k": 0,
        "max_reasoning_steps": 1,
        "max_total_paragraphs": 5,
    },
}


def get_config_for_ablation(preset: str | AblationPresets) -> IRCoTConfig:
    """
    Get configuration for a specific ablation study.
    
    Args:
        preset: Ablation preset name or enum value
        
    Returns:
        Configured IRCoTConfig instance
        
    Raises:
        ValueError: If preset is unknown
    """
    if isinstance(preset, AblationPresets):
        preset = preset.value
    
    if preset not in ABLATION_CONFIGS:
        valid = list(ABLATION_CONFIGS.keys())
        raise ValueError(f"Unknown ablation preset: {preset}. Valid options: {valid}")
    
    config = IRCoTConfig()
    for key, value in ABLATION_CONFIGS[preset].items():
        setattr(config, key, value)
    
    return config


def get_default_config() -> IRCoTConfig:
    """Get default configuration."""
    return IRCoTConfig()
