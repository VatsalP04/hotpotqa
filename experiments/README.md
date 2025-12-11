# HotpotQA Sentence-Level Retrieval Experiments

## Overview

This framework provides scripts to systematically evaluate and optimize sentence-level retrieval for multi-hop question answering on HotpotQA.

## Project Structure

```
hotpotqa_experiments/
├── scripts/
│   ├── 01_compare_retrievers.py      # BM25 vs Dense vs Hybrid
│   ├── 02_sentence_vs_paragraph.py   # Main comparison experiment
│   ├── 03_sentence_optimizations.py  # Test all optimizations
│   └── run_all_experiments.py        # Master runner
├── src/
│   └── reasoning/
│       └── sentence_retrieval.py     # Optimized retrieval module
├── experiments/                       # Output directory
└── README.md
```

## Quick Start

### Step 1: Test Retriever Methods (BM25 vs Dense)

First, determine which base retriever works best for your data:

```bash
# With mock embeddings (for testing)
python scripts/01_compare_retrievers.py --max_examples 100 --seed 42 --use_mock

# With actual Mistral embeddings (requires API)
python scripts/01_compare_retrievers.py --max_examples 100 --seed 42
```

**Output:**
- `experiments/retriever_comparison/retriever_bm25_*.csv`
- `experiments/retriever_comparison/retriever_dense_*.csv`
- `experiments/retriever_comparison/retriever_hybrid_*.csv`
- `experiments/retriever_comparison/retriever_comparison_*.json`

**What to look for:**
- Compare `title_recall` across methods
- If BM25 wins: Your questions have distinctive keywords
- If Dense wins: Your questions need semantic understanding
- If Hybrid wins: Use it for best of both worlds

### Step 2: Compare Sentence vs Paragraph Level

Run the main comparison experiment:

```bash
python scripts/02_sentence_vs_paragraph.py \
    --max_examples 100 \
    --seed 42 \
    --top_k 3 \
    --context_window 1
```

**Output:**
- `experiments/sentence_vs_paragraph/<timestamp>/paragraph_results.csv`
- `experiments/sentence_vs_paragraph/<timestamp>/sentence_results.csv`
- `experiments/sentence_vs_paragraph/<timestamp>/comparison.json`

**Key Metrics to Compare:**
| Metric | What It Tells You |
|--------|-------------------|
| `sp_strict_f1` | Main metric - exact sentence match |
| `sp_soft_recall_tol1` | How many were "close" (±1 sentence) |
| `sp_title_recall` | Document-level accuracy |
| `answer_f1` | End-to-end answer quality |

**Decision Criteria:**
- If sentence-level SP-F1 > paragraph-level: ✅ Proceed with sentence optimization
- If paragraph-level wins: Check error distribution first

### Step 3: Optimize Sentence-Level Retrieval

Once sentence-level shows promise, test optimizations:

```bash
python scripts/03_sentence_optimizations.py \
    --max_examples 100 \
    --seed 42 \
    --top_k 8
```

**Configurations Tested:**
1. `baseline` - Plain sentence retrieval
2. `context_window` - Embed sentences with neighbors
3. `coref_resolution` - Resolve pronouns before indexing
4. `coref_plus_context` - Both optimizations
5. `hybrid_retrieval` - BM25 + Dense fusion
6. `full_optimization` - All optimizations enabled

**Output:**
- Individual CSV for each configuration
- `comparison_summary.json` with aggregated metrics

### Step 4: Run All Experiments

For convenience, run everything at once:

```bash
python scripts/run_all_experiments.py \
    --max_examples 100 \
    --seed 42 \
    --top_k 5
```

## Integration with Your Existing Code

### Option A: Use the Standalone Module

Copy `src/reasoning/sentence_retrieval.py` to your project and import:

```python
from src.reasoning.sentence_retrieval import (
    OptimizedSentenceRetriever,
    ParagraphWithSentences,
)

# Convert your context to ParagraphWithSentences
paragraphs = [
    ParagraphWithSentences(title, sentences)
    for title, sentences in example['context']
]

# Create retriever with desired optimizations
retriever = OptimizedSentenceRetriever(
    paragraphs=paragraphs,
    use_coref=True,           # Enable coreference resolution
    use_context_window=True,   # Embed with context
    use_hybrid=False,          # BM25 only (or True for hybrid)
    use_reranking=False,       # Enable if you have cross-encoder
    context_window_size=1,
)

# Retrieve
results = retriever.retrieve(question, top_k=10)

# Get supporting facts for evaluation
supporting_facts = retriever.get_supporting_facts()

# Get formatted context for LLM
context = retriever.get_context_for_llm()
```

### Option B: Update Your Existing Evaluation Script

Add these imports to your `run_experiment.py`:

```python
from src.reasoning.sentence_retrieval import (
    OptimizedSentenceRetriever,
    ParagraphWithSentences,
)
```

Then replace the retriever initialization section:

```python
# In your run_evaluation function, replace the retriever setup with:

if retriever_type == "paragraph":
    # Your existing paragraph retriever
    ...
    
elif retriever_type == "sentence_optimized":
    # New optimized sentence retriever
    paragraphs = [
        ParagraphWithSentences(title, [s.strip() for s in sent_list])
        for title, sent_list in context
    ]
    
    retriever = OptimizedSentenceRetriever(
        paragraphs=paragraphs,
        use_coref=True,
        use_context_window=True,
        context_window_size=1,
        use_hybrid=False,
        use_reranking=False,
    )
```

## Understanding the Evaluation Metrics

### Strict vs Soft Metrics

```
Gold: [(Title_A, 2), (Title_B, 0)]
Pred: [(Title_A, 3), (Title_B, 0)]

Strict Match:
  - (Title_A, 3) vs (Title_A, 2) → No match (different sentence)
  - (Title_B, 0) vs (Title_B, 0) → Match!
  - Strict Recall: 1/2 = 0.5

Soft Match (tolerance=1):
  - (Title_A, 3) is within 1 of (Title_A, 2) → Match!
  - (Title_B, 0) matches exactly → Match!
  - Soft Recall: 2/2 = 1.0
```

**Why this matters:**
- High soft recall + low strict recall = Your retriever finds the right area but not exact sentence
- This suggests the sentence boundaries might be arbitrary, or you need better reranking

### Error Type Analysis

| Error Type | Meaning | Solution |
|------------|---------|----------|
| `correct` | Perfect match | - |
| `wrong_document` | Retrieved wrong Wikipedia article | Improve document retrieval |
| `off_by_one` | Right document, adjacent sentence | Add reranking or context windows |
| `off_by_two` | Right document, nearby sentence | Check sentence splitting |
| `wrong_sentence` | Right document, wrong sentence | Improve sentence selection |

## Recommended Experiment Flow

```
┌─────────────────────────────────────────────────────┐
│ 1. Run Retriever Comparison                         │
│    → Determine: BM25 vs Dense vs Hybrid             │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│ 2. Run Sentence vs Paragraph Comparison             │
│    → If sentence wins: Continue to step 3           │
│    → If paragraph wins: Analyze error distribution  │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│ 3. Run Sentence Optimizations                       │
│    → Find best configuration                        │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│ 4. Integrate Best Config into Main Pipeline         │
│    → Update your run_experiment.py                  │
└─────────────────────────────────────────────────────┘
```

## Adding Your Own Data

If not using the default HotpotQA loader:

```bash
# Provide path to your data JSON
python scripts/02_sentence_vs_paragraph.py \
    --data_path /path/to/your/hotpotqa_dev.json \
    --max_examples 100
```

Expected data format:
```json
[
  {
    "_id": "unique_id",
    "question": "What is...",
    "answer": "The answer",
    "supporting_facts": [["Title1", 0], ["Title2", 3]],
    "context": [
      ["Title1", ["Sentence 0", "Sentence 1", "..."]],
      ["Title2", ["Sentence 0", "Sentence 1", "..."]]
    ]
  }
]
```

## Dependencies

Core (already in your project):
- Python 3.8+
- json, csv, random (stdlib)

Optional for full optimizations:
```bash
# For dense retrieval with actual embeddings
pip install mistralai  # Your Mistral client

# For cross-encoder reranking
pip install sentence-transformers

# For advanced coreference resolution
pip install spacy coreferee
python -m spacy download en_core_web_sm
python -m coreferee install en
```

## Ablation Study for Your Report

Use these experiments to build your ablation table:

| Configuration | SP Precision | SP Recall | SP F1 | Answer F1 |
|--------------|--------------|-----------|-------|-----------|
| Paragraph Baseline | x.xx | x.xx | x.xx | x.xx |
| Sentence Baseline | x.xx | x.xx | x.xx | x.xx |
| + Context Window | x.xx | x.xx | x.xx | x.xx |
| + Coref Resolution | x.xx | x.xx | x.xx | x.xx |
| + Hybrid Retrieval | x.xx | x.xx | x.xx | x.xx |
| + Reranking | x.xx | x.xx | x.xx | x.xx |

This shows the incremental contribution of each optimization.

## Troubleshooting

**"ModuleNotFoundError: No module named 'src'"**
- Run scripts from the project root directory
- Or add: `sys.path.insert(0, '/path/to/your/project')`

**"Using mock embeddings"**
- Install your embedding client or pass `--use_mock` for testing
- Mock embeddings are deterministic but not semantically meaningful

**Low SP precision with sentence-level**
- Reduce `top_k` to return fewer sentences
- Enable reranking to filter better

**Results don't match between runs**
- Always set `--seed` for reproducibility
- Check if data loading shuffles deterministically
