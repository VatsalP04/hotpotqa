#!/usr/bin/env python3
"""
Experiment 2: Sentence-Level vs Paragraph-Level Retrieval Comparison

This script runs a controlled comparison between:
1. Paragraph-level retrieval (baseline)
2. Sentence-level retrieval with context window expansion

Produces two CSVs and a comparison report.

Usage:
    python scripts/02_sentence_vs_paragraph.py --max_examples 100 --seed 42
"""

import sys
import json
import csv
import argparse
import random
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from collections import defaultdict
import math

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Import from existing modules
from src.data.loader import load_hotpotqa
from src.models.mistral_client import MistralClient
from evaluation.eval import f1_score as eval_f1_score


# =============================================================================
# Data Models
# =============================================================================
@dataclass
class Paragraph:
    pid: int
    title: str
    text: str
    score: float = 0.0


@dataclass
class Sentence:
    title: str
    sentence_idx: int
    text: str
    score: float = 0.0
    context_window: Optional[str] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None


@dataclass
class ParagraphWithSentences:
    title: str
    sentences: List[str]
    
    @property
    def full_text(self) -> str:
        return ' '.join(self.sentences)


# =============================================================================
# BM25 Implementation (shared)
# =============================================================================
class BM25Index:
    """BM25 index that can work at paragraph or sentence level."""
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freqs = defaultdict(int)
        self.doc_lengths = []
        self.tokenized_docs = []
        self.documents = []
        self.avg_doc_length = 0
        self.N = 0
    
    def _tokenize(self, text: str) -> List[str]:
        import re
        return re.findall(r'\w+', text.lower())
    
    def index(self, documents: List[Any], text_fn):
        """Index documents using provided text extraction function."""
        self.documents = documents
        
        for doc in documents:
            text = text_fn(doc)
            tokens = self._tokenize(text)
            self.tokenized_docs.append(tokens)
            self.doc_lengths.append(len(tokens))
            
            for term in set(tokens):
                self.doc_freqs[term] += 1
        
        self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 1
        self.N = len(documents)
    
    def _idf(self, term: str) -> float:
        df = self.doc_freqs.get(term, 0)
        if df == 0:
            return 0
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)
    
    def _score(self, query_tokens: List[str], doc_idx: int) -> float:
        doc_tokens = self.tokenized_docs[doc_idx]
        doc_len = self.doc_lengths[doc_idx]
        
        tf = defaultdict(int)
        for token in doc_tokens:
            tf[token] += 1
        
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            
            term_freq = tf[term]
            idf = self._idf(term)
            numerator = term_freq * (self.k1 + 1)
            denominator = term_freq + self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_length))
            score += idf * (numerator / denominator)
        
        return score
    
    def search(self, query: str, top_k: int = 10) -> List[Tuple[Any, float]]:
        """Search and return (document, score) pairs."""
        query_tokens = self._tokenize(query)
        
        scores = []
        for idx in range(len(self.documents)):
            score = self._score(query_tokens, idx)
            scores.append((score, idx))
        
        scores.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for score, idx in scores[:top_k]:
            results.append((self.documents[idx], score))
        
        return results


# =============================================================================
# Paragraph-Level Retriever
# =============================================================================
class ParagraphRetriever:
    """Retrieves at paragraph level."""
    
    def __init__(self, paragraphs: List[ParagraphWithSentences]):
        self.paragraphs = paragraphs
        self.index = BM25Index()
        self.index.index(paragraphs, lambda p: p.full_text)
        self._retrieved_sp = []
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Paragraph]:
        """Retrieve top-k paragraphs."""
        results = self.index.search(query, top_k)
        
        self._retrieved_sp = []
        output = []
        
        for i, (para, score) in enumerate(results):
            output.append(Paragraph(
                pid=i,
                title=para.title,
                text=para.full_text,
                score=score
            ))
            
            # For SP evaluation: claim ALL sentences in retrieved paragraphs
            for sent_idx in range(len(para.sentences)):
                self._retrieved_sp.append((para.title, sent_idx))
        
        return output
    
    def get_supporting_facts(self) -> List[Tuple[str, int]]:
        """Return predicted supporting facts."""
        return self._retrieved_sp


# =============================================================================
# Sentence-Level Retriever with Context Window
# =============================================================================
class SentenceLevelRetriever:
    """
    Retrieves at sentence level with context window expansion.
    Implements Option 3: Core sentence for evaluation, window for context.
    """
    
    def __init__(self, paragraphs: List[ParagraphWithSentences], context_window: int = 1):
        self.paragraphs = paragraphs
        self.context_window = context_window
        self.sentences = []
        self._retrieved_sp = []
        self._retrieved_metadata = []
        
        # Build sentence index
        for para in paragraphs:
            for sent_idx, sent_text in enumerate(para.sentences):
                self.sentences.append(Sentence(
                    title=para.title,
                    sentence_idx=sent_idx,
                    text=sent_text,
                ))
        
        # Index sentences with context for better retrieval
        self.index = BM25Index()
        self.index.index(self.sentences, lambda s: self._get_sentence_with_context(s))
    
    def _get_sentence_with_context(self, sentence: Sentence) -> str:
        """Get sentence text with surrounding context for embedding/indexing."""
        # Find the paragraph
        para = None
        for p in self.paragraphs:
            if p.title == sentence.title:
                para = p
                break
        
        if para is None:
            return sentence.text
        
        # Build context window
        idx = sentence.sentence_idx
        start = max(0, idx - self.context_window)
        end = min(len(para.sentences), idx + self.context_window + 1)
        
        context_text = ' '.join(para.sentences[start:end])
        return f"{para.title}: {context_text}"
    
    def _expand_context(self, sentence: Sentence) -> Sentence:
        """Expand a retrieved sentence with its context window."""
        # Find the paragraph
        para = None
        for p in self.paragraphs:
            if p.title == sentence.title:
                para = p
                break
        
        if para is None:
            return sentence
        
        idx = sentence.sentence_idx
        start = max(0, idx - self.context_window)
        end = min(len(para.sentences), idx + self.context_window + 1)
        
        expanded_text = ' '.join(para.sentences[start:end])
        
        sentence.context_window = expanded_text
        sentence.span_start = start
        sentence.span_end = end - 1  # Inclusive end
        
        return sentence
    
    def retrieve(self, query: str, top_k_sentences: int = 10) -> List[Paragraph]:
        """
        Retrieve top sentences and return as expanded paragraphs.
        
        Returns Paragraph objects for compatibility with downstream components,
        but tracks sentence-level supporting facts internally.
        """
        results = self.index.search(query, top_k_sentences)
        
        self._retrieved_sp = []
        self._retrieved_metadata = []
        seen_sp = set()
        
        # Expand sentences and deduplicate
        expanded_chunks = []
        for sentence, score in results:
            sentence.score = score
            expanded = self._expand_context(sentence)
            
            # Track core sentence as supporting fact (Option 3)
            sp_tuple = (expanded.title, expanded.sentence_idx)
            if sp_tuple not in seen_sp:
                seen_sp.add(sp_tuple)
                self._retrieved_sp.append(sp_tuple)
                
                self._retrieved_metadata.append({
                    'title': expanded.title,
                    'core_idx': expanded.sentence_idx,
                    'span_start': expanded.span_start,
                    'span_end': expanded.span_end,
                    'score': expanded.score,
                    'core_text': expanded.text,
                    'expanded_text': expanded.context_window,
                })
            
            expanded_chunks.append(expanded)
        
        # Convert to Paragraph objects for compatibility
        # Group by title to avoid redundant chunks
        by_title = defaultdict(list)
        for sent in expanded_chunks:
            by_title[sent.title].append(sent)
        
        output = []
        for i, (title, sents) in enumerate(by_title.items()):
            # Take best scoring sentence's expanded context
            best_sent = max(sents, key=lambda s: s.score)
            output.append(Paragraph(
                pid=i,
                title=title,
                text=best_sent.context_window or best_sent.text,
                score=best_sent.score
            ))
        
        return output
    
    def get_supporting_facts(self) -> List[Tuple[str, int]]:
        """Return predicted supporting facts (core sentences only)."""
        return self._retrieved_sp
    
    def get_metadata(self) -> List[Dict]:
        """Return rich metadata for analysis."""
        return self._retrieved_metadata


# =============================================================================
# Evaluation Metrics
# =============================================================================
def sp_metrics(pred_sp: List[Tuple[str, int]], gold_sp: List[Tuple[str, int]]) -> Dict:
    """Compute supporting fact metrics with multiple granularities."""
    pred_set = set(map(tuple, pred_sp))
    gold_set = set(map(tuple, gold_sp))
    
    # Strict metrics
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    # Soft metrics: count gold facts that have a prediction within tolerance
    def soft_recall(tolerance: int) -> float:
        matches = 0
        for gold_title, gold_idx in gold_set:
            for pred_title, pred_idx in pred_set:
                if gold_title == pred_title and abs(gold_idx - pred_idx) <= tolerance:
                    matches += 1
                    break
        return matches / len(gold_set) if gold_set else 0
    
    soft_recall_1 = soft_recall(1)
    soft_recall_2 = soft_recall(2)
    
    # Title-level metrics
    pred_titles = set(t for t, _ in pred_set)
    gold_titles = set(t for t, _ in gold_set)
    
    title_tp = len(pred_titles & gold_titles)
    title_precision = title_tp / len(pred_titles) if pred_titles else 0
    title_recall = title_tp / len(gold_titles) if gold_titles else 0
    
    return {
        'strict_precision': precision,
        'strict_recall': recall,
        'strict_f1': f1,
        'soft_recall_tol1': soft_recall_1,
        'soft_recall_tol2': soft_recall_2,
        'title_precision': title_precision,
        'title_recall': title_recall,
        'num_pred': len(pred_set),
        'num_gold': len(gold_set),
    }


def compute_answer_f1(prediction: str, ground_truth: str) -> Tuple[float, float, float]:
    """Compute token-level F1 score for answer using evaluation module."""
    # Use the existing evaluation function
    f1, precision, recall = eval_f1_score(prediction, ground_truth)
    return (f1, precision, recall)


def categorize_error(metrics: Dict) -> str:
    """Categorize the type of retrieval error."""
    if metrics['strict_f1'] >= 0.8:
        return 'correct'
    elif metrics['title_recall'] == 0:
        return 'wrong_document'
    elif metrics['soft_recall_tol1'] > metrics['strict_recall']:
        return 'off_by_one'
    elif metrics['soft_recall_tol2'] > metrics['strict_recall']:
        return 'off_by_two'
    else:
        return 'wrong_sentence'


# =============================================================================
# LLM Wrapper for Answer Generation
# =============================================================================
class AnswerGenerator:
    """LLM wrapper for answer generation using Mistral."""
    
    def __init__(self, mistral_client: Optional[MistralClient] = None, use_simple: bool = False):
        """
        Initialize answer generator.
        
        Args:
            mistral_client: Mistral client for API calls
            use_simple: If True, use simple extractive method instead of API
        """
        self.client = mistral_client
        self.use_simple = use_simple or (mistral_client is None)
    
    def generate_answer(self, question: str, context: str) -> str:
        """Generate answer from question and context."""
        if self.use_simple:
            return self._simple_extractive(question, context)
        else:
            return self._mistral_generate(question, context)
    
    def _simple_extractive(self, question: str, context: str) -> str:
        """Simple extractive answer (fallback method)."""
        import re
        
        question_words = set(re.findall(r'\w+', question.lower()))
        question_words -= {'what', 'who', 'where', 'when', 'which', 'how', 'is', 'are', 'was', 'were', 'the', 'a', 'an'}
        
        sentences = re.split(r'[.!?]', context)
        
        best_sentence = ""
        best_overlap = 0
        
        for sent in sentences:
            sent_words = set(re.findall(r'\w+', sent.lower()))
            overlap = len(question_words & sent_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_sentence = sent.strip()
        
        # Return first few words as "answer"
        words = best_sentence.split()[:10]
        return ' '.join(words) if words else "unknown"
    
    def _mistral_generate(self, question: str, context: str) -> str:
        """Generate answer using Mistral API."""
        try:
            answer = self.client.answer_question(
                question=question,
                context=context,
                system_prompt="You are a helpful assistant. Answer the question based on the given context. Provide a concise answer."
            )
            return answer.strip()
        except Exception as e:
            print(f"Warning: Mistral API call failed: {e}. Using simple extraction.")
            return self._simple_extractive(question, context)


# =============================================================================
# Main Experiment Runner
# =============================================================================
def run_single_method(
    dev_data: List[Dict],
    retriever_type: str,
    llm,
    top_k: int = 5,
    context_window: int = 1,
) -> Tuple[List[Dict], Dict]:
    """
    Run evaluation with a single retrieval method.
    
    Returns:
        (csv_rows, aggregated_metrics)
    """
    csv_rows = []
    all_metrics = []
    
    for i, example in enumerate(dev_data):
        qid = example.get('_id', str(i))
        question = example['question']
        gold_answer = example.get('answer', 'N/A')
        gold_sp = example.get('supporting_facts', [])
        context = example['context']
        
        # Build paragraphs
        paragraphs = [
            ParagraphWithSentences(title, sentences)
            for title, sentences in context
        ]
        
        # Initialize retriever based on type
        if retriever_type == 'paragraph':
            retriever = ParagraphRetriever(paragraphs)
            retrieved = retriever.retrieve(question, top_k)
        else:  # sentence
            retriever = SentenceLevelRetriever(paragraphs, context_window)
            retrieved = retriever.retrieve(question, top_k * 3)  # More sentences
        
        # Get supporting facts
        pred_sp = retriever.get_supporting_facts()
        
        # Limit SP predictions to reasonable number
        pred_sp = pred_sp[:top_k * 3]
        
        # Generate answer
        context_text = '\n'.join([f"{p.title}: {p.text}" for p in retrieved])
        generated_answer = llm.generate_answer(question, context_text)
        
        # Compute metrics
        sp_result = sp_metrics(pred_sp, gold_sp)
        ans_f1, ans_p, ans_r = compute_answer_f1(generated_answer, gold_answer)
        
        error_type = categorize_error(sp_result)
        
        row = {
            'qid': qid,
            'question': question,
            'gold_answer': gold_answer,
            'generated_answer': generated_answer,
            'answer_f1': round(ans_f1, 4),
            'sp_strict_precision': round(sp_result['strict_precision'], 4),
            'sp_strict_recall': round(sp_result['strict_recall'], 4),
            'sp_strict_f1': round(sp_result['strict_f1'], 4),
            'sp_soft_recall_tol1': round(sp_result['soft_recall_tol1'], 4),
            'sp_soft_recall_tol2': round(sp_result['soft_recall_tol2'], 4),
            'sp_title_recall': round(sp_result['title_recall'], 4),
            'num_pred_sp': sp_result['num_pred'],
            'num_gold_sp': sp_result['num_gold'],
            'error_type': error_type,
            'pred_sp': str(pred_sp[:10]),  # First 10 for CSV
            'gold_sp': str(gold_sp),
        }
        
        csv_rows.append(row)
        all_metrics.append({**sp_result, 'answer_f1': ans_f1})
        
        # Progress
        if (i + 1) % 20 == 0:
            avg_sp_f1 = sum(m['strict_f1'] for m in all_metrics) / len(all_metrics)
            avg_ans_f1 = sum(m['answer_f1'] for m in all_metrics) / len(all_metrics)
            print(f"  [{i+1}/{len(dev_data)}] SP-F1: {avg_sp_f1:.3f}, Ans-F1: {avg_ans_f1:.3f}")
    
    # Aggregate
    n = len(all_metrics)
    aggregated = {
        'n_examples': n,
        'avg_answer_f1': sum(m['answer_f1'] for m in all_metrics) / n,
        'avg_sp_strict_precision': sum(m['strict_precision'] for m in all_metrics) / n,
        'avg_sp_strict_recall': sum(m['strict_recall'] for m in all_metrics) / n,
        'avg_sp_strict_f1': sum(m['strict_f1'] for m in all_metrics) / n,
        'avg_sp_soft_recall_tol1': sum(m['soft_recall_tol1'] for m in all_metrics) / n,
        'avg_sp_soft_recall_tol2': sum(m['soft_recall_tol2'] for m in all_metrics) / n,
        'avg_sp_title_recall': sum(m['title_recall'] for m in all_metrics) / n,
    }
    
    # Error type distribution
    error_counts = defaultdict(int)
    for row in csv_rows:
        error_counts[row['error_type']] += 1
    aggregated['error_distribution'] = dict(error_counts)
    
    return csv_rows, aggregated


def save_csv(csv_rows: List[Dict], csv_path: Path, metadata: Dict):
    """Save results to CSV with metadata header."""
    if not csv_rows:
        return
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        # Write metadata as comments
        for key, value in metadata.items():
            f.write(f"# {key}: {value}\n")
        f.write("#\n")
        
        # Write data
        fieldnames = list(csv_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)
    
    print(f"  Saved: {csv_path}")


def print_comparison(para_agg: Dict, sent_agg: Dict):
    """Print detailed comparison between methods."""
    print("\n" + "="*80)
    print("COMPARISON: PARAGRAPH-LEVEL vs SENTENCE-LEVEL RETRIEVAL")
    print("="*80)
    
    metrics = [
        ('Answer F1', 'avg_answer_f1'),
        ('SP Strict Precision', 'avg_sp_strict_precision'),
        ('SP Strict Recall', 'avg_sp_strict_recall'),
        ('SP Strict F1', 'avg_sp_strict_f1'),
        ('SP Soft Recall (±1)', 'avg_sp_soft_recall_tol1'),
        ('SP Soft Recall (±2)', 'avg_sp_soft_recall_tol2'),
        ('SP Title Recall', 'avg_sp_title_recall'),
    ]
    
    print(f"\n{'Metric':<25} {'Paragraph':<15} {'Sentence':<15} {'Δ':<15} {'Winner':<10}")
    print("-"*80)
    
    for name, key in metrics:
        para_val = para_agg.get(key, 0)
        sent_val = sent_agg.get(key, 0)
        delta = sent_val - para_val
        
        if abs(delta) < 0.001:
            winner = "Tie"
        elif delta > 0:
            winner = "Sentence ✓"
        else:
            winner = "Paragraph ✓"
        
        delta_str = f"{delta:+.4f}"
        print(f"{name:<25} {para_val:<15.4f} {sent_val:<15.4f} {delta_str:<15} {winner:<10}")
    
    print("\n" + "-"*80)
    print("ERROR TYPE DISTRIBUTION:")
    print("-"*80)
    
    print(f"\n{'Error Type':<20} {'Paragraph':<15} {'Sentence':<15}")
    print("-"*50)
    
    all_types = set(para_agg.get('error_distribution', {}).keys()) | \
                set(sent_agg.get('error_distribution', {}).keys())
    
    for error_type in sorted(all_types):
        para_count = para_agg.get('error_distribution', {}).get(error_type, 0)
        sent_count = sent_agg.get('error_distribution', {}).get(error_type, 0)
        print(f"{error_type:<20} {para_count:<15} {sent_count:<15}")
    
    print("\n" + "="*80)
    
    # Summary recommendation
    sp_improvement = sent_agg['avg_sp_strict_f1'] - para_agg['avg_sp_strict_f1']
    ans_improvement = sent_agg['avg_answer_f1'] - para_agg['avg_answer_f1']
    
    print("\n📊 SUMMARY:")
    print(f"  SP F1 Change: {sp_improvement:+.4f} ({'+' if sp_improvement > 0 else ''}{sp_improvement*100:.1f}%)")
    print(f"  Answer F1 Change: {ans_improvement:+.4f} ({'+' if ans_improvement > 0 else ''}{ans_improvement*100:.1f}%)")
    
    if sp_improvement > 0.02:
        print("\n  ✅ RECOMMENDATION: Sentence-level retrieval shows significant SP improvement.")
        print("     Proceed with sentence-level optimization.")
    elif sp_improvement > 0:
        print("\n  ⚠️ RECOMMENDATION: Sentence-level shows marginal improvement.")
        print("     Consider optimizing context window and reranking.")
    else:
        print("\n  ❌ RECOMMENDATION: Paragraph-level performs better.")
        print("     Investigate why sentence-level is underperforming.")
    
    print("="*80)


def main():
    parser = argparse.ArgumentParser(description="Compare Sentence vs Paragraph retrieval")
    parser.add_argument("--max_examples", type=int, default=100,
                        help="Number of examples to evaluate")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument("--top_k", type=int, default=3,
                        help="Top-k paragraphs/sentences to use")
    parser.add_argument("--context_window", type=int, default=1,
                        help="Context window size for sentence retrieval")
    parser.add_argument("--data_path", type=str, default=None,
                        help="Path to HotpotQA dev data JSON")
    
    args = parser.parse_args()
    
    # Set seed
    random.seed(args.seed)
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "experiments" / "sentence_vs_paragraph" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*80)
    print("EXPERIMENT 2: SENTENCE-LEVEL vs PARAGRAPH-LEVEL RETRIEVAL")
    print("="*80)
    print(f"Max Examples: {args.max_examples}")
    print(f"Top-K: {args.top_k}")
    print(f"Context Window: {args.context_window}")
    print(f"Seed: {args.seed}")
    print(f"Output: {output_dir}")
    print("="*80 + "\n")
    
    # Load data
    if args.data_path:
        print(f"Loading data from: {args.data_path}")
        with open(args.data_path, 'r') as f:
            dev_data = json.load(f)
    else:
        # Use the project's data loader
        print(f"Loading data from: {PROJECT_ROOT / 'data' / 'hotpotqa'}")
        dev_data = load_hotpotqa(
            data_dir=PROJECT_ROOT / "data" / "hotpotqa",
            split="dev",
            max_examples=None,
            shuffle=False,
            seed=args.seed
        )
    
    # Shuffle and limit
    random.shuffle(dev_data)
    dev_data = dev_data[:args.max_examples]
    print(f"Loaded {len(dev_data)} examples\n")
    
    # Initialize LLM
    try:
        print("Initializing Mistral client for answer generation...")
        mistral_client = MistralClient()
        llm = AnswerGenerator(mistral_client, use_simple=False)
        print("✅ Using Mistral API for answer generation\n")
    except Exception as e:
        print(f"WARNING: Could not initialize Mistral client: {e}")
        print("Using simple extractive method for answer generation\n")
        llm = AnswerGenerator(use_simple=True)
    
    # Run paragraph-level
    print("📘 Running PARAGRAPH-LEVEL retrieval...")
    print("-"*40)
    para_rows, para_agg = run_single_method(
        dev_data=dev_data,
        retriever_type='paragraph',
        llm=llm,
        top_k=args.top_k,
    )
    
    # Run sentence-level
    print("\n📗 Running SENTENCE-LEVEL retrieval...")
    print("-"*40)
    sent_rows, sent_agg = run_single_method(
        dev_data=dev_data,
        retriever_type='sentence',
        llm=llm,
        top_k=args.top_k,
        context_window=args.context_window,
    )
    
    # Save CSVs
    para_metadata = {
        'method': 'paragraph',
        'top_k': args.top_k,
        'n_examples': args.max_examples,
        'timestamp': timestamp,
    }
    sent_metadata = {
        'method': 'sentence',
        'top_k': args.top_k,
        'context_window': args.context_window,
        'n_examples': args.max_examples,
        'timestamp': timestamp,
    }
    
    save_csv(para_rows, output_dir / "paragraph_results.csv", para_metadata)
    save_csv(sent_rows, output_dir / "sentence_results.csv", sent_metadata)
    
    # Save aggregated comparison
    comparison = {
        'paragraph': para_agg,
        'sentence': sent_agg,
        'config': {
            'max_examples': args.max_examples,
            'top_k': args.top_k,
            'context_window': args.context_window,
            'seed': args.seed,
        }
    }
    
    with open(output_dir / "comparison.json", 'w') as f:
        json.dump(comparison, f, indent=2)
    print(f"  Saved: {output_dir / 'comparison.json'}")
    
    # Print comparison
    print_comparison(para_agg, sent_agg)
    
    print(f"\n📁 All results saved to: {output_dir}")


def create_sample_data() -> List[Dict]:
    """Create sample data for testing without actual HotpotQA data."""
    return [
        {
            '_id': 'sample_1',
            'question': 'What government position is held by the country where Combate Americas is based?',
            'answer': 'President',
            'supporting_facts': [['Combate Americas', 0], ['United States', 1]],
            'context': [
                ['Combate Americas', [
                    'Combate Americas is a mixed martial arts promotion based in the United States.',
                    'It was founded in 2014 by Campbell McLaren.',
                    'The promotion focuses on Latino fighters.'
                ]],
                ['United States', [
                    'The United States of America is a country in North America.',
                    'The head of government is the President.',
                    'The current capital is Washington, D.C.'
                ]],
                ['Mixed martial arts', [
                    'Mixed martial arts is a combat sport.',
                    'It allows various fighting techniques.',
                    'Popular organizations include UFC and Bellator.'
                ]],
            ]
        },
        {
            '_id': 'sample_2',
            'question': 'Who directed the film that starred the actor who played Iron Man?',
            'answer': 'Jon Favreau',
            'supporting_facts': [['Iron Man', 0], ['Robert Downey Jr.', 1]],
            'context': [
                ['Iron Man', [
                    'Iron Man is a 2008 superhero film directed by Jon Favreau.',
                    'It stars Robert Downey Jr. as Tony Stark.',
                    'The film was a commercial success.'
                ]],
                ['Robert Downey Jr.', [
                    'Robert Downey Jr. is an American actor.',
                    'He is best known for playing Iron Man in the MCU.',
                    'He was born in 1965 in New York City.'
                ]],
                ['Jon Favreau', [
                    'Jon Favreau is an American filmmaker.',
                    'He directed Iron Man and Iron Man 2.',
                    'He also acted in several films.'
                ]],
            ]
        },
    ] * 50  # Repeat for 100 examples


if __name__ == "__main__":
    main()
