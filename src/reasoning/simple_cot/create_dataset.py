#%%
# Setup Python Path
import sys
from pathlib import Path

# Add project root to path so we can import src modules
try:
    project_root = Path(__file__).parent.parent.parent.parent
except NameError:
    project_root = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

#%%
# Imports and Setup
import os
import csv
import pandas as pd
from tqdm import tqdm
from typing import Literal
import src.config

from src.data.loader import load_hotpotqa
from src.reasoning.simple_cot.simple_cot import SimpleCoT, build_paragraphs_from_example
from src.reasoning.simple_cot.utils import f1_score, calculate_recall
from src.reasoning.simple_cot.prompts import build_answer_prompt

#%%
# Configuration
MODEL_TYPE: Literal["llama", "mistral"] = "mistral"  # Change to "mistral" to use Mistral API
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"  # For Llama
MISTRAL_MODEL = "ministral-8b-2512"  # For Mistral (similar size to Llama 8B)

DATA_DIR = str(project_root / "data" / "hotpotqa")
TRAIN_SIZE = 28000
VAL_SIZE = 7000
OUTPUT_DIR = str(project_root / "outputs" / "simple_cot")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TRAIN_CSV_PATH = os.path.join(OUTPUT_DIR, "train_dataset.csv")
VAL_CSV_PATH = os.path.join(OUTPUT_DIR, "val_dataset.csv")

#%%
# Load Data
print("Loading data...")
train_data_raw = load_hotpotqa(DATA_DIR, split="train", max_examples=TRAIN_SIZE + VAL_SIZE, shuffle=True)

train_examples_raw = train_data_raw[:TRAIN_SIZE]
val_examples_raw = train_data_raw[TRAIN_SIZE:TRAIN_SIZE + VAL_SIZE]

print(f"Loaded {len(train_examples_raw)} train and {len(val_examples_raw)} val examples")

#%%
# Setup Model/LLM Client
if MODEL_TYPE == "llama":
    print(f"\nLoading Llama model: {MODEL_NAME}")
    from transformer_lens import HookedTransformer
    import torch
    
    model = HookedTransformer.from_pretrained(MODEL_NAME, device="cuda" if torch.cuda.is_available() else "cpu")
    model.eval()
    
    from src.reasoning.simple_cot.llm_client import HookedTransformerLLMClient
    llm_client = HookedTransformerLLMClient(model=model)
    print("Using HookedTransformer for generation")
    
elif MODEL_TYPE == "mistral":
    print(f"\nUsing Mistral API with model: {MISTRAL_MODEL}")
    from src.reasoning.ircot.llm_client import MistralLLMClient
    from src.models.mistral_client import get_mistral_client
    
    mistral_client = get_mistral_client()
    mistral_client.model = MISTRAL_MODEL
    llm_client = MistralLLMClient(client=mistral_client)
    print("Using Mistral API for generation")
else:
    raise ValueError(f"Unknown MODEL_TYPE: {MODEL_TYPE}")

#%%
# Create Dataset Function
def create_dataset_csv(examples: list, output_path: str, split_name: str, target_size: int):
    """Create or resume CSV dataset with full text sequences and labels.
    
    If CSV exists, resumes from where it left off. Continues until target_size rows are reached.
    """
    print(f"\nCreating {split_name} dataset...")
    
    # Check if CSV exists and how many rows we have
    start_idx = 0
    file_exists = os.path.exists(output_path) and os.path.getsize(output_path) > 0
    
    if file_exists:
        try:
            existing_df = pd.read_csv(output_path, on_bad_lines='skip', engine='python')
            start_idx = len(existing_df)
            print(f"Found existing CSV with {start_idx} rows. Resuming from index {start_idx}...")
            
            # If we already have enough rows, we're done
            if start_idx >= target_size:
                print(f"Dataset already complete with {start_idx} rows (target: {target_size})")
                return existing_df
        except Exception as e:
            print(f"Warning: Could not read existing CSV ({e}). Starting from scratch.")
            start_idx = 0
            file_exists = False
    
    # Determine how many examples we need to process
    remaining = target_size - start_idx
    if remaining <= 0:
        print(f"Dataset already complete!")
        return pd.read_csv(output_path, on_bad_lines='skip', engine='python')
    
    print(f"Processing {remaining} examples (from index {start_idx} to {target_size - 1})...")
    
    # Process examples starting from start_idx
    rows = []
    examples_to_process = examples[start_idx:target_size]
    SAVE_INTERVAL = 50  # Save to CSV every N questions
    
    for local_idx, ex in tqdm(enumerate(examples_to_process), total=len(examples_to_process), desc=f"Processing {split_name}"):
        actual_idx = start_idx + local_idx
        
        question = ex['question']
        gold_answer = ex['answer']
        gold_supporting_facts = ex.get('supporting_facts', [])
        
        # Build paragraphs from this example's context only
        example_paragraphs = build_paragraphs_from_example(ex)
        
        # Create SimpleCoT instance
        simple_cot = SimpleCoT(
            model_name=MODEL_NAME if MODEL_TYPE == "llama" else None,
            paragraphs=example_paragraphs,
            llm_client=llm_client
        )
        
        # Process question to get chain of thought and answer
        result = simple_cot.process(question)
        
        # Compute correctness label
        f1, _, _ = f1_score(result['answer'], gold_answer)
        correct = 1 if f1 >= 0.5 else 0
        
        # Compute recall
        recall = calculate_recall(result['retrieved_paragraphs'], gold_supporting_facts)
        
        # Build full text: prompt + answer
        prompt = build_answer_prompt(result['retrieved_paragraphs'], question, result['chain_of_thought'])
        full_text = prompt + " " + result['answer']
        
        # Extract gold sentences
        gold_sentences = []
        for fact in gold_supporting_facts:
            if len(fact) >= 2:
                title = fact[0]
                sent_idx = fact[1]
                for para in ex.get('context', []):
                    if len(para) >= 2 and para[0] == title and sent_idx < len(para[1]):
                        gold_sentences.append(para[1][sent_idx])
        
        # Format retrieved paragraphs
        retrieved_titles = [p.title for p in result['retrieved_paragraphs']]
        retrieved_texts = [p.text for p in result['retrieved_paragraphs']]
        
        # Create row
        row = {
            'question': question,
            'full_text': full_text,
            'prompt': prompt,
            'answer': result['answer'],
            'gold_answer': gold_answer,
            'correct': correct,
            'f1_score': f1,
            'recall': recall,
            'chain_of_thought': result['chain_of_thought'],
            'retrieved_titles': ' | '.join(retrieved_titles),
            'retrieved_texts': ' | '.join(retrieved_texts),
            'gold_sentences': ' | '.join(gold_sentences),
            'example_idx': actual_idx
        }
        
        rows.append(row)
        
        # Clear memory
        del simple_cot, result, example_paragraphs
        
        # Save to CSV every SAVE_INTERVAL questions
        if len(rows) >= SAVE_INTERVAL:
            new_df = pd.DataFrame(rows)
            
            if file_exists:
                # Append to existing CSV
                new_df.to_csv(output_path, mode='a', header=False, index=False, quoting=csv.QUOTE_ALL)
            else:
                # Create new CSV (first time)
                new_df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL)
                file_exists = True  # Mark as existing for future appends
            
            print(f"  Saved {len(rows)} examples to CSV (total so far: {start_idx + len(rows)})")
            rows = []  # Clear accumulated rows
    
    # Save any remaining rows at the end
    if rows:
        new_df = pd.DataFrame(rows)
        
        if file_exists:
            # Append to existing CSV
            new_df.to_csv(output_path, mode='a', header=False, index=False, quoting=csv.QUOTE_ALL)
            print(f"  Saved final {len(rows)} examples to CSV")
        else:
            # Create new CSV (if we had fewer than SAVE_INTERVAL total)
            new_df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL)
            print(f"  Created CSV with {len(rows)} examples")
    
    # Read full dataset to return
    if os.path.exists(output_path):
        full_df = pd.read_csv(output_path, on_bad_lines='skip', engine='python')
        print(f"Total rows in dataset: {len(full_df)} (target: {target_size})")
        print(f"  Correct: {full_df['correct'].sum()}, Incorrect: {(full_df['correct'] == 0).sum()}")
        return full_df
    else:
        return pd.DataFrame()

#%%
# Create Training Dataset
# Will resume from existing CSV if it exists, continue until TRAIN_SIZE rows
train_df = create_dataset_csv(train_examples_raw, TRAIN_CSV_PATH, "train", target_size=TRAIN_SIZE)

#%%
# Create Validation Dataset
# Will resume from existing CSV if it exists, continue until VAL_SIZE rows
val_df = create_dataset_csv(val_examples_raw, VAL_CSV_PATH, "val", target_size=VAL_SIZE)

#%%
print("\nDataset creation complete!")
print(f"Training dataset: {TRAIN_CSV_PATH}")
print(f"Validation dataset: {VAL_CSV_PATH}")

