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
from typing import Literal, Tuple, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import src.config

from src.data.loader import load_hotpotqa
from src.reasoning.simple_cot.simple_cot import SimpleCoT, build_paragraphs_from_example
from src.reasoning.simple_cot.utils import f1_score, calculate_recall
from src.reasoning.simple_cot.prompts import build_answer_prompt

#%%
# Configuration
MODEL_TYPE: Literal["llama", "mistral"] = "llama"  # Change to "mistral" to use Mistral API
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"  # For Llama
MISTRAL_MODEL = "ministral-8b-2512"  # For Mistral (similar size to Llama 8B)

DATA_DIR = str(project_root / "data" / "hotpotqa")
TRAIN_SIZE = 28000
VAL_SIZE = 7000
OUTPUT_DIR = str(project_root / "outputs" / "simple_cot")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TRAIN_CSV_PATH = os.path.join(OUTPUT_DIR, "train_dataset.csv")
VAL_CSV_PATH = os.path.join(OUTPUT_DIR, "val_dataset.csv")

# Performance settings
USE_PARALLEL = (MODEL_TYPE == "mistral")  # parallel only for API model
MAX_WORKERS = 5  # Number of parallel workers (adjust based on API rate limits)
SAVE_INTERVAL = 10  # Save to CSV every N questions (small for frequent incremental saves)
RETRIEVAL_K = 3  # Number of paragraphs to retrieve (matches SimpleCoT default)

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
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = HookedTransformer.from_pretrained(
        MODEL_NAME,
        device=device,
        dtype="bfloat16" if device == "cuda" else "float32",
    )
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
# Helper function to process a single example
def process_single_example(
    args: Tuple[int, Dict[str, Any], Any, int]
) -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    """
    Process a single example.
    
    Args:
        args: Tuple of (index, example, llm_client, retrieval_k)
        
    Returns:
        Tuple of (index, row_dict, error_message)
    """
    idx, ex, shared_llm_client, retrieval_k = args
    
    try:
        question = ex['question']
        gold_answer = ex['answer']
        gold_supporting_facts = ex.get('supporting_facts', [])
        
        # Build paragraphs from this example's context only
        example_paragraphs = build_paragraphs_from_example(ex)
        
        # Create SimpleCoT instance (each example has different paragraphs, so we need a new one)
        # But we reuse the LLM client which is thread-safe for API calls
        simple_cot = SimpleCoT(
            model_name=MODEL_NAME if MODEL_TYPE == "llama" else None,
            paragraphs=example_paragraphs,
            llm_client=shared_llm_client,
            retrieval_k=retrieval_k
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
        
        # Helper function to remove newlines and normalize whitespace
        def sanitize_text(text):
            """Remove newlines and normalize whitespace in text fields"""
            if text is None:
                return ""
            if isinstance(text, str):
                # Replace newlines and carriage returns with spaces
                text = text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
                # Normalize multiple spaces to single space
                text = ' '.join(text.split())
                return text
            return str(text)
        
        # Create row with sanitized text fields
        row = {
            'question': sanitize_text(question),
            'full_text': sanitize_text(full_text),
            'prompt': sanitize_text(prompt),
            'answer': sanitize_text(result['answer']),
            'gold_answer': sanitize_text(gold_answer),
            'correct': correct,
            'f1_score': f1,
            'recall': recall,
            'chain_of_thought': sanitize_text(result['chain_of_thought']),
            'retrieved_titles': sanitize_text(' | '.join(retrieved_titles)),
            'retrieved_texts': sanitize_text(' | '.join(retrieved_texts)),
            'gold_sentences': sanitize_text(' | '.join(gold_sentences)),
            'example_idx': idx
        }
        
        return (idx, row, None)
        
    except Exception as e:
        return (idx, None, str(e))

#%%
# Create Dataset Function
def create_dataset_csv(examples: list, output_path: str, split_name: str, target_size: int, llm_client: Any):
    """Create or resume CSV dataset with full text sequences and labels.
    
    If CSV exists, resumes from where it left off. Continues until target_size rows are reached.
    Now with parallel processing support.
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
    
    if USE_PARALLEL:
        print(f"Using {MAX_WORKERS} parallel workers for faster processing...")
        print("Note: With parallel processing, CSV saves happen when consecutive rows are ready.")
        print("      All results will be saved when processing completes.")
    else:
        print("Processing sequentially (parallel processing disabled)...")
        print("Note: Sequential mode saves incrementally every {} examples.".format(SAVE_INTERVAL))
    
    # Process examples starting from start_idx
    examples_to_process = examples[start_idx:target_size]
    total_to_process = len(examples_to_process)
    
    if USE_PARALLEL:
        # PARALLEL PROCESSING MODE
        # Thread-safe collections for tracking progress
        results_lock = threading.Lock()
        processed_count = 0
        error_count = 0
        
        # Prepare arguments for parallel processing
        task_args = [
            (start_idx + local_idx, ex, llm_client, RETRIEVAL_K)
            for local_idx, ex in enumerate(examples_to_process)
        ]
        
        # Process with ThreadPoolExecutor
        # Use dict to store results as they complete (out of order is OK)
        all_results = {}  # Dict: idx -> row
        last_saved_idx = start_idx - 1  # Track the last index we've saved
        last_save_check = 0  # Track when we last checked for saves
        
        def save_ready_results():
            """Save consecutive rows that are ready, in sorted order"""
            nonlocal last_saved_idx, file_exists
            
            # Find consecutive rows starting from last_saved_idx + 1
            rows_to_save = []
            next_idx = last_saved_idx + 1
            
            while next_idx in all_results:
                rows_to_save.append(all_results.pop(next_idx))
                next_idx += 1
            
            # Save ANY consecutive rows we have IMMEDIATELY (don't wait for batches)
            # This ensures progress is saved even if results come in out of order
            if len(rows_to_save) > 0:
                # Save all consecutive rows we have, batching for efficiency
                batch_size = min(SAVE_INTERVAL, len(rows_to_save))
                batch = rows_to_save[:batch_size]
                new_df = pd.DataFrame(batch)
                
                if file_exists:
                    new_df.to_csv(output_path, mode='a', header=False, index=False, quoting=csv.QUOTE_ALL)
                else:
                    new_df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL)
                    file_exists = True
                
                last_saved_idx += len(batch)
                total_saved = last_saved_idx - start_idx + 1
                print(f"  ✓ Saved {len(batch)} examples to CSV (total so far: {total_saved})")
                
                # Put back any remaining rows that didn't get saved this time
                remaining = rows_to_save[batch_size:]
                if remaining:
                    for j, row in enumerate(remaining):
                        all_results[last_saved_idx + 1 + j] = row
                
                # Continue saving if we have more consecutive rows
                if len(remaining) >= SAVE_INTERVAL:
                    # Recursively save more consecutive rows
                    save_ready_results()
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all tasks
            future_to_idx = {
                executor.submit(process_single_example, args): args[0]
                for args in task_args
            }
            
            # Process results as they complete
            pbar = tqdm(total=total_to_process, desc=f"Processing {split_name}")
            
            for future in as_completed(future_to_idx):
                idx, row, error = future.result()
                
                with results_lock:
                    processed_count += 1
                    
                    if error:
                        error_count += 1
                        print(f"\nError processing example {idx}: {error}")
                    else:
                        # Store result
                        all_results[idx] = row
                        
                        # Try to save every time we get a result (maximum frequency)
                        save_ready_results()
                        last_save_check = processed_count
                        
                        # Debug: Show status every 50 examples
                        if processed_count % 50 == 0:
                            min_idx = min(all_results.keys()) if all_results else None
                            max_idx = max(all_results.keys()) if all_results else None
                            print(f"\n  Status: {processed_count} processed, {len(all_results)} unsaved, last_saved_idx={last_saved_idx}, min_idx={min_idx}, max_idx={max_idx}")
                    
                    # Update progress bar
                    pbar.update(1)
                    
                    # Calculate and display ETA
                    if processed_count % 10 == 0 and processed_count > 0:
                        elapsed = pbar.format_dict['elapsed']
                        if elapsed and processed_count > 0:
                            rate = processed_count / elapsed
                            remaining_examples = total_to_process - processed_count
                            eta_seconds = remaining_examples / rate if rate > 0 else 0
                            eta_hours = eta_seconds / 3600
                            pbar.set_postfix({
                                'errors': error_count,
                                'ETA': f"{eta_hours:.2f}h" if eta_hours >= 1 else f"{eta_seconds/60:.1f}m"
                            })
            
            pbar.close()
        
        # Save any remaining consecutive rows at the end
        # Keep saving until no more consecutive rows are available
        while True:
            rows_to_save_final = []
            next_idx = last_saved_idx + 1
            
            # Collect consecutive rows starting from last_saved_idx + 1
            while next_idx in all_results:
                rows_to_save_final.append(all_results.pop(next_idx))
                next_idx += 1
            
            if rows_to_save_final:
                new_df = pd.DataFrame(rows_to_save_final)
                
                if file_exists:
                    new_df.to_csv(output_path, mode='a', header=False, index=False, quoting=csv.QUOTE_ALL)
                else:
                    new_df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL)
                    file_exists = True
                
                last_saved_idx += len(rows_to_save_final)
                total_saved = last_saved_idx - start_idx + 1
                print(f"  Saved final {len(rows_to_save_final)} examples to CSV (total: {total_saved})")
            else:
                # No more consecutive rows, break
                break
        
        # Report summary
        total_results = len(all_results) + (last_saved_idx - start_idx + 1) if last_saved_idx >= start_idx else len(all_results)
        print(f"\nProcessing complete. Results collected: {total_results}, Errors: {error_count}")
        
        # Report any unsaved results (due to gaps from errors)
        if all_results:
            print(f"Warning: {len(all_results)} examples could not be saved due to gaps (missing earlier indices)")
            unsaved_indices = sorted(all_results.keys())
            print(f"  Unsaved indices (first 10): {unsaved_indices[:10]}{'...' if len(unsaved_indices) > 10 else ''}")
            print(f"  Last saved index: {last_saved_idx}, First unsaved index: {min(unsaved_indices)}")
        
        if error_count > 0:
            print(f"Warning: {error_count} examples had processing errors")
    
    else:
        # SEQUENTIAL PROCESSING MODE (original behavior)
        rows = []
        error_count = 0
        
        for local_idx, ex in tqdm(enumerate(examples_to_process), total=len(examples_to_process), desc=f"Processing {split_name}"):
            actual_idx = start_idx + local_idx
            
            try:
                # Process example using the helper function
                idx, row, error = process_single_example((actual_idx, ex, llm_client, RETRIEVAL_K))
                
                if error:
                    error_count += 1
                    print(f"\nError processing example {idx}: {error}")
                    continue
                
                rows.append(row)
                
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
            
            except Exception as e:
                error_count += 1
                print(f"\nError processing example {actual_idx}: {e}")
                continue
        
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
        
        if error_count > 0:
            print(f"Warning: {error_count} examples had processing errors")
    
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
train_df = create_dataset_csv(train_examples_raw, TRAIN_CSV_PATH, "train", target_size=TRAIN_SIZE, llm_client=llm_client)

#%%
# Create Validation Dataset
# Will resume from existing CSV if it exists, continue until VAL_SIZE rows
val_df = create_dataset_csv(val_examples_raw, VAL_CSV_PATH, "val", target_size=VAL_SIZE, llm_client=llm_client)

#%%
print("\nDataset creation complete!")
print(f"Training dataset: {TRAIN_CSV_PATH}")
print(f"Validation dataset: {VAL_CSV_PATH}")
