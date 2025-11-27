#!/usr/bin/env python3
"""
Test script to verify Wikipedia dump loading works correctly.
Run this to test the loading function before using it in the notebook.
"""

import json
import tarfile
import bz2
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm

# Setup paths
project_root = Path(__file__).parent.parent
wiki_dump_path = project_root / 'data/raw/enwiki-20171001-pages-meta-current-withlinks-abstracts.tar.bz2'

def load_wikipedia_dump(dump_path: Path, max_articles: int = None) -> List[Dict]:
    """
    Load Wikipedia articles from tar.bz2 dump.

    The dump contains multiple .bz2 files, each with one JSON object per line.
    Each JSON has: id, url, title, text (list of sentences), text_with_links, etc.

    Args:
        dump_path: Path to the tar.bz2 file
        max_articles: Maximum number of articles to load (for testing)

    Returns:
        List of article dictionaries with 'title' and 'text' keys
    """
    articles = []

    print(f"Opening Wikipedia dump: {dump_path.name}")

    with tarfile.open(dump_path, 'r:bz2') as tar:
        members = tar.getmembers()
        print(f"Total files in archive: {len(members)}")

        # Filter to only process .bz2 files (not directories)
        bz2_members = [m for m in members if m.name.endswith('.bz2') and m.isfile()]
        print(f"BZ2 files found: {len(bz2_members)}")

        if max_articles:
            # Estimate how many files to process based on max_articles
            # Assuming ~100-500 articles per file
            max_files = min(max(1, max_articles // 100), len(bz2_members))
            bz2_members = bz2_members[:max_files]
            print(f"Processing first {len(bz2_members)} files to get ~{max_articles} articles...")

        for member in tqdm(bz2_members, desc="Processing files"):
            if max_articles and len(articles) >= max_articles:
                break

            try:
                # Extract the compressed file
                f = tar.extractfile(member)
                if f is None:
                    continue

                # Decompress the bz2 content
                decompressed = bz2.decompress(f.read())

                # Each line is a separate JSON object
                for line in decompressed.decode('utf-8').strip().split('\n'):
                    if not line.strip():
                        continue

                    try:
                        article_data = json.loads(line)

                        # Extract title and text
                        title = article_data.get('title', '')

                        # Text is stored as a list of sentences
                        text_list = article_data.get('text', [])
                        if isinstance(text_list, list):
                            text = ' '.join(text_list)
                        else:
                            text = str(text_list)

                        if title and text:
                            articles.append({
                                'id': article_data.get('id', ''),
                                'title': title,
                                'text': text,
                                'url': article_data.get('url', '')
                            })

                        if max_articles and len(articles) >= max_articles:
                            break

                    except json.JSONDecodeError as e:
                        # Skip malformed JSON lines
                        continue

            except Exception as e:
                print(f"Error processing {member.name}: {e}")
                continue

    print(f"\n✅ Loaded {len(articles):,} Wikipedia articles")
    return articles


if __name__ == "__main__":
    print("="*80)
    print("Testing Wikipedia Dump Loading")
    print("="*80)

    # Check if file exists
    print(f"\nWikipedia dump path: {wiki_dump_path}")
    print(f"File exists: {wiki_dump_path.exists()}")

    if wiki_dump_path.exists():
        file_size_gb = wiki_dump_path.stat().st_size / (1024**3)
        print(f"File size: {file_size_gb:.2f} GB")
    else:
        print("ERROR: Wikipedia dump file not found!")
        print("Please ensure the file is at: data/raw/enwiki-20171001-pages-meta-current-withlinks-abstracts.tar.bz2")
        exit(1)

    # Load a small sample
    print("\n" + "="*80)
    print("Loading 1000 articles for testing...")
    print("="*80 + "\n")

    wiki_articles = load_wikipedia_dump(wiki_dump_path, max_articles=1000)

    # Show results
    if wiki_articles:
        print("\n" + "="*80)
        print("SUCCESS! Sample Articles:")
        print("="*80)

        # Show first 3 articles
        for i, article in enumerate(wiki_articles[:3], 1):
            print(f"\n{i}. Title: {article['title']}")
            print(f"   ID: {article['id']}")
            print(f"   Text preview (first 200 chars): {article['text'][:200]}...")

        print("\n" + "="*80)
        print(f"Total articles loaded: {len(wiki_articles):,}")
        print("="*80)

        # Show some statistics
        print("\nStatistics:")
        avg_text_len = sum(len(a['text']) for a in wiki_articles) / len(wiki_articles)
        print(f"  - Average text length: {avg_text_len:.0f} characters")
        print(f"  - Shortest article: {min(len(a['text']) for a in wiki_articles)} chars")
        print(f"  - Longest article: {max(len(a['text']) for a in wiki_articles)} chars")

    else:
        print("\n❌ ERROR: No articles were loaded!")
        print("Check the function implementation and file format.")
