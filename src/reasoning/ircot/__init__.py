"""
Interleaving Retrieval Chain-of-Thought (IRCoT) Implementation

This module implements the IRCoT algorithm from the ACL 2023 paper:
"Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions"

IRCoT addresses the challenge of multi-hop question answering by:
1. Starting with an initial retrieval based on the question
2. Generating reasoning steps one sentence at a time
3. Retrieving additional documents based on each reasoning step
4. Continuing until a stopping condition is met (e.g., "answer is" appears)

Key Components:
- IRCoTRetriever: Core iterative retrieval + reasoning loop
- FAISSRetriever: Dense retrieval using pre-built Wikipedia FAISS index
- MistralLLMClient: LLM interface for generating reasoning steps
- CoTDemo: Few-shot demonstrations from official IRCoT prompts
- QAReader: Final answer generation from retrieved context

Usage:
    from src.reasoning.ircot import (
        IRCoTRetriever, 
        MistralLLMClient, 
        load_faiss_retriever_from_notebooks,
        load_default_hotpot_demos,
        IRCoTConfig
    )
    
    # Initialize components
    retriever = load_faiss_retriever_from_notebooks("notebooks")
    llm = MistralLLMClient()
    demos = load_default_hotpot_demos(max_examples=3)
    config = IRCoTConfig()
    
    # Run IRCoT
    ircot = IRCoTRetriever(retriever, llm, demos, config)
    result = ircot.run("Your multi-hop question here")
"""

from .config import IRCoTConfig
from .ircot import IRCoTRetriever, IRCoTResult
from .llm_client import LLMClient, MistralLLMClient
from .demo_loader import load_cot_demos_from_file, load_default_hotpot_demos
from .prompts import CoTDemo
from .qa_reader import QAReader, QAResult
from .retriever import (
    Paragraph, 
    Retriever, 
    FAISSRetriever,
    InMemoryRetriever,
    Sentence,
    ParagraphWithSentences,
    DistractorRetrieverAdapter,
    load_faiss_retriever_from_notebooks,
)

__all__ = [
    "IRCoTConfig",
    "IRCoTRetriever",
    "IRCoTResult",
    "LLMClient",
    "MistralLLMClient",
    "CoTDemo",
    "load_cot_demos_from_file",
    "load_default_hotpot_demos",
    "QAReader",
    "QAResult",
    "Paragraph",
    "Retriever",
    "FAISSRetriever",
    "InMemoryRetriever",
    "Sentence",
    "ParagraphWithSentences",
    "DistractorRetrieverAdapter",
    "load_faiss_retriever_from_notebooks",
]

