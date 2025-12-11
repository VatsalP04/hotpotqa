#!/usr/bin/env python3

import sys
import json
import csv
import argparse
import random
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

# Add project root to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------
# ONLY necessary imports
# ---------------------------------------------------------
from src.data.loader import load_hotpotqa
from src.reasoning.decomposition import DecompositionReasoner, DecompositionConfig
from src.reasoning.ircot import (
    IRCoTRetriever,
    IRCoTConfig,
    QAReader,
    load_default_hotpot_demos,
    Paragraph,
    ParagraphWithSentences,
    InMemoryRetriever,
    DistractorRetrieverAdapter,
    SentenceRetriever,
    context_window_expand,
    SentenceWindowRetriever,
    MistralLLMClient,
)
from evaluation.eval import eval as official_eval, f1_score


# ---------------------------------------------------------
# Utility: SP metrics
# ---------------------------------------------------------
def sp_metrics(prediction_sp, gold_sp):
    pred_set = set(map(tuple, prediction_sp))
    gold_set = set(map(tuple, gold_sp))
    
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    
    return precision, recall, f1


# ---------------------------------------------------------
# Dataclass for pipeline output
# ---------------------------------------------------------
@dataclass
class MethodResult:
    answer: str
    debug_lines: List[str]
    sub_queries: List[str] = field(default_factory=list)
    sub_answers: List[str] = field(default_factory=list)


# ---------------------------------------------------------
# Decomposition Wrapper
# ---------------------------------------------------------
def run_decomposition(question: str, retriever, llm, config: DecompositionConfig) -> MethodResult:
    reasoner = DecompositionReasoner(
        retriever=retriever,
        llm=llm,
        config=config,
    )
    
    result = reasoner.run(question)
    cleaned = result.final_answer.strip().replace("**", "")
    cleaned = cleaned.split("\n")[0].rstrip(".")

    return MethodResult(
        answer=cleaned,
        debug_lines=[],
        sub_queries=[sq.question for sq in result.sub_qas],
        sub_answers=[sq.answer for sq in result.sub_qas],
    )


# ---------------------------------------------------------
# IRCoT Wrapper
# ---------------------------------------------------------
def run_ircot(question: str, retriever, llm, config: IRCoTConfig, demos) -> MethodResult:
    ircot = IRCoTRetriever(retriever=retriever, llm=llm, demos=demos, config=config)
    result = ircot.run(question)
    
    reader = QAReader(llm=llm, demos=demos, config=config)
    qa_result = reader.answer(question, result.retrieved_paragraphs)

    cleaned = qa_result.answer.strip().replace("**", "")
    cleaned = cleaned.split("\n")[0].rstrip(".")

    return MethodResult(
        answer=cleaned,
        debug_lines=[],
        sub_queries=result.cot_steps,
        sub_answers=[],
    )


# ---------------------------------------------------------
# Detect supporting fact explosion
# ---------------------------------------------------------
def check_sp_explosion(predicted_sp, gold_sp, ratio=2.0, precision_threshold=0.4):
    pred_count = len(predicted_sp)
    gold_count = len(gold_sp)
    
    prec, rec, f1 = sp_metrics(predicted_sp, gold_sp)
    explosion = pred_count > ratio * gold_count and prec < precision_threshold

    msg = f"Pred={pred_count}, Gold={gold_count}, Precision={prec:.3f}, Explosion={explosion}"
    return explosion, msg


# ---------------------------------------------------------
# Save CSV
# ---------------------------------------------------------
def save_csv(csv_rows: List[Dict], metadata: Dict, csv_path: Path):
    base_columns = [
        "question", "correct", "sp_precision", "sp_recall",
        "generated_answer", "gold_answer"
    ]

    max_subq = max((row.get("num_subqueries", 0) for row in csv_rows), default=0)
    max_suba = max((row.get("num_subanswers", 0) for row in csv_rows), default=0)
    max_ret = max((row.get("num_retrieved", 0) for row in csv_rows), default=0)
    max_gold = max((row.get("num_gold", 0) for row in csv_rows), default=0)

    columns = base_columns
    columns += [f"subquery_{i+1}" for i in range(max_subq)]
    columns += [f"subanswer_{i+1}" for i in range(max_suba)]
    columns += ["num_retrieved", "num_gold"]
    columns += [f"retrieved_{i+1}" for i in range(max_ret)]
    columns += [f"gold_{i+1}" for i in range(max_gold)]
    columns += ["sp_explosion", "sp_explosion_msg", "num_pred_sp", "num_gold_sp"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(list(metadata.keys()))
        writer.writerow([metadata[k] for k in metadata.keys()])
        writer.writerow([])

        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)


# ---------------------------------------------------------
# Save Metadata
# ---------------------------------------------------------
def save_metadata(metadata: Dict, metadata_path: Path):
    """Save experiment metadata to JSON file."""
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)


# ---------------------------------------------------------
# MAIN EVALUATION LOOP
# ---------------------------------------------------------
def run_evaluation(llm, embedder_client, dev_data, method, retriever_type,
                   top_k_paragraphs, output_path, csv_path, metadata_path=None):

    if method == "decomposition":
        config = DecompositionConfig()
        demos = None
    else:
        config = IRCoTConfig()
        demos = load_default_hotpot_demos(max_examples=config.max_demos)

    predictions = {"answer": {}, "sp": {}}
    csv_rows = []

    for i, example in enumerate(dev_data, 1):
        qid = example["_id"]
        question = example["question"]
        gold_answer = example.get("answer", "N/A")
        gold_sp = example.get("supporting_facts", [])
        context = example["context"]

        print(f"[{i}/{len(dev_data)}] {question[:80]}")

        try:
            # Convert context into paragraph models
            paragraphs_with_sentences = [
                ParagraphWithSentences(title, [s.strip() for s in sent_list])
                for title, sent_list in context
            ]

            raw_mistral = embedder_client.client.client

            # Build retriever based on type
            if retriever_type == "paragraph":
                paragraphs_for_retriever = [
                    Paragraph(pid=i, title=p.title, text=p.full_text)
                    for i, p in enumerate(paragraphs_with_sentences)
                ]
                base_retriever = InMemoryRetriever(paragraphs_for_retriever, raw_mistral)
                retriever = DistractorRetrieverAdapter(
                    base_retriever,
                    paragraphs_with_sentences,
                    top_k_paragraphs=top_k_paragraphs
                )

            elif retriever_type == "sentence":
                s_retriever = SentenceRetriever(paragraphs_with_sentences, raw_mistral)
                top_sents = s_retriever.retrieve_sentences(question, top_k=top_k_paragraphs * 3)
                expanded_chunks = context_window_expand(
                    top_sents,
                    paragraphs_with_sentences,
                    window=1
                )
                retriever = SentenceWindowRetriever(expanded_chunks)

            else:
                raise ValueError(f"Unknown retriever type: {retriever_type}")

            # Run method
            if method == "decomposition":
                method_result = run_decomposition(question, retriever, llm, config)
            else:
                method_result = run_ircot(question, retriever, llm, config, demos)

            cleaned = method_result.answer
            predictions["answer"][qid] = cleaned

            # Get supporting facts
            if hasattr(retriever, "get_supporting_facts"):
                sp_list = retriever.get_supporting_facts()
            else:
                sp_list = []
            predictions["sp"][qid] = sp_list

            # SP explosion detection
            sp_explosion, sp_expl_msg = check_sp_explosion(sp_list, gold_sp)

            # Metrics
            sp_prec, sp_rec, sp_f1 = sp_metrics(sp_list, gold_sp)
            ans_f1, _, _ = f1_score(cleaned, gold_answer)
            correct = 1 if ans_f1 > 0.5 else 0

            # Build CSV row
            row = {
                "question": question,
                "generated_answer": cleaned,
                "gold_answer": gold_answer,
                "correct": correct,
                "sp_precision": round(sp_prec, 4),
                "sp_recall": round(sp_rec, 4),
                "num_pred_sp": len(sp_list),
                "num_gold_sp": len(gold_sp),
                "sp_explosion": int(sp_explosion),
                "sp_explosion_msg": sp_expl_msg,
            }

            for j, q in enumerate(method_result.sub_queries):
                row[f"subquery_{j+1}"] = q

            for j, a in enumerate(method_result.sub_answers):
                row[f"subanswer_{j+1}"] = a

            row["num_subqueries"] = len(method_result.sub_queries)
            row["num_subanswers"] = len(method_result.sub_answers)

            csv_rows.append(row)
            print(f"   ✔ {cleaned} | Gold: {gold_answer}")

        except Exception as e:
            print("   ERROR:", e)
            predictions["answer"][qid] = "error"
            predictions["sp"][qid] = []
            csv_rows.append({"question": question, "generated_answer": "ERROR"})

    # Metadata
    metadata = {
        "experiment_id": f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "method": method,
        "retriever_type": retriever_type,
        "llm_model": getattr(llm, "model_name", "unknown"),
        "max_examples": len(dev_data),
        "top_k_paragraphs": top_k_paragraphs,
        "timestamp": datetime.now().isoformat(),
    }

    # Save files
    if output_path:
        with open(output_path, "w") as f:
            json.dump(predictions, f, indent=2)
        print(f"\n✓ Predictions saved to {output_path}")

    if csv_path:
        save_csv(csv_rows, metadata, csv_path)
        print(f"✓ Results CSV saved to {csv_path}")

    if metadata_path:
        save_metadata(metadata, metadata_path)
        print(f"✓ Metadata saved to {metadata_path}")

    return predictions, csv_rows, metadata


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="HotpotQA Sentence-Level Retrieval Experiments")
    parser.add_argument("--method", choices=["decomposition", "ircot"], default="decomposition",
                        help="Reasoning method to use")
    parser.add_argument("--retriever_type", choices=["paragraph", "sentence"], default="paragraph",
                        help="Retriever type: paragraph-level or sentence-level")
    parser.add_argument("--max_examples", type=int, default=None,
                        help="Max examples to evaluate (for quick testing)")
    parser.add_argument("--shuffle_data", action="store_true",
                        help="Shuffle data before evaluation")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--top_k_paragraphs", type=int, default=2,
                        help="Top-k paragraphs/sentences to retrieve")
    parser.add_argument("--data_dir", type=str, default="data/hotpotqa",
                        help="Path to HotpotQA data directory")

    args = parser.parse_args()

    # Prepare experiment directories
    exp_base = PROJECT_ROOT / "experiments"
    exp_base.mkdir(exist_ok=True)

    # Create subdirectories for each configuration
    exp_name = f"{args.method}_{args.retriever_type}"
    exp_dir = exp_base / exp_name
    exp_dir.mkdir(exist_ok=True)

    # Create timestamped subdirectory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = exp_dir / timestamp
    run_dir.mkdir(exist_ok=True)

    # Define output paths
    predictions_path = run_dir / "predictions.json"
    csv_path = run_dir / "results.csv"
    metadata_path = run_dir / "metadata.json"

    print(f"\n{'='*80}")
    print(f"🔍 Retriever Type: {args.retriever_type.upper()}")
    print(f"📘 Method: {args.method.upper()}")
    print(f"📁 Experiment Dir: {exp_dir}")
    print(f"💾 Output Dir: {run_dir}")
    print(f"{'='*80}\n")

    # Load dataset
    data_dir = PROJECT_ROOT / args.data_dir
    dev_data = load_hotpotqa(data_dir=data_dir, split="dev", max_examples=None)
    print(f"✓ Loaded {len(dev_data)} examples from {args.data_dir}")

    # Set seed if provided
    if args.seed is not None:
        random.seed(args.seed)
        print(f"✓ Set random seed to {args.seed}")

    # Shuffle if requested
    if args.shuffle_data:
        random.shuffle(dev_data)
        print(f"✓ Shuffled data")

    # Limit examples
    if args.max_examples:
        dev_data = dev_data[:args.max_examples]
        print(f"✓ Limited to {args.max_examples} examples for testing")

    # Initialize LLM
    print(f"✓ Initializing Mistral LLM client...\n")
    llm = MistralLLMClient()

    # Run evaluation
    run_evaluation(
        llm=llm,
        embedder_client=llm,
        dev_data=dev_data,
        method=args.method,
        retriever_type=args.retriever_type,
        top_k_paragraphs=args.top_k_paragraphs,
        output_path=predictions_path,
        csv_path=csv_path,
        metadata_path=metadata_path,
    )

    print(f"\n{'='*80}")
    print(f"✅ Experiment completed!")
    print(f"Results available in: {run_dir}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
