import re
import string
from collections import Counter
from typing import List, Dict, Any, Tuple
from src.reasoning.ircot.retriever import Paragraph, Sentence


def normalize_answer(s: str) -> str:
    def remove_articles(text):
        return re.sub(r'\b(a|an|the)\b', ' ', text)

    def white_space_fix(text):
        return ' '.join(text.split())

    def remove_punc(text):
        exclude = set(string.punctuation)
        return ''.join(ch for ch in text if ch not in exclude)

    def lower(text):
        return text.lower()

    return white_space_fix(remove_articles(remove_punc(lower(s))))


def f1_score(prediction: str, ground_truth: str) -> Tuple[float, float, float]:
    normalized_prediction = normalize_answer(prediction)
    normalized_ground_truth = normalize_answer(ground_truth)

    ZERO_METRIC = (0.0, 0.0, 0.0)

    if normalized_prediction in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return ZERO_METRIC
    if normalized_ground_truth in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return ZERO_METRIC

    prediction_tokens = normalized_prediction.split()
    ground_truth_tokens = normalized_ground_truth.split()
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return ZERO_METRIC
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1, precision, recall


def calculate_recall(retrieved_paragraphs: List[Paragraph], gold_supporting_facts: List[List]) -> float:
    if not gold_supporting_facts:
        return 1.0 if not retrieved_paragraphs else 0.0
    
    retrieved_titles = {p.title for p in retrieved_paragraphs}
    gold_titles = {fact[0] for fact in gold_supporting_facts}
    
    if not gold_titles:
        return 1.0
    
    intersection = retrieved_titles & gold_titles
    return len(intersection) / len(gold_titles)


def split_cot_into_sentences(cot: str) -> List[str]:
    sentences = re.split(r'[.!?]\s+', cot)
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences


def format_for_csv(
    question: str,
    correct: int,
    recall: float,
    answer: str,
    gold_answer: str,
    chain_of_thought: str,
    retrieved_paragraphs: List[Paragraph],
    gold_sentences: List[str]
) -> Dict[str, Any]:
    cot_sentences = split_cot_into_sentences(chain_of_thought)
    retrieved_texts = [p.text for p in retrieved_paragraphs]
    
    result = {
        'question': question,
        'correct': correct,
        'recall': recall,
        'answer': answer,
        'gold_answer': gold_answer,
    }
    
    for i, sent in enumerate(cot_sentences):
        result[f'chain_of_thought_{i}'] = sent.replace('\n', ' ').replace('\r', ' ')
    
    for i, text in enumerate(retrieved_texts):
        result[f'retrieved_sentence_{i}'] = text.replace('\n', ' ').replace('\r', ' ')
    
    for i, text in enumerate(gold_sentences):
        result[f'gold_sentence_{i}'] = text.replace('\n', ' ').replace('\r', ' ')
    
    return result

