
# Download Hotpot Data
wget http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json
wget http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_fullwiki_v1.json
wget http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_train_v1.1.json

# Download GloVe
# Make the script robust to being run from any working directory by resolving
# the script's directory and placing embeddings into ../embeddings relative to
# this script file.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOVE_DIR="$DIR/../embeddings"
mkdir -p "$GLOVE_DIR"
# Download zipped embeddings into data/embeddings (skip if already present)
if [ ! -f "$GLOVE_DIR/glove.840B.300d.zip" ] && [ ! -f "$GLOVE_DIR/glove.840B.300d.txt" ]; then
	wget http://nlp.stanford.edu/data/glove.840B.300d.zip -O "$GLOVE_DIR/glove.840B.300d.zip"
	unzip "$GLOVE_DIR/glove.840B.300d.zip" -d "$GLOVE_DIR"
else
	echo "GloVe files already present in $GLOVE_DIR — skipping download."
fi

# Download Spacy language models
python3 -m spacy download en
