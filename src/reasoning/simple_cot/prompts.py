from typing import List
from src.reasoning.ircot.retriever import Paragraph


def format_paragraphs(paragraphs: List[Paragraph]) -> str:
    blocks = []
    for p in paragraphs:
        blocks.append(f"Wikipedia Title: {p.title}\n{p.text}")
    return "\n\n".join(blocks)


def build_cot_prompt(paragraphs: List[Paragraph], question: str) -> str:
    context = format_paragraphs(paragraphs)
    prompt = f"""{context}

Question: {question}

Let's think step by step."""
    return prompt


def build_answer_prompt(paragraphs: List[Paragraph], question: str, chain_of_thought: str) -> str:
    context = format_paragraphs(paragraphs)
    prompt = f"""{context}

Question: {question}

Chain of Thought: {chain_of_thought}

Based on the chain of thought above, provide a short answer. For yes/no questions, answer only "yes" or "no". For other questions, provide the shortest answer possible (maximum a few words).

Answer:"""
    return prompt

