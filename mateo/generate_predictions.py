#!/usr/bin/env python3
"""
Generate predictions with probe-guided re-querying.

This script runs the decomposition pipeline on the dev split with cache enabled,
applies probes at each stage, and if a probe fires (indicating incorrect answer),
prompts the model to regenerate subqueries and re-runs the question (max once).
"""

import argparse
import json
import os
import re
import string
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import torch
from datasets import load_dataset
from transformer_lens import HookedTransformer

from mateo.decomposition import run_decomposition
from mateo.decomposition.prompts import build_planning_prompt
from mateo.probes import load_probe, BaseProbe
import sentence_transformers


# -------------------------
#  Constants
# -------------------------

MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
PROBE_DIR = "trained_probes2"
TOKEN_OFFSET = 0 
HOOK_TYPE = "resid_post"
TOKEN_POOLING = "single"


# -------------------------
#  Utility Functions
# -------------------------

def normalize_answer(s: str) -> str:
    """Normalize answer for F1 calculation."""
    def remove_articles(text):
        return re.sub(r'\b(a|an|the)\b', ' ', text)
    
    def white_space_fix(text):
        return ' '.join(text.split())
    
    def remove_punc(text):
        exclude = set(string.punctuation)
        return ''.join(ch for ch in text if ch not in exclude)
    
    def lower(text):
        return text.lower()
    
    return white_space_fix(remove_articles(remove_punc(lower(s))))


def f1_score(prediction: str, ground_truth: str) -> Tuple[float, float, float]:
    """Calculate F1 score between prediction and ground truth."""
    normalized_prediction = normalize_answer(prediction)
    normalized_ground_truth = normalize_answer(ground_truth)
    
    if normalized_prediction in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return 0.0, 0.0, 0.0
    if normalized_ground_truth in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return 0.0, 0.0, 0.0
    
    prediction_tokens = normalized_prediction.split()
    ground_truth_tokens = normalized_ground_truth.split()
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0, 0.0, 0.0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return f1, precision, recall


def extract_gold_sentences(example: Dict) -> List[str]:
    """Extract gold sentences from supporting_facts."""
    context_raw = example.get("context", [])
    supporting_facts_raw = example.get("supporting_facts", [])
    
    gold_sentences = []
    
    # Normalize context format
    if isinstance(context_raw, dict):
        normalized_context = list(zip(context_raw['title'], context_raw['sentences']))
    elif isinstance(context_raw, list):
        normalized_context = []
        for item in context_raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                title = item[0]
                sentences = item[1]
                if not isinstance(sentences, list):
                    sentences = list(sentences) if hasattr(sentences, '__iter__') else [str(sentences)]
                normalized_context.append((title, sentences))
    else:
        normalized_context = []
    
    # Normalize supporting_facts format
    if isinstance(supporting_facts_raw, dict):
        supporting_facts = list(zip(supporting_facts_raw['title'], supporting_facts_raw['sent_id']))
    elif isinstance(supporting_facts_raw, list):
        supporting_facts = supporting_facts_raw
    else:
        supporting_facts = []
    
    # Process supporting facts
    for sp in supporting_facts:
        if isinstance(sp, (list, tuple)) and len(sp) >= 2:
            title = sp[0]
            sent_idx = sp[1]
            
            for para_title, sentences in normalized_context:
                if para_title == title and sent_idx < len(sentences):
                    gold_sentences.append(sentences[sent_idx])
                    break
    
    return gold_sentences


def calculate_retrieval_recall(retrieved_sentences: List[str], gold_sentences: List[str]) -> float:
    """Calculate retrieval recall: proportion of gold sentences in retrieved sentences."""
    if not gold_sentences:
        return 0.0
    
    retrieved_set = set(normalize_answer(s) for s in retrieved_sentences)
    gold_set = set(normalize_answer(s) for s in gold_sentences)
    
    intersection = retrieved_set & gold_set
    return len(intersection) / len(gold_set) if gold_set else 0.0


def get_activations_at_token(
    model: HookedTransformer,
    full_text: str,
    layer: int,
    token_offset: int = 0,
) -> np.ndarray:
    """
    Extract activations from a specific token position (with offset from end).
    
    Args:
        model: HookedTransformer model
        full_text: Full text (prompt + response) to extract activations from
        layer: Layer to extract activations from
        token_offset: Offset from the last token (0 = last token)
    
    Returns:
        Activation vector of shape (d_model,)
    """
    tokenizer = model.tokenizer
    
    # Tokenize the full text (already formatted)
    # Note: full_text should already include the prompt + response
    tokens = model.to_tokens(full_text, prepend_bos=True)[0]  # (T,)
    length = tokens.shape[0]
    
    # Get position (last token - offset)
    # In training, we remove EOT and run inference on that token
    # Here, we run inference on activations that generated EOT tokens
    # So we use the last token (which generated EOT) with offset
    pos = max(0, length - 1 - token_offset)
    
    # Run with cache
    hook_name = f"blocks.{layer}.hook_{HOOK_TYPE}"
    with torch.no_grad():
        _, cache = model.run_with_cache(
            tokens.unsqueeze(0),
            return_type="logits",
            names_filter=lambda name: name == hook_name,
        )
    
    acts = cache[hook_name][0, pos, :].float().cpu().numpy()  # (d_model,)
    
    del cache
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    return acts


def load_probe_by_key(probe_key: str) -> Tuple[Optional[BaseProbe], Optional[int]]:
    """
    Load a probe from checkpoint by constructing its key.
    
    Probe key format: "final_L16_mlp_correct_given_recall1__offset0"
    Checkpoint key format: "final__correct_given_recall1__mlp__L16__resid_post__resid"
    
    Returns:
        (probe, layer) tuple, or (None, None) if not found
    """
    if probe_key is None or probe_key == "none":
        return None, None
    
    checkpoint_path = os.path.join(PROBE_DIR, "checkpoint.pt")
    if not os.path.exists(checkpoint_path):
        print(f"Warning: Checkpoint not found at {checkpoint_path}")
        return None, None
    
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    meta_dict = checkpoint.get("meta", {})
    
    # Parse probe_key: "final_L16_mlp_correct_given_recall1__offset0"
    # Extract: context_type, layer, probe_type, task_name
    probe_key_parts = probe_key.split("__")[0]  # Remove offset suffix
    parts = probe_key_parts.split("_")
    
    if len(parts) < 3:
        print(f"Warning: Invalid probe key format: {probe_key}")
        return None, None
    
    # Try to parse: context_type_L{layer}_probe_type_task_name
    parsed_context_type = parts[0]  # e.g., "final"
    parsed_layer = None
    parsed_probe_type = None
    parsed_task_name = None
    
    # Find layer (L{number})
    for i, part in enumerate(parts):
        if part.startswith("L") and part[1:].isdigit():
            parsed_layer = int(part[1:])
            # Probe type is everything between L{layer} and task_name
            if i + 1 < len(parts):
                # Task name is typically the last part, probe type is in between
                # For "final_L16_mlp_correct_given_recall1", we have:
                # parts[0] = "final", parts[1] = "L16", parts[2] = "mlp", rest = "correct_given_recall1"
                parsed_probe_type = parts[i + 1]  # e.g., "mlp"
                parsed_task_name = "_".join(parts[i + 2:])  # e.g., "correct_given_recall1"
            break
    
    # Find probe with matching metadata
    print(f"  Searching for probe: {probe_key}")
    print(f"  Parsed: context_type={parsed_context_type}, layer={parsed_layer}, "
          f"probe_type={parsed_probe_type}, task_name={parsed_task_name}")
    
    best_match = None
    best_match_score = 0
    
    for key, meta in meta_dict.items():
        context_type = meta.get("context_type", "")
        task_name = meta.get("task_name", "")
        probe_type = meta.get("probe_type", "")
        layer = meta.get("layer", -1)
        hook_type = meta.get("hook_type", HOOK_TYPE)
        token_pooling = meta.get("token_pooling", TOKEN_POOLING)
        token_offset_meta = meta.get("token_offset", TOKEN_OFFSET)
        
        # Calculate match score
        match_score = 0
        if parsed_context_type and context_type == parsed_context_type:
            match_score += 10
        if parsed_layer is not None and layer == parsed_layer:
            match_score += 10
        if parsed_probe_type and probe_type == parsed_probe_type:
            match_score += 10
        if parsed_task_name and task_name == parsed_task_name:
            match_score += 10
        if token_offset_meta == TOKEN_OFFSET:
            match_score += 5
        
        # Also try string matching as fallback
        if probe_key == key or probe_key in key or key in probe_key:
            match_score += 20
        
        if match_score > best_match_score:
            best_match_score = match_score
            best_match = (key, meta, layer)
    
    if best_match and best_match_score >= 20:  # Require at least some matching
        key, meta, layer = best_match
        print(f"  Best match: {key} (score={best_match_score})")
        
        # Try to load from individual file first
        probe_file = os.path.join(PROBE_DIR, f"{key}.pt")
        if os.path.exists(probe_file):
            probe = load_probe(probe_file)
            print(f"  ✓ Loaded probe from {probe_file}")
            return probe, layer
        else:
            print(f"  ✗ Probe file not found: {probe_file}")
            print(f"  Available files in {PROBE_DIR}: {[f for f in os.listdir(PROBE_DIR) if f.endswith('.pt')][:5]}")
            return None, None
    else:
        print(f"  ✗ No good match found (best score: {best_match_score})")
        print(f"  Available keys (first 10): {list(meta_dict.keys())[:10]}")
        return None, None


def build_regenerate_subqueries_prompt(question: str, original_subqueries: List[str]) -> str:
    """Build prompt to regenerate subqueries.
    
    Starts with the normal planning prompt, then appends the original subqueries and asks for
    completely new, better subqueries.
    """
    # Start with the normal planning prompt
    from mateo.decomposition.prompts import build_planning_prompt
    normal_prompt = build_planning_prompt(question)
    
    # Format the raw subqueries as they were generated
    subqueries_text = "\n".join([f"{i+1}. {sq}" for i, sq in enumerate(original_subqueries)])
    
    # Append feedback and instruction
    prompt_parts = [
        normal_prompt,
        "",
        "---",
        "",
        "The subqueries you generated:",
        subqueries_text,
        "",
        "These subqueries were not optimal. Please generate COMPLETELY DIFFERENT, BETTER subqueries that will lead to the correct answer.",
        "Make sure the new subqueries are definitely different from the ones above, but still optimal for the question.",
        "This is your second chance to get the right subqueries that will lead to the correct answer.",
        "Use the exact same format as shown in the examples above (numbered, with placeholders if needed).",
    ]
    
    return "\n".join(prompt_parts)


def build_regenerate_final_answer_prompt(question: str, sub_qa_history: List[Tuple[str, str]], original_answer: str) -> str:
    """Build prompt to regenerate final answer.
    
    Shows the question and facts, then the wrong answer, then instructs to generate a different, correct answer.
    """
    prompt_parts = [
        "Answer the main question using ONLY the facts below.",
        "Give a SHORT answer (a few words). Do not explain.",
        "CRITICAL: You must provide an answer. Never say 'I don't know', 'idk', 'answer not provided', 'not provided', 'no information', 'there is no information', or similar phrases.",
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
        "---",
        "",
        f"Your answer: {original_answer}",
        "",
        "This answer is WRONG. Please generate a DIFFERENT and CORRECT answer based on the facts above.",
        "Make sure your new answer is definitely different from the wrong answer above, but still accurately answers the question.",
        "This is your second chance to get the right answer.",
        "CRITICAL: You must provide an answer. Never say 'I don't know', 'idk', 'answer not provided', 'not provided', 'no information', 'there is no information', or similar phrases.",
        "",
        "Answer:",
    ])
    
    return "\n".join(prompt_parts)


def parse_subqueries(response: str) -> List[str]:
    """Parse numbered subqueries from model response."""
    subqueries = []
    lines = response.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Remove leading numbers/bullets
        cleaned = re.sub(r'^[\d]+[.\)]\s*', '', line)
        cleaned = re.sub(r'^[-•]\s*', '', cleaned)
        cleaned = cleaned.strip()
        
        # Remove trailing special tokens
        cleaned = re.sub(r'\s*<\|.*?\|>\s*$', '', cleaned)
        cleaned = re.sub(r'\s*<end_of_turn>\s*$', '', cleaned)
        cleaned = cleaned.strip()
        
        # Skip if it's a label or too short
        if not cleaned or cleaned.endswith(':') or len(cleaned) <= 5:
            continue
        
        # Check if it looks like a question
        if '?' in cleaned or '[ANSWER_' in cleaned:
            subqueries.append(cleaned)
            if len(subqueries) >= 3:  # Limit to 3
                break
    
    return subqueries[:3] if subqueries else []


def generate_with_cache_and_probe(
    model: HookedTransformer,
    prompt: str,
    max_new_tokens: int,
    probe: Optional[BaseProbe] = None,
    probe_layer: Optional[int] = None,
    probe_threshold: float = 0.5,
    stage_name: str = "unknown",
) -> Tuple[str, str, bool, float]:
    """
    Generate text with cache and optionally check probe.
    
    Returns:
        (full_text, response_text, probe_fired, probe_time)
    """
    tokenizer = model.tokenizer
    
    # Format prompt
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
    ]
    formatted_prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    
    # Tokenize
    inputs = tokenizer(
        formatted_prompt,
        return_tensors="pt",
        truncation=True,
        max_length=2048
    ).to(model.cfg.device)
    
    # Generate
    probe_time = 0.0
    probe_fired = False
    
    with torch.no_grad():
        outputs = model.generate(
            inputs.input_ids,
            max_new_tokens=max_new_tokens,
            temperature=0.0,
            do_sample=False,
            verbose=False
        )
    
    # Decode
    full_text = tokenizer.decode(outputs[0], skip_special_tokens=False)
    response_text = tokenizer.decode(
        outputs[0][inputs.input_ids.shape[1]:],
        skip_special_tokens=True
    ).strip()
    
    # Check probe if provided
    if probe is not None and probe_layer is not None:
        probe_start = time.time()
        try:
            planning_acts = get_activations_at_token(
                model, full_text, probe_layer, TOKEN_OFFSET
            )
            planning_prob = probe.predict_proba(planning_acts.reshape(1, -1))[0]
            probe_time = time.time() - probe_start
            
            # Always print probe output with stage name
            fired = planning_prob < probe_threshold
            print(f"  [{stage_name.upper()}] Probe prob={planning_prob:.4f}, threshold={probe_threshold:.4f}, FIRED={fired}, layer={probe_layer}")
            
            # Probe fires if probability < threshold (indicating incorrect answer)
            # Probes predict correctness (1 = correct, 0 = incorrect)
            # So low probability means incorrect, high probability means correct
            if fired:
                probe_fired = True
        except Exception as e:
            print(f"  [{stage_name.upper()}] ERROR running probe: {e}")
            import traceback
            traceback.print_exc()
            probe_time = 0.0
    elif probe is None and probe_layer is None:
        # Probe not provided - print for first few calls to confirm
        if not hasattr(generate_with_cache_and_probe, '_no_probe_count'):
            generate_with_cache_and_probe._no_probe_count = {}
        if stage_name not in generate_with_cache_and_probe._no_probe_count:
            generate_with_cache_and_probe._no_probe_count[stage_name] = 0
        generate_with_cache_and_probe._no_probe_count[stage_name] += 1
        if generate_with_cache_and_probe._no_probe_count[stage_name] <= 2:
            print(f"  [{stage_name.upper()}] No probe configured (probe=None, layer=None)")
    else:
        print(f"  [{stage_name.upper()}] WARNING: Probe or layer is None! probe={probe is not None}, layer={probe_layer}")
    
    del inputs, outputs
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    return full_text, response_text, probe_fired, probe_time


def run_decomposition_with_probes(
    question: str,
    model: HookedTransformer,
    retriever,
    context: List,
    planning_probe: Optional[BaseProbe],
    planning_probe_threshold: float,
    subanswer_probe: Optional[BaseProbe],
    subanswer_probe_threshold: float,
    final_probe: Optional[BaseProbe],
    final_probe_threshold: float,
    planning_probe_layer: Optional[int] = None,
    subanswer_probe_layer: Optional[int] = None,
    final_probe_layer: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, float]]:
    """
    Run decomposition with probe monitoring.
    
    Returns:
        (result_dict, probe_info_dict, timing_dict)
    """
    probe_info = {
        "planning_fired": False,
        "subanswer_fired": False,
        "final_fired": False,
        "re_query_triggered": False,
    }
    
    timing = {
        "probe_time": 0.0,
        "regeneration_time": 0.0,
    }
    
    # Stage 1: Planning
    planning_prompt = build_planning_prompt(question)
    planning_full, planning_response, planning_fired, probe_time = generate_with_cache_and_probe(
        model, planning_prompt, 512, planning_probe, planning_probe_layer, planning_probe_threshold, "planning"
    )
    timing["probe_time"] += probe_time
    
    original_subqueries = None
    if planning_fired:
        probe_info["planning_fired"] = True
        probe_info["re_query_triggered"] = True
        
        # Parse original subqueries for regeneration prompt
        from mateo.decomposition.decomposition import parse_subqueries as parse_sq
        original_subqueries = parse_sq(planning_response)
        if not original_subqueries:
            original_subqueries = [question]
        
        # Regenerate subqueries - just ask for better subqueries, don't show the answer
        regen_start = time.time()
        regenerate_prompt = build_regenerate_subqueries_prompt(question, original_subqueries)
        _, planning_response, _, _ = generate_with_cache_and_probe(
            model, regenerate_prompt, 512, None, None, 0.5, "planning_regen"
        )
        timing["regeneration_time"] += time.time() - regen_start
        
        # Debug: print original vs new subqueries
        new_subqueries = parse_sq(planning_response)
        if not new_subqueries:
            new_subqueries = [question]
        print(f"  [PLANNING_REGEN] Original subqueries: {original_subqueries}")
        print(f"  [PLANNING_REGEN] New subqueries: {new_subqueries}")
        # Update planning_response to use new subqueries for parsing below
        planning_response = "\n".join([f"{i+1}. {sq}" for i, sq in enumerate(new_subqueries)])
    
    # Parse subqueries
    from mateo.decomposition.decomposition import parse_subqueries as parse_sq
    subqueries = parse_sq(planning_response)
    if not subqueries:
        subqueries = [question]
    if len(subqueries) > 3:
        subqueries = subqueries[:3]
    
    # Debug: print subqueries being used (always, for debugging)
    print(f"  [SUBQUERIES] Using subqueries: {subqueries}")
    
    # Stage 2: Execute subqueries
    from mateo.decomposition.decomposition import fill_placeholders, build_subanswer_prompt, build_final_answer_prompt
    from mateo.decomposition.retrieve import retrieve_top_paragraphs, paragraphs_to_sentences
    
    filled_subqueries = subqueries.copy()
    answers_so_far = []
    all_retrieved_sentences = []
    subanswer_full_list = []
    
    for i, subquery_template in enumerate(subqueries):
        filled_subquery = fill_placeholders(subquery_template, answers_so_far)
        
        # Retrieve
        retrieved_paragraphs = retrieve_top_paragraphs(
            retriever, filled_subquery, context, top_k=2
        )
        retrieved_sentences = paragraphs_to_sentences(retrieved_paragraphs)
        all_retrieved_sentences.extend(retrieved_sentences)
        
        # Generate subanswer
        subanswer_prompt = build_subanswer_prompt(filled_subquery, retrieved_sentences)
        subanswer_full, subanswer_response, subanswer_fired, probe_time = generate_with_cache_and_probe(
            model, subanswer_prompt, 256, subanswer_probe, subanswer_probe_layer, subanswer_probe_threshold, f"subanswer_{i+1}"
        )
        timing["probe_time"] += probe_time
        
        if subanswer_fired:
            probe_info["subanswer_fired"] = True
            # Note: We don't re-query for subanswer, just track it
        
        subanswer_full_list.append(subanswer_full)
        subanswer = subanswer_response.strip()
        if subanswer.lower().startswith("answer:"):
            subanswer = subanswer[7:].strip()
        
        answers_so_far.append(subanswer)
        filled_subqueries[i] = fill_placeholders(subquery_template, answers_so_far)
    
    # Stage 3: Final answer
    sub_qa_history = [
        (filled_subqueries[i], answers_so_far[i])
        for i in range(len(filled_subqueries))
    ]
    final_prompt = build_final_answer_prompt(question, sub_qa_history)
    final_full, final_response, final_fired, probe_time = generate_with_cache_and_probe(
        model, final_prompt, 256, final_probe, final_probe_layer, final_probe_threshold, "final"
    )
    timing["probe_time"] += probe_time
    
    original_final_answer = None
    if final_fired:
        probe_info["final_fired"] = True
        probe_info["re_query_triggered"] = True
        
        # Save original answer for debugging
        original_final_answer = final_response.strip()
        if original_final_answer.lower().startswith("answer:"):
            original_final_answer = original_final_answer[7:].strip()
        
        # Regenerate final answer if probe fired
        regen_start = time.time()
        regenerate_prompt = build_regenerate_final_answer_prompt(question, sub_qa_history, original_final_answer)
        _, final_response, _, _ = generate_with_cache_and_probe(
            model, regenerate_prompt, 256, None, None, 0.5, "final_regen"
        )
        timing["regeneration_time"] += time.time() - regen_start
        
        # Debug: print original vs regenerated answer
        regenerated_answer = final_response.strip()
        if regenerated_answer.lower().startswith("answer:"):
            regenerated_answer = regenerated_answer[7:].strip()
        print(f"  [FINAL_REGEN] Original: '{original_final_answer[:100]}' -> Regenerated: '{regenerated_answer[:100]}'")
    
    final_answer = final_response.strip()
    if final_answer.lower().startswith("answer:"):
        final_answer = final_answer[7:].strip()
    
    # Deduplicate retrieved sentences
    all_retrieved_sentences = list(dict.fromkeys(all_retrieved_sentences))
    
    result = {
        "answer": final_answer,
        "planning": planning_full,
        "subanswer": subanswer_full_list,
        "final": final_full,
        "retrieved_sentences": all_retrieved_sentences,
    }
    
    return result, probe_info, timing


def main():
    parser = argparse.ArgumentParser(
        description="Generate predictions with probe-guided re-querying"
    )
    parser.add_argument(
        "--test_run",
        action="store_true",
        default=False,
        help="If True, only process 5 questions (default: False, process all)",
    )
    parser.add_argument(
        "--planning_probe",
        type=str,
        default="none",
        help="Probe key for planning stage (or 'none')",
    )
    parser.add_argument(
        "--subanswer_probe",
        type=str,
        default="none",
        help="Probe key for subanswer stage (or 'none')",
    )
    parser.add_argument(
        "--final_probe",
        type=str,
        default="final_L16_mlp_correct_given_recall1__offset0",
        help="Probe key for final stage (default: final_L16_mlp_correct_given_recall1__offset0, or 'none')",
    )
    parser.add_argument(
        "--planning_threshold",
        type=float,
        default=0.5,
        help="Threshold for planning probe (default: 0.5)",
    )
    parser.add_argument(
        "--subanswer_threshold",
        type=float,
        default=0.5,
        help="Threshold for subanswer probe (default: 0.5)",
    )
    parser.add_argument(
        "--final_threshold",
        type=float,
        default=0.4,
        help="Threshold for final probe (default: 0.4). Probe fires when prob < threshold (predicts incorrect answer).",
    )
    args = parser.parse_args()
    
    # Load dataset
    dataset = load_dataset("hotpot_qa", "distractor", split="validation")
    if args.test_run:
        dataset = dataset.select(range(5))
        print("Running in test mode: processing 5 questions")
    else:
        print(f"Processing all {len(dataset)} questions")
    
    # Load model and retriever
    print("Loading model...")
    model = HookedTransformer.from_pretrained(MODEL_NAME)
    print("Loading retriever...")
    retriever = sentence_transformers.SentenceTransformer("all-MiniLM-L6-v2")
    
    # Load probes (placeholder - will be filled by user)
    planning_probe, planning_probe_layer = load_probe_by_key(args.planning_probe)
    subanswer_probe, subanswer_probe_layer = load_probe_by_key(args.subanswer_probe)
    final_probe, final_probe_layer = load_probe_by_key(args.final_probe)
    
    print(f"\n=== Probe Configuration ===")
    print(f"Planning probe: {args.planning_probe}")
    print(f"  -> Layer: {planning_probe_layer}, Loaded: {planning_probe is not None}, Threshold: {args.planning_threshold}")
    print(f"Subanswer probe: {args.subanswer_probe}")
    print(f"  -> Layer: {subanswer_probe_layer}, Loaded: {subanswer_probe is not None}, Threshold: {args.subanswer_threshold}")
    print(f"Final probe: {args.final_probe}")
    print(f"  -> Layer: {final_probe_layer}, Loaded: {final_probe is not None}, Threshold: {args.final_threshold}")
    print(f"===========================\n")
    
    # Initialize metrics
    predictions = {"answer": {}}
    
    total_accuracy = 0.0
    total_retrieval = 0.0
    probe_re_query_counts = {
        "planning": 0,
        "subanswer": 0,
        "final": 0,
    }
    probe_re_query_correct_counts = {
        "planning": 0,
        "subanswer": 0,
        "final": 0,
    }
    total_question_time = 0.0
    total_probe_time = 0.0
    total_regeneration_time = 0.0
    
    num_processed = 0
    
    print("\nStarting prediction generation...")
    print("First few questions:")
    for i, example in enumerate(dataset):
        if i < 3:
            print(f"  {i+1}. {example['question'][:80]}...")
    
    print("\nProcessing questions...")
    
    for i, example in enumerate(dataset):
        question = example["question"]
        gold_answer = example["answer"]
        gold_supporting_facts = example.get("supporting_facts", [])
        context_raw = example["context"]
        example_id = example["id"]
        
        # Normalize context format
        if isinstance(context_raw, dict):
            context = list(zip(context_raw['title'], context_raw['sentences']))
        elif isinstance(context_raw, list):
            context = context_raw
        else:
            context = []
        
        question_start_time = time.time()
        re_query_attempted = False
        
        try:
            # Run decomposition with probes (first attempt)
            result, probe_info, timing = run_decomposition_with_probes(
                question,
                model,
                retriever,
                context,
                planning_probe,
                args.planning_threshold,
                subanswer_probe,
                args.subanswer_threshold,
                final_probe,
                args.final_threshold,
                planning_probe_layer,
                subanswer_probe_layer,
                final_probe_layer,
            )
            
            # If planning or final probe fired, mark that we attempted a re-query
            # Note: The regeneration already happened in run_decomposition_with_probes
            if (probe_info["planning_fired"] or probe_info["final_fired"]) and probe_info["re_query_triggered"]:
                re_query_attempted = True
            
            question_time = time.time() - question_start_time
            total_question_time += question_time
            total_probe_time += timing["probe_time"]
            total_regeneration_time += timing["regeneration_time"]
            
            # Extract results
            answer = result["answer"]
            retrieved_sentences = result["retrieved_sentences"]
            
            # Calculate metrics
            gold_sentences = extract_gold_sentences(example)
            f1, prec, rec = f1_score(answer, gold_answer)
            correct = 1 if f1 >= 0.5 else 0
            retrieval_recall = calculate_retrieval_recall(retrieved_sentences, gold_sentences)
            retrieval = 1 if abs(retrieval_recall - 1.0) < 1e-8 else 0
            
            total_accuracy += correct
            total_retrieval += retrieval
            
            # Track probe re-query stats
            # Count planning re-queries
            if probe_info["re_query_triggered"] and probe_info["planning_fired"] and re_query_attempted:
                probe_re_query_counts["planning"] += 1
                if correct:
                    probe_re_query_correct_counts["planning"] += 1
            
            # Count final re-queries
            if probe_info["re_query_triggered"] and probe_info["final_fired"]:
                probe_re_query_counts["final"] += 1
                if correct:
                    probe_re_query_correct_counts["final"] += 1
                else:
                    # Debug: print when re-query didn't help
                    print(f"  [FINAL_REGEN_FAIL] Question {num_processed}: Predicted='{answer[:80]}', Gold='{gold_answer[:80]}', F1={f1:.3f}")
            
            # Debug: print probe firing info for first few examples
            if num_processed <= 5:
                print(f"  [DEBUG Q{num_processed}] planning_fired={probe_info['planning_fired']}, "
                      f"subanswer_fired={probe_info['subanswer_fired']}, "
                      f"final_fired={probe_info['final_fired']}, "
                      f"re_query_triggered={probe_info['re_query_triggered']}")
            
            # Note: subanswer and final probes don't trigger re-queries, so we don't count them
            
            # Store prediction in the required format: {"answer": {question_id: answer}}
            predictions["answer"][example_id] = answer
            
            num_processed += 1
            
            # Save every 10 questions
            if num_processed % 10 == 0:
                # Save predictions
                with open("predictions.json", "w") as f:
                    json.dump(predictions, f, indent=2)
                
                # Calculate and save metrics (single row with current totals)
                avg_accuracy = total_accuracy / num_processed
                avg_retrieval = total_retrieval / num_processed
                avg_question_time = total_question_time / num_processed
                avg_probe_time = total_probe_time / num_processed
                avg_regeneration_time = total_regeneration_time / num_processed
                
                metrics_row = {
                    "num_questions": num_processed,
                    "avg_accuracy": avg_accuracy,
                    "avg_retrieval": avg_retrieval,
                    "planning_re_query_count": probe_re_query_counts["planning"],
                    "subanswer_re_query_count": probe_re_query_counts["subanswer"],
                    "final_re_query_count": probe_re_query_counts["final"],
                    "planning_re_query_correct": probe_re_query_correct_counts["planning"],
                    "subanswer_re_query_correct": probe_re_query_correct_counts["subanswer"],
                    "final_re_query_correct": probe_re_query_correct_counts["final"],
                    "avg_question_time": avg_question_time,
                    "avg_probe_time": avg_probe_time,
                    "avg_regeneration_time": avg_regeneration_time,
                }
                
                # Save metrics CSV as single row (overwrite each time)
                df = pd.DataFrame([metrics_row])
                df.to_csv("metrics.csv", index=False)
                
                # Write metrics to txt file (overwrite each time)
                with open("metrics.txt", "w") as f:
                    f.write("=" * 60 + "\n")
                    f.write("METRICS OVER ALL QUESTIONS\n")
                    f.write("=" * 60 + "\n\n")
                    f.write(f"Number of questions processed: {num_processed}\n\n")
                    f.write("Accuracy Metrics:\n")
                    f.write(f"  Average accuracy: {avg_accuracy:.4f}\n")
                    f.write(f"  Average retrieval: {avg_retrieval:.4f}\n\n")
                    f.write("Re-query Counts:\n")
                    f.write(f"  Planning: {probe_re_query_counts['planning']}\n")
                    f.write(f"  Subanswer: {probe_re_query_counts['subanswer']}\n")
                    f.write(f"  Final: {probe_re_query_counts['final']}\n\n")
                    f.write("Re-query Correct Counts:\n")
                    f.write(f"  Planning: {probe_re_query_correct_counts['planning']}\n")
                    f.write(f"  Subanswer: {probe_re_query_correct_counts['subanswer']}\n")
                    f.write(f"  Final: {probe_re_query_correct_counts['final']}\n\n")
                    f.write("Timing Metrics:\n")
                    f.write(f"  Average question time: {avg_question_time:.4f}s\n")
                    f.write(f"  Average probe time: {avg_probe_time:.4f}s\n")
                    f.write(f"  Average regeneration time: {avg_regeneration_time:.4f}s\n")
                    f.write("=" * 60 + "\n")
                
                print(f"\nProcessed {num_processed} questions")
                print(f"  Avg accuracy: {avg_accuracy:.4f}")
                print(f"  Avg retrieval: {avg_retrieval:.4f}")
                print(f"  Re-query counts: planning={probe_re_query_counts['planning']}, "
                      f"subanswer={probe_re_query_counts['subanswer']}, "
                      f"final={probe_re_query_counts['final']}")
        
        except Exception as e:
            print(f"\nError processing question {i+1}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Final save
    with open("predictions.json", "w") as f:
        json.dump(predictions, f, indent=2)
    
    # Final metrics
    if num_processed > 0:
        avg_accuracy = total_accuracy / num_processed
        avg_retrieval = total_retrieval / num_processed
        avg_question_time = total_question_time / num_processed
        avg_probe_time = total_probe_time / num_processed
        avg_regeneration_time = total_regeneration_time / num_processed
        
        metrics_row = {
            "num_questions": num_processed,
            "avg_accuracy": avg_accuracy,
            "avg_retrieval": avg_retrieval,
            "planning_re_query_count": probe_re_query_counts["planning"],
            "subanswer_re_query_count": probe_re_query_counts["subanswer"],
            "final_re_query_count": probe_re_query_counts["final"],
            "planning_re_query_correct": probe_re_query_correct_counts["planning"],
            "subanswer_re_query_correct": probe_re_query_correct_counts["subanswer"],
            "final_re_query_correct": probe_re_query_correct_counts["final"],
            "avg_question_time": avg_question_time,
            "avg_probe_time": avg_probe_time,
            "avg_regeneration_time": avg_regeneration_time,
        }
        
        # Save metrics CSV as single row
        df = pd.DataFrame([metrics_row])
        df.to_csv("metrics.csv", index=False)
        
        # Write final metrics to txt file
        with open("metrics.txt", "w") as f:
            f.write("=" * 60 + "\n")
            f.write("FINAL METRICS OVER ALL QUESTIONS\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Number of questions processed: {num_processed}\n\n")
            f.write("Accuracy Metrics:\n")
            f.write(f"  Average accuracy: {avg_accuracy:.4f}\n")
            f.write(f"  Average retrieval: {avg_retrieval:.4f}\n\n")
            f.write("Re-query Counts:\n")
            f.write(f"  Planning: {probe_re_query_counts['planning']}\n")
            f.write(f"  Subanswer: {probe_re_query_counts['subanswer']}\n")
            f.write(f"  Final: {probe_re_query_counts['final']}\n\n")
            f.write("Re-query Correct Counts:\n")
            f.write(f"  Planning: {probe_re_query_correct_counts['planning']}\n")
            f.write(f"  Subanswer: {probe_re_query_correct_counts['subanswer']}\n")
            f.write(f"  Final: {probe_re_query_correct_counts['final']}\n\n")
            f.write("Timing Metrics:\n")
            f.write(f"  Average question time: {avg_question_time:.4f}s\n")
            f.write(f"  Average probe time: {avg_probe_time:.4f}s\n")
            f.write(f"  Average regeneration time: {avg_regeneration_time:.4f}s\n")
            f.write("=" * 60 + "\n")
        
        print(f"\n=== Final Results ===")
        print(f"Processed {num_processed} questions")
        print(f"Average accuracy: {avg_accuracy:.4f}")
        print(f"Average retrieval: {avg_retrieval:.4f}")
        print(f"Re-query counts: planning={probe_re_query_counts['planning']}, "
              f"subanswer={probe_re_query_counts['subanswer']}, "
              f"final={probe_re_query_counts['final']}")
        print(f"Average question time: {avg_question_time:.4f}s")
        print(f"Average probe time: {avg_probe_time:.4f}s")
        print(f"Average regeneration time: {avg_regeneration_time:.4f}s")


if __name__ == "__main__":
    main()
