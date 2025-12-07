"""
IRCoT - Interleaved Retrieval with Chain-of-Thought for HotpotQA.

This package implements the IRCoT method from Trivedi et al. (2023) for
multi-hop question answering on the HotpotQA dataset.

Quick Start:
    from ircot import IRCoTQA, IRCoTConfig
    
    # Create system with default config
    qa = IRCoTQA()
    
    # Answer a question
    result = qa.answer(
        question="What is the capital of France?",
        context=[("France", ["Paris is the capital of France."])]
    )
    print(result["answer"])

Main Components:
    - IRCoTSystem: Core IRCoT algorithm implementation
    - IRCoTQA: High-level QA pipeline
    - IRCoTConfig: Configuration management
    - HotpotQALoader: Dataset loading utilities
    - evaluate: Evaluation metrics (EM, F1)

Example Usage:
    # Load data
    from ircot import HotpotQALoader, subsample
    loader = HotpotQALoader()
    instances = loader.load_dev()
    sample = subsample(instances, n=100)
    
    # Run predictions
    from ircot import IRCoTQA, format_for_prediction
    qa = IRCoTQA()
    questions = [format_for_prediction(inst) for inst in sample]
    predictions = qa.batch_answer(questions)
    
    # Evaluate
    from ircot import detailed_evaluation, format_report
    gold = [inst.to_dict() for inst in sample]
    results = detailed_evaluation(predictions, gold)
    print(format_report(results))
"""

__version__ = "2.0.0"
__author__ = "6CCSANLP Coursework"

# =============================================================================
# Core Types
# =============================================================================

from .types import (
    # Data types
    Paragraph,
    RetrievalResult,
    ReasoningStep,
    IRCoTResult,
    QAResult,
    HotpotQAInstance,
    CoTDemo,
    # Type aliases
    Context,
    SupportingFacts,
    # Protocols
    LLMProtocol,
    EmbeddingsProtocol,
    RetrieverProtocol,
)

# =============================================================================
# Configuration
# =============================================================================

from .config import (
    IRCoTConfig,
    get_default_config,
    get_config_for_ablation,
    AblationPresets,
    ABLATION_CONFIGS,
    # Constants
    ModelDefaults,
    ReasoningDefaults,
    GenerationDefaults,
    AnswerMarkers,
)

# =============================================================================
# Core System
# =============================================================================

from .ircot import (
    IRCoTSystem,
    IRCoTQA,
    QAReader,
)

# =============================================================================
# Retrieval
# =============================================================================

from .retriever import (
    DenseRetriever,
    IRCoTRetriever,
)

# =============================================================================
# Embeddings
# =============================================================================

from .embeddings import (
    MistralEmbeddings,
    CachedEmbeddings,
    create_embeddings,
    cosine_similarity,
)

# =============================================================================
# LLM Client
# =============================================================================

from .llm_client import (
    LLMClient,
    MistralLLMClient,
    MockLLMClient,
    create_llm_client,
)

# =============================================================================
# Data Loading
# =============================================================================

from .data_loader import (
    HotpotQALoader,
    download_hotpotqa,
    subsample,
    get_statistics,
    format_for_prediction,
)

# =============================================================================
# Demo Loading
# =============================================================================

from .demo_loader import (
    load_default_demos,
    load_demos_from_file,
)

# =============================================================================
# Answer Extraction
# =============================================================================

from .answer_extraction import (
    AnswerExtractor,
    SentenceExtractor,
    ExtractedAnswer,
)

# =============================================================================
# Evaluation
# =============================================================================

from .evaluate import (
    # Core metrics
    exact_match,
    f1_score,
    precision_recall_f1,
    normalize_answer,
    # Evaluation functions
    evaluate,
    evaluate_single,
    evaluate_retrieval,
    detailed_evaluation,
    # Reporting
    format_report,
    save_official_format,
    error_analysis,
)

# =============================================================================
# Prompts
# =============================================================================

from .prompts import (
    build_reason_prompt,
    build_qa_prompt,
    build_direct_qa_prompt,
    build_reflection_prompt,
    get_system_instruction,
    format_paragraph,
    format_paragraphs,
)

# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # Version
    "__version__",
    
    # Types
    "Paragraph",
    "RetrievalResult",
    "ReasoningStep",
    "IRCoTResult",
    "QAResult",
    "HotpotQAInstance",
    "CoTDemo",
    "Context",
    "SupportingFacts",
    "LLMProtocol",
    "EmbeddingsProtocol",
    "RetrieverProtocol",
    "ExtractedAnswer",
    
    # Configuration
    "IRCoTConfig",
    "get_default_config",
    "get_config_for_ablation",
    "AblationPresets",
    "ABLATION_CONFIGS",
    "ModelDefaults",
    "ReasoningDefaults",
    "GenerationDefaults",
    "AnswerMarkers",
    
    # Core System
    "IRCoTSystem",
    "IRCoTQA",
    "QAReader",
    
    # Retrieval
    "DenseRetriever",
    "IRCoTRetriever",
    
    # Embeddings
    "MistralEmbeddings",
    "CachedEmbeddings",
    "create_embeddings",
    "cosine_similarity",
    
    # LLM
    "LLMClient",
    "MistralLLMClient",
    "MockLLMClient",
    "create_llm_client",
    
    # Data
    "HotpotQALoader",
    "download_hotpotqa",
    "subsample",
    "get_statistics",
    "format_for_prediction",
    
    # Demos
    "load_default_demos",
    "load_demos_from_file",
    
    # Answer Extraction
    "AnswerExtractor",
    "SentenceExtractor",
    
    # Evaluation
    "exact_match",
    "f1_score",
    "precision_recall_f1",
    "normalize_answer",
    "evaluate",
    "evaluate_single",
    "evaluate_retrieval",
    "detailed_evaluation",
    "format_report",
    "save_official_format",
    "error_analysis",
    
    # Prompts
    "build_reason_prompt",
    "build_qa_prompt",
    "build_direct_qa_prompt",
    "build_reflection_prompt",
    "get_system_instruction",
    "format_paragraph",
    "format_paragraphs",
]
