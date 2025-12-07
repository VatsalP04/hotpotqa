import re
import torch
from typing import List, Tuple, Dict, Any
from mateo.decomposition.prompts import build_planning_prompt, build_subanswer_prompt, build_final_answer_prompt
from mateo.decomposition.retrieve import retrieve_top_paragraphs, paragraphs_to_sentences


def clean_text(text: str) -> str:
    """Clean text by removing newlines and normalizing whitespace."""
    if not text:
        return ""
    # Remove newlines and normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def parse_subqueries(response: str) -> List[str]:
    """
    Parse numbered subqueries from model response.
    Extracts text between numbered items (e.g., between "1." and "2.").
    More robust parsing that handles various formats.
    """
    subqueries = []
    lines = response.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # First, try to split on numbered patterns if multiple subqueries are on one line
        # Pattern: "1. text 2. text 3. text" -> split into separate items
        numbered_items = re.split(r'\s+(\d+[.\)])\s+', line)
        
        if len(numbered_items) > 1:
            # Multiple numbered items on one line - process each
            current_item = numbered_items[0].strip()
            for i in range(1, len(numbered_items), 2):
                # Save previous item if valid
                if current_item and len(current_item) > 5:
                    cleaned = _clean_subquery_text(current_item)
                    if cleaned:
                        subqueries.append(cleaned)
                
                # Start new item (skip the number, take the text)
                if i + 1 < len(numbered_items):
                    current_item = numbered_items[i + 1].strip()
                else:
                    current_item = ""
            
            # Don't forget the last item
            if current_item and len(current_item) > 5:
                cleaned = _clean_subquery_text(current_item)
                if cleaned:
                    subqueries.append(cleaned)
        else:
            # Single item on line - process normally
            # Remove leading numbers/bullets (e.g., "1.", "1)", "-", "•")
            cleaned = re.sub(r'^[\d]+[.\)]\s*', '', line)
            cleaned = re.sub(r'^[-•]\s*', '', cleaned)
            cleaned = _clean_subquery_text(cleaned)
            if cleaned:
                subqueries.append(cleaned)
    
    return subqueries


def _clean_subquery_text(text: str) -> str:
    """Clean and validate subquery text."""
    if not text:
        return ""
    
    text = text.strip()
    
    # Remove any trailing special tokens or formatting
    text = re.sub(r'\s*<\|.*?\|>\s*$', '', text)
    text = re.sub(r'\s*<end_of_turn>\s*$', '', text)
    text = re.sub(r'\s*<eos>\s*$', '', text)
    text = text.strip()
    
    # Skip if it's a label like "Sub-questions:" or empty after cleaning
    # Also skip if it's too short (likely not a real question)
    if not text or text.endswith(':') or len(text) <= 5:
        return ""
    
    # Check if it looks like a question (contains question mark or [ANSWER_X] placeholder)
    if '?' in text or '[ANSWER_' in text:
        return text
    
    # Also accept if it's a reasonable length and doesn't look like metadata
    if len(text) > 10 and not text.lower().startswith(('example', 'note', 'important', 'output', 'q:', 'question')):
        return text
    
    return ""


def fill_placeholders(subquery: str, answers: List[str]) -> str:
    """Fill [ANSWER_1], [ANSWER_2], etc. placeholders with actual answers."""
    filled = subquery
    for i, answer in enumerate(answers, 1):
        placeholder = f"[ANSWER_{i}]"
        filled = filled.replace(placeholder, answer)
    return filled


def generate_text(model, prompt: str, max_new_tokens: int = 512, temperature: float = 0.0) -> str:
    """
    Generate text from HookedTransformer model.
    
    Args:
        model: HookedTransformer model
        prompt: Input prompt string
        max_new_tokens: Maximum number of tokens to generate
        temperature: Sampling temperature (0.0 for deterministic)
        
    Returns:
        Generated text string
    """
    tokenizer = model.tokenizer
    
    # Format prompt with chat template
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
    ]
    
    formatted_prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    
    # Tokenize input
    inputs = tokenizer(
        formatted_prompt,
        return_tensors="pt",
        truncation=True,
        max_length=2048
    ).to(model.cfg.device)
    
    # Generate
    with torch.no_grad():
        outputs = model.generate(
            inputs.input_ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature if temperature > 0 else 1.0,
            do_sample=temperature > 0,
            verbose=False
        )
    
    # Decode generated text (only the new tokens, not the prompt)
    generated_text = tokenizer.decode(
        outputs[0][inputs.input_ids.shape[1]:],
        skip_special_tokens=True
    )
    
    # Clean up
    del inputs, outputs
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    return generated_text.strip()


def run_decomposition(
    question: str, 
    model, 
    retriever, 
    context: List  # List of [title, sentences] lists or (title, sentences) tuples
) -> Dict[str, Any]:
    """
    Run the full decomposition pipeline.
    
    Args:
        question: Main question to answer
        model: HookedTransformer model for generation
        retriever: SentenceTransformer retriever
        context: List of (title, sentences) tuples from dataset
        
    Returns:
        Dictionary with all pipeline outputs
    """
    # Stage 1: Planning - generate subqueries
    planning_prompt = build_planning_prompt(question)
    planning_response = generate_text(model, planning_prompt, max_new_tokens=512, temperature=0.0)
    planning_response = clean_text(planning_response)
    
    # Parse subqueries from response
    subqueries = parse_subqueries(planning_response)
    
    # Limit to maximum 3 subqueries as per prompt instructions
    if len(subqueries) > 3:
        subqueries = subqueries[:3]
    
    # If parsing failed or returned empty, try to extract from raw response
    if not subqueries:
        # Try a more lenient parse - look for any lines with question marks or ANSWER placeholders
        lines = planning_response.strip().split('\n')
        for line in lines:
            line = line.strip()
            if '?' in line or '[ANSWER_' in line:
                # Try to extract the question part
                cleaned = re.sub(r'^[\d]+[.\)]\s*', '', line)
                cleaned = cleaned.strip()
                if cleaned and len(cleaned) > 5:
                    subqueries.append(cleaned)
                    if len(subqueries) >= 3:  # Limit to 3
                        break
    
    if not subqueries:
        # Fallback: treat main question as only subquery
        subqueries = [question]
    
    # Stage 2: Execute subqueries and fill placeholders
    filled_subqueries = subqueries.copy()  # Will be updated in loop
    answers_so_far = []
    all_retrieved_paragraphs = []
    subquery_index_to_sentences = {}  # Track retrieved sentences by index
    
    for i, subquery_template in enumerate(subqueries):
        # Fill placeholders with previous answers
        filled_subquery = fill_placeholders(subquery_template, answers_so_far)
        
        # Retrieve top 2 paragraphs
        retrieved_paragraphs = retrieve_top_paragraphs(
            retriever, 
            filled_subquery, 
            context, 
            top_k=2
        )
        all_retrieved_paragraphs.extend(retrieved_paragraphs)
        
        # Convert paragraphs to sentences for prompt
        retrieved_sentences = paragraphs_to_sentences(retrieved_paragraphs)
        
        # Store retrieved sentences by index
        subquery_index_to_sentences[i] = retrieved_sentences
        
        # Build subanswer prompt
        subanswer_prompt = build_subanswer_prompt(filled_subquery, retrieved_sentences)
        
        # Generate answer
        subanswer_response = generate_text(model, subanswer_prompt, max_new_tokens=256, temperature=0.0)
        subanswer = clean_text(subanswer_response)
        
        # Extract just the answer (remove "Answer:" prefix if present)
        if subanswer.lower().startswith("answer:"):
            subanswer = subanswer[7:].strip()
        
        answers_so_far.append(subanswer)
        
        # Update the filled subquery in the list
        # Replace placeholders with actual answers
        updated_subquery = fill_placeholders(subquery_template, answers_so_far)
        filled_subqueries[i] = updated_subquery
    
    # Stage 3: Generate final answer
    # Build sub_qa_history from filled subqueries and their answers
    sub_qa_history = [
        (filled_subqueries[i], answers_so_far[i]) 
        for i in range(len(filled_subqueries))
    ]
    
    final_prompt = build_final_answer_prompt(question, sub_qa_history)
    final_response = generate_text(model, final_prompt, max_new_tokens=256, temperature=0.0)
    final_answer = clean_text(final_response)
    
    # Extract just the answer (remove "Answer:" prefix if present)
    if final_answer.lower().startswith("answer:"):
        final_answer = final_answer[7:].strip()
    
    # Re-fill all subqueries with all final answers to ensure all placeholders are filled
    subquery_to_sentences = {}
    for i, subquery_template in enumerate(subqueries):
        # Fill with all final answers (answers_so_far now contains all answers)
        fully_filled_subquery = fill_placeholders(subquery_template, answers_so_far)
        # Store the fully filled subquery (with all [ANSWER_X] replaced) as the key
        subquery_to_sentences[fully_filled_subquery] = subquery_index_to_sentences[i]
    
    return {
        "question": clean_text(question),
        "answer": final_answer,
        "subqueries": subquery_to_sentences,  # Dictionary mapping subqueries (with all fillers filled) to their retrieved sentences
    }
