"""
Minimal demo wiring for IRCoT retriever + reader using the dummy LLM client.

Swap `EchoLLMClient` for `MistralLLMClient` (or your own implementation) to
call a real model.
"""

from typing import List

from .config import IRCoTConfig
from .ircot import IRCoTRetriever
from .llm_client import EchoLLMClient
from .prompts import CoTDemo
from .qa_reader import QAReader
from .retriever import Paragraph, TfidfRetriever, build_corpus_from_texts


def build_dummy_demos(paragraphs: List[Paragraph]) -> List[CoTDemo]:
    """
    Very small synthetic demos to illustrate structure.
    Replace with real demos (few-shot examples) for actual experiments.
    """

    if len(paragraphs) < 2:
        return []

    demo1 = CoTDemo(
        paragraphs=[paragraphs[0]],
        question="Who wrote the hit song that X is most recognized for?",
        cot_answer=(
            "X is most recognized for the hit song 'Example Song'. "
            "'Example Song' was written by Example Author. "
            "So the answer is: Example Author."
        ),
    )

    demo2 = CoTDemo(
        paragraphs=[paragraphs[1]],
        question="In what country was Example Coaster manufactured?",
        cot_answer=(
            "Example Coaster was manufactured by Example Rides. "
            "Example Rides is a company from Exampleland. "
            "So the answer is: Exampleland."
        ),
    )

    return [demo1, demo2]


def main() -> None:
    texts = [
        "Example Rides is a roller coaster manufacturer based in Exampleland.",
        "Example Author wrote the hit song 'Example Song' in 1999.",
        "Another document about some unrelated topic.",
    ]
    titles = ["Example Rides", "Example Song", "Unrelated Doc"]

    paragraphs = build_corpus_from_texts(texts, titles=titles)
    retriever = TfidfRetriever(paragraphs)
    llm = EchoLLMClient()  # Swap to MistralLLMClient for real completions
    config = IRCoTConfig()
    demos = build_dummy_demos(paragraphs)

    ircot = IRCoTRetriever(
        retriever=retriever,
        llm=llm,
        demos=demos,
        config=config,
    )

    reader = QAReader(
        llm=llm,
        demos=demos,
        config=config,
    )

    question = "In what country was Example Coaster manufactured?"
    ircot_result = ircot.run(question)

    print("=== IRCoT CoT Steps ===")
    for i, s in enumerate(ircot_result.cot_steps, start=1):
        print(f"[{i}] {s}")

    print("\n=== Retrieved Paragraph Titles ===")
    for p in ircot_result.retrieved_paragraphs:
        print(f"- {p.title}")

    qa_result = reader.answer(
        question=ircot_result.question,
        paragraphs=ircot_result.retrieved_paragraphs,
    )

    print("\n=== Reader Output ===")
    print("Answer:", qa_result.answer)
    print("Full CoT / Text:\n", qa_result.cot)


if __name__ == "__main__":
    main()

