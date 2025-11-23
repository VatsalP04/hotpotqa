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


class EchoLLMClient(LLMClient):
    """
    Dummy client for debugging wiring.

    It does not call a real model – replace with Mistral/OpenAI for experiments.
    """

    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        _ = (prompt, max_new_tokens, temperature, stop)
        return "This is a dummy LLM output. The answer is: DUMMY_ANSWER."


class MistralLLMClient(LLMClient):
    """
    Adapter that exposes the generic `LLMClient` interface via `MistralClient`.
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

