"""
Prompt templates for Query Decomposition method.

This module contains prompts for:
- Planning sub-questions
- Answering sub-questions
- Generating final answers
- Query rewriting for fallback retrieval
"""

from typing import List, Tuple


def build_planning_prompt(main_question: str) -> str:
    """Build prompt for planning sub-questions from a main question."""
    prompt_parts = [
        "Break down the question into simple factual steps.",
        "IMPORTANT: Order steps so each can be answered BEFORE the next one needs it.",
        "Use [ANSWER_1], [ANSWER_2], etc. as placeholders for answers from earlier steps.",
        "",
        "Example 1:",
        "Q: Which river flows through the capital of the country where Kyoto is located?",
        "1. In which country is Kyoto located? [ANSWER_1]",
        "2. What is the capital of [ANSWER_1]? [ANSWER_2]",
        "3. Which river flows through [ANSWER_2]? [ANSWER_3]",
        "",
        "Example 2:",
        "Q: Who directed the movie starring the actor who played Iron Man?",
        "1. Who played Iron Man? [ANSWER_1]",
        "2. What movie stars [ANSWER_1]? [ANSWER_2]",
        "3. Who directed [ANSWER_2]? [ANSWER_3]",
        "",
        "Example 3:",
        "Q: What year was the university founded where Albert Einstein worked?",
        "1. Where did Albert Einstein work? [ANSWER_1]",
        "2. What year was [ANSWER_1] founded? [ANSWER_2]",
        "",
        "Example 4:",
        "Q: Which company was founded earlier, SpaceX or Tesla?",
        "1. In what year was SpaceX founded? [ANSWER_1]",
        "2. In what year was Tesla founded? [ANSWER_2]",
        "3. Which year is earlier, [ANSWER_1] or [ANSWER_2]? [ANSWER_3]",
        "",
        "Example 5:",
        "Q: Which actor appeared in both Inception and The Dark Knight?",
        "1. Which actors appeared in Inception? [ANSWER_1]",
        "2. Which actors appeared in The Dark Knight? [ANSWER_2]",
        "3. Which actor appears in both [ANSWER_1] and [ANSWER_2]? [ANSWER_3]",
        "",
        "Example 6:",
        "Q: Which British author wrote the novel Frankenstein?",
        "1. Who wrote the novel Frankenstein? [ANSWER_1]",
        "2. Is [ANSWER_1] a British author? [ANSWER_2]",
        "3. Which British author wrote Frankenstein? [ANSWER_3]",
        "",
        f"Q: {main_question}",
    ]

    return "\n".join(prompt_parts)


def build_subanswer_prompt(
    sub_question: str,
    retrieved_paragraphs: List[str],
) -> str:
    """Build prompt for answering a sub-question given retrieved context."""
    prompt_parts = [
        "Answer the question using ONLY the provided context.",
        "Give a VERY SHORT answer (a few words) using the exact wording from the context. Do not explain.",
        "If the answer is not in the context, respond with the single token NOT_FOUND.",
        "",
        "Context:",
    ]

    for i, para in enumerate(retrieved_paragraphs, 1):
        prompt_parts.append(f"[{i}] {para}")

    prompt_parts.extend([
        "",
        f"Question: {sub_question}",
        "",
        "Answer (or NOT_FOUND):",
    ])

    return "\n".join(prompt_parts)


def build_final_answer_prompt(
    main_question: str,
    sub_qa_history: List[Tuple[str, str]],
) -> str:
    """Build prompt for generating final answer from sub-QA history."""
    prompt_parts = [
        "Answer the main question using ONLY the facts below.",
        "Give a SHORT answer (a few words). Do not explain.",
        "",
        f"Main Question: {main_question}",
        "",
        "Facts:",
    ]
    
    for i, (sq, sa) in enumerate(sub_qa_history, 1):
        prompt_parts.append(f"  - {sq} → {sa}")
    
    prompt_parts.extend([
        "",
        "Answer:",
    ])
    
    return "\n".join(prompt_parts)


def build_query_rewrite_prompt(
    main_question: str,
    failed_sub_question: str,
    previous_answers: List[Tuple[str, str]],
) -> str:
    """Build prompt for rewriting a query when initial retrieval fails."""
    prompt_parts = [
        "You are writing a search query to help answer a sub-question derived from a query decomposition prompt from a multi-hop QA problem.",
        "The query should be specific, include key entities, and mention any constraints (dates, nationalities, relationships).",
        "Return ONLY the query text.",
        "",
        f"Main Question: {main_question}",
        "",
        "Previously Answered Steps:",
    ]
    
    if previous_answers:
        for q, a in previous_answers:
            prompt_parts.append(f"  - {q} -> {a}")
    else:
        prompt_parts.append("  - (none)")
    
    prompt_parts.extend([
        "",
        f"Sub-question: {failed_sub_question}",
        "",
        "Search Query:",
    ])
    
    return "\n".join(prompt_parts)

