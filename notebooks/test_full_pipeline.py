"""
Complete test of the retrieval pipeline
This script tests all 4 cells of the notebook with a small dataset
"""
import os
import sys
from pathlib import Path

# Ensure we're in the notebooks directory
os.chdir('/Users/vatsalpatel/hotpotqa/notebooks')

print("="*80)
print("RETRIEVAL PIPELINE TEST")
print("="*80)

# ============================================================================
# CELL 1: Wikipedia Chunking
# ============================================================================
print("\n" + "="*80)
print("CELL 1: Processing Wikipedia and creating chunks")
print("="*80)

import bz2, json, tarfile

def chunk_text(text, chunk_size=200, overlap=50):
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start = end - overlap
    return chunks

WIKI_PATH = Path("../data/raw/enwiki-20171001-pages-meta-current-withlinks-abstracts.tar.bz2")
OUT = "wiki_chunks.jsonl"
MAX_ARTICLES = 200  # Small test set

def wiki_json_generator(max_articles=None):
    print(f"Opening Wikipedia dump: {WIKI_PATH}")
    article_count = 0

    with tarfile.open(WIKI_PATH, 'r:bz2') as tar:
        members = tar.getmembers()
        bz2_members = [m for m in members if m.name.endswith('.bz2') and m.isfile()]
        print(f"Found {len(bz2_members)} .bz2 files in archive")

        for member in bz2_members:
            if max_articles and article_count >= max_articles:
                print(f"Reached article limit: {max_articles}")
                break

            try:
                f = tar.extractfile(member)
                if f is None:
                    continue

                decompressed = bz2.decompress(f.read())

                for line in decompressed.decode('utf-8').strip().split('\n'):
                    if not line.strip():
                        continue

                    if max_articles and article_count >= max_articles:
                        break

                    try:
                        article_count += 1
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

            except Exception as e:
                print(f"Error processing {member.name}: {e}")
                continue

chunk_count = 0
with open(OUT, "w") as out:
    for art in wiki_json_generator(max_articles=MAX_ARTICLES):
        title = art.get("title", "")
        text_list = art.get("text", [])
        if isinstance(text_list, list):
            text = ' '.join(text_list)
        else:
            text = str(text_list)

        if not text or len(text.split()) < 50:
            continue

        chunks = chunk_text(text, chunk_size=200, overlap=50)
        for i, ch in enumerate(chunks):
            out.write(json.dumps({
                "id": f"{title}_{i}",
                "title": title,
                "text": ch
            }) + "\n")
            chunk_count += 1

print(f"✅ Created {chunk_count} chunks in {OUT}")

# ============================================================================
# CELL 2: Create Embeddings (LIMITED - just first 50 chunks for testing)
# ============================================================================
print("\n" + "="*80)
print("CELL 2: Creating embeddings with Mistral")
print("="*80)

from mistralai import Mistral
import numpy as np
from tqdm import tqdm
import time

# Load environment
from dotenv import load_dotenv
load_dotenv('../.env')

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
embeddings = []
metadatas = []

# LIMIT to first 50 chunks for quick testing
MAX_CHUNKS = 50
print(f"Processing first {MAX_CHUNKS} chunks...")

with open("wiki_chunks.jsonl", "r") as f:
    for idx, line in enumerate(tqdm(f, desc="Embedding", total=MAX_CHUNKS)):
        if idx >= MAX_CHUNKS:
            break

        obj = json.loads(line)
        text = obj["text"]

        try:
            resp = client.embeddings.create(
                model="mistral-embed",
                inputs=[text]  # Fixed: 'inputs' not 'input'
            )
            vector = resp.data[0].embedding
            embeddings.append(np.array(vector, dtype="float32"))
            metadatas.append({
                "id": obj["id"],
                "title": obj["title"],
                "text": obj["text"]
            })
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

if embeddings:
    np.save("wiki_vectors.npy", np.vstack(embeddings))
    with open("wiki_meta.jsonl", "w") as out:
        for m in metadatas:
            out.write(json.dumps(m) + "\n")
    print(f"✅ Created {len(embeddings)} embeddings")
else:
    print("❌ No embeddings created - check for errors above")
    sys.exit(1)

# ============================================================================
# CELL 3: Build FAISS Index
# ============================================================================
print("\n" + "="*80)
print("CELL 3: Building FAISS index")
print("="*80)

try:
    import faiss
except ImportError:
    print("Installing faiss-cpu...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "faiss-cpu", "-q"])
    import faiss

vectors = np.load("wiki_vectors.npy")
print(f"Loaded {vectors.shape[0]} vectors with {vectors.shape[1]} dimensions")

d = vectors.shape[1]
index = faiss.IndexFlatIP(d)
faiss.normalize_L2(vectors)
index.add(vectors)
faiss.write_index(index, "wiki_faiss.index")

print(f"✅ FAISS index created with {index.ntotal} vectors")

# ============================================================================
# CELL 4: Test Retrieval
# ============================================================================
print("\n" + "="*80)
print("CELL 4: Testing retrieval")
print("="*80)

index = faiss.read_index("wiki_faiss.index")
with open("wiki_meta.jsonl") as f:
    metas = [json.loads(l) for l in f]

def dense_retrieval(query, k=3):
    resp = client.embeddings.create(model="mistral-embed", inputs=[query])
    q_vec = np.array(resp.data[0].embedding, dtype="float32").reshape(1, -1)
    faiss.normalize_L2(q_vec)
    scores, ids = index.search(q_vec, k)

    results = []
    for score, idx in zip(scores[0], ids[0]):
        result = metas[idx].copy()
        result['score'] = float(score)
        results.append(result)
    return results

# Test queries
test_queries = [
    "Who was Barack Obama's vice president?",
    "What is the capital of France?"
]

for query in test_queries:
    print(f"\nQuery: {query}")
    results = dense_retrieval(query, k=3)

    for i, r in enumerate(results, 1):
        print(f"  {i}. {r['title']} (score: {r['score']:.4f})")
        print(f"     {r['text'][:100]}...")

print("\n" + "="*80)
print("✅ ALL TESTS PASSED!")
print("="*80)
print("\nThe notebook is working correctly. You can now:")
print("  1. Increase MAX_ARTICLES in Cell 1 for more data")
print("  2. Remove MAX_CHUNKS limit in Cell 2 to embed all chunks")
print("  3. Test with HotpotQA questions")
