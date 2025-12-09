"""
Prompts for Simple Chain-of-Thought reasoning.

Follows the official HotpotQA SimpleCoT format:
1. Generate chain of thought from paragraphs and question
2. Generate final answer from chain of thought
"""

from typing import List
from src.reasoning.core.types import Paragraph


def format_paragraphs(paragraphs: List[Paragraph]) -> str:
    """
    Format paragraphs in the HotpotQA style.
    
    Format: "Wikipedia Title: {title}\n{text}"
    """
    blocks = []
    for p in paragraphs:
        blocks.append(f"Wikipedia Title: {p.title}\n{p.text}")
    return "\n\n".join(blocks)


def build_cot_prompt(paragraphs: List[Paragraph], question: str) -> str:
    """
    Build prompt for chain-of-thought generation.
    
    Args:
        paragraphs: List of Paragraph objects
        question: The question to answer
    
    Returns:
        Prompt for CoT generation
    """
    context = format_paragraphs(paragraphs)
    
    prompt = f"""{context}

Question: {question}

Let's think step by step."""
    
    return prompt


def build_answer_prompt(
    paragraphs: List[Paragraph],
    question: str,
    chain_of_thought: str
) -> str:
    """
    Build prompt for final answer generation from chain of thought.
    
    Args:
        paragraphs: List of Paragraph objects
        question: The question to answer
        chain_of_thought: The generated chain of thought
    
    Returns:
        Prompt for answer generation
    """
    context = format_paragraphs(paragraphs)
    
    prompt = f"""{context}

Question: {question}

Chain of Thought: {chain_of_thought}

Based on the chain of thought above, provide a short answer. For yes/no questions, answer only "yes" or "no". For other questions, provide the shortest answer possible (maximum a few words).

Answer:"""
    
    return prompt

