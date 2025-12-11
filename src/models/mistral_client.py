"""
Mistral API Client for HotpotQA project.

This module provides a wrapper around the Mistral API for easy integration
with the question answering pipeline.
"""

from typing import Optional, List, Dict, Any
from mistralai import Mistral

from ..config import (
    MISTRAL_API_KEY,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    validate_config,
)


class MistralClient:
    """
    Wrapper class for Mistral API interactions.
    
    Provides convenient methods for question answering and other NLP tasks.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """
        Initialize the Mistral client.
        
        Args:
            api_key: Mistral API key. If None, uses MISTRAL_API_KEY from config.
            model: Model name to use. If None, uses DEFAULT_MODEL from config.
            temperature: Sampling temperature. If None, uses DEFAULT_TEMPERATURE.
            max_tokens: Maximum tokens to generate. If None, uses DEFAULT_MAX_TOKENS.
        """
        self.api_key = api_key or MISTRAL_API_KEY
        if not self.api_key:
            validate_config()  # Will raise error if not set
        
        self.client = Mistral(api_key=self.api_key)
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature if temperature is not None else DEFAULT_TEMPERATURE
        self.max_tokens = max_tokens or DEFAULT_MAX_TOKENS
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to Mistral API.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys.
            model: Override default model for this request.
            temperature: Override default temperature for this request.
            max_tokens: Override default max_tokens for this request.
            **kwargs: Additional parameters to pass to the API.
        
        Returns:
            API response dictionary.
        """
        # Mistral API accepts simple dict messages directly
        response = self.client.chat.complete(
            model=model or self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            **kwargs
        )
        
        return {
            "content": response.choices[0].message.content,
            "role": response.choices[0].message.role,
            "finish_reason": response.choices[0].finish_reason,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "model": response.model,
        }
    
    def answer_question(
        self,
        question: str,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Answer a question, optionally with context.
        
        Args:
            question: The question to answer.
            context: Optional context to provide to the model.
            system_prompt: Optional system prompt to guide the model.
            **kwargs: Additional parameters for the chat method.
        
        Returns:
            The answer string.
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        user_content = question
        if context:
            user_content = f"Context:\n{context}\n\nQuestion: {question}"
        
        messages.append({"role": "user", "content": user_content})
        
        response = self.chat(messages, **kwargs)
        return response["content"]
    
    def embed(
        self,
        texts: List[str],
        model: str = "mistral-embed"
    ) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of text strings to embed.
            model: Embedding model to use (default: mistral-embed).
        
        Returns:
            List of embedding vectors (each vector is a list of floats).
        """
        if not texts:
            return []
        
        response = self.client.embeddings.create(
            model=model,
            inputs=texts
        )
        
        return [data.embedding for data in response.data]

# Convenience function for quick access
def get_mistral_client(**kwargs) -> MistralClient:
    """Get a configured MistralClient instance."""
    return MistralClient(**kwargs)


if __name__ == "__main__":
    # Test the client
    try:
        client = get_mistral_client()
        print("✅ Mistral client initialized successfully!")
        print(f"   Model: {client.model}")
        print(f"   Temperature: {client.temperature}")
        print(f"   Max Tokens: {client.max_tokens}")
        
        # Test with a simple question
        print("\n🧪 Testing API with a simple question...")
        answer = client.answer_question("What is 2+2?")
        print(f"   Answer: {answer}")
    except Exception as e:
        print(f"❌ Error: {e}")

