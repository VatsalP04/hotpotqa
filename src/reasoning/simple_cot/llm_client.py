from typing import Optional, Sequence
from abc import ABC, abstractmethod
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

try:
    from transformer_lens import HookedTransformer
except ImportError:
    HookedTransformer = None


class LLMClient(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        pass


class TransformerLensLLMClient(LLMClient):
    def __init__(
        self,
        model_name: str = "meta-llama/Llama-3.1-8B-Instruct",
        device: Optional[str] = None
    ):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        
        self.device = device
        self.model_name = model_name
        
        print(f"Loading model {model_name} for text generation...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map=device if device == "cuda" else None
        )
        if device == "cpu":
            self.model = self.model.to(device)
        self.model.eval()
        print(f"Model loaded on {device}")

    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
        
        formatted_prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        inputs = self.tokenizer(
            formatted_prompt,
            return_tensors="pt",
            truncation=True,
            max_length=2048
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature if temperature > 0 else None,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id
            )
        
        generated_text = self.tokenizer.decode(
            outputs[0][inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )
        
        if stop:
            for stop_seq in stop:
                idx = generated_text.find(stop_seq)
                if idx != -1:
                    generated_text = generated_text[:idx]
                    break
        
        return generated_text.strip()


class HookedTransformerLLMClient(LLMClient):
    """LLMClient that uses HookedTransformer for both generation and activation extraction."""
    
    def __init__(
        self,
        model: HookedTransformer,
    ):
        if HookedTransformer is None:
            raise ImportError("transformer_lens is required. Install with: pip install transformer-lens")
        
        self.model = model
        self.tokenizer = model.tokenizer  # Use HookedTransformer's tokenizer
        
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
    
    def generate(
        self,
        prompt: str,
        max_new_tokens: int,
        temperature: float = 0.0,
        stop: Optional[Sequence[str]] = None,
    ) -> str:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
        
        formatted_prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        inputs = self.tokenizer(
            formatted_prompt,
            return_tensors="pt",
            truncation=True,
            max_length=2048
        ).to(self.model.cfg.device)
        
        # Clear cache before generation to free memory
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        with torch.no_grad():
            # HookedTransformer.generate has a different API than AutoModelForCausalLM
            # It doesn't support pad_token_id or eos_token_id parameters
            outputs = self.model.generate(
                inputs.input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature if temperature > 0 else 1.0,
                do_sample=temperature > 0,
                verbose=False
            )
        
        generated_text = self.tokenizer.decode(
            outputs[0][inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )
        
        # Clear tensors to free memory
        del inputs, outputs
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        if stop:
            for stop_seq in stop:
                idx = generated_text.find(stop_seq)
                if idx != -1:
                    generated_text = generated_text[:idx]
                    break
        
        return generated_text.strip()

