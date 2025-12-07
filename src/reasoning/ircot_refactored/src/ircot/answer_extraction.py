"""
Answer extraction utilities for IRCoT.

This module centralizes all answer extraction logic that was previously
duplicated across ircot.py, qa_reader.py, and prompts.py. Having a single
source of truth for answer extraction ensures consistency and makes
maintenance easier.
"""

from __future__ import annotations

import re
from typing import Tuple, Optional, List
from dataclasses import dataclass

from .config import AnswerMarkers


@dataclass
class ExtractedAnswer:
    """Result of answer extraction."""
    answer: str
    full_cot: str
    found: bool
    extraction_method: str  # For debugging: which pattern matched


class AnswerExtractor:
    """
    Extracts answers from Chain-of-Thought reasoning text.
    
    Consolidates all answer extraction patterns and logic into a single class.
    Supports multiple extraction patterns for robustness.
    """
    
    # Compiled patterns for efficiency (ordered by specificity)
    PATTERNS = [
        (re.compile(r"[Ss]o the answer is[:\s]+(.+)", re.DOTALL), "so_the_answer_is"),
        (re.compile(r"[Tt]he answer is[:\s]+(.+)", re.DOTALL), "the_answer_is"),
        (re.compile(r"[Aa]nswer is[:\s]+(.+)", re.DOTALL), "answer_is"),
        (re.compile(r"[Aa]nswer[:\s]+(.+)", re.DOTALL), "answer_colon"),
    ]
    
    @classmethod
    def extract(cls, text: str) -> ExtractedAnswer:
        """
        Extract answer from CoT text using multiple patterns.
        
        Args:
            text: The CoT reasoning text
            
        Returns:
            ExtractedAnswer with the extracted answer or empty if not found
        """
        if not text or not text.strip():
            return ExtractedAnswer(
                answer="",
                full_cot="",
                found=False,
                extraction_method="empty_input"
            )
        
        text = text.strip()
        
        # Try each pattern in order of specificity
        for pattern, method_name in cls.PATTERNS:
            match = pattern.search(text)
            if match:
                answer = cls._clean_answer(match.group(1))
                if answer:
                    return ExtractedAnswer(
                        answer=answer,
                        full_cot=text,
                        found=True,
                        extraction_method=method_name
                    )
        
        # Fallback: try to find answer marker directly
        fallback_result = cls._fallback_extraction(text)
        if fallback_result:
            return fallback_result
        
        # Last resort: use last sentence if it's short enough
        last_sentence = cls._extract_last_sentence(text)
        if last_sentence and len(last_sentence) < 50:
            return ExtractedAnswer(
                answer=last_sentence,
                full_cot=text,
                found=True,
                extraction_method="last_sentence"
            )
        
        # Could not extract answer
        return ExtractedAnswer(
            answer="",
            full_cot=text,
            found=False,
            extraction_method="not_found"
        )
    
    @classmethod
    def _clean_answer(cls, raw_answer: str) -> str:
        """
        Clean extracted answer by removing formatting and truncating.
        
        Args:
            raw_answer: Raw extracted text
            
        Returns:
            Cleaned answer string
        """
        if not raw_answer:
            return ""
        
        answer = raw_answer.strip()
        
        # Remove markdown formatting
        answer = answer.replace("**", "").replace("*", "")
        
        # Take only first line/sentence
        for delimiter in ["\n", ". ", ".\n"]:
            idx = answer.find(delimiter)
            if idx != -1:
                answer = answer[:idx]
                break
        
        # Remove trailing punctuation (but keep internal punctuation)
        answer = answer.rstrip(".,;:!?")
        
        return answer.strip()
    
    @classmethod
    def _fallback_extraction(cls, text: str) -> Optional[ExtractedAnswer]:
        """
        Fallback extraction using direct string search.
        
        Args:
            text: The CoT text
            
        Returns:
            ExtractedAnswer if found, None otherwise
        """
        lower_text = text.lower()
        marker = AnswerMarkers.PRIMARY.lower()
        
        idx = lower_text.rfind(marker)
        if idx == -1:
            return None
        
        after = text[idx + len(marker):].strip(" :\n")
        
        # Take first line
        newline_idx = after.find("\n")
        if newline_idx != -1:
            after = after[:newline_idx]
        
        answer = cls._clean_answer(after)
        if answer:
            return ExtractedAnswer(
                answer=answer,
                full_cot=text,
                found=True,
                extraction_method="fallback_rfind"
            )
        
        return None
    
    @classmethod
    def _extract_last_sentence(cls, text: str) -> str:
        """
        Extract the last sentence from text.
        
        Args:
            text: The text to extract from
            
        Returns:
            Last sentence or empty string
        """
        sentences = text.split(".")
        for sent in reversed(sentences):
            sent = sent.strip()
            if sent and len(sent) > 2:
                return sent
        return ""
    
    @classmethod
    def contains_answer_marker(cls, text: str) -> bool:
        """
        Check if text contains an answer marker.
        
        Args:
            text: Text to check
            
        Returns:
            True if answer marker found
        """
        if not text:
            return False
        
        lower_text = text.lower()
        return any(marker.lower() in lower_text for marker in [AnswerMarkers.PRIMARY] + AnswerMarkers.ALTERNATIVES)


class SentenceExtractor:
    """
    Extracts sentences from LLM output for step-by-step reasoning.
    
    Handles the complexity of:
    - Proper sentence boundary detection
    - Skipping repeated content from previous CoT
    - Handling edge cases in LLM output
    """
    
    # Pattern for sentence boundary detection
    SENTENCE_PATTERN = re.compile(r'([^.!?]+[.!?]+)\s*')
    
    @classmethod
    def get_next_sentence(cls, text: str, previous_cot: str = "") -> str:
        """
        Extract the next NEW sentence from LLM output.
        
        If the LLM repeats previous CoT (common behavior), this method
        skips the repeated content and returns the next new sentence.
        
        Args:
            text: LLM output text
            previous_cot: Previously generated CoT to skip if repeated
            
        Returns:
            Next new sentence (not a repeat of previous_cot)
        """
        if not text or not text.strip():
            return ""
        
        # Extract sentences using pattern
        sentences = cls.SENTENCE_PATTERN.findall(text)
        
        # Fallback: try simple split if pattern fails
        if not sentences:
            sentences = cls._simple_sentence_split(text)
        
        if not sentences:
            return text.strip()
        
        # Clean sentences
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return text.strip()
        
        # If no previous CoT, return first sentence
        if not previous_cot:
            return sentences[0]
        
        # Check if first sentence is a repeat
        if cls._is_repeat(sentences[0], previous_cot):
            return sentences[1] if len(sentences) > 1 else ""
        
        return sentences[0]
    
    @classmethod
    def split_into_sentences(cls, text: str) -> List[str]:
        """
        Split text into individual sentences.
        
        Args:
            text: Text to split
            
        Returns:
            List of sentences
        """
        if not text:
            return []
        
        # Handle "So the answer is" specially to preserve it
        if "So the answer is:" in text:
            parts = text.split("So the answer is:")
            sentences = cls.SENTENCE_PATTERN.findall(parts[0])
            sentences = [s.strip() + "." for s in sentences if s.strip()]
            if parts[1].strip():
                sentences.append(f"So the answer is: {parts[1].strip()}")
            return sentences
        
        sentences = cls.SENTENCE_PATTERN.findall(text)
        return [s.strip() for s in sentences if s.strip()]
    
    @classmethod
    def _simple_sentence_split(cls, text: str) -> List[str]:
        """Fallback sentence splitting."""
        for delim in [".", "?", "!"]:
            idx = text.find(delim)
            if idx != -1:
                return [text[:idx + 1].strip()]
        return [text.strip()] if text.strip() else []
    
    @classmethod
    def _is_repeat(cls, sentence: str, previous_cot: str) -> bool:
        """
        Check if sentence is a repeat of previous CoT.
        
        Args:
            sentence: Sentence to check
            previous_cot: Previous CoT content
            
        Returns:
            True if sentence appears to be a repeat
        """
        # Normalize for comparison
        prev_norm = cls._normalize(previous_cot)
        sent_norm = cls._normalize(sentence)
        
        # Check substring containment
        if prev_norm in sent_norm or sent_norm in prev_norm:
            return True
        
        # Check word overlap at start
        prev_words = prev_norm.split()[:5]
        sent_words = sent_norm.split()[:5]
        
        if prev_words and len(prev_words) >= 3 and prev_words == sent_words:
            return True
        
        return False
    
    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison."""
        return re.sub(r'\*\*|\*', '', text.lower().strip())
