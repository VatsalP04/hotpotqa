"""
Tokenization utilities for HotpotQA.

This module provides wrappers around different tokenizers (HuggingFace, spaCy, NLTK)
with a unified interface for easy switching between tokenization strategies.
"""

import logging
from typing import Dict, List, Any, Optional, Union
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseTokenizer(ABC):
    """Abstract base class for tokenizers."""

    @abstractmethod
    def tokenize(self, text: str) -> List[str]:
        """Tokenize text into tokens."""
        pass

    @abstractmethod
    def encode(self, text: str, **kwargs) -> Dict[str, Any]:
        """Encode text into model inputs."""
        pass

    @abstractmethod
    def decode(self, token_ids: List[int], **kwargs) -> str:
        """Decode token IDs back to text."""
        pass


class HuggingFaceTokenizer(BaseTokenizer):
    """
    Wrapper around HuggingFace transformers tokenizers.

    Supports all tokenizers from the transformers library.
    """

    def __init__(
        self,
        model_name: str = "bert-base-uncased",
        max_length: int = 512,
        truncation: bool = True,
        padding: Union[str, bool] = "max_length",
        add_special_tokens: bool = True,
        return_tensors: Optional[str] = None
    ):
        """
        Initialize HuggingFace tokenizer.

        Args:
            model_name: Name of the pretrained model/tokenizer
            max_length: Maximum sequence length
            truncation: Whether to truncate sequences
            padding: Padding strategy ('max_length', 'longest', True, False)
            add_special_tokens: Whether to add special tokens ([CLS], [SEP], etc.)
            return_tensors: Return type ('pt', 'tf', 'np', or None)
        """
        try:
            from transformers import AutoTokenizer
        except ImportError:
            raise ImportError(
                "HuggingFace transformers not installed. "
                "Install with: pip install transformers"
            )

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model_name = model_name
        self.max_length = max_length
        self.truncation = truncation
        self.padding = padding
        self.add_special_tokens = add_special_tokens
        self.return_tensors = return_tensors

        logger.info(f"Initialized HuggingFace tokenizer: {model_name}")

    def tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into tokens.

        Args:
            text: Input text

        Returns:
            List of tokens
        """
        return self.tokenizer.tokenize(text)

    def encode(
        self,
        text: str,
        text_pair: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Encode text into model inputs.

        Args:
            text: Primary input text
            text_pair: Optional second text (for pair classification)
            **kwargs: Additional arguments passed to tokenizer

        Returns:
            Dictionary with input_ids, attention_mask, etc.
        """
        # Merge default kwargs with provided kwargs
        encode_kwargs = {
            'max_length': self.max_length,
            'truncation': self.truncation,
            'padding': self.padding,
            'add_special_tokens': self.add_special_tokens,
            'return_tensors': self.return_tensors,
        }
        encode_kwargs.update(kwargs)

        return self.tokenizer(text, text_pair, **encode_kwargs)

    def decode(self, token_ids: List[int], skip_special_tokens: bool = True) -> str:
        """
        Decode token IDs back to text.

        Args:
            token_ids: List of token IDs
            skip_special_tokens: Whether to remove special tokens

        Returns:
            Decoded text
        """
        return self.tokenizer.decode(token_ids, skip_special_tokens=skip_special_tokens)

    def batch_encode(
        self,
        texts: List[str],
        text_pairs: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Encode multiple texts in batch.

        Args:
            texts: List of input texts
            text_pairs: Optional list of second texts
            **kwargs: Additional arguments

        Returns:
            Batched encoding dictionary
        """
        encode_kwargs = {
            'max_length': self.max_length,
            'truncation': self.truncation,
            'padding': self.padding,
            'add_special_tokens': self.add_special_tokens,
            'return_tensors': self.return_tensors,
        }
        encode_kwargs.update(kwargs)

        return self.tokenizer(texts, text_pairs, **encode_kwargs)


class SpacyTokenizer(BaseTokenizer):
    """
    Wrapper around spaCy tokenizer.

    Provides linguistic features like POS tags, dependencies, etc.
    """

    def __init__(self, model_name: str = "en_core_web_sm"):
        """
        Initialize spaCy tokenizer.

        Args:
            model_name: Name of the spaCy model
        """
        try:
            import spacy
        except ImportError:
            raise ImportError(
                "spaCy not installed. Install with: pip install spacy && "
                "python -m spacy download en_core_web_sm"
            )

        try:
            self.nlp = spacy.load(model_name)
        except OSError:
            logger.warning(f"spaCy model '{model_name}' not found. Downloading...")
            import subprocess
            subprocess.run(["python", "-m", "spacy", "download", model_name])
            self.nlp = spacy.load(model_name)

        self.model_name = model_name
        logger.info(f"Initialized spaCy tokenizer: {model_name}")

    def tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into tokens.

        Args:
            text: Input text

        Returns:
            List of tokens
        """
        doc = self.nlp(text)
        return [token.text for token in doc]

    def encode(self, text: str, **kwargs) -> Dict[str, Any]:
        """
        Encode text with linguistic features.

        Args:
            text: Input text
            **kwargs: Additional arguments (unused)

        Returns:
            Dictionary with tokens and linguistic features
        """
        doc = self.nlp(text)
        return {
            'tokens': [token.text for token in doc],
            'pos_tags': [token.pos_ for token in doc],
            'lemmas': [token.lemma_ for token in doc],
            'is_stop': [token.is_stop for token in doc],
            'entities': [(ent.text, ent.label_) for ent in doc.ents],
        }

    def decode(self, token_ids: List[int], **kwargs) -> str:
        """
        spaCy doesn't use token IDs, so this joins tokens.

        Args:
            token_ids: List of tokens (not IDs)
            **kwargs: Additional arguments

        Returns:
            Joined text
        """
        if isinstance(token_ids[0], str):
            return " ".join(token_ids)
        else:
            raise ValueError("SpacyTokenizer.decode expects string tokens, not IDs")


class NLTKTokenizer(BaseTokenizer):
    """
    Wrapper around NLTK tokenizers.

    Simple and lightweight tokenization suitable for classical ML models.
    """

    def __init__(self, method: str = "word"):
        """
        Initialize NLTK tokenizer.

        Args:
            method: Tokenization method ('word', 'wordpunct', 'sent')
        """
        try:
            import nltk
        except ImportError:
            raise ImportError("NLTK not installed. Install with: pip install nltk")

        # Download required data
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            logger.info("Downloading NLTK punkt tokenizer...")
            nltk.download('punkt', quiet=True)
            nltk.download('punkt_tab', quiet=True)

        self.method = method
        self.nltk = nltk
        logger.info(f"Initialized NLTK tokenizer: {method}")

    def tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into tokens.

        Args:
            text: Input text

        Returns:
            List of tokens
        """
        if self.method == "word":
            return self.nltk.word_tokenize(text)
        elif self.method == "wordpunct":
            return self.nltk.wordpunct_tokenize(text)
        elif self.method == "sent":
            return self.nltk.sent_tokenize(text)
        else:
            raise ValueError(f"Unknown method: {self.method}")

    def encode(self, text: str, **kwargs) -> Dict[str, Any]:
        """
        Encode text into tokens.

        Args:
            text: Input text
            **kwargs: Additional arguments (unused)

        Returns:
            Dictionary with tokens
        """
        return {
            'tokens': self.tokenize(text),
        }

    def decode(self, tokens: List[str], **kwargs) -> str:
        """
        Decode tokens back to text.

        Args:
            tokens: List of tokens
            **kwargs: Additional arguments

        Returns:
            Joined text
        """
        return " ".join(tokens)


def get_tokenizer(
    tokenizer_type: str = "huggingface",
    **kwargs
) -> BaseTokenizer:
    """
    Factory function to create a tokenizer.

    Args:
        tokenizer_type: Type of tokenizer ('huggingface', 'spacy', 'nltk')
        **kwargs: Arguments passed to the tokenizer constructor

    Returns:
        Tokenizer instance

    Example:
        >>> tokenizer = get_tokenizer('huggingface', model_name='bert-base-uncased')
        >>> encoded = tokenizer.encode("What is the capital of France?")
    """
    tokenizer_type = tokenizer_type.lower()

    if tokenizer_type == "huggingface" or tokenizer_type == "hf":
        return HuggingFaceTokenizer(**kwargs)
    elif tokenizer_type == "spacy":
        return SpacyTokenizer(**kwargs)
    elif tokenizer_type == "nltk":
        return NLTKTokenizer(**kwargs)
    else:
        raise ValueError(
            f"Unknown tokenizer type: {tokenizer_type}. "
            f"Choose from: 'huggingface', 'spacy', 'nltk'"
        )


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)

    text = "What is the capital of France? Paris is the capital."

    print("Testing tokenizers...")
    print(f"Input text: {text}\n")

    # Test HuggingFace tokenizer
    try:
        print("--- HuggingFace Tokenizer ---")
        hf_tokenizer = get_tokenizer("huggingface", model_name="bert-base-uncased")
        tokens = hf_tokenizer.tokenize(text)
        print(f"Tokens: {tokens}")
        encoded = hf_tokenizer.encode(text, return_tensors=None)
        print(f"Encoded keys: {encoded.keys()}")
        print(f"Input IDs shape: {len(encoded['input_ids'])}")
        decoded = hf_tokenizer.decode(encoded['input_ids'])
        print(f"Decoded: {decoded}\n")
    except ImportError as e:
        print(f"Skipping HuggingFace: {e}\n")

    # Test NLTK tokenizer
    try:
        print("--- NLTK Tokenizer ---")
        nltk_tokenizer = get_tokenizer("nltk", method="word")
        tokens = nltk_tokenizer.tokenize(text)
        print(f"Tokens: {tokens}")
        encoded = nltk_tokenizer.encode(text)
        print(f"Encoded tokens: {encoded['tokens']}\n")
    except ImportError as e:
        print(f"Skipping NLTK: {e}\n")

    print("✅ Tokenizer module working!")
