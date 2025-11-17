"""Central configuration for the HotpotQA project."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

# Load environment variables from the project root
# __file__ is src/config/__init__.py, so we need to go up 2 levels to get project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_API_BASE = os.getenv("MISTRAL_API_BASE", "https://api.mistral.ai/v1")
DEFAULT_MODEL = os.getenv("MISTRAL_DEFAULT_MODEL", "mistral-large-latest")
DEFAULT_TEMPERATURE = float(os.getenv("MISTRAL_DEFAULT_TEMPERATURE", "0.2"))
DEFAULT_MAX_TOKENS = int(os.getenv("MISTRAL_DEFAULT_MAX_TOKENS", "512"))


def validate_config() -> None:
    """Ensure required configuration values are provided."""
    missing = []
    if not MISTRAL_API_KEY:
        missing.append("MISTRAL_API_KEY")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def dump_config() -> Dict[str, Any]:
    """Utility for debugging configuration."""
    return {
        "MISTRAL_API_KEY_SET": bool(MISTRAL_API_KEY),
        "MISTRAL_API_BASE": MISTRAL_API_BASE,
        "DEFAULT_MODEL": DEFAULT_MODEL,
        "DEFAULT_TEMPERATURE": DEFAULT_TEMPERATURE,
        "DEFAULT_MAX_TOKENS": DEFAULT_MAX_TOKENS,
    }
