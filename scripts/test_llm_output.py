#!/usr/bin/env python3
"""
Test script to inspect LLM output for IRCoT on a single example.
This helps debug answer extraction issues.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.loader import load_hotpotqa
from src.reasoning.ircot import (
    IRCoTConfig,
    IRCoTRetriever,
    MistralLLMClient,
    QAReader,
    load_default_hotpot_demos,
    InMemoryRetriever,
    Paragraph,
    ParagraphWithSentences,
    DistractorRetrieverAdapter,
)
from src.reasoning.ircot.prompts import build_ircot_reason_prompt, build_reader_prompt_cot

def main():
    print("=" * 80)
    print("IRCoT LLM Output Inspection")
    print("=" * 80)
    
    # Load one example
    examples = load_hotpotqa(split="dev", data_dir="data/hotpotqa")
    example = examples[0]  # Use first example
    
    question = example['question']
    context = example['context']
    gold_answer = example['answer']
    
    print(f"\n📝 Question: {question}")
    print(f"✅ Gold Answer: {gold_answer}")
    print(f"\n📚 Context paragraphs: {len(context)}")
    for i, (title, sentences) in enumerate(context[:3], 1):
        print(f"   {i}. {title}: {len(sentences)} sentences")
    
    # Initialize components
    print("\n🤖 Initializing IRCoT components...")
    llm = MistralLLMClient()
    demos = load_default_hotpot_demos(max_examples=3)
    config = IRCoTConfig()
    
    # Build paragraphs from context
    paragraphs_with_sentences = [
        ParagraphWithSentences(title=title, sentences=[s.strip() for s in sent_list])
        for title, sent_list in context
    ]
    
    paragraphs_for_retriever = [
        Paragraph(pid=idx, title=p.title, text=p.full_text)
        for idx, p in enumerate(paragraphs_with_sentences)
    ]
    
    # Build retriever
    raw_mistral = llm.client.client
    memory_retriever = InMemoryRetriever(paragraphs_for_retriever, raw_mistral)
    retriever_adapter = DistractorRetrieverAdapter(
        memory_retriever,
        paragraphs_with_sentences,
        top_k_paragraphs=config.k_step
    )
    
    # Initialize IRCoT
    ircot = IRCoTRetriever(
        retriever=retriever_adapter,
        llm=llm,
        demos=demos,
        config=config,
    )
    
    print("\n" + "=" * 80)
    print("STEP 1: IRCoT Reasoning Loop")
    print("=" * 80)
    
    # Run IRCoT
    ircot_result = ircot.run(question)
    
    print(f"\n📊 CoT Steps ({len(ircot_result.cot_steps)}):")
    for i, step in enumerate(ircot_result.cot_steps, 1):
        print(f"\n   Step {i}: {step}")
        print(f"   Contains 'answer is': {'answer is' in step.lower()}")
    
    print(f"\n📚 Retrieved Paragraphs: {len(ircot_result.retrieved_paragraphs)}")
    for p in ircot_result.retrieved_paragraphs[:3]:
        print(f"   - {p.title}: {p.text[:80]}...")
    
    print("\n" + "=" * 80)
    print("STEP 2: QA Reader")
    print("=" * 80)
    
    # Generate final answer with QA reader
    reader = QAReader(llm=llm, demos=demos, config=config)
    
    # Build the prompt to see what we're sending
    prompt = build_reader_prompt_cot(
        demos=demos,
        retrieved_paragraphs=ircot_result.retrieved_paragraphs,
        question=question,
        config=config,
    )
    
    print("\n📝 QA Reader Prompt (last 1000 chars):")
    print("-" * 80)
    print(prompt[-1000:])
    print("-" * 80)
    
    # Generate answer
    qa_result = reader.answer(question, ircot_result.retrieved_paragraphs)
    
    print(f"\n🤖 QA Reader Raw Output:")
    print("-" * 80)
    print(qa_result.cot)
    print("-" * 80)
    
    print(f"\n✅ Extracted Answer: '{qa_result.answer}'")
    print(f"   Length: {len(qa_result.answer)} chars")
    print(f"   Contains 'answer is': {'answer is' in qa_result.cot.lower()}")
    
    # Try to extract from CoT steps
    print("\n" + "=" * 80)
    print("STEP 3: Extract from CoT Steps (like official IRCoT)")
    print("=" * 80)
    
    import re
    full_cot = " ".join(ircot_result.cot_steps)
    print(f"\n📝 Full CoT: {full_cot}")
    
    # Try official IRCoT pattern
    answer_pattern = re.compile(r".* answer is (.*)", re.IGNORECASE | re.DOTALL)
    
    # Check each CoT step
    for i, step in enumerate(ircot_result.cot_steps, 1):
        match = answer_pattern.match(step)
        if match:
            extracted = match.group(1).strip().rstrip(".")
            print(f"\n✅ Found answer in Step {i}: '{extracted}'")
            break
    else:
        # Check full CoT
        match = answer_pattern.match(full_cot)
        if match:
            extracted = match.group(1).strip().rstrip(".")
            print(f"\n✅ Found answer in full CoT: '{extracted}'")
        else:
            print("\n❌ No 'answer is' pattern found in CoT steps")
    
    print("\n" + "=" * 80)
    print("COMPARISON")
    print("=" * 80)
    print(f"Gold Answer:     {gold_answer}")
    print(f"QA Reader:       {qa_result.answer}")
    if match:
        print(f"CoT Extraction:   {extracted}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()

