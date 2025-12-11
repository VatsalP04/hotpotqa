#!/usr/bin/env python3
"""
Experiment 1: Compare Retrieval Methods (BM25 vs Dense Cosine)

This script compares BM25 (sparse) vs Dense (Mistral embeddings + cosine) retrieval
at the paragraph level to determine which base retriever works better.

Usage:
    python scripts/01_compare_retrievers.py --max_examples 100 --seed 42
"""

import sys
import json
import csv
import argparse
import random
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import math

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Import from existing modules
from src.data.loader import load_hotpotqa
from src.models.mistral_client import MistralClient


# =============================================================================
# BM25 Implementation
# =============================================================================
class BM25Retriever:
    """Simple BM25 retriever implementation."""
    
    def __init__(self, paragraphs: List['Paragraph'], k1: float = 1.5, b: float = 0.75):
        self.paragraphs = paragraphs
        self.k1 = k1
        self.b = b
        
        # Build index
        self.doc_freqs = defaultdict(int)  # term -> number of docs containing term
        self.doc_lengths = []
        self.tokenized_docs = []
        
        for para in paragraphs:
            tokens = self._tokenize(para.text)
            self.tokenized_docs.append(tokens)
            self.doc_lengths.append(len(tokens))
            
            # Count document frequency (unique terms per doc)
            unique_terms = set(tokens)
            for term in unique_terms:
                self.doc_freqs[term] += 1
        
        self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 1
        self.N = len(paragraphs)
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization: lowercase and split on non-alphanumeric."""
        import re
        return re.findall(r'\w+', text.lower())
    
    def _idf(self, term: str) -> float:
        """Compute IDF for a term."""
        df = self.doc_freqs.get(term, 0)
        if df == 0:
            return 0
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)
    
    def _score(self, query_tokens: List[str], doc_idx: int) -> float:
        """Compute BM25 score for a document."""
        doc_tokens = self.tokenized_docs[doc_idx]
        doc_len = self.doc_lengths[doc_idx]
        
        # Term frequencies in document
        tf = defaultdict(int)
        for token in doc_tokens:
            tf[token] += 1
        
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            
            term_freq = tf[term]
            idf = self._idf(term)
            
            # BM25 formula
            numerator = term_freq * (self.k1 + 1)
            denominator = term_freq + self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_length))
            
            score += idf * (numerator / denominator)
        
        return score
    
    def retrieve(self, query: str, top_k: int = 5) -> List['Paragraph']:
        """Retrieve top-k paragraphs for a query."""
        query_tokens = self._tokenize(query)
        
        scores = []
        for idx in range(len(self.paragraphs)):
            score = self._score(query_tokens, idx)
            scores.append((score, idx))
        
        # Sort by score descending
        scores.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for score, idx in scores[:top_k]:
            para = self.paragraphs[idx]
            para.score = score
            results.append(para)
        
        return results


# =============================================================================
# Dense (Cosine) Retriever
# =============================================================================
class DenseRetriever:
    """Dense retriever using embeddings and cosine similarity."""
    
    def __init__(self, paragraphs: List['Paragraph'], embed_client):
        self.paragraphs = paragraphs
        self.embed_client = embed_client
        
        # Pre-compute embeddings for all paragraphs
        print("    Computing paragraph embeddings...")
        texts = [f"{p.title}: {p.text}" for p in paragraphs]
        self.embeddings = self._batch_embed(texts)
    
    def _batch_embed(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Embed texts in batches."""
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # Assuming embed_client has an embed method
            embeddings = self.embed_client.embed(batch)
            all_embeddings.extend(embeddings)
        return all_embeddings
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def retrieve(self, query: str, top_k: int = 5) -> List['Paragraph']:
        """Retrieve top-k paragraphs using dense similarity."""
        query_embedding = self.embed_client.embed([query])[0]
        
        scores = []
        for idx, doc_embedding in enumerate(self.embeddings):
            sim = self._cosine_similarity(query_embedding, doc_embedding)
            scores.append((sim, idx))
        
        scores.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for score, idx in scores[:top_k]:
            para = self.paragraphs[idx]
            para.score = score
            results.append(para)
        
        return results


# =============================================================================
# Hybrid Retriever (BM25 + Dense)
# =============================================================================
class HybridRetriever:
    """Combines BM25 and Dense retrieval with score fusion."""
    
    def __init__(self, paragraphs: List['Paragraph'], embed_client, 
                 bm25_weight: float = 0.3, dense_weight: float = 0.7):
        self.bm25 = BM25Retriever(paragraphs)
        self.dense = DenseRetriever(paragraphs, embed_client)
        self.paragraphs = paragraphs
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
    
    def retrieve(self, query: str, top_k: int = 5) -> List['Paragraph']:
        """Retrieve using hybrid scoring."""
        # Get more candidates from each
        k_candidates = min(top_k * 3, len(self.paragraphs))
        
        bm25_results = self.bm25.retrieve(query, k_candidates)
        dense_results = self.dense.retrieve(query, k_candidates)
        
        # Normalize scores and combine
        scores = {}
        
        # Normalize BM25 scores
        bm25_scores = [p.score for p in bm25_results]
        bm25_max = max(bm25_scores) if bm25_scores else 1
        bm25_min = min(bm25_scores) if bm25_scores else 0
        bm25_range = bm25_max - bm25_min if bm25_max != bm25_min else 1
        
        for p in bm25_results:
            normalized = (p.score - bm25_min) / bm25_range
            scores[p.pid] = self.bm25_weight * normalized
        
        # Normalize Dense scores (already 0-1 for cosine)
        for p in dense_results:
            pid = p.pid
            if pid in scores:
                scores[pid] += self.dense_weight * p.score
            else:
                scores[pid] = self.dense_weight * p.score
        
        # Sort and return
        sorted_pids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        results = []
        for pid in sorted_pids[:top_k]:
            para = self.paragraphs[pid]
            para.score = scores[pid]
            results.append(para)
        
        return results


# =============================================================================
# Data Models
# =============================================================================
@dataclass
class Paragraph:
    pid: int
    title: str
    text: str
    score: float = 0.0


# =============================================================================
# Evaluation Metrics
# =============================================================================
def compute_retrieval_metrics(retrieved_titles: List[str], gold_sp: List[Tuple[str, int]]) -> Dict:
    """
    Compute retrieval metrics at the title (document) level.
    
    Args:
        retrieved_titles: List of retrieved document titles
        gold_sp: List of (title, sentence_idx) tuples from gold standard
    
    Returns:
        Dictionary of metrics
    """
    gold_titles = set(t for t, _ in gold_sp)
    retrieved_set = set(retrieved_titles)
    
    # Title-level metrics
    tp = len(gold_titles & retrieved_set)
    
    precision = tp / len(retrieved_set) if retrieved_set else 0
    recall = tp / len(gold_titles) if gold_titles else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    # Hit@k metrics
    hit_1 = 1 if retrieved_titles and retrieved_titles[0] in gold_titles else 0
    hit_3 = 1 if any(t in gold_titles for t in retrieved_titles[:3]) else 0
    hit_5 = 1 if any(t in gold_titles for t in retrieved_titles[:5]) else 0
    
    # Mean Reciprocal Rank
    mrr = 0
    for i, title in enumerate(retrieved_titles):
        if title in gold_titles:
            mrr = 1 / (i + 1)
            break
    
    return {
        'title_precision': precision,
        'title_recall': recall,
        'title_f1': f1,
        'hit@1': hit_1,
        'hit@3': hit_3,
        'hit@5': hit_5,
        'mrr': mrr,
        'gold_titles': list(gold_titles),
        'retrieved_titles': retrieved_titles,
    }


# =============================================================================
# Mock Embedding Client (for testing without API)
# =============================================================================
class MockEmbedClient:
    """Mock embedding client for testing without API calls."""
    
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate mock embeddings (deterministic hash-based vectors)."""
        import hashlib
        
        embeddings = []
        for text in texts:
            # Create deterministic "embedding" based on text hash
            hash_val = hashlib.md5(text.encode()).hexdigest()
            # Convert to 128-dim vector
            embedding = [int(hash_val[i:i+2], 16) / 255.0 for i in range(0, 32, 1)]
            # Pad to 128 dimensions
            embedding = (embedding * 4)[:128]
            embeddings.append(embedding)
        
        return embeddings


# =============================================================================
# Embedding Client Wrapper
# =============================================================================
class EmbeddingClient:
    """Wrapper for Mistral embedding client."""
    
    def __init__(self, mistral_client: MistralClient):
        self.client = mistral_client
    
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using Mistral API."""
        return self.client.embed(texts)


# =============================================================================
# Main Experiment Runner
# =============================================================================
def run_retriever_comparison(
    dev_data: List[Dict],
    embed_client,
    top_k: int = 5,
    output_dir: Path = None,
) -> Dict:
    """
    Compare BM25, Dense, and Hybrid retrievers on the dataset.
    """
    
    results = {
        'bm25': [],
        'dense': [],
        'hybrid': [],
    }
    
    for i, example in enumerate(dev_data):
        question = example['question']
        context = example['context']
        gold_sp = example.get('supporting_facts', [])
        
        print(f"[{i+1}/{len(dev_data)}] {question[:60]}...")
        
        # Build paragraphs from context
        paragraphs = []
        for pid, (title, sentences) in enumerate(context):
            text = ' '.join(sentences)
            paragraphs.append(Paragraph(pid=pid, title=title, text=text))
        
        if len(paragraphs) < 2:
            print("    Skipping: not enough paragraphs")
            continue
        
        # Initialize retrievers
        bm25_retriever = BM25Retriever(paragraphs)
        dense_retriever = DenseRetriever(paragraphs, embed_client)
        hybrid_retriever = HybridRetriever(paragraphs, embed_client)
        
        # Retrieve with each method
        for name, retriever in [
            ('bm25', bm25_retriever),
            ('dense', dense_retriever),
            ('hybrid', hybrid_retriever),
        ]:
            retrieved = retriever.retrieve(question, top_k)
            retrieved_titles = [p.title for p in retrieved]
            
            metrics = compute_retrieval_metrics(retrieved_titles, gold_sp)
            metrics['question'] = question
            metrics['qid'] = example.get('_id', str(i))
            
            results[name].append(metrics)
        
        # Progress update
        if (i + 1) % 10 == 0:
            for name in results:
                avg_recall = sum(r['title_recall'] for r in results[name]) / len(results[name])
                print(f"    {name.upper()} Avg Recall@{top_k}: {avg_recall:.3f}")
    
    return results


def aggregate_results(results: Dict) -> Dict:
    """Aggregate results across all examples."""
    aggregated = {}
    
    for method, method_results in results.items():
        if not method_results:
            continue
        
        n = len(method_results)
        aggregated[method] = {
            'n_examples': n,
            'avg_title_precision': sum(r['title_precision'] for r in method_results) / n,
            'avg_title_recall': sum(r['title_recall'] for r in method_results) / n,
            'avg_title_f1': sum(r['title_f1'] for r in method_results) / n,
            'avg_hit@1': sum(r['hit@1'] for r in method_results) / n,
            'avg_hit@3': sum(r['hit@3'] for r in method_results) / n,
            'avg_hit@5': sum(r['hit@5'] for r in method_results) / n,
            'avg_mrr': sum(r['mrr'] for r in method_results) / n,
        }
    
    return aggregated


def save_results(results: Dict, aggregated: Dict, output_dir: Path, timestamp: str):
    """Save detailed and aggregated results."""
    
    # Save detailed results as CSV for each method
    for method, method_results in results.items():
        csv_path = output_dir / f"retriever_{method}_{timestamp}.csv"
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            if method_results:
                fieldnames = ['qid', 'question', 'title_precision', 'title_recall', 
                             'title_f1', 'hit@1', 'hit@3', 'hit@5', 'mrr',
                             'gold_titles', 'retrieved_titles']
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(method_results)
        
        print(f"  Saved: {csv_path}")
    
    # Save aggregated comparison
    comparison_path = output_dir / f"retriever_comparison_{timestamp}.json"
    with open(comparison_path, 'w') as f:
        json.dump(aggregated, f, indent=2)
    print(f"  Saved: {comparison_path}")
    
    return comparison_path


def print_comparison_table(aggregated: Dict):
    """Print a nice comparison table."""
    print("\n" + "="*80)
    print("RETRIEVER COMPARISON RESULTS")
    print("="*80)
    
    metrics = ['avg_title_recall', 'avg_title_f1', 'avg_hit@1', 'avg_hit@3', 'avg_mrr']
    
    # Header
    header = f"{'Method':<12}"
    for m in metrics:
        header += f"{m.replace('avg_', ''):<15}"
    print(header)
    print("-"*80)
    
    # Rows
    for method in ['bm25', 'dense', 'hybrid']:
        if method not in aggregated:
            continue
        
        row = f"{method.upper():<12}"
        for m in metrics:
            value = aggregated[method].get(m, 0)
            row += f"{value:<15.4f}"
        print(row)
    
    print("="*80)
    
    # Winner
    best_method = max(aggregated.keys(), key=lambda x: aggregated[x]['avg_title_recall'])
    print(f"\n🏆 Best Retriever (by recall): {best_method.upper()}")
    print(f"   Title Recall: {aggregated[best_method]['avg_title_recall']:.4f}")


# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Compare BM25 vs Dense vs Hybrid retrievers")
    parser.add_argument("--max_examples", type=int, default=100,
                        help="Number of examples to evaluate")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument("--top_k", type=int, default=5,
                        help="Number of paragraphs to retrieve")
    parser.add_argument("--data_path", type=str, default=None,
                        help="Path to HotpotQA dev data JSON")
    parser.add_argument("--use_mock", action="store_true",
                        help="Use mock embeddings (for testing without API)")
    
    args = parser.parse_args()
    
    # Set seed
    random.seed(args.seed)
    
    # Create output directory
    output_dir = PROJECT_ROOT / "experiments" / "retriever_comparison"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print("\n" + "="*80)
    print("EXPERIMENT 1: RETRIEVER COMPARISON (BM25 vs Dense vs Hybrid)")
    print("="*80)
    print(f"Max Examples: {args.max_examples}")
    print(f"Top-K: {args.top_k}")
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
    random.seed(args.seed)
    random.shuffle(dev_data)
    dev_data = dev_data[:args.max_examples]
    print(f"Loaded {len(dev_data)} examples\n")
    
    # Initialize embedding client
    if args.use_mock:
        print("Using MOCK embeddings (for testing only)\n")
        embed_client = MockEmbedClient()
    else:
        try:
            print("Initializing Mistral embedding client...")
            mistral_client = MistralClient()
            embed_client = EmbeddingClient(mistral_client)
            print("✅ Using Mistral embeddings\n")
        except Exception as e:
            print(f"WARNING: Could not initialize Mistral client: {e}")
            print("Falling back to mock embeddings\n")
            embed_client = MockEmbedClient()
    
    # Run comparison
    results = run_retriever_comparison(
        dev_data=dev_data,
        embed_client=embed_client,
        top_k=args.top_k,
        output_dir=output_dir,
    )
    
    # Aggregate and save
    aggregated = aggregate_results(results)
    save_results(results, aggregated, output_dir, timestamp)
    
    # Print comparison
    print_comparison_table(aggregated)
    
    print(f"\nResults saved to: {output_dir}")


if __name__ == "__main__":
    main()
