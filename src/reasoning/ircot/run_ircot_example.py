"""
IRCoT Pipeline Demonstration Script

This script demonstrates the complete IRCoT (Interleaving Retrieval with Chain-of-Thought)
pipeline using production-ready components:

Components Used:
- FAISS-based dense retrieval using pre-built Wikipedia index (161 documents)
- Mistral LLM for reasoning step generation and answer synthesis
- Official few-shot prompts from the IRCoT repository
- Real HotpotQA multi-hop questions

Pipeline Flow:
1. Load few-shot demonstrations from official IRCoT prompts
2. Initialize FAISS retriever with pre-built Wikipedia index
3. Initialize Mistral LLM client for text generation
4. Run IRCoT iterative retrieval loop:
   - Start with initial retrieval based on question
   - Generate reasoning steps one sentence at a time
   - Retrieve additional documents based on each reasoning step
   - Continue until answer is found or limits reached
5. Generate comprehensive final answer using QA reader

This demonstrates the full IRCoT algorithm as described in the ACL 2023 paper,
showing how iterative retrieval guided by reasoning steps can effectively
handle complex multi-hop questions.

Usage:
    uv run python -m src.reasoning.ircot.run_ircot_example
"""

from pathlib import Path

from .config import IRCoTConfig
from .demo_loader import load_default_hotpot_demos
from .ircot import IRCoTRetriever
from .llm_client import MistralLLMClient
from .qa_reader import QAReader
from .retriever import load_faiss_retriever_from_notebooks


def main() -> None:
    config = IRCoTConfig()
    demos = load_default_hotpot_demos(max_examples=config.max_demos)
    
    print("=== IRCoT Pipeline Demo ===")
    print(f"Loaded {len(demos)} few-shot demonstrations")

    # Load FAISS retriever
    project_root = Path(__file__).resolve().parents[3]  # Go up to hotpotqa/
    notebooks_dir = project_root / "notebooks"
    
    print(f"Loading FAISS index from: {notebooks_dir}")
    retriever = load_faiss_retriever_from_notebooks(str(notebooks_dir))
    print("✅ FAISS retriever loaded successfully")

    # Initialize Mistral LLM
    llm = MistralLLMClient()
    print("✅ MistralLLMClient initialized")

    # Initialize IRCoT components
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

    # Use first demo question
    question = demos[0].question if demos else "What album was Nobody Loves You written by John Lennon released on?"
    print(f"\n=== Question ===")
    print(f"Q: {question}")

    # Run IRCoT retrieval loop
    print(f"\n=== Running IRCoT Retrieval Loop ===")
    ircot_result = ircot.run(question)

    print(f"\n=== IRCoT Chain-of-Thought Steps ===")
    if ircot_result.cot_steps:
        for i, step in enumerate(ircot_result.cot_steps, start=1):
            print(f"[{i}] {step}")
    else:
        print("No reasoning steps generated")

    print(f"\n=== Retrieved Paragraphs ({len(ircot_result.retrieved_paragraphs)}) ===")
    for i, p in enumerate(ircot_result.retrieved_paragraphs, start=1):
        print(f"{i}. {p.title}")
        print(f"   {p.text[:100]}...")

    # Generate final answer
    print(f"\n=== Generating Final Answer ===")
    qa_result = reader.answer(
        question=ircot_result.question,
        paragraphs=ircot_result.retrieved_paragraphs,
    )

    print(f"\n=== Final Results ===")
    print(f"Answer: {qa_result.answer}")
    print(f"\nFull Reasoning:")
    print(qa_result.cot)


if __name__ == "__main__":
    main()

