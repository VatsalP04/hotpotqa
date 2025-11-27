"""Test script for Cell 1 - Wikipedia chunking with small limit"""
import os, bz2, json, tarfile
from pathlib import Path

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

# Use the tar.bz2 file directly
WIKI_PATH = Path("../data/raw/enwiki-20171001-pages-meta-current-withlinks-abstracts.tar.bz2")
OUT = "wiki_chunks_test.jsonl"

# Very small limit for testing
MAX_ARTICLES = 100

def wiki_json_generator(max_articles=None):
    """
    Read Wikipedia articles directly from tar.bz2 archive.
    """
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

print("Starting to process Wikipedia articles and create chunks...")
print(f"Article limit: {MAX_ARTICLES}")
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

print(f"\n✅ Done! Created {chunk_count} chunks in {OUT}")
print(f"Sample chunk:")
with open(OUT, "r") as f:
    first_chunk = json.loads(f.readline())
    print(f"  Title: {first_chunk['title']}")
    print(f"  Text preview: {first_chunk['text'][:100]}...")
