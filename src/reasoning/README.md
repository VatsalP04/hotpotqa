# Reasoning Methods & Experiments

This directory contains implementations of reasoning methods (IRCoT, Decomposition, SimpleCoT) and experiment runners for comparison and ablation studies.

## Overview

- **Methods**: IRCoT, Query Decomposition, SimpleCoT
- **Experiments**: Method comparison, ablation studies, single method evaluation
- **Features**: Comprehensive metrics, visualization, checkpointing, resume capability

## Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
export MISTRAL_API_KEY=your_api_key_here
```

Or create a `.env` file:
```env
MISTRAL_API_KEY=your_api_key_here
```

## Running Method Comparison

Compare multiple methods (IRCoT, Decomposition, SimpleCoT) on the same dataset.

### Basic Usage

```bash
cd hotpotqa
python -m src.reasoning.experiments.run_experiments compare \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --num_samples 50 \
    --output_dir ./outputs
```

### Options

- `--data_path`: Path to HotpotQA JSON file (required)
- `--num_samples`: Number of samples to process (default: all)
- `--output_dir`: Output directory (default: `./outputs`)
- `--seed`: Random seed (default: 42)
- `--methods`: Methods to compare (default: `ircot decomposition simplecot`)
- `--use_dense`: Use dense (embedding) retrieval instead of BM25
- `--no_plots`: Skip plot generation

### Examples

```bash
# Compare all three methods with BM25 retrieval
python -m src.reasoning.experiments.run_experiments compare \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --num_samples 100

# Compare specific methods with dense retrieval
python -m src.reasoning.experiments.run_experiments compare \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --methods ircot decomposition \
    --use_dense \
    --num_samples 50

# Skip visualization
python -m src.reasoning.experiments.run_experiments compare \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --no_plots
```

### Output

Comparison generates:
- `comparison_YYYYMMDD_HHMMSS/` directory containing:
  - `all_per_question.json`: Per-question results for all methods
  - `all_summaries.json`: Aggregated metrics per method
  - `comparison_report.md`: Markdown report with metrics
  - `plots/`: Visualization plots (if enabled)

### Checkpointing

The comparison runner automatically saves checkpoints every 100 questions. You can:
- Stop the run with `Ctrl+C` at any time
- Resume later - it will automatically detect and continue from the last checkpoint
- Adjust checkpoint interval with code modification

## Running Full Pipeline (Ablation Study)

Run ablation studies for the Query Decomposition method, including the full pipeline variant.

### Basic Usage

```bash
cd hotpotqa
python -m src.reasoning.experiments.run_ablation \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --num_samples 100 \
    --output_dir ./outputs/ablation
```

### Ablation Variants

The script runs 5 variants by default:

1. **Decomp_RelaxedInitial**: Relaxed prompt (no NOT_FOUND) as initial answering
2. **Decomp_NoFallback**: NOT_FOUND prompt only, no fallbacks (baseline)
3. **Decomp_DirectRelaxed**: NOT_FOUND → direct relaxed fallback (no search)
4. **Decomp_SearchFallback**: NOT_FOUND → search query fallback only
5. **Decomp_FullPipeline**: Full pipeline with search fallback → relaxed fallback

### Options

- `--data_path`: Path to HotpotQA JSON file (required)
- `--num_samples`: Number of samples (default: 100)
- `--output_dir`: Output directory (default: `./outputs/ablation`)
- `--seed`: Random seed (default: 42)
- `--variants`: Specific variants to run (default: all)
- `--no_plots`: Skip plot generation
- `--no_resume`: Don't resume from checkpoints (start fresh)
- `--checkpoint_interval`: Save checkpoint every N questions (default: 100)

### Examples

```bash
# Run all 5 ablation variants
python -m src.reasoning.experiments.run_ablation \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --num_samples 100

# Run only specific variants
python -m src.reasoning.experiments.run_ablation \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --variants Decomp_NoFallback Decomp_FullPipeline \
    --num_samples 50

# Run with custom checkpoint interval
python -m src.reasoning.experiments.run_ablation \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --checkpoint_interval 50
```

### Output

Each variant generates its own output directory:
- `Decomp_RelaxedInitial_YYYYMMDD_HHMMSS/`
- `Decomp_NoFallback_YYYYMMDD_HHMMSS/`
- `Decomp_DirectRelaxed_YYYYMMDD_HHMMSS/`
- `Decomp_SearchFallback_YYYYMMDD_HHMMSS/`
- `Decomp_FullPipeline_YYYYMMDD_HHMMSS/`

Plus a comparison directory:
- `comparison_YYYYMMDD_HHMMSS/` with combined results

Each directory contains:
- `per_question.json`: Detailed per-question results
- `report.md`: Summary report
- `summary.json`: Aggregated metrics
- `plots/`: Visualization plots (if enabled)

## Running Single Method

Evaluate a single method without comparison.

### Usage

```bash
python -m src.reasoning.experiments.run_experiments single \
    --method ircot \
    --data_path data/hotpotqa/hotpot_dev_distractor_v1.json \
    --num_samples 20
```

### Options

- `--method`: Method to run (`ircot`, `decomposition`)
- `--data_path`: Path to HotpotQA JSON file (required)
- `--num_samples`: Number of samples (default: all)
- `--output_dir`: Output directory (default: `./outputs`)
- `--seed`: Random seed (default: 42)
- `--use_dense`: Use dense retrieval instead of BM25
- `--no_plots`: Skip plot generation

## Metrics

All experiments compute comprehensive metrics:

### Answer Quality
- **EM (Exact Match)**: Percentage of exact matches with gold answer
- **F1**: Token-level F1 score

### Retrieval Quality
- **Gold Recall**: Proportion of gold sentences retrieved
- **First Retrieval Recall**: Recall from first retrieval step

### Efficiency
- **Total Tokens**: Total tokens used (input + output)
- **F1 per 1K Tokens**: Efficiency metric
- **Total Time**: Wall-clock time

### Question Type Breakdown
- **Comparison questions**: Questions comparing entities
- **Bridge questions**: Questions requiring multi-hop reasoning

## Visualization

Plots are automatically generated (unless `--no_plots` is used):

- `em_f1.png`: EM and F1 scores
- `recall.png`: Retrieval recall metrics
- `efficiency.png`: Token usage and efficiency
- `question_type_comparison.png`: Performance by question type
- `efficiency_comparison.png`: Efficiency comparison across methods

## Checkpointing & Resume

Both comparison and ablation runners support checkpointing:

- **Automatic checkpointing**: Saves progress every N questions (default: 100)
- **Automatic resume**: Detects existing checkpoints and continues
- **Manual resume**: Just run the same command again - it will resume automatically
- **Fresh start**: Use `--no_resume` to start from scratch

## Troubleshooting

### API Key Issues

```bash
# Set environment variable
export MISTRAL_API_KEY=your_key

# Or use .env file
echo "MISTRAL_API_KEY=your_key" > .env
```

### Out of Memory

- Reduce `--num_samples`
- Use BM25 retrieval (default) instead of dense retrieval
- Process in smaller batches

### Slow Performance

- Use BM25 retrieval (faster, no API calls)
- Reduce sample size for testing
- Check API rate limits for Mistral

### Missing Dependencies

```bash
pip install transformers torch sentence-transformers scikit-learn matplotlib pandas
```

## File Structure

```
src/reasoning/
├── experiments/
│   ├── run_experiments.py    # Main comparison script
│   ├── run_ablation.py        # Ablation study script
│   ├── runner.py              # Experiment runner
│   └── adapters.py            # Method adapters
├── methods/
│   ├── ircot/                 # IRCoT implementation
│   ├── decomposition/         # Query Decomposition
│   └── simple_cot/            # Simple Chain-of-Thought
├── core/
│   ├── metrics.py             # Metrics calculation
│   ├── visualization.py       # Plot generation
│   └── types.py               # Type definitions
└── prompts/                   # Prompt templates

