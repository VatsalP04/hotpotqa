"""
Unified LLM Client with token tracking.

Provides a clean abstraction over language model APIs with:
- Protocol-based interface for dependency injection
- Mistral implementation with native token tracking
- Support for system instructions and stop sequences
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence, Dict, List, Any

logger = logging.getLogger(__name__)

# LangSmith integration (optional)
try:
    from langsmith import traceable
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    traceable = lambda **kwargs: lambda f: f  # No-op decorator


# =============================================================================
# Token Usage Tracking
# =============================================================================

@dataclass
class TokenUsage:
    """Token usage for a single API call."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str = ""
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    call_type: str = "generation"  # "generation" or "embedding"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "call_type": self.call_type,
        }


class UsageTracker:
    """Tracks cumulative token usage across multiple API calls."""
    
    def __init__(self):
        self._usages: List[TokenUsage] = []
        self._current_question_usages: List[TokenUsage] = []
    
    def log(self, usage: TokenUsage) -> None:
        """Log a token usage record."""
        self._usages.append(usage)
        self._current_question_usages.append(usage)
    
    def start_question(self) -> None:
        """Mark the start of a new question (reset per-question tracking)."""
        self._current_question_usages = []
    
    def get_question_usage(self) -> Dict[str, int]:
        """Get token usage for current question."""
        return {
            "prompt_tokens": sum(u.prompt_tokens for u in self._current_question_usages),
            "completion_tokens": sum(u.completion_tokens for u in self._current_question_usages),
            "total_tokens": sum(u.total_tokens for u in self._current_question_usages),
            "num_calls": len(self._current_question_usages),
        }
    
    def get_total_usage(self) -> Dict[str, int]:
        """Get total token usage across all calls."""
        return {
            "prompt_tokens": sum(u.prompt_tokens for u in self._usages),
            "completion_tokens": sum(u.completion_tokens for u in self._usages),
            "total_tokens": sum(u.total_tokens for u in self._usages),
            "num_calls": len(self._usages),
        }
    
    def reset(self) -> None:
        """Reset all tracked usage."""
        self._usages = []
        self._current_question_usages = []


# =============================================================================
# LLM Client Interface
# =============================================================================

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
        """Generate text completion."""
        pass
    
    def get_usage_stats(self) -> Dict[str, int]:
        """Get cumulative token usage statistics."""
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    def reset_usage_stats(self) -> None:
        """Reset token usage counters."""
        pass


class MistralLLMClient(LLMClient):
    """
    Mistral API client with native token tracking.
    
    Extracts token usage directly from the API response.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mistral-small-latest",
        system_instruction: Optional[str] = None
    ):
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Mistral API key required. Set MISTRAL_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        self._model = model
        self._system_instruction = system_instruction
        self._client = None  # Lazy initialization
        self._usage_tracker = UsageTracker()
        
        # LangSmith configuration
        self._langsmith_enabled = (
            LANGSMITH_AVAILABLE and 
            os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate when API usage is unavailable."""
        if not text:
            return 0
        words = len(text.split())
        chars = len(text)
        return max(words, chars // 4, 1)
    
    @property
    def client(self):
        """Lazy-initialize Mistral client."""
        if self._client is None:
            from mistralai import Mistral
            self._client = Mistral(api_key=self._api_key)
        return self._client
    
    @property
    def usage_tracker(self) -> UsageTracker:
        """Get the usage tracker."""
        return self._usage_tracker
    
    @traceable(name="mistral_generate", run_type="llm")
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
            
            # Extract native token usage from Mistral response
            prompt_tokens = getattr(response.usage, "prompt_tokens", 0) if hasattr(response, "usage") else 0
            completion_tokens = getattr(response.usage, "completion_tokens", 0) if hasattr(response, "usage") else 0
            total_tokens = getattr(response.usage, "total_tokens", 0) if hasattr(response, "usage") else 0
            
            # Fallback to estimation
            if prompt_tokens == 0 and completion_tokens == 0:
                prompt_tokens = self._estimate_tokens("\n".join(m["content"] for m in messages))
                completion_tokens = self._estimate_tokens(text)
                total_tokens = prompt_tokens + completion_tokens
            
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                model=self._model,
                call_type="generation",
            )
            self._usage_tracker.log(usage)
            
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
    
    def get_usage_stats(self) -> Dict[str, int]:
        """Get cumulative token usage statistics."""
        total = self._usage_tracker.get_total_usage()
        return {
            "input_tokens": total.get("prompt_tokens", 0),
            "output_tokens": total.get("completion_tokens", 0),
            "total_tokens": total.get("total_tokens", 0),
            "embedding_tokens": 0,
        }
    
    def reset_usage_stats(self) -> None:
        """Reset token usage counters."""
        self._usage_tracker.reset()


class MockLLMClient(LLMClient):
    """Mock LLM client for testing."""
    
    def __init__(self, responses: Optional[list] = None):
        self._responses = responses or ["Mock response. So the answer is: test."]
        self._call_count = 0
        self._prompts = []
        self._usage_tracker = UsageTracker()
    
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
        
        # Simulate token usage
        usage = TokenUsage(
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(response.split()),
            total_tokens=len(prompt.split()) + len(response.split()),
            model="mock",
        )
        self._usage_tracker.log(usage)
        
        return response
    
    def get_usage_stats(self) -> Dict[str, int]:
        total = self._usage_tracker.get_total_usage()
        return {
            "input_tokens": total.get("prompt_tokens", 0),
            "output_tokens": total.get("completion_tokens", 0),
            "total_tokens": total.get("total_tokens", 0),
            "embedding_tokens": 0,
        }
    
    def reset_usage_stats(self) -> None:
        self._usage_tracker.reset()


# =============================================================================
# Factory Function
# =============================================================================

def create_llm_client(
    api_key: Optional[str] = None,
    model: str = "mistral-small-latest",
    system_instruction: Optional[str] = None,
    mock: bool = False
) -> LLMClient:
    """Factory function to create LLM client."""
    if mock:
        return MockLLMClient()
    
    return MistralLLMClient(
        api_key=api_key,
        model=model,
        system_instruction=system_instruction
    )

