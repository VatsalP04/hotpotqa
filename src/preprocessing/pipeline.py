"""
End-to-end preprocessing pipeline for HotpotQA.

This module provides a complete pipeline that orchestrates data loading,
cleaning, tokenization, context processing, and multi-hop feature extraction.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from tqdm import tqdm

from ..config.config_manager import ConfigManager
from ..data.loader import load_hotpotqa
from ..utils.cleaning import clean_text
from ..utils.normalization import normalize_text
from .tokenizer import get_tokenizer
from .context import (
    flatten_context,
    extract_supporting_context,
    truncate_context_to_length,
    format_context_for_qa
)
from .multihop import create_multihop_features

logger = logging.getLogger(__name__)


class HotpotQAPreprocessor:
    """
    Complete preprocessing pipeline for HotpotQA dataset.

    This class orchestrates all preprocessing steps including loading, cleaning,
    tokenization, context processing, and feature extraction.
    """

    def __init__(self, config: Optional[Union[ConfigManager, Dict[str, Any]]] = None):
        """
        Initialize the preprocessor.

        Args:
            config: Configuration object or dictionary. If None, loads default config.
        """
        if config is None:
            config = ConfigManager()
        elif isinstance(config, dict):
            # Convert dict to ConfigManager
            base_config = ConfigManager()
            base_config.merge_config(config)
            config = base_config

        self.config = config

        # Extract commonly used config values
        self.data_config = config.get_section('data')
        self.prep_config = config.get_section('preprocessing')

        # Initialize tokenizer if configured
        self.tokenizer = None
        tokenizer_config = self.prep_config.get('tokenization', {})
        if tokenizer_config:
            self.tokenizer = get_tokenizer(
                tokenizer_config.get('tokenizer_type', 'huggingface'),
                model_name=tokenizer_config.get('model_name', 'bert-base-uncased'),
                max_length=tokenizer_config.get('max_length', 512),
                truncation=tokenizer_config.get('truncation', True),
                padding=tokenizer_config.get('padding', 'max_length'),
                add_special_tokens=tokenizer_config.get('add_special_tokens', True),
                return_tensors=tokenizer_config.get('return_tensors', None)
            )

        logger.info("Initialized HotpotQA preprocessor")

    def load_data(self, split: str = "train") -> List[Dict[str, Any]]:
        """
        Load raw data from disk.

        Args:
            split: Dataset split to load ('train' or 'dev')

        Returns:
            List of raw examples
        """
        logger.info(f"Loading {split} data...")

        data_dir = self.data_config.get('raw_dir', 'data/raw')
        max_examples = self.data_config.get('max_examples', None)
        shuffle = self.data_config.get('shuffle_seed', None) is not None

        data = load_hotpotqa(
            data_dir=data_dir,
            split=split,
            max_examples=max_examples,
            shuffle=shuffle,
            seed=self.data_config.get('shuffle_seed', 42),
            validate=True
        )

        logger.info(f"Loaded {len(data)} examples")
        return data

    def clean_example(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean text in an example.

        Args:
            example: Raw example

        Returns:
            Example with cleaned text
        """
        cleaning_config = self.prep_config.get('cleaning', {})

        # Clean question
        if 'question' in example:
            example['question'] = clean_text(
                example['question'],
                remove_extra_whitespace=cleaning_config.get('remove_extra_whitespace', True),
                normalize_unicode=cleaning_config.get('normalize_unicode', True),
                remove_html=cleaning_config.get('remove_html', True)
            )

        # Clean answer
        if 'answer' in example:
            example['answer'] = clean_text(
                example['answer'],
                remove_extra_whitespace=cleaning_config.get('remove_extra_whitespace', True),
                normalize_unicode=cleaning_config.get('normalize_unicode', True),
                remove_html=cleaning_config.get('remove_html', True)
            )

        # Clean context
        if 'context' in example:
            cleaned_context = []
            for title, sentences in example['context']:
                cleaned_title = clean_text(title)
                cleaned_sentences = [clean_text(sent) for sent in sentences]
                cleaned_context.append([cleaned_title, cleaned_sentences])
            example['context'] = cleaned_context

        return example

    def normalize_example(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize text in an example.

        Args:
            example: Example with cleaned text

        Returns:
            Example with normalized text
        """
        cleaning_config = self.prep_config.get('cleaning', {})
        lowercase = cleaning_config.get('lowercase', False)

        if lowercase:
            # Normalize question
            if 'question' in example:
                example['question'] = normalize_text(example['question'], lowercase=True)

            # Normalize answer
            if 'answer' in example:
                example['answer'] = normalize_text(example['answer'], lowercase=True)

            # Normalize context
            if 'context' in example:
                normalized_context = []
                for title, sentences in example['context']:
                    normalized_title = normalize_text(title, lowercase=True)
                    normalized_sentences = [normalize_text(sent, lowercase=True) for sent in sentences]
                    normalized_context.append([normalized_title, normalized_sentences])
                example['context'] = normalized_context

        return example

    def process_context(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process context according to configuration.

        Args:
            example: Example with cleaned/normalized text

        Returns:
            Example with processed context fields
        """
        context_config = self.prep_config.get('context', {})

        # Truncate context if needed
        max_context_length = context_config.get('max_context_length', None)
        if max_context_length:
            supporting_titles = [title for title, _ in example.get('supporting_facts', [])]
            example['context'] = truncate_context_to_length(
                example['context'],
                max_tokens=max_context_length,
                method='whitespace',
                prioritize_supporting=True,
                supporting_titles=supporting_titles
            )

        # Limit number of paragraphs
        max_paragraphs = context_config.get('max_paragraphs', None)
        if max_paragraphs and len(example.get('context', [])) > max_paragraphs:
            example['context'] = example['context'][:max_paragraphs]

        # Create flattened context
        example['context_flat'] = flatten_context(
            example['context'],
            include_titles=context_config.get('include_titles', True),
            title_template=context_config.get('title_template', 'Title: {title}\n'),
            paragraph_separator=context_config.get('paragraph_separator', '\n\n')
        )

        # Create supporting context
        example['supporting_context'] = extract_supporting_context(
            example,
            include_titles=context_config.get('include_titles', True)
        )

        return example

    def extract_multihop_features(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract multi-hop reasoning features.

        Args:
            example: Processed example

        Returns:
            Example with multi-hop features
        """
        multihop_config = self.prep_config.get('multihop', {})

        if multihop_config.get('extract_supporting_facts', True):
            multihop_features = create_multihop_features(example)
            example['multihop'] = multihop_features

        return example

    def tokenize_example(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tokenize example using configured tokenizer.

        Args:
            example: Processed example

        Returns:
            Example with tokenized fields
        """
        if self.tokenizer is None:
            return example

        # Tokenize question
        if 'question' in example:
            example['question_tokens'] = self.tokenizer.encode(
                example['question'],
                return_tensors=None
            )

        # Tokenize context
        if 'context_flat' in example:
            example['context_tokens'] = self.tokenizer.encode(
                example['context_flat'],
                return_tensors=None
            )

        # Tokenize question + context together
        if 'question' in example and 'context_flat' in example:
            example['qa_tokens'] = self.tokenizer.encode(
                example['question'],
                example['context_flat'],
                return_tensors=None
            )

        return example

    def process_example(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single example through the complete pipeline.

        Args:
            example: Raw example

        Returns:
            Fully processed example
        """
        # Make a copy to avoid modifying original
        example = example.copy()

        # Apply pipeline steps
        example = self.clean_example(example)
        example = self.normalize_example(example)
        example = self.process_context(example)
        example = self.extract_multihop_features(example)

        # Tokenization is optional and can be expensive
        # Only tokenize if explicitly needed
        if self.prep_config.get('tokenization', {}).get('tokenize_during_preprocessing', False):
            example = self.tokenize_example(example)

        return example

    def process_batch(
        self,
        examples: List[Dict[str, Any]],
        show_progress: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Process a batch of examples.

        Args:
            examples: List of raw examples
            show_progress: Whether to show progress bar

        Returns:
            List of processed examples
        """
        logger.info(f"Processing {len(examples)} examples...")

        processed = []
        iterator = tqdm(examples, desc="Processing") if show_progress else examples

        for example in iterator:
            try:
                processed_example = self.process_example(example)
                processed.append(processed_example)
            except Exception as e:
                logger.error(f"Error processing example {example.get('_id', 'UNKNOWN')}: {e}")
                # Optionally continue processing other examples
                continue

        logger.info(f"Successfully processed {len(processed)}/{len(examples)} examples")
        return processed

    def save_processed_data(
        self,
        processed_examples: List[Dict[str, Any]],
        output_path: Union[str, Path],
        include_raw: bool = None
    ) -> None:
        """
        Save processed data to disk.

        Args:
            processed_examples: List of processed examples
            output_path: Path to save the data
            include_raw: Whether to include raw fields (overrides config if provided)
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output_config = self.prep_config.get('output', {})
        save_format = output_config.get('save_format', 'json')

        if include_raw is None:
            include_raw = output_config.get('include_raw', False)

        # Optionally remove raw fields to save space
        if not include_raw:
            fields_to_remove = ['context', 'supporting_facts']  # Keep flattened versions
            processed_examples = [
                {k: v for k, v in ex.items() if k not in fields_to_remove}
                for ex in processed_examples
            ]

        logger.info(f"Saving {len(processed_examples)} processed examples to {output_path}")

        if save_format == 'json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(processed_examples, f, indent=2, ensure_ascii=False)
        elif save_format == 'jsonl':
            with open(output_path, 'w', encoding='utf-8') as f:
                for example in processed_examples:
                    f.write(json.dumps(example, ensure_ascii=False) + '\n')
        elif save_format == 'pickle':
            import pickle
            with open(output_path, 'wb') as f:
                pickle.dump(processed_examples, f)
        else:
            raise ValueError(f"Unknown save format: {save_format}")

        logger.info(f"✅ Saved processed data to {output_path}")

    def run(
        self,
        split: str = "train",
        output_path: Optional[Union[str, Path]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run the complete preprocessing pipeline.

        Args:
            split: Dataset split to process ('train' or 'dev')
            output_path: Path to save processed data (None to not save)

        Returns:
            List of processed examples
        """
        logger.info(f"Running preprocessing pipeline for {split} split")

        # Load data
        examples = self.load_data(split)

        # Process examples
        processed = self.process_batch(examples)

        # Save if output path provided
        if output_path:
            self.save_processed_data(processed, output_path)
        elif self.data_config.get('processed_dir'):
            # Auto-generate output path
            processed_dir = Path(self.data_config['processed_dir'])
            output_path = processed_dir / f"{split}_processed.json"
            self.save_processed_data(processed, output_path)

        logger.info(f"✅ Preprocessing complete for {split} split")
        return processed


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    from pathlib import Path
    import sys

    project_root = Path(__file__).resolve().parents[2]

    try:
        # Load config with 'quick' preset for testing
        from ..config.config_manager import load_config
        config = load_config(preset='quick')

        # Initialize preprocessor
        print("Initializing preprocessor...")
        preprocessor = HotpotQAPreprocessor(config)

        # Run pipeline on small sample
        print("\nRunning preprocessing pipeline...")
        processed = preprocessor.run(split='train', output_path=None)

        print(f"\n✅ Processed {len(processed)} examples")
        print("\nExample output (first example):")
        example = processed[0]
        print(f"  ID: {example['_id']}")
        print(f"  Question: {example['question']}")
        print(f"  Answer: {example['answer']}")
        print(f"  Context length: {len(example.get('context_flat', ''))} chars")
        print(f"  Multi-hop hops: {example.get('multihop', {}).get('num_hops', 'N/A')}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
