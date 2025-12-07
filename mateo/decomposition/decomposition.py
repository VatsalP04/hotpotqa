import re
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
    """
    # Find all numbered lines
    lines = response.strip().split('\n')
    subqueries = []
    
    # Pattern to match numbered lines: "1. Question? [ANSWER_1]"
    numbered_pattern = re.compile(r'^\d+\.\s+(.+)$')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        match = numbered_pattern.match(line)
        if match:
            subquery = match.group(1).strip()
            if subquery:
                subqueries.append(clean_text(subquery))
    
    return subqueries


def fill_placeholders(subquery: str, answers: List[str]) -> str:
    """Fill [ANSWER_1], [ANSWER_2], etc. placeholders with actual answers."""
    filled = subquery
    for i, answer in enumerate(answers, 1):
        placeholder = f"[ANSWER_{i}]"
        filled = filled.replace(placeholder, answer)
    return filled


def run_decomposition(
    question: str, 
    model, 
    retriever, 
    context: List[Tuple[str, List[str]]]
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
    planning_response = model(planning_prompt)
    planning_response = clean_text(planning_response)
    
    # Parse subqueries from response
    subqueries = parse_subqueries(planning_response)
    
    if not subqueries:
        # Fallback: treat main question as only subquery
        subqueries = [question]
    
    # Stage 2: Execute subqueries and fill placeholders
    filled_subqueries = subqueries.copy()  # Will be updated in loop
    answers_so_far = []
    all_retrieved_paragraphs = []
    
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
        
        # Build subanswer prompt
        subanswer_prompt = build_subanswer_prompt(filled_subquery, retrieved_sentences)
        
        # Generate answer
        subanswer_response = model(subanswer_prompt)
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
    final_response = model(final_prompt)
    final_answer = clean_text(final_response)
    
    # Extract just the answer (remove "Answer:" prefix if present)
    if final_answer.lower().startswith("answer:"):
        final_answer = final_answer[7:].strip()
    
    # Get all retrieved sentences (deduplicated)
    all_retrieved_sentences = paragraphs_to_sentences(all_retrieved_paragraphs)
    
    return {
        "question": clean_text(question),
        "answer": final_answer,
        "subqueries": filled_subqueries,
        "retrieved_sentences": all_retrieved_sentences,
    }
