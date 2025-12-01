from typing import List, Tuple


def build_planning_prompt(main_question: str) -> str:

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
        f"Q: {main_question}",
    ]

    return "\n".join(prompt_parts)


def build_subanswer_prompt(
    sub_question: str,
    retrieved_paragraphs: List[str],
) -> str:
    prompt_parts = [
        "Answer the question using ONLY the provided context.",
        "Give a VERY SHORT answer (a few words) using the exact wording from the context. Do not explain.",
        "",
        "Context:",
    ]

    for i, para in enumerate(retrieved_paragraphs, 1):
        prompt_parts.append(f"[{i}] {para}")

    prompt_parts.extend([
        "",
        f"Question: {sub_question}",
        "",
        "Answer:",
    ])

    return "\n".join(prompt_parts)


def build_final_answer_prompt(
    main_question: str,
    sub_qa_history: List[Tuple[str, str]],
) -> str:
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
