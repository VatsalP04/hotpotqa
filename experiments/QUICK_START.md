# Quick Start Commands

## 🚀 Ready to Run!

All scripts are integrated and tested. Here are the exact commands to use:

## Option 1: Quick Test (5 examples, ~30 seconds)

```bash
cd /Users/vatsalpatel/hotpotqa

# Test Experiment 1 - WORKS! ✅
python experiments/01_compare_retrievers.py --max_examples 5 --use_mock --seed 42
```

## Option 2: Individual Experiments (100 examples each)

```bash
cd /Users/vatsalpatel/hotpotqa

# Experiment 1: Compare BM25 vs Dense vs Hybrid
python experiments/01_compare_retrievers.py --max_examples 100 --use_mock --seed 42

# Experiment 2: Sentence vs Paragraph retrieval
python experiments/02_sentence_vs_paragraph.py --max_examples 100 --seed 42 --top_k 3 --context_window 1

# Experiment 3: Test all sentence optimizations
python experiments/03_sentence_optimizations.py --max_examples 100 --use_mock --seed 42 --top_k 8
```

## Option 3: Run All Experiments (RECOMMENDED)

```bash
cd /Users/vatsalpatel/hotpotqa

# Run all three experiments in sequence
python experiments/run_all_experiments.py --max_examples 100 --use_mock --seed 42
```

## Option 4: With Real Mistral API

First, ensure your `.env` file has the API key:
```bash
cat .env | grep MISTRAL_API_KEY
```

Then run without `--use_mock`:
```bash
python experiments/run_all_experiments.py --max_examples 100 --seed 42
```

## Expected Output Locations

After running, check these directories:

```bash
# Experiment 1 results
ls -la experiments/retriever_comparison/

# Experiment 2 results  
ls -la experiments/sentence_vs_paragraph/

# Experiment 3 results
ls -la experiments/sentence_optimizations/
```

## Verify Installation

Test that all imports work:
```bash
cd /Users/vatsalpatel/hotpotqa
python -c "from src.data.loader import load_hotpotqa; from src.models.mistral_client import MistralClient; from src.reasoning.sentence_retrieval import OptimizedSentenceRetriever; print('✅ All imports successful!')"
```

## Troubleshooting

If you get import errors:
```bash
# Make sure you're in the project root
pwd  # Should show: /Users/vatsalpatel/hotpotqa

# Try explicitly
cd /Users/vatsalpatel/hotpotqa
python experiments/01_compare_retrievers.py --max_examples 5 --use_mock
```

## What Each Experiment Does

### Experiment 1: Retriever Comparison
- Tests BM25 (keyword-based) vs Dense (embedding-based) vs Hybrid
- Shows which retrieval method works best for your data
- **Output**: CSV files for each method + comparison JSON

### Experiment 2: Sentence vs Paragraph
- Compares retrieving full paragraphs vs individual sentences
- Tests context window expansion
- **Output**: Results for both methods + detailed comparison

### Experiment 3: Sentence Optimizations
- Tests 6 different configurations:
  - Baseline (plain BM25)
  - Context window
  - Coreference resolution
  - Coref + Context
  - Hybrid retrieval
  - Full optimization
- **Output**: CSV for each config + comparison summary

## Pro Tips

1. **Start small**: Use `--max_examples 10` for quick testing
2. **Use mock mode**: Add `--use_mock` to avoid API calls during testing
3. **Set seed**: Always use `--seed 42` for reproducibility
4. **Check outputs**: Review CSV files to understand results

## Example: Full Workflow

```bash
# 1. Navigate to project
cd /Users/vatsalpatel/hotpotqa

# 2. Quick test (30 seconds)
python experiments/01_compare_retrievers.py --max_examples 5 --use_mock --seed 42

# 3. Run all experiments (takes longer)
python experiments/run_all_experiments.py --max_examples 100 --use_mock --seed 42

# 4. Review results
ls -la experiments/retriever_comparison/
ls -la experiments/sentence_vs_paragraph/
ls -la experiments/sentence_optimizations/

# 5. Analyze the comparison JSONs
cat experiments/retriever_comparison/retriever_comparison_*.json
cat experiments/sentence_vs_paragraph/*/comparison.json
cat experiments/sentence_optimizations/*/comparison_summary.json
```

## Success Criteria

You'll know it's working when you see:
- ✅ "Loading data from: /Users/vatsalpatel/hotpotqa/data/hotpotqa"
- ✅ "Loaded X examples"
- ✅ Progress bars showing [1/100], [2/100], etc.
- ✅ CSV files created in experiments/ directories
- ✅ Final comparison tables printed

## Ready to Go! 🎉

Just run:
```bash
python experiments/run_all_experiments.py --max_examples 100 --use_mock --seed 42
```

And let it run! It will execute all three experiments and generate comprehensive results.
