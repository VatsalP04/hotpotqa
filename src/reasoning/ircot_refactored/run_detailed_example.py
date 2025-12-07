#!/usr/bin/env python3
"""
Detailed example script to run one question and show everything the LLM sees.

This script demonstrates the two-stage IRCoT process:
1. Stage 1: Interleaved retrieval + CoT generation
2. Stage 2: QA Reader generates final answer from all paragraphs

It shows:
- All prompts sent to the LLM (with system instructions)
- Raw LLM responses
- Extracted sentences
- QA Reader prompt and response
- Final answer extraction
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import List, Optional

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env from project root (hotpotqa/) or current directory
    project_root = Path(__file__).parent.parent.parent
    env_files = [
        project_root / ".env",
        Path(__file__).parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file)
            break
except ImportError:
    # python-dotenv not installed, skip .env loading
    pass

# Add src to path (script is at ircot_refactored root, so add src/)
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ircot import (
    IRCoTConfig,
    HotpotQALoader,
    load_default_demos,
    evaluate_single,
    precision_recall_f1,
)
from ircot.ircot import IRCoTSystem
from ircot.llm_client import LLMClient
from ircot.prompts import (
    build_reason_prompt, 
    build_qa_prompt, 
    get_system_instruction, 
    get_qa_reader_system_instruction
)
from ircot.answer_extraction import SentenceExtractor, AnswerExtractor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LoggingLLMClient(LLMClient):
    """LLM Client wrapper that logs all prompts and responses."""
    
    def __init__(self, base_llm: LLMClient):
        self.base_llm = base_llm
        self.interactions = []
        self.current_step = 0
        self.in_qa_reader = False
    
    def generate(self, prompt: str, max_new_tokens: int, temperature: float = 0.0, stop=None) -> str:
        """Generate with logging."""
        # Detect if this is QA Reader - QA Reader prompts start fresh with "Let's reason step by step"
        # and don't have previous CoT continuation
        # Reasoning steps have "A: " followed by previous CoT
        has_previous_cot = "A: " in prompt and len(prompt.split("A: ")) > 1
        is_qa_reader = not has_previous_cot and ("Let's reason step by step" in prompt or "Q:" in prompt)
        
        if is_qa_reader:
            self.in_qa_reader = True
            interaction_type = "QA_READER"
        else:
            self.current_step += 1
            self.in_qa_reader = False
            interaction_type = f"REASONING_STEP_{self.current_step}"
        
        # Get system instruction if present
        system_instruction = None
        if hasattr(self.base_llm, '_system_instruction'):
            system_instruction = getattr(self.base_llm, '_system_instruction', None)
        
        # Call base LLM
        response = self.base_llm.generate(prompt, max_new_tokens, temperature, stop)
        
        # Log interaction
        self.interactions.append({
            "type": interaction_type,
            "system_instruction": system_instruction,
            "prompt": prompt,
            "response": response,
            "max_tokens": max_new_tokens,
            "temperature": temperature
        })
        
        return response


def run_detailed_example(
    data_path: str = None,
    question_index: int = 0,
    use_ircot: bool = True
):
    """
    Run a detailed example showing all LLM interactions.
    
    Args:
        data_path: Path to data file (auto-finds if None)
        question_index: Which question to use (0 = first)
        use_ircot: Use IRCoT (True) or baseline (False)
    """
    # Find data
    if data_path is None:
        candidates = [
            "data/hotpotqa/hotpot_dev_distractor_v1.json",
            "data/hotpot_dev_distractor_v1.json",
            "../data/hotpotqa/hotpot_dev_distractor_v1.json",
            "../../data/hotpotqa/hotpot_dev_distractor_v1.json",
        ]
        for path in candidates:
            if os.path.exists(path):
                data_path = path
                break
        
        if data_path is None:
            print("❌ Could not find data file. Please specify --data_path")
            print("   Looking for: hotpot_dev_distractor_v1.json")
            return
    
    print("="*80)
    print("IRCoT DETAILED EXAMPLE RUN")
    print("="*80)
    print(f"\n📁 Data file: {data_path}")
    print(f"🔢 Question index: {question_index}")
    print(f"🔄 Mode: {'IRCoT (interleaved)' if use_ircot else 'Baseline (one-step)'}")
    
    # Load data
    print("\n📚 Loading data...")
    loader = HotpotQALoader()
    instances = loader.load(filepath=data_path)
    print(f"✓ Loaded {len(instances)} instances")
    
    if question_index >= len(instances):
        print(f"❌ Question index {question_index} out of range (max: {len(instances)-1})")
        return
    
    instance = instances[question_index]
    print(f"\n📋 Selected Question:")
    print(f"   ID: {instance.id}")
    print(f"   Question: {instance.question}")
    print(f"   Gold Answer: {instance.answer}")
    print(f"   Type: {instance.question_type}")
    print(f"   Level: {instance.level}")
    print(f"   Context paragraphs: {len(instance.context)}")
    print(f"   Supporting facts: {len(instance.supporting_facts)}")
    
    # Load demos
    print("\n📖 Loading few-shot demonstrations...")
    demos = load_default_demos(3)
    print(f"✓ Loaded {len(demos)} demonstrations")
    
    # Check for API key (after .env loading)
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        print("\n❌ ERROR: MISTRAL_API_KEY environment variable is not set!")
        print("   Please set it in one of these ways:")
        print("   1. Add to .env file in project root: MISTRAL_API_KEY=your-key")
        print("   2. Export in shell: export MISTRAL_API_KEY='your-api-key-here'")
        print("   3. Run inline: MISTRAL_API_KEY='your-key' uv run python ...")
        print("\n   Note: If using .env file, install python-dotenv:")
        print("   uv add python-dotenv")
        return
    
    # Create config - explicitly set mistral-small-latest for text generation
    config = IRCoTConfig(
        initial_retrieval_k=2,
        step_retrieval_k=1,
        max_reasoning_steps=4,
        max_total_paragraphs=5,
        num_few_shot_examples=3,
        use_system_instruction=True,
        mistral_api_key=api_key,  # Explicitly set from env
        mistral_model="mistral-small-latest",  # Explicitly set to small
        mistral_embed_model="mistral-embed"  # Keep embeddings model separate
    )
    
    # Create system with logging LLM
    print("\n🔧 Initializing IRCoT system...")
    try:
        system = IRCoTSystem(config, demos)
    except ValueError as e:
        if "API key" in str(e):
            print(f"\n❌ ERROR: {e}")
            print("   Please set MISTRAL_API_KEY environment variable")
            return
        raise
    
    # Wrap the LLM with logging
    logging_llm = LoggingLLMClient(system.llm)
    system.llm = logging_llm
    
    # Also wrap QA Reader's LLM
    qa_logging_llm = LoggingLLMClient(system.qa_reader.llm)
    system.qa_reader.llm = qa_logging_llm
    
    print("✓ System initialized with logging")
    
    print("\n🚀 Running IRCoT...")
    print("-" * 80)
    
    # Run the system
    result = system.answer(
        question=instance.question,
        context=instance.context,
        use_interleaved=use_ircot
    )
    
    print("\n✅ IRCoT completed!")
    print(f"   Answer: {result.answer}")
    print(f"   Steps: {result.num_steps}")
    print(f"   Paragraphs used: {len(result.retrieved_paragraphs)}")
    print(f"   Terminated by answer: {result.terminated_by_answer}")
    print(f"   Processing time: {result.processing_time:.2f}s")
    
    # Show all interactions
    all_interactions = logging_llm.interactions + qa_logging_llm.interactions
    
    print("\n" + "="*80)
    print("="*80)
    print("DETAILED LLM INTERACTIONS - STEP BY STEP")
    print("="*80)
    print("="*80)
    
    # Show reasoning steps first (interleaved retrieval)
    reasoning_interactions = [i for i in all_interactions if i['type'].startswith('REASONING_STEP')]
    
    if reasoning_interactions:
        print("\n" + "="*80)
        print("STAGE 1: INTERLEAVED RETRIEVAL + REASONING STEPS")
        print("="*80)
        
        cumulative_cot = ""
        for i, interaction in enumerate(reasoning_interactions, 1):
            step_num = interaction['type'].replace('REASONING_STEP_', '')
            print(f"\n{'#'*80}")
            print(f"# REASONING STEP {step_num}")
            print(f"{'#'*80}")
            
            # Show system instruction
            if interaction['system_instruction']:
                print(f"\n📋 SYSTEM INSTRUCTION:")
                print("-" * 80)
                print(interaction['system_instruction'])
            
            # Show prompt
            print(f"\n📝 PROMPT SENT TO LLM (Step {step_num}):")
            print("-" * 80)
            prompt = interaction['prompt']
            # Show full prompt but with clear markers
            print(prompt)
            print(f"\n[Prompt length: {len(prompt)} characters]")
            
            # Show raw response
            print(f"\n🤖 RAW LLM RESPONSE (Step {step_num}):")
            print("-" * 80)
            raw_response = interaction['response']
            print(raw_response)
            
            # Extract and show the new sentence that was added
            print(f"\n✂️  EXTRACTED NEW CoT SENTENCE (Step {step_num}):")
            print("-" * 80)
            # Try to extract the next sentence
            sentences = SentenceExtractor.split_into_sentences(raw_response)
            if sentences:
                new_sentence = sentences[0] if len(sentences) > 0 else raw_response[:200]
                print(new_sentence)
                
                # Update cumulative CoT for display
                cumulative_cot = f"{cumulative_cot} {new_sentence}".strip()
            else:
                new_sentence = raw_response[:200] + "..."
                print(new_sentence)
                cumulative_cot = f"{cumulative_cot} {new_sentence}".strip()
            
            # Show cumulative CoT so far
            print(f"\n📚 CUMULATIVE CoT AFTER STEP {step_num}:")
            print("-" * 80)
            print(cumulative_cot)
            print(f"[Cumulative length: {len(cumulative_cot)} characters]")
            
            # Show parameters
            print(f"\n⚙️  GENERATION PARAMETERS:")
            print(f"   Max tokens: {interaction['max_tokens']}")
            print(f"   Temperature: {interaction['temperature']}")
            
            # Show what paragraphs were available at this step
            if i <= len(result.reasoning_steps):
                step_info = result.reasoning_steps[i] if i < len(result.reasoning_steps) else result.reasoning_steps[-1]
                if step_info.retrieved_paragraphs:
                    print(f"\n📄 PARAGRAPHS AVAILABLE AT THIS STEP:")
                    print("-" * 80)
                    for p in step_info.retrieved_paragraphs:
                        print(f"   - {p.title} ({len(p.sentences)} sentences)")
    
    # Show QA Reader interaction
    qa_interactions = [i for i in all_interactions if i['type'] == 'QA_READER']
    if qa_interactions:
        print("\n\n" + "="*80)
        print("="*80)
        print("STAGE 2: QA READER - FINAL ANSWER GENERATION")
        print("="*80)
        print("="*80)
        
        qa_interaction = qa_interactions[0]
        
        print(f"\n✅ IMPORTANT: QA Reader does NOT see the interleaved CoT!")
        print("   It only sees:")
        print("   - Few-shot demonstrations (examples)")
        print("   - All retrieved paragraphs")
        print("   - The question")
        print("   - System instruction (different from reasoning steps)")
        
        if qa_interaction['system_instruction']:
            print(f"\n📋 QA READER SYSTEM INSTRUCTION:")
            print("-" * 80)
            print(qa_interaction['system_instruction'])
        
        print(f"\n📝 QA READER PROMPT:")
        print("-" * 80)
        prompt = qa_interaction['prompt']
        print(prompt)
        print(f"\n[Prompt length: {len(prompt)} characters]")
        
        print(f"\n🤖 QA READER RAW RESPONSE:")
        print("-" * 80)
        print(qa_interaction['response'])
        
        # Extract answer from QA Reader response
        extracted = AnswerExtractor.extract(qa_interaction['response'])
        print(f"\n✅ EXTRACTED ANSWER FROM QA READER:")
        print("-" * 80)
        print(f"   Answer: {extracted.answer}")
        print(f"   Found: {extracted.found}")
        print(f"   Method: {extracted.extraction_method}")
        
        print(f"\n⚙️  GENERATION PARAMETERS:")
        print(f"   Max tokens: {qa_interaction['max_tokens']}")
        print(f"   Temperature: {qa_interaction['temperature']}")
    
    # Show reasoning steps summary
    print("\n" + "="*80)
    print("REASONING STEPS SUMMARY (STAGE 1)")
    print("="*80)
    
    for step in result.reasoning_steps:
        print(f"\n📌 Step {step.step_number}:")
        print(f"   CoT Sentence: {step.cot_sentence[:200]}...")
        print(f"   Retrieved paragraphs: {len(step.retrieved_paragraphs)}")
        if step.retrieved_paragraphs:
            titles = [p.title for p in step.retrieved_paragraphs]
            print(f"   Titles: {', '.join(titles[:3])}{'...' if len(titles) > 3 else ''}")
        print(f"   Cumulative CoT length: {len(step.cumulative_cot)} chars")
    
    
    # Show final reasoning chain
    print("\n" + "="*80)
    print("FINAL REASONING CHAIN (from QA Reader)")
    print("="*80)
    print(result.reasoning_chain)
    
    # Evaluate
    print("\n" + "="*80)
    print("EVALUATION")
    print("="*80)
    metrics = evaluate_single(result.answer, instance.answer)
    print(f"   Exact Match: {metrics['em']:.4f} ({'✓' if metrics['em'] > 0 else '✗'})")
    print(f"   Precision:   {metrics['precision']:.4f} ({metrics['precision']*100:.2f}%)")
    print(f"   Recall:      {metrics['recall']:.4f} ({metrics['recall']*100:.2f}%)")
    print(f"   F1 Score:   {metrics['f1']:.4f} ({metrics['f1']*100:.2f}%)")
    print(f"\n   Prediction: {result.answer}")
    print(f"   Gold:        {instance.answer}")
    
    # Show retrieved paragraphs vs gold
    print("\n" + "="*80)
    print("RETRIEVAL ANALYSIS")
    print("="*80)
    retrieved_titles = {p.title for p in result.retrieved_paragraphs}
    gold_titles = {sf[0] for sf in instance.supporting_facts}
    
    print(f"   Retrieved: {len(retrieved_titles)} paragraphs")
    print(f"   Gold:      {len(gold_titles)} paragraphs")
    print(f"   Overlap:   {len(retrieved_titles & gold_titles)} paragraphs")
    
    if retrieved_titles:
        print(f"\n   Retrieved titles:")
        for title in sorted(retrieved_titles):
            marker = "✓" if title in gold_titles else "✗"
            print(f"     {marker} {title}")
    
    if gold_titles:
        print(f"\n   Gold titles:")
        for title in sorted(gold_titles):
            marker = "✓" if title in retrieved_titles else "✗"
            print(f"     {marker} {title}")
    
    # Calculate retrieval metrics
    if gold_titles:
        tp = len(retrieved_titles & gold_titles)
        precision = tp / len(retrieved_titles) if retrieved_titles else 0.0
        recall = tp / len(gold_titles) if gold_titles else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        print(f"\n   Retrieval Precision: {precision:.4f} ({precision*100:.2f}%)")
        print(f"   Retrieval Recall:    {recall:.4f} ({recall*100:.2f}%)")
        print(f"   Retrieval F1:        {f1:.4f} ({f1*100:.2f}%)")
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"✓ Total LLM calls: {len(all_interactions)}")
    print(f"  - Reasoning steps: {len([i for i in all_interactions if i['type'].startswith('REASONING')])}")
    print(f"  - QA Reader: {len([i for i in all_interactions if i['type'] == 'QA_READER'])}")
    print(f"✓ Final answer: {result.answer}")
    print(f"✓ Answer metrics: EM={metrics['em']:.4f}, P={metrics['precision']:.4f}, R={metrics['recall']:.4f}, F1={metrics['f1']:.4f}")
    print("="*80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run detailed IRCoT example showing all LLM interactions")
    parser.add_argument("--data_path", help="Path to data file (auto-finds if not specified)")
    parser.add_argument("--question_index", type=int, default=0, help="Question index (0-based, default: 0)")
    parser.add_argument("--baseline", action="store_true", help="Use baseline instead of IRCoT")
    
    args = parser.parse_args()
    
    run_detailed_example(
        data_path=args.data_path,
        question_index=args.question_index,
        use_ircot=not args.baseline
    )

