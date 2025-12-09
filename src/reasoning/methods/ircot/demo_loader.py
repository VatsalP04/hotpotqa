"""
Demo loader for IRCoT few-shot demonstrations.

Loads demonstrations from the official IRCoT prompt files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from src.reasoning.core.types import CoTDemo, Paragraph

# Pattern to match demo blocks
_BLOCK_PATTERN = re.compile(
    r"^# METADATA:.*?(?=^# METADATA:|\Z)",
    flags=re.MULTILINE | re.DOTALL
)


def load_default_demos(max_examples: Optional[int] = None) -> List[CoTDemo]:
    """
    Load default HotpotQA demonstrations.
    
    Args:
        max_examples: Maximum demos to load
    
    Returns:
        List of CoTDemo objects
    """
    # Try multiple locations
    locations = [
        Path(__file__).parent.parent.parent / "resources" / "demos" / "gold_with_2_distractors_context_cot_qa_codex.txt",
        Path(__file__).parent.parent.parent.parent.parent / "resources" / "demos" / "gold_with_2_distractors_context_cot_qa_codex.txt",
        # Legacy paths
        Path("src/reasoning/resources/demos/gold_with_2_distractors_context_cot_qa_codex.txt"),
        Path("resources/gold_with_2_distractors_context_cot_qa_codex.txt"),
    ]
    
    for path in locations:
        if path.exists():
            return load_demos_from_file(str(path), max_examples)
    
    raise FileNotFoundError(
        f"Could not find demonstration file. Tried: {[str(p) for p in locations]}"
    )


def load_demos_from_file(
    filepath: str,
    max_examples: Optional[int] = None
) -> List[CoTDemo]:
    """
    Load demonstrations from a prompt file.
    
    Args:
        filepath: Path to the prompt file
        max_examples: Maximum demos to load
    
    Returns:
        List of CoTDemo objects
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    
    text = path.read_text(encoding="utf-8")
    blocks = _BLOCK_PATTERN.findall(text)
    
    demos = []
    index_start = -1
    
    for block in blocks:
        demo = _parse_block(block, index_start)
        if demo:
            demos.append(demo)
            index_start -= len(demo.paragraphs)
        
        if max_examples and len(demos) >= max_examples:
            break
    
    return demos


def _parse_block(block_text: str, index_start: int) -> Optional[CoTDemo]:
    """Parse a single demonstration block."""
    lines = block_text.strip().splitlines()
    if not lines:
        return None
    
    # Skip metadata line
    lines = lines[1:]
    
    paragraphs: List[Paragraph] = []
    index = index_start
    question = ""
    answer = ""
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            i += 1
            continue
        
        if line.startswith("Wikipedia Title:"):
            title = line.split(":", 1)[1].strip()
            i += 1
            text_lines = []
            
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
                sentences = [s.strip() + "." for s in text.split(".") if s.strip()]
                
                paragraph = Paragraph(
                    title=title,
                    text=text,
                    sentences=tuple(sentences) if sentences else (text,),
                    index=index
                )
                paragraphs.append(paragraph)
                index -= 1
        
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
        cot_answer=answer
    )

