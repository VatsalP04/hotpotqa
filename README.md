# 6CCSANLP – Open Question Answering (HotpotQA)

This repository hosts the coursework implementation for **6CCSANLP: Large Language Model based Open Question Answering**. The project targets HotpotQA and supports multiple methodological tracks (prompting, SFT, RAG, reasoning-centric hybrids) under a shared, reproducible toolbox.

## Repository Layout
```
├── data/hotpotqa/          # HotpotQA JSON files + official evaluator
├── docs/                   # Coursework brief, planning notes
├── notebooks/              # Jupyter notebooks for EDA & prototyping
├── reports/                # Drafts/exports of the ACL-style paper
├── results/                # Logs, checkpoints, dev predictions
├── scripts/                # Utility entrypoints (e.g., API smoke tests)
├── src/
│   ├── config/             # Environment + API configuration helpers
│   ├── models/             # Model and API clients (Mistral, etc.)
│   ├── pipelines/          # Future training/inference pipelines
│   ├── retrieval/          # RAG components (to be implemented)
│   ├── reasoning/          # Structured reasoning utilities
│   └── training/           # Fine-tuning code
└── evaluation/             # Official HotpotQA evaluation script wrapper
```

## Quick Start
1. **Install uv (if needed)**: https://github.com/astral-sh/uv
2. **Sync the environment**:
   ```bash
   cd /home/rebal/Cursor/NLP/hotpotqa
   uv sync
   ```
3. **Configure secrets**:
   ```bash
   cp .env.example .env
   # fill in MISTRAL_API_KEY and optional overrides
   ```
4. **Smoke test the Mistral integration** (requires a valid key):
   ```bash
   uv run python scripts/test_mistral_client.py
   ```
   You should see the configured model name and a toy answer.
5. **Notebook workflow**:
   ```bash
   uv run jupyter lab eda.ipynb
   ```

## Mistral API Usage
- Configuration lives in `src/config/__init__.py`, automatically loading `.env`.
- The reusable wrapper is `src.models.mistral_client.MistralClient`:
  ```python
  from src.models.mistral_client import get_mistral_client
  client = get_mistral_client()
  answer = client.answer_question("Explain multi-hop reasoning.")
  ```
- Customise defaults via env vars (model, temperature, max tokens) or per-call overrides.

## Coursework Checklist
- Literature review **must** cite Lin Gui’s recommended references (see `docs/coursework_brief.md`) plus ≥5 additional sources.
- Report: ACL 2025 template, 4–6 pages, includes Introduction, Literature Review, Methodology, Experiments, Conclusion, and team details.
- Deliverables: runnable code, dev predictions, final PDF report — bundled in a zip named after the team.

## Next Steps
- Finalise task decomposition across prompting/SFT/RAG/reasoning tracks.
- Implement retrieval and reasoning modules under `src/`.
- Track experiments/results inside `results/` with clear metadata.

> Need inspiration? Review the previous HotpotQA work cited in the brief and adapt the provided Colab workflows for local runs.
