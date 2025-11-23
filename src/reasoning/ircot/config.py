from dataclasses import dataclass


@dataclass
class IRCoTConfig:
    """
    Configuration for IRCoT-style retrieval and QA.

    Mirrors the hyperparameter ranges described in the ACL'23 paper.
    """

    # Retrieval
    k_step: int = 4  # K paragraphs per retrieval step
    max_paragraphs: int = 15  # Total paragraphs allowed across steps
    max_steps: int = 8  # Maximum reasoning steps

    # LLM generation
    temperature: float = 0.2
    max_new_tokens_reason: int = 128
    max_new_tokens_reader: int = 256

    # Prompting / demos
    max_demos: int = 3
    use_cot_reader: bool = True

    # Misc
    answer_trigger: str = "answer is"

