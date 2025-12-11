# HotpotQA Sentence-Level Retrieval Experiments - Integration Guide

## ✅ Integration Complete!

All experiment scripts have been successfully integrated into your codebase with proper imports, connections, and dependencies.

## 📁 Project Structure

```
hotpotqa/
├── src/
│   ├── models/
│   │   └── mistral_client.py          # ✅ Added embed() method
│   ├── data/
│   │   └── loader.py                  # ✅ Used for data loading
│   ├── reasoning/
│   │   └── sentence_retrieval.py      # ✅ Moved from experiments/
│   └── config/
│       └── __init__.py                # ✅ Used for API keys
├── evaluation/
│   └── eval.py                        # ✅ Used for metrics
├── experiments/
│   ├── 01_compare_retrievers.py       # ✅ Integrated
│   ├── 02_sentence_vs_paragraph.py    # ✅ Integrated
│   ├── 03_sentence_optimizations.py   # ✅ Integrated
│   ├── run_all_experiments.py         # ✅ Integrated
│   └── README.md                      # Original documentation
└── data/
    └── hotpotqa/
        └── hotpot_dev_distractor_v1.json
```

## 🔧 Changes Made

### 1. **MistralClient Enhancement**
   - **File**: `src/models/mistral_client.py`
   - **Change**: Added `embed()` method for generating embeddings
   - **Usage**: 
     ```python
     client = MistralClient()
     embeddings = client.embed(["text1", "text2"])
     ```

### 2. **Sentence Retrieval Module**
   - **File**: `src/reasoning/sentence_retrieval.py`
   - **Location**: Moved from `experiments/` to `src/reasoning/`
   - **Contains**:
     - `OptimizedSentenceRetriever` - Main retrieval class with multiple optimizations
     - `ParagraphWithSentences` - Data model for paragraphs
     - `SentenceChunk` - Data model for sentences
     - `CoreferenceResolver` - Coreference resolution utilities
     - `BM25SentenceIndex` - BM25 indexing for sentences
     - `DenseSentenceIndex` - Dense retrieval with embeddings
     - `CrossEncoderReranker` - Reranking utilities

### 3. **Experiment Scripts**

#### **01_compare_retrievers.py**
   - **Purpose**: Compare BM25 vs Dense vs Hybrid retrievers
   - **Imports**:
     - `load_hotpotqa` from `src.data.loader`
     - `MistralClient` from `src.models.mistral_client`
   - **New Classes**:
     - `EmbeddingClient` - Wrapper for Mistral embeddings
     - `MockEmbedClient` - Mock embeddings for testing
   - **Usage**:
     ```bash
     # With mock embeddings (no API calls)
     python experiments/01_compare_retrievers.py --max_examples 100 --use_mock
     
     # With real Mistral embeddings
     python experiments/01_compare_retrievers.py --max_examples 100
     ```

#### **02_sentence_vs_paragraph.py**
   - **Purpose**: Compare sentence-level vs paragraph-level retrieval
   - **Imports**:
     - `load_hotpotqa` from `src.data.loader`
     - `MistralClient` from `src.models.mistral_client`
     - `f1_score` (as `eval_f1_score`) from `evaluation.eval`
   - **New Classes**:
     - `AnswerGenerator` - LLM wrapper with simple extractive fallback
   - **Usage**:
     ```bash
     python experiments/02_sentence_vs_paragraph.py --max_examples 100 --top_k 3 --context_window 1
     ```

#### **03_sentence_optimizations.py**
   - **Purpose**: Test various sentence-level optimizations
   - **Imports**:
     - `load_hotpotqa` from `src.data.loader`
     - `MistralClient` from `src.models.mistral_client`
     - `OptimizedSentenceRetriever`, `ParagraphWithSentences` from `src.reasoning.sentence_retrieval`
   - **Configurations Tested**:
     - `baseline` - Plain BM25 sentence retrieval
     - `context_window` - Embed sentences with surrounding context
     - `coref_resolution` - Resolve pronouns before indexing
     - `coref_plus_context` - Both optimizations
     - `hybrid_retrieval` - BM25 + Dense fusion
     - `full_optimization` - All optimizations enabled
   - **Usage**:
     ```bash
     # With mock embeddings
     python experiments/03_sentence_optimizations.py --max_examples 100 --use_mock
     
     # With real embeddings
     python experiments/03_sentence_optimizations.py --max_examples 100 --top_k 8
     ```

#### **run_all_experiments.py**
   - **Purpose**: Master script to run all experiments in sequence
   - **Fixed**: Updated script paths from `scripts/` to `experiments/`
   - **Usage**:
     ```bash
     # Run all experiments
     python experiments/run_all_experiments.py --max_examples 100 --seed 42
     
     # Skip specific experiments
     python experiments/run_all_experiments.py --skip_retriever --max_examples 50
     
     # Use mock embeddings
     python experiments/run_all_experiments.py --use_mock --max_examples 50
     ```

## 🚀 Quick Start

### Option 1: Run Individual Experiments

```bash
cd /Users/vatsalpatel/hotpotqa

# Experiment 1: Compare retrievers (with mock embeddings - no API calls)
python experiments/01_compare_retrievers.py --max_examples 50 --use_mock --seed 42

# Experiment 2: Sentence vs Paragraph (uses simple extraction, no API needed)
python experiments/02_sentence_vs_paragraph.py --max_examples 50 --seed 42

# Experiment 3: Optimizations (with mock embeddings)
python experiments/03_sentence_optimizations.py --max_examples 50 --use_mock --seed 42
```

### Option 2: Run All Experiments at Once

```bash
cd /Users/vatsalpatel/hotpotqa

# Run all experiments with mock embeddings (fastest, no API)
python experiments/run_all_experiments.py --max_examples 50 --use_mock --seed 42
```

### Option 3: With Real Mistral API (requires API key)

Make sure your `.env` file has:
```bash
MISTRAL_API_KEY=your_api_key_here
```

Then run:
```bash
# All experiments with real embeddings
python experiments/run_all_experiments.py --max_examples 50 --seed 42
```

## 📊 Output Structure

Each experiment creates outputs in the `experiments/` directory:

```
experiments/
├── retriever_comparison/
│   ├── retriever_bm25_20251209_HHMMSS.csv
│   ├── retriever_dense_20251209_HHMMSS.csv
│   ├── retriever_hybrid_20251209_HHMMSS.csv
│   └── retriever_comparison_20251209_HHMMSS.json
├── sentence_vs_paragraph/
│   └── 20251209_HHMMSS/
│       ├── paragraph_results.csv
│       ├── sentence_results.csv
│       └── comparison.json
└── sentence_optimizations/
    └── 20251209_HHMMSS/
        ├── baseline_results.csv
        ├── context_window_results.csv
        ├── coref_resolution_results.csv
        ├── coref_plus_context_results.csv
        ├── hybrid_retrieval_results.csv
        ├── full_optimization_results.csv
        └── comparison_summary.json
```

## 🔍 Integration Points

### Data Loading
All scripts now use the centralized `load_hotpotqa()` function:
```python
from src.data.loader import load_hotpotqa

data = load_hotpotqa(
    data_dir=PROJECT_ROOT / "data" / "hotpotqa",
    split="dev",
    max_examples=None,
    shuffle=False,
    seed=42
)
```

### Mistral API
All scripts use the enhanced `MistralClient`:
```python
from src.models.mistral_client import MistralClient

client = MistralClient()
embeddings = client.embed(["text1", "text2"])
answer = client.answer_question("What is X?", context="Context here")
```

### Evaluation Metrics
Uses existing evaluation functions:
```python
from evaluation.eval import f1_score

f1, precision, recall = f1_score(prediction, ground_truth)
```

### Sentence Retrieval
Import and use the optimized retriever:
```python
from src.reasoning.sentence_retrieval import (
    OptimizedSentenceRetriever, 
    ParagraphWithSentences
)

paragraphs = [
    ParagraphWithSentences(title, sentences)
    for title, sentences in context
]

retriever = OptimizedSentenceRetriever(
    paragraphs=paragraphs,
    use_coref=True,
    use_context_window=True,
    use_hybrid=False,
    use_reranking=False,
)

results = retriever.retrieve(question, top_k=10)
supporting_facts = retriever.get_supporting_facts()
```

## 🧪 Testing Status

All scripts have been tested for:
- ✅ Syntax validation (py_compile)
- ✅ Import resolution
- ✅ CLI argument parsing
- ✅ Integration with existing modules

## 📝 Next Steps

1. **Run a test experiment**:
   ```bash
   python experiments/01_compare_retrievers.py --max_examples 10 --use_mock
   ```

2. **Review the output**:
   - Check `experiments/retriever_comparison/` for results
   - Verify CSV files are generated correctly

3. **Run full experiments**:
   ```bash
   # Run all experiments with 100 examples (takes longer)
   python experiments/run_all_experiments.py --max_examples 100 --use_mock
   ```

4. **With Real API** (when ready):
   - Ensure Mistral API key is set in `.env`
   - Remove `--use_mock` flag
   - Monitor API usage/costs

## 🔧 Troubleshooting

### Import Errors
If you see `ModuleNotFoundError`:
```bash
# Ensure you're running from project root
cd /Users/vatsalpatel/hotpotqa
python experiments/01_compare_retrievers.py ...
```

### API Key Issues
If Mistral API fails:
```bash
# Check your .env file
cat .env | grep MISTRAL_API_KEY

# Or use mock mode
python experiments/... --use_mock
```

### Data Path Issues
If data loading fails:
```bash
# Verify data file exists
ls -la data/hotpotqa/hotpot_dev_distractor_v1.json

# Or provide explicit path
python experiments/... --data_path /path/to/your/data.json
```

## 📚 References

- Original README: `experiments/README.md`
- Data Loader: `src/data/loader.py`
- Mistral Client: `src/models/mistral_client.py`
- Sentence Retrieval: `src/reasoning/sentence_retrieval.py`
- Evaluation: `evaluation/eval.py`

## ✨ Summary

All experiment scripts are now fully integrated with:
- ✅ Proper imports from existing modules
- ✅ Centralized data loading
- ✅ Mistral API integration with fallbacks
- ✅ Mock embedding support for testing
- ✅ Consistent CLI interfaces
- ✅ Validated syntax and imports
- ✅ Ready to run!

You can now use `run_all_experiments.py` to execute all experiments in sequence!
