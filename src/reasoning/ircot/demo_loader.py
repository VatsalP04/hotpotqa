"""
IRCoT Few-Shot Demonstration Loader

This module loads and parses few-shot demonstrations from the official IRCoT repository.
The demonstrations are used to teach the LLM how to perform multi-hop reasoning through
in-context learning.

Key Functions:
- load_default_hotpot_demos(): Loads HotpotQA demonstrations from the official prompt file
- load_cot_demos_from_file(): Generic loader for any IRCoT prompt file
- _parse_block(): Parses individual demonstration blocks from the prompt format

The official IRCoT prompt files contain carefully curated examples with:
- Multiple Wikipedia paragraphs (2 "gold" + 2 "distractors" per example)
- Complex multi-hop questions requiring reasoning across paragraphs
- Step-by-step reasoning chains ending with "So the answer is: [ANSWER]"

These demonstrations are critical for IRCoT performance as they teach the model:
1. How to reason step-by-step across multiple documents
2. How to ignore irrelevant information (distractors)
3. How to structure the final answer
4. The expected format and style of reasoning

File Format:
The prompt files use a specific format with metadata headers and structured blocks:
    # METADATA: {"qid": "question_id"}
    Wikipedia Title: Document 1
    [Document 1 text]
    
    Wikipedia Title: Document 2
    [Document 2 text]
    
    Q: [Multi-hop question]
    A: [Step-by-step reasoning] So the answer is: [Final answer].
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from .prompts import CoTDemo
from .retriever import Paragraph

_BLOCK_PATTERN = re.compile(
    r"^# METADATA:.*?(?=^# METADATA:|\Z)", flags=re.MULTILINE | re.DOTALL
)


def _parse_block(block_text: str, pid_start: int) -> Optional[CoTDemo]:
    """
    Parse a single block from the official IRCoT prompt files.

    Each block contains multiple "Wikipedia Title:" sections followed by
    a single Q/A pair. We convert them into our `CoTDemo` structure.
    """

    lines = block_text.strip().splitlines()
    if not lines:
        return None

    # Drop the metadata line
    lines = lines[1:]
    paragraphs: List[Paragraph] = []
    pid = pid_start
    i = 0
    question = ""
    answer = ""

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        if line.startswith("Wikipedia Title:"):
            title = line.split(":", 1)[1].strip()
            i += 1
            text_lines: List[str] = []

            while i < len(lines):
                current = lines[i]
                if current.startswith("Wikipedia Title:") or current.startswith("Q:"):
                    break
                if current.strip() == "":
                    i += 1
                    break
                text_lines.append(current.strip())
                i += 1

            text = " ".join(text_lines).strip()
            if text:
                paragraphs.append(Paragraph(pid=pid, title=title, text=text))
                pid -= 1

        elif line.startswith("Q:"):
            question = line.split(":", 1)[1].strip()
            i += 1
            while i < len(lines) and not lines[i].startswith("A:"):
                i += 1
            if i < len(lines) and lines[i].startswith("A:"):
                answer = lines[i].split(":", 1)[1].strip()
            break
        else:
            i += 1

    if not (paragraphs and question and answer):
        return None

    return CoTDemo(
        paragraphs=paragraphs,
        question=question,
        cot_answer=answer,
    )


def load_cot_demos_from_file(
    prompt_file: str, max_examples: Optional[int] = None
) -> List[CoTDemo]:
    """
    Load CoT demonstrations from the official IRCoT prompt files.

    Args:
        prompt_file: Path to the `.txt` prompt file.
        max_examples: Optional limit on number of demos to load.
    """

    path = Path(prompt_file)
    if not path.exists():
        raise FileNotFoundError(f"Could not find prompt file: {path}")

    text = path.read_text(encoding="utf-8")
    blocks = _BLOCK_PATTERN.findall(text)

    demos: List[CoTDemo] = []
    pid_start = -1

    for block in blocks:
        demo = _parse_block(block, pid_start=pid_start)
        if demo:
            demos.append(demo)
            pid_start -= len(demo.paragraphs)

        if max_examples is not None and len(demos) >= max_examples:
            break

    return demos


def load_default_hotpot_demos(max_examples: Optional[int] = None) -> List[CoTDemo]:
    """
    Convenience helper that loads the default HotpotQA CoT demonstrations.

    It uses the `gold_with_2_distractors_context_cot_qa_codex.txt` file
    that ships with the official IRCoT repository.
    """

    default_path = (
        Path(__file__)
        .resolve()
        .parent
        / "resources"
        / "prompts"
        / "hotpotqa"
        / "gold_with_2_distractors_context_cot_qa_codex.txt"
    )
    return load_cot_demos_from_file(str(default_path), max_examples=max_examples)


