"""Quick check to verify the Mistral client configuration."""

import sys
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Check if we're in the right environment
try:
    import mistralai
    import dotenv
except ImportError as e:
    print("❌ Error: Missing dependencies. Please use 'uv run python' instead of 'python3'")
    print(f"   Missing: {e}")
    print("\n   Try: uv run python scripts/test_mistral_client.py")
    sys.exit(1)

from src.models.mistral_client import get_mistral_client


def main() -> None:
    try:
        client = get_mistral_client()
        print("✅ Client initialised. Model:", client.model)
        response = client.answer_question("What is 2 + 2?")
        print("Response:", response)
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n   Make sure you have:")
        print("   1. Created .env file with MISTRAL_API_KEY")
        print("   2. Run: uv run python scripts/test_mistral_client.py")


if __name__ == "__main__":
    main()