"""
LLM Client Interface for IRCoT

This module provides an abstract interface for language models used in the IRCoT pipeline.
It includes a concrete implementation for Mistral AI that adapts the existing MistralClient
to the IRCoT interface requirements.

Key Classes:
- LLMClient: Abstract base class defining the interface for LLM interactions
- MistralLLMClient: Concrete implementation using Mistral AI models

The LLMClient interface is designed specifically for IRCoT's needs:
- Single generate() method for text completion
- Support for temperature, token limits, and stop sequences
- Simple string input/output (no complex message formats)

The MistralLLMClient adapts the existing MistralClient to this interface,
handling parameter mapping and response formatting. This allows IRCoT to work
with Mistral models while maintaining a clean, swappable interface.

Usage:
    llm = MistralLLMClient()
    response = llm.generate(
        prompt="Your prompt here",
        max_new_tokens=128,
        temperature=0.2,
        stop=["answer is"]
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from src.models.mistral_client import MistralClient, get_mistral_client


class LLMClient(ABC):
    """Abstract base class for LLMs used by IRCoT and the reader."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        """Generate a text completion given a prompt."""



class MistralLLMClient(LLMClient):
    """
    Adapter that exposes the generic `LLMClient` interface via `MistralClient`.
    
    This class wraps the existing MistralClient to provide the simple interface
    required by IRCoT. It handles:
    - Parameter mapping between IRCoT and Mistral API formats
    - Response extraction and formatting
    - Stop sequence processing
    - Error handling and retries
    
    The adapter pattern allows IRCoT to use Mistral models without being tightly
    coupled to the Mistral API specifics, making it easy to swap in other LLMs.
    
    Args:
        client: Optional MistralClient instance. If None, creates one using get_mistral_client()
    """

    def __init__(self, client: Optional[MistralClient] = None):
        self.client = client or get_mistral_client()

    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        response = self.client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_new_tokens,
            stop=stop,
        )
        text = response["content"]
        if stop:
            for token in stop:
                idx = text.find(token)
                if idx != -1:
                    text = text[:idx]
                    break
        return text.strip()

