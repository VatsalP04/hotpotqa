"""
Reasoning methods for multi-hop question answering.

This package provides implementations of various reasoning methods
for the HotpotQA dataset.

Structure:
- core/: Shared infrastructure (types, LLM, embeddings, retriever, evaluation)
- prompts/: All prompt templates
- methods/: Reasoning method implementations (IRCoT, Decomposition)
- experiments/: Experiment framework

Quick Start:
    from src.reasoning.core import LLMClient, Paragraph, normalize_answer
    from src.reasoning.methods.ircot import IRCoTSystem, IRCoTConfig
    from src.reasoning.methods.decomposition import DecompositionReasoner

Example:
    from src.reasoning.methods.ircot import IRCoTSystem, IRCoTConfig, load_default_demos
    
    config = IRCoTConfig()
    demos = load_default_demos()
    system = IRCoTSystem(config, demos)
    result = system.answer(question, context)
    print(result.answer)
"""

__version__ = "2.0.0"
