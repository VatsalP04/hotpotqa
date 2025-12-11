from typing import List, Tuple


def build_planning_prompt(question: str) -> str:

    prompt_parts = [
        "Break down the question into the MINIMUM number of simple factual steps needed to answer it.",
        "Use ONLY 1-3 subqueries. Use 1 subquery if the question can be answered directly.",
        "Use 2-3 subqueries ONLY if the question requires multiple steps.",
        "",
        "CRITICAL: Order steps so each can be answered BEFORE the next one needs it.",
        "Use [ANSWER_1], [ANSWER_2], etc. as placeholders for answers from earlier steps.",
        "",
        "Output ONLY numbered subqueries, one per line, in the exact format shown below.",
        "Do not include any additional text before or after the numbered list.",
        "",
        "Example 1 (1 subquery - direct question):",
        "Q: What is the capital of France?",
        "1. What is the capital of France? [ANSWER_1]",
        "",
        "Example 2 (2 subqueries - needs one intermediate step):",
        "Q: What year was the university founded where Albert Einstein worked?",
        "1. Where did Albert Einstein work? [ANSWER_1]",
        "2. What year was [ANSWER_1] founded? [ANSWER_2]",
        "",
        "Example 3 (3 subqueries - needs two intermediate steps):",
        "Q: Which river flows through the capital of the country where Kyoto is located?",
        "1. In which country is Kyoto located? [ANSWER_1]",
        "2. What is the capital of [ANSWER_1]? [ANSWER_2]",
        "3. Which river flows through [ANSWER_2]? [ANSWER_3]",
        "",
        f"Q: {question}",
    ]

    return "\n".join(prompt_parts)


def build_subanswer_prompt(sub_question: str, context: List[str]) -> str:
    prompt_parts = [
        "Answer the question using ONLY the provided context.",
        "Give a VERY SHORT answer (a few words) using the exact wording from the context. Do not explain.",
        "CRITICAL: You must provide an answer. Never say 'I don't know', 'idk', 'answer not provided', 'no information', or similar phrases.",
        "If the answer is not explicitly in the context, make your best guess based on the context provided.",
        "",
        "Context:",
    ]

    for i, para in enumerate(context, 1):
        prompt_parts.append(f"[{i}] {para}")

    prompt_parts.extend([
        "",
        f"Question: {sub_question}",
        "",
        "Answer:",
    ])

    return "\n".join(prompt_parts)


def build_final_answer_prompt(question: str, sub_qa_history: List[Tuple[str, str]]) -> str:
    prompt_parts = [
        "Answer the main question using ONLY the facts below.",
        "Give a SHORT answer (a few words). Do not explain.",
        "CRITICAL: You must provide an answer. Never say 'I don't know', 'idk', 'answer not provided', 'no information', 'there is no information', or similar phrases.",
        "If the answer is not explicitly in the facts, make your best guess based on the facts provided.",
        "",
        f"Main Question: {question}",
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