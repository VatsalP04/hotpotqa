from typing import List, Dict, Any, Optional
from src.reasoning.ircot.retriever import Paragraph, InMemoryRetriever
from .llm_client import LLMClient, TransformerLensLLMClient
from .prompts import build_cot_prompt, build_answer_prompt
import re
import os
from mistralai import Mistral


def build_paragraphs_from_example(example: Dict[str, Any]) -> List[Paragraph]:
    paragraphs = []
    context = example.get('context', [])
    for idx, (title, sentences) in enumerate(context):
        text = " ".join(sentences) if isinstance(sentences, list) else str(sentences)
        paragraphs.append(Paragraph(pid=idx, title=title, text=text))
    return paragraphs


def build_paragraphs_from_examples(examples: List[Dict[str, Any]]) -> List[Paragraph]:
    all_paragraphs = []
    seen_paragraphs = set()
    
    for example in examples:
        context = example.get('context', [])
        for title, sentences in context:
            text = " ".join(sentences) if isinstance(sentences, list) else str(sentences)
            paragraph_key = (title, text)
            if paragraph_key not in seen_paragraphs:
                seen_paragraphs.add(paragraph_key)
                all_paragraphs.append(Paragraph(pid=len(all_paragraphs), title=title, text=text))
    
    return all_paragraphs


class SimpleCoT:
    def __init__(
        self,
        retriever: Optional[InMemoryRetriever] = None,
        llm_client: Optional[LLMClient] = None,
        retrieval_k: int = 3,
        model_name: str = "meta-llama/Llama-3.1-8B-Instruct",
        paragraphs: Optional[List[Paragraph]] = None,
        mistral_api_key: Optional[str] = None
    ):
        if retriever is None:
            if paragraphs is None:
                raise ValueError("Either retriever or paragraphs must be provided")
            
            api_key = mistral_api_key or os.environ.get("MISTRAL_API_KEY")
            if not api_key:
                raise ValueError("MISTRAL_API_KEY must be provided or set in environment")
            
            mistral_client = Mistral(api_key=api_key)
            self.retriever = InMemoryRetriever(paragraphs, mistral_client)
        else:
            self.retriever = retriever
        
        if llm_client is None:
            self.llm_client = TransformerLensLLMClient(model_name=model_name)
        else:
            self.llm_client = llm_client
        self.retrieval_k = retrieval_k

    def retrieve(self, question: str) -> List[Paragraph]:
        return self.retriever.retrieve(question, top_k=self.retrieval_k)

    def generate_chain_of_thought(self, paragraphs: List[Paragraph], question: str) -> str:
        prompt = build_cot_prompt(paragraphs, question)
        cot = self.llm_client.generate(
            prompt=prompt,
            max_new_tokens=512,
            temperature=0.7
        )
        return cot.strip()

    def generate_answer(self, paragraphs: List[Paragraph], question: str, chain_of_thought: str) -> str:
        prompt = build_answer_prompt(paragraphs, question, chain_of_thought)
        answer = self.llm_client.generate(
            prompt=prompt,
            max_new_tokens=50,
            temperature=0.0
        )
        answer = answer.strip()
        
        answer = self._clean_answer(answer)
        return answer

    def _clean_answer(self, answer: str) -> str:
        answer = answer.strip()
        answer = re.sub(r'^[Aa]nswer:\s*', '', answer)
        answer = re.sub(r'^[Tt]he answer is\s*', '', answer)
        answer = re.sub(r'^[Ii]t is\s*', '', answer)
        answer = answer.strip()
        
        if answer.lower() in ['yes', 'no']:
            return answer.lower()
        
        return answer

    def process(self, question: str) -> Dict[str, Any]:
        paragraphs = self.retrieve(question)
        chain_of_thought = self.generate_chain_of_thought(paragraphs, question)
        answer = self.generate_answer(paragraphs, question, chain_of_thought)
        
        return {
            'question': question,
            'retrieved_paragraphs': paragraphs,
            'chain_of_thought': chain_of_thought,
            'answer': answer
        }

