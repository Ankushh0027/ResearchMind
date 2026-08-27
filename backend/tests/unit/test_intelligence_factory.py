"""Unit tests for intelligence and embedding factory constructors."""

import pytest
from pydantic import ValidationError

from app.adapters.llm.factory import create_llm_client
from app.adapters.llm.gemini import GeminiLLMClient
from app.adapters.llm.mock_llm import MockLLMClient
from app.config.settings import AppSettings
from app.rag.embeddings import MockEmbeddingModel
from app.rag.factory import create_embedding_model
from app.rag.gemini import GeminiEmbeddingModel


def test_create_llm_client_in_memory_default() -> None:
    """Test 1: Verify default create_llm_client returns MockLLMClient."""
    settings = AppSettings()
    assert settings.llm_provider == "in_memory"

    client = create_llm_client(settings=settings)
    assert isinstance(client, MockLLMClient)


def test_create_llm_client_injected_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify injected LLMClientProtocol is returned when provider is in_memory or mock."""
    custom_mock = MockLLMClient(default_response_text="Custom mock")

    monkeypatch.setenv("LLM_PROVIDER", "in_memory")
    client = create_llm_client(settings=AppSettings(), client=custom_mock)
    assert client is custom_mock

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    client2 = create_llm_client(settings=AppSettings(), client=custom_mock)
    assert client2 is custom_mock


def test_create_llm_client_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 2: Verify create_llm_client creates GeminiLLMClient when LLM_PROVIDER is gemini."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro-custom")
    monkeypatch.setenv("GEMINI_TEMPERATURE", "0.5")
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "4096")
    monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "45.0")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "5")
    monkeypatch.setenv("GEMINI_INITIAL_RETRY_DELAY_SECONDS", "0.5")
    monkeypatch.setenv("GEMINI_MAX_RETRY_DELAY_SECONDS", "15.0")

    settings = AppSettings()
    client = create_llm_client(settings=settings)

    assert isinstance(client, GeminiLLMClient)
    assert client.api_key == "test-secret-gemini-key"
    assert client.model_name == "gemini-2.5-pro-custom"
    assert client.temperature == 0.5
    assert client.max_output_tokens == 4096
    assert client.request_timeout_seconds == 45.0
    assert client.max_retries == 5
    assert client.initial_retry_delay_seconds == 0.5
    assert client.max_retry_delay_seconds == 15.0


def test_create_embedding_model_in_memory_default() -> None:
    """Test 3: Verify default create_embedding_model returns MockEmbeddingModel."""
    settings = AppSettings()
    assert settings.embedding_provider == "in_memory"

    model = create_embedding_model(settings=settings)
    assert isinstance(model, MockEmbeddingModel)


def test_create_embedding_model_injected_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify injected EmbeddingModelProtocol is returned when provider is in_memory or mock."""
    custom_emb = MockEmbeddingModel(dimension=64)

    monkeypatch.setenv("EMBEDDING_PROVIDER", "in_memory")
    model = create_embedding_model(settings=AppSettings(), client=custom_emb)
    assert model is custom_emb

    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    model2 = create_embedding_model(settings=AppSettings(), client=custom_emb)
    assert model2 is custom_emb


def test_create_embedding_model_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 4: Verify create_embedding_model creates GeminiEmbeddingModel when EMBEDDING_PROVIDER is gemini."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-emb-key")
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004-custom")
    monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "30.0")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "4")

    settings = AppSettings()
    model = create_embedding_model(settings=settings)

    assert isinstance(model, GeminiEmbeddingModel)
    assert model.api_key == "test-secret-emb-key"
    assert model.model_name == "text-embedding-004-custom"
    assert model.request_timeout_seconds == 30.0
    assert model.max_retries == 4


def test_invalid_llm_and_embedding_provider_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 5: Verify that unsupported provider values fail Pydantic validation."""
    monkeypatch.setenv("LLM_PROVIDER", "unsupported_llm_backend")
    with pytest.raises(ValidationError):
        AppSettings()

    monkeypatch.undo()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "unsupported_emb_backend")
    with pytest.raises(ValidationError):
        AppSettings()
