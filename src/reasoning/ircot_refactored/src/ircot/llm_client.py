"""
LLM Client interface for IRCoT.

Provides a clean abstraction over language model APIs with:
- Protocol-based interface for dependency injection
- Mistral implementation
- Support for system instructions and stop sequences
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract base class for language model clients."""
    
    @abstractmethod
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        """
        Generate text completion.
        
        Args:
            prompt: Input prompt
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0 = deterministic)
            stop: Stop sequences
            
        Returns:
            Generated text
        """
        pass


class MistralLLMClient(LLMClient):
    """
    Mistral API client for text generation.
    
    Wraps the Mistral API to provide the LLMClient interface.
    Handles API key resolution from environment if not provided.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mistral-small-latest",
        system_instruction: Optional[str] = None
    ):
        """
        Initialize Mistral client.
        
        Args:
            api_key: API key (or uses MISTRAL_API_KEY env var)
            model: Model identifier
            system_instruction: Optional system instruction for all requests
            
        Raises:
            ValueError: If no API key available
        """
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Mistral API key required. Set MISTRAL_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        self._model = model
        self._system_instruction = system_instruction
        self._client = None  # Lazy initialization
    
    @property
    def client(self):
        """Lazy-initialize Mistral client."""
        if self._client is None:
            from mistralai import Mistral
            self._client = Mistral(api_key=self._api_key)
        return self._client
    
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        """Generate text using Mistral API."""
        messages = []
        
        if self._system_instruction:
            messages.append({
                "role": "system",
                "content": self._system_instruction
            })
        
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        try:
            response = self.client.chat.complete(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_new_tokens,
                stop=list(stop) if stop else None,
            )
            
            text = response.choices[0].message.content
            
            # Apply stop sequences (in case API didn't handle them)
            if stop:
                for token in stop:
                    idx = text.find(token)
                    if idx != -1:
                        text = text[:idx]
                        break
            
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error generating text: {e}")
            raise


class MockLLMClient(LLMClient):
    """
    Mock LLM client for testing.
    
    Returns predefined responses for testing without API calls.
    """
    
    def __init__(self, responses: Optional[list] = None):
        """
        Initialize mock client.
        
        Args:
            responses: List of responses to return (cycled)
        """
        self._responses = responses or ["Mock response. So the answer is: test."]
        self._call_count = 0
        self._prompts = []  # Track prompts for verification
    
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        """Return mock response."""
        self._prompts.append(prompt)
        response = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return response
    
    @property
    def call_count(self) -> int:
        return self._call_count
    
    @property
    def prompts(self) -> list:
        return self._prompts


def create_llm_client(
    api_key: Optional[str] = None,
    model: str = "mistral-small-latest",
    system_instruction: Optional[str] = None,
    mock: bool = False
) -> LLMClient:
    """
    Factory function to create LLM client.
    
    Args:
        api_key: API key (optional, uses env var if not provided)
        model: Model identifier
        system_instruction: Optional system instruction
        mock: If True, return mock client for testing
        
    Returns:
        LLMClient instance
    """
    if mock:
        return MockLLMClient()
    
    return MistralLLMClient(
        api_key=api_key,
        model=model,
        system_instruction=system_instruction
    )
