#%%
from mateo.decomposition import run_decomposition
from transformer_lens import HookedTransformer
from datasets import load_dataset
import sentence_transformers
import json
import re
import string
from collections import Counter


#%%
MODEL = HookedTransformer.from_pretrained("meta-llama/Llama-3.1-8B-Instruct")

#%%
RETRIEVER = sentence_transformers.SentenceTransformer("all-MiniLM-L6-v2")

#%%
TRAIN_DATASET = load_dataset("hotpotqa", "train")

#%%
TRAIN_SAMPLE_SIZE = 28000
DEV_SAMPLE_SIZE = 7000
TEST_SAMPLE_SIZE = 7000
SAVE_FREQUENCY = 10
METHOD = "decomposition"
PREDICTIONS_PATH = f"{METHOD}_predictions.json"
CSV_PATH = f"{METHOD}.csv"

#%%
def normalize_answer(s):
    """Normalize answer for F1 calculation."""
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


def f1_score(prediction, ground_truth):
    """Calculate F1 score between prediction and ground truth."""
    normalized_prediction = normalize_answer(prediction)
    normalized_ground_truth = normalize_answer(ground_truth)
    
    if normalized_prediction in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return 0.0
    if normalized_ground_truth in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return 0.0
    
    prediction_tokens = normalized_prediction.split()
    ground_truth_tokens = normalized_ground_truth.split()
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return f1


def extract_gold_sentences(example):
    """Extract gold sentences from supporting_facts."""
    context = example.get("context", [])
    supporting_facts = example.get("supporting_facts", [])
    
    gold_sentences = []
    for title, sent_idx in supporting_facts:
        # Find the paragraph with this title
        for para_title, sentences in context:
            if para_title == title and sent_idx < len(sentences):
                gold_sentences.append(sentences[sent_idx])
                break
    
    return gold_sentences


def calculate_recall(retrieved_sentences, gold_sentences):
    """Calculate recall: proportion of gold sentences in retrieved sentences."""
    if not gold_sentences:
        return 0.0
    
    # Normalize sentences for comparison
    retrieved_set = set(normalize_answer(s) for s in retrieved_sentences)
    gold_set = set(normalize_answer(s) for s in gold_sentences)
    
    intersection = gold_set & retrieved_set
    return len(intersection) / len(gold_set) if gold_set else 0.0


#%%
predictions = {}

for i in range(TRAIN_SAMPLE_SIZE):
    example = TRAIN_DATASET[i]
    question = example["question"]
    gold_answer = example["answer"]
    gold_supporting_facts = example["supporting_facts"]
    context = example["context"]
    example_id = example["_id"]
    
    if METHOD == "decomposition":
        # Run decomposition pipeline
        full_output = run_decomposition(question, MODEL, RETRIEVER, context)
        
        # Extract results
        answer = full_output["answer"]
        subqueries = full_output["subqueries"]
        retrieved_sentences = full_output["retrieved_sentences"]
        
        # Extract gold sentences
        gold_sentences = extract_gold_sentences(example)
        
        # Calculate metrics
        f1 = f1_score(answer, gold_answer)
        correct = 1 if f1 > 0.5 else 0
        recall = calculate_recall(retrieved_sentences, gold_sentences)
        
        # Build result dict in specified order
        result = {
            "question": question,
            "answer": answer,
            "gold_answer": gold_answer,
            "correct": correct,
            "recall": recall,
            "subqueries": subqueries,
            "retrieved_sentences": retrieved_sentences,
            "gold_sentences": gold_sentences,
        }
        
        # Add to predictions dict with _id as key
        predictions[example_id] = result
        
        # Save periodically
        if (i + 1) % SAVE_FREQUENCY == 0:
            with open(PREDICTIONS_PATH, 'w') as f:
                json.dump(predictions, f, indent=2)
            print(f"Saved predictions after {i + 1} examples")

# Save final predictions
with open(PREDICTIONS_PATH, 'w') as f:
    json.dump(predictions, f, indent=2)
print(f"Final predictions saved to {PREDICTIONS_PATH}")
