#!/usr/bin/env python3

import sys
import json
import csv
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field

# Add project root to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.loader import load_hotpotqa
from src.reasoning.ircot import (
    MistralLLMClient,
    IRCoTRetriever,
    IRCoTConfig,
    QAReader,
    config,
    load_default_hotpot_demos,
    InMemoryRetriever,
    Paragraph,
    ParagraphWithSentences,
    DistractorRetrieverAdapter,
)
from src.reasoning.decomposition import (
    DecompositionReasoner,
    DecompositionConfig,
)
from evaluation.eval import eval as official_eval, f1_score, normalize_answer

def sp_metrics(prediction_sp, gold_sp):
    pred_set = set(map(tuple, prediction_sp))
    gold_set = set(map(tuple, gold_sp))
    
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0.0
    
    return prec, recall, f1

@dataclass
class MethodResult:
    """Result from running a QA method (decomposition or IRCoT)."""
    answer: str
    debug_lines: List[str]
    sub_queries: List[str] = field(default_factory=list)
    sub_answers: List[str] = field(default_factory=list)

def run_decomposition(question: str, retriever_adapter: DistractorRetrieverAdapter, 
                      llm, config: DecompositionConfig) -> MethodResult:
    reasoner = DecompositionReasoner(
        retriever=retriever_adapter,
        llm=llm,
        config=config,
    )
    
    result = reasoner.run(question)
    
    debug_lines = []
    debug_lines.append(f"\n📋 Planned Sub-Questions ({len(result.planned_questions)}):")
    for j, pq in enumerate(result.planned_questions, 1):
        debug_lines.append(f"   {j}. {pq}")
    
    debug_lines.append(f"\n📝 Executed Sub-Questions and Answers:")
    for j, sub_qa in enumerate(result.sub_qas, 1):
        debug_lines.append(f"   Q{j}: {sub_qa.question}")
        debug_lines.append(f"   A{j}: {sub_qa.answer}")
        debug_lines.append(f"       Retrieved: {sub_qa.retrieved_titles}")
    
    # Clean up final answer
    cleaned_answer = result.final_answer
    if "**" in cleaned_answer:
        cleaned_answer = cleaned_answer.replace("**", "")
    if "\n" in cleaned_answer:
        cleaned_answer = cleaned_answer.split("\n")[0].strip()
    cleaned_answer = cleaned_answer.rstrip(".")
    
    # Extract sub-queries and sub-answers
    sub_queries = [sq.question for sq in result.sub_qas]
    sub_answers = [sq.answer for sq in result.sub_qas]
    
    return MethodResult(
        answer=cleaned_answer,
        debug_lines=debug_lines,
        sub_queries=sub_queries,
        sub_answers=sub_answers,
    )


def run_ircot(question: str, retriever_adapter: DistractorRetrieverAdapter,
              llm, config: IRCoTConfig, demos) -> MethodResult:
    ircot = IRCoTRetriever(
        retriever=retriever_adapter,
        llm=llm,
        demos=demos,
        config=config,
    )
    
    result = ircot.run(question)
    
    debug_lines = []
    debug_lines.append(f"\n🔗 Chain-of-Thought Steps ({len(result.cot_steps)}):")
    for j, step in enumerate(result.cot_steps, 1):
        debug_lines.append(f"   {j}. {step}")
    
    debug_lines.append(f"\n📚 Retrieved Paragraphs ({len(result.retrieved_paragraphs)}):")
    for p in result.retrieved_paragraphs[:5]:  # Show first 5
        debug_lines.append(f"   - {p.title}: {p.text[:80]}...")
    
    # Use QA Reader for final answer
    reader = QAReader(llm=llm, demos=demos, config=config)
    qa_result = reader.answer(question, result.retrieved_paragraphs)
    
    # Clean up answer
    cleaned_answer = qa_result.answer
    if "**" in cleaned_answer:
        cleaned_answer = cleaned_answer.replace("**", "")
    if "\n" in cleaned_answer:
        cleaned_answer = cleaned_answer.split("\n")[0].strip()
    cleaned_answer = cleaned_answer.rstrip(".")
    
    # For IRCoT, use CoT steps as "sub-queries" (reasoning steps)
    # No separate sub-answers for IRCoT
    return MethodResult(
        answer=cleaned_answer,
        debug_lines=debug_lines,
        sub_queries=result.cot_steps,
        sub_answers=[],  # IRCoT doesn't have separate sub-answers
    )


def get_gold_sentence_texts(context: List[List], gold_sp: List[List]) -> List[str]:
    # Build a lookup: (title, sent_idx) -> text
    lookup: Dict[Tuple[str, int], str] = {}
    for title, sent_list in context:
        for sent_idx, sent_text in enumerate(sent_list):
            lookup[(title, sent_idx)] = sent_text.strip()
    
    # Get texts for gold SPs
    texts = []
    for sp in gold_sp:
        key = (sp[0], sp[1])
        if key in lookup:
            texts.append(lookup[key])
        else:
            texts.append(f"[NOT FOUND: {sp[0]}:{sp[1]}]")
    
    return texts
def check_sp_explosion(predicted_sp, gold_sp, threshold_ratio=2.0, precision_threshold=0.4):
    """
    Determine if supporting fact explosion occurred.
    
    Explosion defined as:
    - Predicted SP count > threshold_ratio × gold SP count
    - AND precision < precision_threshold
    
    Returns: (bool, explanation_string)
    """
    pred_count = len(predicted_sp)
    gold_count = len(gold_sp)
    
    pred_set = set(map(tuple, predicted_sp))
    gold_set = set(map(tuple, gold_sp))
    
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    explosion = (pred_count > threshold_ratio * gold_count) and (precision < precision_threshold)

    explanation = (
        f"Pred {pred_count} vs Gold {gold_count} | "
        f"Precision {precision:.3f} | Explosion: {explosion}"
    )
    return explosion, explanation

def run_evaluation(
    llm: Any,
    embedder_client: Any,
    dev_data: List[Dict],
    method: str = "decomposition",
    top_k_paragraphs: int = 2,
    output_path: Optional[Path] = None,
    csv_path: Optional[Path] = None,
) -> Tuple[Dict, List[Dict]]:
    # Method-specific config
    if method == "decomposition":
        config = DecompositionConfig()
        demos = None
    else:  # ircot
        config = IRCoTConfig()
        demos = load_default_hotpot_demos(max_examples=config.max_demos)
    
    predictions = {"answer": {}, "sp": {}}
    csv_rows = []
    
    for i, example in enumerate(dev_data, 1):
        qid = example['_id']
        question = example['question']
        gold_answer = example.get('answer', 'N/A')
        gold_sp = example.get('supporting_facts', [])
        context = example['context']
        
        print(f"[{i}/{len(dev_data)}] {question[:60]}...")
        
        try:
            # Build paragraphs from context
            paragraphs_with_sentences = [
                ParagraphWithSentences(title=title, sentences=[s.strip() for s in sent_list])
                for title, sent_list in context
            ]
            
            # Create Paragraph objects for the retriever (pid, title, full_text)
            paragraphs_for_retriever = [
                Paragraph(pid=idx, title=p.title, text=p.full_text)
                for idx, p in enumerate(paragraphs_with_sentences)
            ]
            
            # Get raw Mistral client for embeddings
            raw_mistral = embedder_client.client.client
            
            # Build in-memory retriever
            memory_retriever = InMemoryRetriever(paragraphs_for_retriever, raw_mistral)
            
            # Wrap with adapter for SP tracking
            retriever_adapter = DistractorRetrieverAdapter(
                memory_retriever,
                paragraphs_with_sentences,
                top_k_paragraphs=top_k_paragraphs
            )
            
            # Run the selected method
            if method == "decomposition":
                method_result = run_decomposition(
                    question, retriever_adapter, llm, config
                )
            else:  # ircot
                method_result = run_ircot(
                    question, retriever_adapter, llm, config, demos
                )
            
            cleaned_answer = method_result.answer
            
            # Store predictions
            predictions["answer"][qid] = cleaned_answer
            sp_list = retriever_adapter.get_supporting_facts()
            predictions["sp"][qid] = sp_list

            # --- SP EXPLOSION ANALYSIS ---
            sp_explosion, sp_expl_msg = check_sp_explosion(sp_list, gold_sp)

            print("----- SP EXPLOSION DEBUG -----")
            print("Predicted SPs:", sp_list)
            print("Gold SPs:", gold_sp)
            print(sp_expl_msg)
            print("------------------------------")

            
            # Calculate per-example metrics
            ans_f1, ans_prec, ans_recall = f1_score(cleaned_answer, gold_answer)
            sp_prec, sp_recall, sp_f1 = sp_metrics(sp_list, gold_sp)
            correct = 1 if ans_f1 > 0.5 else 0
            
            # Get sentence texts
            retrieved_texts = retriever_adapter.get_unique_retrieved_texts()
            gold_texts = get_gold_sentence_texts(context, gold_sp)
            
            # Build CSV row
            row = {
                'question': question,
                'correct': correct,
                'sp_recall': round(sp_recall, 4),
                'sp_precision': round(sp_prec, 4),
                'generated_answer': cleaned_answer,
                'gold_answer': gold_answer,
            }
            
            for idx, sq in enumerate(method_result.sub_queries):
                row[f'subquery_{idx+1}'] = sq
            for idx, sa in enumerate(method_result.sub_answers):
                row[f'subanswer_{idx+1}'] = sa
            
            row['num_subqueries'] = len(method_result.sub_queries)
            row['num_subanswers'] = len(method_result.sub_answers)
            row['num_retrieved'] = len(retrieved_texts)
            row['num_gold'] = len(gold_texts)

            # --- SP explosion fields ---
            row['sp_explosion'] = int(sp_explosion)
            row['sp_explosion_msg'] = sp_expl_msg
            row['num_pred_sp'] = len(sp_list)   # predicted SP count
            row['num_gold_sp'] = len(gold_sp)   # gold SP count

            
            for idx, text in enumerate(retrieved_texts):
                row[f'retrieved_{idx+1}'] = text
            for idx, text in enumerate(gold_texts):
                row[f'gold_{idx+1}'] = text
            
            csv_rows.append(row)
            
            print(f"   Answer: {cleaned_answer} | Gold: {gold_answer} | Correct: {correct}")
            
        except Exception as e:
            print(f"   ERROR: {e}")
            import traceback
            traceback.print_exc()
            predictions["answer"][qid] = "error"
            predictions["sp"][qid] = []
            
            csv_rows.append({
                'question': question,
                'correct': 0,
                'sp_precision': 0,
                'sp_recall': 0,
                'generated_answer': 'ERROR',
                'gold_answer': gold_answer,
                'num_subqueries': 0,
                'num_subanswers': 0,
                'num_retrieved': 0,
                'num_gold': len(gold_sp),
            })
    
    # ---- Build metadata row for experiment ----
    metadata = {
        "experiment_id": f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "method": method,
        "llm_model": getattr(llm, "model_name", "unknown"),
        "embedding_model": getattr(embedder_client, "embedding_model", "unknown"),
        "top_k": top_k_paragraphs,
        "max_examples": len(dev_data),
        "shuffle_data": getattr(args, "shuffle_data", False),
        "seed": getattr(args, "seed", None)
    }

    # Convert configs to JSON so it's readable
    try:
        metadata["config"] = json.dumps(config.__dict__)
    except:
        metadata["config"] = str(config)


    # Save if paths provided
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(predictions, f)
        print(f"Predictions saved to {output_path}")
    
    if csv_path:
        save_csv(csv_rows,metadata, csv_path)
        print(f"CSV saved to {csv_path}")
    
    return predictions, csv_rows, metadata


def save_csv(csv_rows: List[Dict], metadata: Dict, csv_path: Path):
    base_columns = ['question', 'correct', 'sp_precision', 'sp_recall',
                    'generated_answer', 'gold_answer']

    max_subqueries = max((row.get('num_subqueries', 0) for row in csv_rows), default=0)
    max_subanswers = max((row.get('num_subanswers', 0) for row in csv_rows), default=0)
    max_retrieved = max((row.get('num_retrieved', 0) for row in csv_rows), default=0)
    max_gold = max((row.get('num_gold', 0) for row in csv_rows), default=0)

    subquery_columns = [f'subquery_{i+1}' for i in range(max_subqueries)]
    subanswer_columns = [f'subanswer_{i+1}' for i in range(max_subanswers)]
    count_columns = ['num_retrieved', 'num_gold']
    retrieved_columns = [f'retrieved_{i+1}' for i in range(max_retrieved)]
    gold_columns = [f'gold_{i+1}' for i in range(max_gold)]

    all_columns = (
        base_columns +
        subquery_columns +
        subanswer_columns +
        count_columns +
        retrieved_columns +
        gold_columns
    )

    # Build metadata header
    metadata_header = list(metadata.keys())
    metadata_values = [metadata[k] for k in metadata_header]

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # ---- Write metadata row ----
        writer.writerow(metadata_header)
        writer.writerow(metadata_values)
        writer.writerow([])   # blank line for readability

        # ---- Write results table ----
        writer = csv.DictWriter(f, fieldnames=all_columns, extrasaction='ignore')
        writer.writeheader()

        for row in csv_rows:
            writer.writerow(row)

def main():
    exp_dir = PROJECT_ROOT / "experiments"
    exp_dir.mkdir(exist_ok=True)

    parser = argparse.ArgumentParser(description="Run QA pipeline evaluation")
    parser.add_argument("--method", type=str, choices=["decomposition", "ircot"], 
                        default="decomposition", help="QA method to use")
    parser.add_argument("--max_examples", type=int, default=None, help="Limit number of examples")
    parser.add_argument("--output", type=str, default="predictions.json", help="Output predictions file")
    parser.add_argument("--csv_output", type=str, default="results.csv", help="Output CSV file")
    parser.add_argument("--data_dir", type=str, default="data/hotpotqa", help="Path to HotpotQA data directory")
    parser.add_argument("--top_k_paragraphs", type=int, default=2, help="Number of paragraphs to retrieve per sub-query")
    args = parser.parse_args()

    print(f"Starting Evaluation Pipeline (Method: {args.method.upper()})")
    print(f"  Retrieving top {args.top_k_paragraphs} paragraphs per sub-query")
    
    # 1. Load Data
    data_dir = PROJECT_ROOT / args.data_dir
    try:
        dev_data = load_hotpotqa(
            data_dir=data_dir,
            split="dev",
            max_examples=args.max_examples,
            shuffle=False 
        )
        print(f"Loaded {len(dev_data)} examples from {data_dir}")
    except FileNotFoundError:
        print(f"Could not find data in {data_dir}")
        return

    # 2. Initialize LLM (Mistral API for both generation and embeddings)
    llm = MistralLLMClient()
    
    # 3. Run evaluation
    # ---- Save to experiments folder with unique filenames ----
    from datetime import datetime

    exp_dir = PROJECT_ROOT / "experiments"
    exp_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_path = exp_dir / f"predictions_{timestamp}.json"
    csv_path = exp_dir / f"results_{timestamp}.csv"

    print(f"\n📁 Output will be saved to:")
    print(f"   {output_path}")
    print(f"   {csv_path}")


    predictions, csv_rows, metadata = run_evaluation(
        llm=llm,
        embedder_client=llm,  # Same client for embeddings
        dev_data=dev_data,
        method=args.method,
        top_k_paragraphs=args.top_k_paragraphs,
        output_path=output_path,
        csv_path=csv_path,
    )

    # 4. Run Official Evaluation
    print("\nRunning Official Evaluation...")
    gold_file = data_dir / "hotpot_dev_distractor_v1.json"
    
    subset_gold_path = None
    if args.max_examples:
        subset_gold_path = PROJECT_ROOT / "temp_gold_subset.json"
        with open(subset_gold_path, 'w') as f:
            json.dump(dev_data, f)
        gold_file = subset_gold_path

    try:
        official_eval(str(output_path), str(gold_file))
    except Exception as e:
        print(f"Evaluation failed: {e}")

    if subset_gold_path and subset_gold_path.exists():
        subset_gold_path.unlink()


if __name__ == "__main__":
    main()
