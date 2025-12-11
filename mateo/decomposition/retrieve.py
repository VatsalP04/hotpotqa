from typing import List, Tuple
import numpy as np


def retrieve_top_paragraphs(
    retriever, 
    query: str, 
    context: List, 
    top_k: int = 2
) -> List[Tuple[str, List[str]]]:
    """
    Retrieve top_k most relevant paragraphs from context using the retriever.
    
    Args:
        retriever: SentenceTransformer model for encoding
        query: Query string to search for
        context: List of [title, sentences] lists or (title, sentences) tuples representing paragraphs
        top_k: Number of top paragraphs to retrieve
        
    Returns:
        List of top_k (title, sentences) tuples
    """
    if not context:
        return []
    
    # Normalize context format - handle both lists and tuples
    normalized_context = []
    for item in context:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            title = item[0]
            sentences = item[1]
            # Ensure sentences is a list
            if not isinstance(sentences, list):
                sentences = list(sentences) if hasattr(sentences, '__iter__') else [str(sentences)]
            normalized_context.append((title, sentences))
        else:
            # Skip malformed items
            continue
    
    if not normalized_context:
        return []
    
    # Encode the query
    query_embedding = retriever.encode(query, convert_to_numpy=True)
    
    # Encode each paragraph (join sentences into text)
    paragraph_texts = []
    for title, sentences in normalized_context:
        paragraph_text = " ".join(sentences)
        paragraph_texts.append(paragraph_text)
    
    # Encode all paragraphs
    paragraph_embeddings = retriever.encode(paragraph_texts, convert_to_numpy=True)
    
    # Compute cosine similarities
    # Normalize embeddings for cosine similarity
    query_norm = query_embedding / np.linalg.norm(query_embedding)
    para_norms = paragraph_embeddings / np.linalg.norm(paragraph_embeddings, axis=1, keepdims=True)
    
    similarities = np.dot(para_norms, query_norm)
    
    # Get top_k indices
    top_indices = np.argsort(similarities)[::-1][:top_k]
    
    # Return top_k paragraphs (as tuples)
    return [normalized_context[i] for i in top_indices]


def paragraphs_to_sentences(paragraphs: List[Tuple[str, List[str]]]) -> List[str]:
    """
    Convert list of paragraph tuples to flat list of sentences.
    Deduplicates by tracking paragraph titles.
    
    Args:
        paragraphs: List of (title, sentences) tuples
        
    Returns:
        Flat list of sentence strings (deduplicated by title)
    """
    seen_titles = set()
    all_sentences = []
    
    for title, sentences in paragraphs:
        # Deduplicate by title
        if title not in seen_titles:
            seen_titles.add(title)
            all_sentences.extend(sentences)
    
    return all_sentences
