"""
Prompt templates for IRCoT (Interleaved Retrieval Chain-of-Thought).

Following the official IRCoT format from Trivedi et al. (2023).
"""

from __future__ import annotations

from typing import List, Optional

from src.reasoning.core.types import CoTDemo, Paragraph


# =============================================================================
# System Instructions
# =============================================================================

SYSTEM_INSTRUCTION = """You are a helpful assistant that answers questions using step-by-step reasoning.

IMPORTANT: Follow the exact format and style of the examples provided:
1. Provide clear, step-by-step reasoning that connects information from the given paragraphs
2. Use the same writing style and structure as the examples
3. End your reasoning with "So the answer is: [ANSWER]." (exactly as shown in examples)
4. Be concise but thorough in your reasoning steps
5. If the answer is incomplete ('so the answer is' not there) generate the next step of the reasoning 

The examples show the expected format - follow them closely."""


QA_READER_SYSTEM_INSTRUCTION = """You are a helpful assistant that answers questions using complete Chain-of-Thought reasoning.

IMPORTANT: Follow the exact format and style of the examples provided:
1. If a generated Chain-of-Thought is provided, first check if it contains a clear answer
2. If an answer is found in the provided CoT, extract it and present it clearly
3. If no answer is found in the provided CoT, generate your own complete reasoning
4. Review all the provided paragraphs carefully when generating new reasoning
5. Work through the logic systematically to arrive at the answer
6. Always end your reasoning with "So the answer is: [ANSWER]." (exactly as shown in examples)

The examples show the expected format - follow them closely."""


def get_system_instruction() -> str:
    """Get the system instruction for IRCoT reasoning prompts."""
    return SYSTEM_INSTRUCTION


def get_qa_reader_system_instruction() -> str:
    """Get the system instruction for QA Reader prompts."""
    return QA_READER_SYSTEM_INSTRUCTION


# =============================================================================
# Formatting Helpers
# =============================================================================

def format_paragraph(paragraph: Paragraph) -> str:
    """Format a single paragraph in IRCoT style."""
    return f"Wikipedia Title: {paragraph.title}\n{paragraph.text}"


def format_paragraphs(paragraphs: List[Paragraph]) -> str:
    """Format multiple paragraphs in IRCoT style."""
    return "\n\n".join(format_paragraph(p) for p in paragraphs)


def format_demo(demo: CoTDemo) -> str:
    """Format a single few-shot demonstration."""
    parts = [
        format_paragraphs(demo.paragraphs),
        f"Q: {demo.question}",
        f"A: {demo.cot_answer}"
    ]
    return "\n\n".join(parts)


# =============================================================================
# Main Prompt Builders
# =============================================================================

def build_reason_prompt(
    demos: List[CoTDemo],
    paragraphs: List[Paragraph],
    question: str,
    current_cot: str = "",
    num_examples: int = 3,
    include_instruction: bool = True
) -> str:
    """
    Build prompt for a single IRCoT reasoning step.
    
    This follows the official IRCoT prompt format:
    - Optional format instruction
    - Few-shot demonstrations
    - Retrieved paragraphs
    - Question with partial CoT continuation
    """
    parts = []
    
    # Optional instruction
    if include_instruction:
        parts.append("Follow the format of the examples below. Continue the reasoning step-by-step.")
        parts.append("")
    
    # Few-shot demonstrations
    for demo in demos[:num_examples]:
        parts.append(format_demo(demo))
    
    # Current instance
    parts.append(format_paragraphs(paragraphs))
    parts.append(f"Q: {question}")
    
    # Answer prompt with optional continuation
    if current_cot.strip():
        parts.append(f"A: {current_cot} ")
    else:
        parts.append("A: ")
    
    return "\n\n".join(parts)


def build_qa_prompt(
    demos: List[CoTDemo],
    paragraphs: List[Paragraph],
    question: str,
    num_examples: int = 3,
    include_instruction: bool = True,
    interleaved_cot: Optional[str] = None
) -> str:
    """
    Build prompt for QA Reader (final answer generation).
    
    If interleaved_cot is provided, instructs the reader to extract the answer
    from it if found. Otherwise, generates new reasoning.
    """
    parts = []
    
    if include_instruction:
        parts.append(
            "Follow the format of the examples below. "
            "Provide step-by-step reasoning and end with 'So the answer is: [ANSWER].'"
        )
        parts.append("")
    
    # Few-shot demonstrations
    for demo in demos[:num_examples]:
        parts.append(format_demo(demo))
        parts.append("")  # Extra spacing between demos
    
    # Current instance
    parts.append(format_paragraphs(paragraphs))
    parts.append(f"Q: {question}")
    
    # If we have interleaved CoT, instruct to extract from it first
    if interleaved_cot and interleaved_cot.strip():
        parts.append("")
        parts.append("IMPORTANT: The following Chain-of-Thought reasoning was generated step-by-step:")
        parts.append("")
        parts.append(f"Generated CoT:\n{interleaved_cot}")
        parts.append("")
        parts.append(
            "INSTRUCTIONS:\n"
            "1. First, check if the generated CoT above contains a clear answer (look for 'So the answer is:' or similar).\n"
            "2. If an answer is found in the CoT, extract it and present it clearly with 'So the answer is: [ANSWER].'.\n"
            "3. If no clear answer is found in the CoT, generate your own complete reasoning based on the paragraphs above.\n"
            "4. Always end with 'So the answer is: [ANSWER].'"
        )
        parts.append("")
        parts.append("A: ")
    else:
        parts.append("A: Let's reason step by step. ")
    
    return "\n\n".join(parts)


def build_direct_qa_prompt(
    demos: List[CoTDemo],
    paragraphs: List[Paragraph],
    question: str,
    num_examples: int = 3
) -> str:
    """Build prompt for direct QA without CoT (baseline)."""
    from src.reasoning.methods.ircot.answer_extraction import AnswerExtractor
    
    parts = []
    
    # Demonstrations with extracted answers (not full CoT)
    for demo in demos[:num_examples]:
        parts.append(format_paragraphs(demo.paragraphs))
        parts.append(f"Q: {demo.question}")
        
        # Extract just the answer from the CoT
        result = AnswerExtractor.extract(demo.cot_answer)
        parts.append(f"A: {result.answer}")
    
    # Current instance
    parts.append(format_paragraphs(paragraphs))
    parts.append(f"Q: {question}")
    parts.append("A: ")
    
    return "\n\n".join(parts)


# =============================================================================
# Specialized Prompts
# =============================================================================

REFLECTION_TEMPLATE = """Based on your previous reasoning, evaluate whether the answer is well-supported by the evidence.

Question: {question}
Previous reasoning: {cot}
Extracted answer: {answer}

Is this answer correct and well-supported? If not, what additional information would help?
Provide a brief reflection:"""


def build_reflection_prompt(question: str, cot: str, answer: str) -> str:
    """Build prompt for self-reflective reasoning."""
    return REFLECTION_TEMPLATE.format(
        question=question,
        cot=cot,
        answer=answer
    )

