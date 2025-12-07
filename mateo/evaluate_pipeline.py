#%%
import sys
from pathlib import Path

# Add workspace root to Python path for notebook execution
# Try to find the workspace root (parent of mateo directory)
try:
    # If running as script, use __file__
    workspace_root = Path(__file__).parent.parent
except NameError:
    # If running in notebook, search upward from current directory
    current = Path.cwd()
    while current != current.parent:
        if (current / "mateo").exists() and (current / "mateo" / "__init__.py").exists():
            workspace_root = current
            break
        current = current.parent
    else:
        # Fallback: assume we're in workspace root or one level down
        workspace_root = Path.cwd() if (Path.cwd() / "mateo").exists() else Path.cwd().parent

if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

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
TRAIN_DATASET = load_dataset("hotpot_qa", "distractor", split="train")

#%%
TRAIN_SAMPLE_SIZE = 28000
DEV_SAMPLE_SIZE = 7000
TEST_SAMPLE_SIZE = 7000
SAVE_FREQUENCY = 10
METHOD = "decomposition"
PREDICTIONS_PATH = f"{METHOD}_predictions.json"
DATASET_PATH = f"{METHOD}_dataset.json"

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
    context_raw = example.get("context", [])
    supporting_facts_raw = example.get("supporting_facts", [])
    
    gold_sentences = []
    
    # Normalize context format - handle dict format from hotpot_qa dataset
    if isinstance(context_raw, dict):
        # Format: {'title': [...], 'sentences': [[...], [...]]}
        normalized_context = list(zip(context_raw['title'], context_raw['sentences']))
    elif isinstance(context_raw, list):
        # Already in list format
        normalized_context = []
        for item in context_raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                title = item[0]
                sentences = item[1]
                # Ensure sentences is a list
                if not isinstance(sentences, list):
                    sentences = list(sentences) if hasattr(sentences, '__iter__') else [str(sentences)]
                normalized_context.append((title, sentences))
    else:
        normalized_context = []
    
    # Normalize supporting_facts format - handle dict format from hotpot_qa dataset
    if isinstance(supporting_facts_raw, dict):
        # Format: {'title': [...], 'sent_id': [...]}
        supporting_facts = list(zip(supporting_facts_raw['title'], supporting_facts_raw['sent_id']))
    elif isinstance(supporting_facts_raw, list):
        # Already in list format
        supporting_facts = supporting_facts_raw
    else:
        supporting_facts = []
    
    # Process supporting facts
    for sp in supporting_facts:
        if isinstance(sp, (list, tuple)) and len(sp) >= 2:
            title = sp[0]
            sent_idx = sp[1]
            
            # Find the paragraph with this title
            for para_title, sentences in normalized_context:
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
    context_raw = example["context"]
    example_id = example["id"]
    
    # Normalize context format - handle dict format from hotpot_qa dataset
    if isinstance(context_raw, dict):
        # Format: {'title': [...], 'sentences': [[...], [...]]}
        context = list(zip(context_raw['title'], context_raw['sentences']))
    elif isinstance(context_raw, list):
        # Already in list format
        context = context_raw
    else:
        context = []
    
    if METHOD == "decomposition":
        # Run decomposition pipeline
        full_output = run_decomposition(question, MODEL, RETRIEVER, context)
        
        # Extract results
        answer = full_output["answer"]
        subqueries = full_output["subqueries"]  # Dictionary mapping subquery -> retrieved sentences
        
        # Extract gold sentences
        gold_sentences = extract_gold_sentences(example)
        
        # Calculate metrics - get all retrieved sentences from subqueries for recall calculation
        all_retrieved_sentences = []
        for retrieved_sents in subqueries.values():
            all_retrieved_sentences.extend(retrieved_sents)
        # Deduplicate
        all_retrieved_sentences = list(dict.fromkeys(all_retrieved_sentences))  # Preserves order while removing duplicates
        
        f1 = f1_score(answer, gold_answer)
        correct = 1 if f1 > 0.5 else 0
        recall = calculate_recall(all_retrieved_sentences, gold_sentences)
        
        # Build result dict in specified order
        result = {
            "question": question,
            "answer": answer,
            "gold_answer": gold_answer,
            "correct": correct,
            "recall": recall,
            "subqueries": subqueries,  # Dictionary: subquery -> list of retrieved sentences
            "gold_sentences": gold_sentences,
        }
        
        # Add to predictions dict with _id as key
        predictions[example_id] = result
        
        # Save periodically
        if (i + 1) % SAVE_FREQUENCY == 0:
            with open(DATASET_PATH, 'w') as f:
                json.dump(predictions, f, indent=2)
            print(f"Saved predictions after {i + 1} examples")

# Save final predictions
with open(DATASET_PATH, 'w') as f:
    json.dump(predictions, f, indent=2)
print(f"Final predictions saved to {DATASET_PATH}")

# %%
