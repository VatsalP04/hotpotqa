"""
Unit tests for IRCoT system.

Run with: python -m pytest tests/test_ircot.py -v
"""

import pytest
from unittest.mock import Mock, patch
import numpy as np

# Import from package
from ircot import (
    # Types
    Paragraph,
    RetrievalResult,
    IRCoTResult,
    QAResult,
    HotpotQAInstance,
    CoTDemo,
    
    # Config
    IRCoTConfig,
    get_default_config,
    get_config_for_ablation,
    
    # Answer extraction
    AnswerExtractor,
    SentenceExtractor,
    
    # Evaluation
    exact_match,
    f1_score,
    normalize_answer,
    
    # LLM
    MockLLMClient,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_paragraph():
    """Create a sample paragraph."""
    return Paragraph(
        title="Test Article",
        text="This is a test paragraph. It has multiple sentences.",
        sentences=("This is a test paragraph.", "It has multiple sentences."),
        index=0
    )


@pytest.fixture
def sample_context():
    """Create sample HotpotQA context."""
    return [
        ("Paris", ["Paris is the capital of France.", "It is known for the Eiffel Tower."]),
        ("France", ["France is a country in Europe.", "Its capital is Paris."]),
    ]


@pytest.fixture
def sample_instance():
    """Create a sample HotpotQA instance."""
    return HotpotQAInstance(
        id="test_123",
        question="What is the capital of France?",
        answer="Paris",
        context=[
            ("Paris", ["Paris is the capital of France."]),
            ("France", ["France is a country in Europe."])
        ],
        supporting_facts=[("Paris", 0)],
        question_type="bridge",
        level="easy"
    )


@pytest.fixture
def sample_demo(sample_paragraph):
    """Create a sample demonstration."""
    return CoTDemo(
        paragraphs=[sample_paragraph],
        question="What is this about?",
        cot_answer="This is about testing. So the answer is: testing."
    )


@pytest.fixture
def config():
    """Create test configuration."""
    return IRCoTConfig(
        mistral_api_key="test_key",
        initial_retrieval_k=2,
        max_reasoning_steps=3,
        max_total_paragraphs=5,
    )


# =============================================================================
# Test Types
# =============================================================================

class TestParagraph:
    """Tests for Paragraph dataclass."""
    
    def test_creation(self, sample_paragraph):
        assert sample_paragraph.title == "Test Article"
        assert sample_paragraph.index == 0
    
    def test_full_text(self, sample_paragraph):
        full = sample_paragraph.full_text
        assert "Test Article:" in full
        assert "test paragraph" in full
    
    def test_from_context_item(self):
        para = Paragraph.from_context_item(
            title="Title",
            sentences=["Sentence one.", "Sentence two."],
            index=1
        )
        assert para.title == "Title"
        assert para.text == "Sentence one. Sentence two."
        assert para.index == 1
    
    def test_immutability(self, sample_paragraph):
        """Paragraphs should be immutable (frozen)."""
        with pytest.raises(AttributeError):
            sample_paragraph.title = "New Title"
    
    def test_hashable(self, sample_paragraph):
        """Paragraphs should be hashable for use in sets."""
        para_set = {sample_paragraph}
        assert sample_paragraph in para_set


class TestHotpotQAInstance:
    """Tests for HotpotQAInstance."""
    
    def test_from_dict(self):
        data = {
            "_id": "test_id",
            "question": "Test question?",
            "answer": "test answer",
            "context": [["Title", ["Sentence."]]],
            "supporting_facts": [["Title", 0]],
            "type": "bridge",
            "level": "easy"
        }
        inst = HotpotQAInstance.from_dict(data)
        
        assert inst.id == "test_id"
        assert inst.question == "Test question?"
        assert inst.answer == "test answer"
        assert len(inst.context) == 1
    
    def test_to_dict(self, sample_instance):
        d = sample_instance.to_dict()
        assert d["_id"] == "test_123"
        assert d["question"] == "What is the capital of France?"
    
    def test_gold_paragraph_titles(self, sample_instance):
        titles = sample_instance.gold_paragraph_titles
        assert "Paris" in titles


# =============================================================================
# Test Configuration
# =============================================================================

class TestConfig:
    """Tests for IRCoTConfig."""
    
    def test_default_config(self):
        config = get_default_config()
        assert config.initial_retrieval_k == 2
        assert config.max_reasoning_steps == 4
    
    def test_validation_initial_k(self):
        with pytest.raises(ValueError):
            IRCoTConfig(initial_retrieval_k=0)
    
    def test_validation_temperature(self):
        with pytest.raises(ValueError):
            IRCoTConfig(temperature=3.0)
    
    def test_ablation_config(self):
        config = get_config_for_ablation("one_step")
        assert config.max_reasoning_steps == 1
        assert config.initial_retrieval_k == 5
    
    def test_invalid_ablation(self):
        with pytest.raises(ValueError):
            get_config_for_ablation("invalid_name")
    
    def test_to_dict(self, config):
        d = config.to_dict()
        assert "initial_retrieval_k" in d
        assert "mistral_api_key" not in d  # Should not include API key


# =============================================================================
# Test Answer Extraction
# =============================================================================

class TestAnswerExtractor:
    """Tests for AnswerExtractor."""
    
    def test_extract_standard(self):
        text = "The capital is Paris. So the answer is: Paris."
        result = AnswerExtractor.extract(text)
        
        assert result.found
        assert result.answer == "Paris"
    
    def test_extract_lowercase(self):
        text = "After analysis, the answer is: 42"
        result = AnswerExtractor.extract(text)
        
        assert result.found
        assert result.answer == "42"
    
    def test_extract_no_marker(self):
        text = "This text has no answer marker."
        result = AnswerExtractor.extract(text)
        
        # Should use fallback or return empty
        assert result.full_cot == text.strip()
    
    def test_extract_empty(self):
        result = AnswerExtractor.extract("")
        assert not result.found
        assert result.answer == ""
    
    def test_cleans_formatting(self):
        text = "So the answer is: **bold answer**."
        result = AnswerExtractor.extract(text)
        
        assert "**" not in result.answer
    
    def test_contains_marker(self):
        assert AnswerExtractor.contains_answer_marker("So the answer is: X")
        assert AnswerExtractor.contains_answer_marker("the answer is X")
        assert not AnswerExtractor.contains_answer_marker("No marker here")


class TestSentenceExtractor:
    """Tests for SentenceExtractor."""
    
    def test_get_first_sentence(self):
        text = "First sentence. Second sentence."
        result = SentenceExtractor.get_next_sentence(text)
        assert result == "First sentence."
    
    def test_skip_repeated(self):
        text = "Previous content. New sentence."
        previous = "Previous content."
        result = SentenceExtractor.get_next_sentence(text, previous)
        assert result == "New sentence."
    
    def test_empty_input(self):
        result = SentenceExtractor.get_next_sentence("")
        assert result == ""
    
    def test_split_into_sentences(self):
        text = "One. Two. Three."
        sentences = SentenceExtractor.split_into_sentences(text)
        assert len(sentences) >= 3


# =============================================================================
# Test Evaluation Metrics
# =============================================================================

class TestEvaluation:
    """Tests for evaluation metrics."""
    
    def test_normalize_answer(self):
        assert normalize_answer("The Answer") == "answer"
        assert normalize_answer("a test!") == "test"
        assert normalize_answer("  spaces  ") == "spaces"
    
    def test_exact_match_identical(self):
        assert exact_match("Paris", "Paris") == 1.0
    
    def test_exact_match_case_insensitive(self):
        assert exact_match("PARIS", "paris") == 1.0
    
    def test_exact_match_articles(self):
        assert exact_match("the answer", "answer") == 1.0
    
    def test_exact_match_different(self):
        assert exact_match("Paris", "London") == 0.0
    
    def test_f1_identical(self):
        assert f1_score("Paris France", "Paris France") == 1.0
    
    def test_f1_partial(self):
        score = f1_score("Paris France", "Paris")
        assert 0 < score < 1
    
    def test_f1_no_overlap(self):
        assert f1_score("cat", "dog") == 0.0
    
    def test_f1_empty(self):
        assert f1_score("", "") == 1.0
        assert f1_score("word", "") == 0.0


# =============================================================================
# Test LLM Client
# =============================================================================

class TestMockLLMClient:
    """Tests for MockLLMClient."""
    
    def test_returns_response(self):
        client = MockLLMClient(["Response 1", "Response 2"])
        
        r1 = client.generate("prompt", max_new_tokens=100)
        r2 = client.generate("prompt", max_new_tokens=100)
        
        assert r1 == "Response 1"
        assert r2 == "Response 2"
    
    def test_tracks_calls(self):
        client = MockLLMClient()
        
        client.generate("prompt 1", max_new_tokens=100)
        client.generate("prompt 2", max_new_tokens=100)
        
        assert client.call_count == 2
        assert len(client.prompts) == 2
    
    def test_cycles_responses(self):
        client = MockLLMClient(["A"])
        
        assert client.generate("", max_new_tokens=100) == "A"
        assert client.generate("", max_new_tokens=100) == "A"


# =============================================================================
# Integration Tests (Mocked)
# =============================================================================

class TestIRCoTIntegration:
    """Integration tests with mocked dependencies."""
    
    def test_full_pipeline_mocked(self, sample_context, sample_demo, config):
        """Test full pipeline with mocked LLM and embeddings."""
        from ircot import IRCoTSystem
        from ircot.retriever import DenseRetriever, IRCoTRetriever
        
        # Create mock LLM
        mock_llm = MockLLMClient([
            "Paris is mentioned. So the answer is: Paris."
        ])
        
        # Create mock embeddings
        mock_embeddings = Mock()
        mock_embeddings.embed_text.return_value = np.random.rand(1024)
        mock_embeddings.embed_texts.return_value = np.random.rand(2, 1024)
        
        # Create retriever with mocked embeddings
        base_retriever = DenseRetriever(mock_embeddings)
        retriever = IRCoTRetriever(base_retriever, max_paragraphs=5)
        
        # Create system
        system = IRCoTSystem(
            config=config,
            demos=[sample_demo],
            llm=mock_llm,
            retriever=retriever
        )
        
        # Run
        result = system.answer(
            question="What is the capital of France?",
            context=sample_context,
            use_interleaved=True
        )
        
        assert isinstance(result, IRCoTResult)
        assert result.question == "What is the capital of France?"
        # The mocked response should produce "Paris" as the answer
        assert "Paris" in result.answer or result.answer != ""


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
