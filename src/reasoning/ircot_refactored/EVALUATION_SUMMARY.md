# Evaluation Summary

## What the Evaluation Does

The evaluation module (`evaluate.py`) implements comprehensive metrics for HotpotQA question answering:

### 1. **Answer-Level Metrics** (Final Answer Quality)

- **Exact Match (EM)**: Binary score (1.0 if prediction exactly matches gold after normalization, 0.0 otherwise)
- **Precision**: Token-level precision - what fraction of predicted tokens appear in the gold answer
- **Recall**: Token-level recall - what fraction of gold answer tokens appear in the prediction
- **F1 Score**: Harmonic mean of precision and recall

**Normalization**: Answers are normalized before comparison:
- Lowercased
- Articles (a, an, the) removed
- Punctuation removed
- Whitespace normalized

### 2. **Retrieval Metrics** (Paragraph Retrieval Quality)

- **Retrieval Precision**: Fraction of retrieved paragraphs that are in the gold supporting facts
- **Retrieval Recall**: Fraction of gold supporting paragraphs that were retrieved
- **Retrieval F1**: Harmonic mean of retrieval precision and recall

### 3. **Detailed Breakdowns**

- **By Question Type**: Metrics broken down by question type (comparison, bridge, etc.)
- **By Difficulty Level**: Metrics broken down by difficulty (easy, medium, hard)

### 4. **Error Analysis**

- Categorizes errors into:
  - **Partial Match**: F1 > 0.5 (some overlap)
  - **Low Overlap**: 0 < F1 ≤ 0.5 (minimal overlap)
  - **No Overlap**: F1 = 0 (completely wrong)
- Provides sample errors and correct predictions

## Improvements Made

### ✅ Added Precision and Recall for Final Answers

**Before**: Only F1 score was returned (precision and recall were calculated internally but not exposed)

**After**: 
- New function `precision_recall_f1()` returns all three metrics
- `evaluate_single()` now returns `em`, `precision`, `recall`, and `f1`
- `evaluate()` aggregates precision and recall across all predictions
- Reports now show precision and recall alongside F1

**Usage**:
```python
from ircot import evaluate_single, precision_recall_f1

metrics = evaluate_single(prediction="Paris", gold="Paris, France")
# Returns: {"em": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0}

prf = precision_recall_f1("Paris", "Paris France")
# Returns: {"precision": 1.0, "recall": 0.5, "f1": 0.666...}
```

### ✅ Enhanced Reporting

- Reports now display precision and recall for:
  - Overall performance
  - By question type
  - By difficulty level

**Example Report Output**:
```
Overall Performance:
  Exact Match: 0.4500 (45.00%)
  Precision:   0.6234 (62.34%)
  Recall:      0.5891 (58.91%)
  F1 Score:    0.6058 (60.58%)
  Evaluated:   100 instances

By Question Type:
  comparison: EM=0.4200, P=0.6100, R=0.5800, F1=0.5950, N=50
  bridge: EM=0.4800, P=0.6368, R=0.5982, F1=0.6166, N=50
```

## Suggested Further Improvements

### 1. **Supporting Facts Evaluation**
Currently, retrieval metrics compare paragraph titles. Could also evaluate:
- Sentence-level supporting facts (which specific sentences were used)
- Fact-level precision/recall (did the model use the right facts even if from different paragraphs)

### 2. **Multi-Answer Handling**
HotpotQA sometimes has multiple valid answers. Could:
- Check if prediction matches any of multiple gold answers
- Report best-case vs worst-case metrics

### 3. **Confidence Scores**
If the model provides confidence scores:
- Plot precision/recall curves
- Calculate AUC-ROC
- Analyze calibration

### 4. **Error Categorization**
More detailed error analysis:
- **Reasoning Errors**: Model retrieved right paragraphs but reasoned incorrectly
- **Retrieval Errors**: Model couldn't find the right paragraphs
- **Extraction Errors**: Model reasoned correctly but extracted answer wrong
- **Format Errors**: Answer is correct but formatted differently

### 5. **Per-Step Metrics**
For IRCoT, track:
- Answer quality at each reasoning step
- When the correct answer first appears
- How retrieval quality improves over steps

### 6. **Statistical Significance**
- Confidence intervals for metrics
- Statistical tests for comparing methods
- Effect size calculations

### 7. **Visualization**
- Confusion matrices
- Precision-recall curves
- Error distribution plots
- Retrieval quality over time (for IRCoT)

## Running Evaluation

### Basic Usage

```python
from ircot import evaluate, detailed_evaluation, format_report

# Evaluate predictions
results = evaluate(predictions, gold_data)

# Detailed evaluation with breakdowns
detailed = detailed_evaluation(predictions, gold_data, by_type=True, by_level=True)

# Print formatted report
print(format_report(detailed))
```

### Command Line

```bash
# Run experiment and evaluate
python -m ircot.main run --num_samples 100

# Evaluate existing predictions
python -m ircot.main evaluate --predictions pred.json --gold gold.json
```

## Example Output

```
============================================================
EVALUATION REPORT
============================================================

Overall Performance:
  Exact Match: 0.4500 (45.00%)
  Precision:   0.6234 (62.34%)
  Recall:      0.5891 (58.91%)
  F1 Score:    0.6058 (60.58%)
  Evaluated:   100 instances

Retrieval Performance:
  Precision: 0.7123
  Recall:    0.6543
  F1 Score:  0.6818

By Question Type:
  comparison: EM=0.4200, P=0.6100, R=0.5800, F1=0.5950, N=50
  bridge: EM=0.4800, P=0.6368, R=0.5982, F1=0.6166, N=50

By Difficulty:
  easy: EM=0.5500, P=0.7200, R=0.6800, F1=0.6995, N=30
  medium: EM=0.4200, P=0.6100, R=0.5800, F1=0.5950, N=50
  hard: EM=0.3500, P=0.5200, R=0.4800, F1=0.4995, N=20

============================================================
```

