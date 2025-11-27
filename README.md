# HotpotQA NLP Pipeline

A complete, production-ready NLP pipeline for the **HotpotQA multi-hop question answering dataset**. This project provides modular, extensible tools for data loading, preprocessing, validation, analysis, and model training.

## Features

- **Complete Data Pipeline**: Load, validate, and preprocess HotpotQA data
- **Flexible Preprocessing**: Support for multiple tokenizers (HuggingFace, spaCy, NLTK)
- **Multi-hop Reasoning**: Specialized utilities for extracting and analyzing reasoning chains
- **Configurable**: YAML-based configuration with presets (quick, full, RAG, baseline)
- **Production-Ready**: Full logging, error handling, and progress tracking
- **Extensible Architecture**: Modular design for easy customization and extension
- **PyTorch Integration**: Dataset classes compatible with PyTorch DataLoader
- **Comprehensive Validation**: Data quality checks and supporting facts coverage analysis

## Project Structure

```
hotpotqa/
├── configs/                    # Configuration files
│   ├── default.yaml           # Default configuration
│   └── preprocessing.yaml     # Preprocessing presets
├── data/
│   ├── raw/                   # Raw HotpotQA JSON files
│   ├── processed/             # Processed outputs
│   └── cache/                 # Tokenization cache
├── src/                       # Main source code
│   ├── config/
│   │   ├── __init__.py        # Environment configuration
│   │   └── config_manager.py # YAML configuration management
│   ├── data/
│   │   ├── loader.py          # Data loading utilities
│   │   ├── validator.py       # Data validation
│   │   └── dataset.py         # PyTorch Dataset classes
│   ├── preprocessing/
│   │   ├── tokenizer.py       # Tokenization (HF, spaCy, NLTK)
│   │   ├── context.py         # Context processing
│   │   ├── multihop.py        # Multi-hop reasoning features
│   │   └── pipeline.py        # End-to-end preprocessing pipeline
│   ├── utils/
│   │   ├── cleaning.py        # Text cleaning utilities
│   │   ├── normalization.py   # Text normalization
│   │   └── analysis.py        # Dataset analysis tools
│   └── models/
│       └── mistral_client.py  # Mistral API client
├── scripts/                   # Executable scripts
│   ├── run_preprocessing.py   # Run preprocessing pipeline
│   ├── validate_data.py       # Validate dataset
│   ├── analyze_dataset.py     # Generate dataset statistics
│   └── test_mistral_client.py # Test Mistral integration
├── evaluation/
│   └── eval.py               # Official HotpotQA evaluation
├── notebooks/                # Jupyter notebooks for EDA
├── tests/                    # Unit tests
├── logs/                     # Log files
├── requirements.txt          # Python dependencies
├── setup.py                  # Package setup
└── pyproject.toml           # Project configuration
```

## Data & Embeddings

Large pretrained embeddings (for example GloVe) are intentionally kept under `data/embeddings` to avoid bloating the repository root and Git history.

- Embeddings directory: `data/embeddings/`
- Default GloVe filename: `glove.840B.300d.txt`

You can download embeddings using the provided script in `data/hotpotqa/download.sh` or move existing files into `data/embeddings/` (the repo `.gitignore` excludes these large files).

Configuration: the pipeline reads the embeddings path from the YAML config (`configs/default.yaml`) — override with your own config or environment-specific settings if needed.


## Installation

### Prerequisites

- Python 3.10+
- pip or uv package manager

### Option 1: Using pip

```bash
# Clone the repository
git clone https://github.com/yourusername/hotpotqa.git
cd hotpotqa

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install package in development mode
pip install -e .
```

### Option 2: Using uv (recommended)

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and setup
git clone https://github.com/yourusername/hotpotqa.git
cd hotpotqa

# Sync dependencies
uv sync
```

### Environment Configuration

Create a `.env` file for API keys and configuration:

```bash
cp .env.example .env
# Edit .env and add your API keys
```

Example `.env` file:

```env
MISTRAL_API_KEY=your_api_key_here
MISTRAL_DEFAULT_MODEL=mistral-large-latest
MISTRAL_DEFAULT_TEMPERATURE=0.2
MISTRAL_DEFAULT_MAX_TOKENS=512
```

## Quick Start

### 1. Download the HotpotQA Dataset

```bash
# Navigate to data directory
cd data/raw

# Run download script
bash download.sh
```

This will download:
- Training data (~90k examples)
- Development data with distractors (~7.4k examples)

### 2. Validate the Data

```bash
python scripts/validate_data.py --split train --verbose
python scripts/validate_data.py --split dev --check-coverage
```

### 3. Analyze the Dataset

```bash
python scripts/analyze_dataset.py --split train --save-stats --detailed
```

### 4. Run Preprocessing

```bash
# Quick preprocessing (100 examples for testing)
python scripts/run_preprocessing.py --split train --preset quick

# Full preprocessing
python scripts/run_preprocessing.py --split train --preset full

# RAG-optimized preprocessing
python scripts/run_preprocessing.py --split train --preset rag

# Custom configuration
python scripts/run_preprocessing.py --split train --config configs/custom.yaml
```

## Usage

### Data Loading

```python
from src.data import load_hotpotqa

# Load training data
train_data = load_hotpotqa('data/raw', split='train', max_examples=100)

# Access example
example = train_data[0]
print(f"Question: {example['question']}")
print(f"Answer: {example['answer']}")
print(f"Context paragraphs: {len(example['context'])}")
```

### Preprocessing Pipeline

```python
from src.preprocessing import HotpotQAPreprocessor
from src.config import load_config

# Load configuration with preset
config = load_config(preset='quick')

# Initialize preprocessor
preprocessor = HotpotQAPreprocessor(config)

# Run preprocessing
processed_data = preprocessor.run(split='train')

# Access processed example
example = processed_data[0]
print(f"Flattened context: {example['context_flat'][:200]}...")
print(f"Number of hops: {example['multihop']['num_hops']}")
```

### PyTorch Dataset

```python
from src.data import HotpotQADataset, HotpotQAContextDataset
from torch.utils.data import DataLoader

# Load raw data
examples = load_hotpotqa('data/raw', split='train', max_examples=100)

# Create dataset with flattened context
dataset = HotpotQAContextDataset(
    examples,
    max_context_paragraphs=10,
    include_titles=True
)

# Create DataLoader
dataloader = DataLoader(dataset, batch_size=4, shuffle=True)

# Iterate
for batch in dataloader:
    questions = batch['question']
    contexts = batch['context']
    answers = batch['answer']
    # Train your model...
```

### Tokenization

```python
from src.preprocessing import get_tokenizer

# HuggingFace tokenizer
tokenizer = get_tokenizer('huggingface', model_name='bert-base-uncased')
encoded = tokenizer.encode("What is the capital of France?")
print(f"Input IDs: {encoded['input_ids']}")

# NLTK tokenizer (lightweight)
tokenizer = get_tokenizer('nltk', method='word')
tokens = tokenizer.tokenize("What is the capital of France?")
print(f"Tokens: {tokens}")
```

### Multi-hop Analysis

```python
from src.preprocessing.multihop import create_multihop_features

example = train_data[0]
features = create_multihop_features(example)

print(f"Reasoning type: {features['reasoning_type']}")
print(f"Number of hops: {features['num_hops']}")
print(f"Supporting paragraphs: {features['supporting_paragraphs']}")

# Analyze reasoning chain
for hop in features['reasoning_chain']:
    print(f"Hop {hop['hop']}: {hop['paragraph_title']}")
```

### Configuration Management

```python
from src.config import ConfigManager, load_config

# Load default config
config = ConfigManager()

# Access configuration
max_length = config.get('preprocessing.tokenization.max_length')
data_dir = config.get('data.raw_dir')

# Load with preset and overrides
config = load_config(
    preset='quick',
    overrides={
        'data.max_examples': 50,
        'preprocessing.tokenization.max_length': 256
    }
)

# Save custom configuration
config.save('configs/my_config.yaml')
```

## Configuration Presets

### Quick (Development)
- 100 examples
- 256 max tokens
- 5 max paragraphs
- Fast iteration for testing

### Full (Production)
- All examples
- 512 max tokens
- 10 max paragraphs
- Complete preprocessing

### RAG (Retrieval-Augmented Generation)
- All examples
- 4096 max context tokens
- 20 max paragraphs
- Optimized for retrieval systems

### Baseline (Classical ML)
- Lowercase text
- NLTK tokenization
- 1024 max tokens
- Simplified preprocessing

## API Reference

### Data Module (`src.data`)

- `load_hotpotqa()`: Load HotpotQA dataset
- `HotpotQADataset`: Basic PyTorch dataset
- `HotpotQAContextDataset`: Dataset with flattened context
- `HotpotQASupportingFactsDataset`: Dataset with only supporting facts
- `validate_examples()`: Validate data structure
- `validate_supporting_facts_coverage()`: Check supporting facts coverage

### Preprocessing Module (`src.preprocessing`)

- `HotpotQAPreprocessor`: Complete preprocessing pipeline
- `get_tokenizer()`: Factory for tokenizers
- `flatten_context()`: Flatten context paragraphs
- `extract_supporting_context()`: Extract only supporting paragraphs
- `create_multihop_features()`: Extract multi-hop reasoning features
- `analyze_multihop_distribution()`: Analyze multi-hop statistics

### Utils Module (`src.utils`)

- `clean_text()`: Clean and sanitize text
- `normalize_text()`: Normalize text format
- `normalize_answer()`: Normalize for evaluation
- `get_dataset_statistics()`: Comprehensive dataset analysis
- `print_statistics()`: Print formatted statistics

### Config Module (`src.config`)

- `ConfigManager`: YAML configuration management
- `load_config()`: Load configuration with presets

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_loader.py

# Run in verbose mode
pytest -v
```

## Evaluation

Use the official HotpotQA evaluation script:

```python
from evaluation.eval import eval

# Evaluate predictions
eval('path/to/predictions.json', 'data/raw/hotpot_dev_distractor_v1.json')
```

Metrics include:
- **EM** (Exact Match): Exact string match
- **F1**: Token-level F1 score
- **SP EM/F1**: Supporting facts metrics
- **Joint EM/F1**: Combined answer and supporting facts metrics

## Development

### Code Style

```bash
# Format code with black
black src/ scripts/ tests/

# Check style with flake8
flake8 src/ scripts/ tests/
```

### Adding New Features

1. Create your module in `src/`
2. Add tests in `tests/`
3. Update configuration in `configs/`
4. Document in README
5. Run tests and style checks

## Mistral API Integration

This project includes integration with Mistral AI for question answering:

```python
from src.models.mistral_client import get_mistral_client

# Initialize client
client = get_mistral_client()

# Answer a question
answer = client.answer_question(
    question="What is the capital of France?",
    context="Paris is the capital and largest city of France..."
)

print(f"Answer: {answer}")

# Custom settings
answer = client.answer_question(
    question="...",
    context="...",
    temperature=0.7,
    max_tokens=256
)
```

## Coursework Context

This repository supports the **6CCSANLP: Large Language Model based Open Question Answering** coursework, implementing a complete NLP pipeline for HotpotQA that can be used for:

- **Prompting approaches**: Direct question answering with LLMs
- **Supervised Fine-Tuning (SFT)**: Training models on HotpotQA
- **Retrieval-Augmented Generation (RAG)**: Combining retrieval with generation
- **Reasoning-centric hybrids**: Multi-hop reasoning systems

## Performance Considerations

- Use the `quick` preset during development for fast iteration
- Enable caching for tokenization to speed up repeated runs
- Use `max_examples` parameter to work with data subsets
- Consider using `multiprocessing` for large-scale preprocessing

## Troubleshooting

### Data Download Issues

If download fails:
```bash
# Manually download from:
# http://curtis.ml.cmu.edu/datasets/hotpot/
```

### Import Errors

```bash
# Ensure package is installed
pip install -e .

# Or add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/hotpotqa"
```

### Tokenizer Issues

For HuggingFace tokenizers:
```bash
pip install transformers torch
```

For spaCy:
```bash
pip install spacy
python -m spacy download en_core_web_sm
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Ensure all tests pass
5. Submit a pull request

## License

This project is provided for educational purposes as part of the 6CCSANLP coursework.

## Citation

If you use HotpotQA in your research, please cite:

```bibtex
@inproceedings{yang2018hotpotqa,
  title={HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering},
  author={Yang, Zhilin and Qi, Peng and Zhang, Saizheng and Bengio, Yoshua and Cohen, William W and Salakhutdinov, Ruslan and Manning, Christopher D},
  booktitle={Conference on Empirical Methods in Natural Language Processing (EMNLP)},
  year={2018}
}
```

## Acknowledgments

- HotpotQA dataset: [hotpotqa.github.io](https://hotpotqa.github.io/)
- King's College London - 6CCSANLP Module
- Mistral AI for API access

## Contact

For questions or issues, please:
- Open an issue on GitHub
- Contact the course instructor
- Refer to the coursework brief in `docs/`

---

**Built with Python 3.10+ | PyTorch | HuggingFace Transformers**
