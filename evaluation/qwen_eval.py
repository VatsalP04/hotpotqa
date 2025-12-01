# %% Setup paths and imports
import sys
import gc
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1] if "__file__" in dir() else Path.cwd().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.loader import load_hotpotqa
from src.reasoning.ircot import MistralLLMClient
from evaluation.run_evaluation_pipeline import run_evaluation

# %% Load data

MAX_EXAMPLES = 50

dev_data = load_hotpotqa(
    data_dir=PROJECT_ROOT / "data/hotpotqa",
    split="dev",
    max_examples=MAX_EXAMPLES,
    shuffle=False
)
print(f"Loaded {len(dev_data)} examples")

# %% Initialize Mistral (embeddings only)
mistral = MistralLLMClient()

# %% Load Qwen with TransformerLens
from transformer_lens import HookedTransformer

torch.cuda.empty_cache()
gc.collect()

model_name = "Qwen/Qwen2.5-1.5B-Instruct"
model = HookedTransformer.from_pretrained(model_name, device="cuda", dtype=torch.float16)
model.eval()
tokenizer = model.tokenizer
print(f"Loaded {model_name}, VRAM: {torch.cuda.memory_allocated()/1e9:.2f} GB")


# %% Define LLM wrapper
class QwenLLM:
    def generate(self, prompt, max_new_tokens, temperature=0.0, stop=None):
        messages = [{"role": "user", "content": prompt}]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        input_ids = tokenizer.encode(text, return_tensors="pt", truncation=True, max_length=2048).to("cuda")
        
        with torch.no_grad():
            out = model.generate(
                input_ids,
                max_new_tokens=max_new_tokens,
                stop_at_eos=True,
                do_sample=temperature > 0.01,
                temperature=temperature if temperature > 0.01 else None,
            )
        
        result = tokenizer.decode(out[0, input_ids.shape[1]:], skip_special_tokens=True)
        
        if stop:
            for s in stop:
                if s in result:
                    result = result[:result.find(s)]
        
        del input_ids, out
        torch.cuda.empty_cache()
        return result.strip()


qwen = QwenLLM()

# %% Run evaluation
predictions, csv_rows = run_evaluation(
    llm=qwen,
    embedder_client=mistral,
    dev_data=dev_data,
    method="decomposition",
    top_k_paragraphs=2,
    output_path=PROJECT_ROOT / "predictions_qwen.json",
    csv_path=PROJECT_ROOT / "results_qwen.csv",
)

# %% Summary
correct = sum(1 for r in csv_rows if r.get('correct') == 1)
print(f"\nAccuracy: {correct}/{len(csv_rows)} = {correct/len(csv_rows):.1%}")

