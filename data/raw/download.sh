#!/bin/bash
# Download HotpotQA dataset
# Official HotpotQA dataset download script

set -e  # Exit on error

echo "====================================="
echo "HotpotQA Dataset Download Script"
echo "====================================="
echo ""

# Dataset URLs
TRAIN_URL="http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_train_v1.1.json"
DEV_DISTRACTOR_URL="http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json"
DEV_FULLWIKI_URL="http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_fullwiki_v1.json"
TEST_FULLWIKI_URL="http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_test_fullwiki_v1.json"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DATA_DIR="$SCRIPT_DIR"

echo "Data will be downloaded to: $DATA_DIR"
echo ""

# Function to download file
download_file() {
    local url=$1
    local filename=$2
    local filepath="$DATA_DIR/$filename"

    if [ -f "$filepath" ]; then
        echo "✓ $filename already exists, skipping download"
    else
        echo "Downloading $filename..."
        if command -v wget &> /dev/null; then
            wget -O "$filepath" "$url"
        elif command -v curl &> /dev/null; then
            curl -L -o "$filepath" "$url"
        else
            echo "❌ Error: Neither wget nor curl is installed"
            echo "Please install wget or curl and try again"
            exit 1
        fi
        echo "✅ Downloaded $filename"
    fi
    echo ""
}

# Download training data
echo "--- Training Data ---"
download_file "$TRAIN_URL" "hotpot_train_v1.1.json"

# Download dev data with distractors (most commonly used)
echo "--- Development Data (with distractor paragraphs) ---"
download_file "$DEV_DISTRACTOR_URL" "hotpot_dev_distractor_v1.json"

# Optional: Download dev data (fullwiki setting)
read -p "Download dev fullwiki data? (y/N): " response
if [[ "$response" =~ ^[Yy]$ ]]; then
    echo "--- Development Data (fullwiki) ---"
    download_file "$DEV_FULLWIKI_URL" "hotpot_dev_fullwiki_v1.json"
fi

# Optional: Download test data (fullwiki setting, no labels)
read -p "Download test fullwiki data? (y/N): " response
if [[ "$response" =~ ^[Yy]$ ]]; then
    echo "--- Test Data (fullwiki, no labels) ---"
    download_file "$TEST_FULLWIKI_URL" "hotpot_test_fullwiki_v1.json"
fi

echo ""
echo "====================================="
echo "✅ Download Complete!"
echo "====================================="
echo ""
echo "Downloaded files:"
ls -lh "$DATA_DIR"/*.json 2>/dev/null || echo "No JSON files found"
echo ""
echo "You can now validate the data with:"
echo "  python scripts/validate_data.py --split train"
echo "  python scripts/validate_data.py --split dev"
echo ""