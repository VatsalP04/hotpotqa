# Exploratory Data Analysis (EDA) for HotpotQA

This directory contains comprehensive EDA scripts to understand the HotpotQA dataset.

## Setup

The project uses `uv` for dependency management. Dependencies are already defined in `pyproject.toml`.

### Install dependencies (if not already done):
```bash
uv sync
```

## Running the EDA

### Run the complete EDA analysis:
```bash
uv run python eda.py
```

This will:
1. Load both train and dev datasets
2. Compute comprehensive statistics
3. Analyze question types, answer types, supporting facts, and context
4. Generate visualizations saved to `eda_plots/` directory
5. Compare train vs dev splits

## Output

The EDA script generates:
- **Console output**: Statistical summaries and analysis results
- **Visualizations**: Saved in `eda_plots/` directory:
  - `question_lengths_{split}.png` - Distribution of question lengths
  - `answer_lengths_{split}.png` - Distribution of answer lengths
  - `context_articles_{split}.png` - Number of context articles per example
  - `supporting_facts_{split}.png` - Number of supporting facts per example
  - `question_types_{split}.png` - Distribution of question types
  - `question_vs_answer_length_{split}.png` - Scatter plot
  - `total_sentences_{split}.png` - Total sentences in context
  - `correlation_heatmap_{split}.png` - Feature correlations
  - `train_dev_comparison.png` - Comparison between splits

## EDA Features

The script analyzes:
1. **Basic Statistics**: Dataset size, question/answer lengths, context statistics
2. **Question Types**: Distribution of question words (what, who, where, etc.)
3. **Answer Types**: Yes/No, numbers, single words, phrases, long answers
4. **Supporting Facts**: Distribution and patterns of supporting facts
5. **Context Analysis**: Articles and sentences per example
6. **Visualizations**: Comprehensive plots for all metrics
7. **Split Comparison**: Train vs Dev comparison

## Custom Usage

You can also import and use individual functions:

```python
from eda import load_hotpot, basic_statistics, analyze_question_types

# Load data
train_data = load_hotpot("train")

# Run specific analyses
basic_statistics(train_data, "train")
analyze_question_types(train_data)
```

