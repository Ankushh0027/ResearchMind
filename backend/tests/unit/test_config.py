"""Unit tests verifying configuration loading and validation behavior."""

import pytest
from pydantic import ValidationError

from app.config import AppSettings, get_settings


def test_default_settings_initialization() -> None:
    """Verify that settings load with safe defaults without external credentials."""
    settings = AppSettings()
    assert settings.app_name == "ResearchMind"
    assert settings.app_env in ["development", "test", "staging", "production"]
    assert settings.port == 8080
    assert settings.api_v1_prefix == "/api/v1"
    assert isinstance(settings.gemini_model, str)
    assert len(settings.gemini_model) > 0


def test_get_settings_singleton() -> None:
    """Verify get_settings returns a cached instance."""
    settings_a = get_settings()
    settings_b = get_settings()
    assert settings_a is settings_b


def test_custom_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that environment variables properly override default configuration."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom-model")
    monkeypatch.setenv("QDRANT_VECTOR_SIZE", "1536")

    custom_settings = AppSettings()
    assert custom_settings.app_env == "production"
    assert custom_settings.port == 9000
    assert custom_settings.gemini_model == "gemini-custom-model"
    assert custom_settings.qdrant_vector_size == 1536


def test_invalid_app_env_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that invalid environment names fail validation."""
    monkeypatch.setenv("APP_ENV", "invalid-environment")
    with pytest.raises(ValidationError):
        AppSettings()


def test_invalid_log_level_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that unsupported log levels fail validation."""
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE_UNSUPPORTED")
    with pytest.raises(ValidationError):
        AppSettings()


def test_pubsub_settings_and_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Pub/Sub configuration fields and environment overrides."""
    default_settings = AppSettings()
    assert default_settings.job_transport == "in_memory"
    assert default_settings.pubsub_tasks_topic == "researchmind-agent-tasks"
    assert default_settings.pubsub_tasks_subscription == "researchmind-agent-tasks-sub"
    assert default_settings.pubsub_dead_letter_topic == "researchmind-agent-tasks-dlq"
    assert default_settings.pubsub_max_attempts == 3
    assert default_settings.pubsub_ack_deadline_seconds == 60
    assert default_settings.pubsub_ack_extension_seconds == 60

    monkeypatch.setenv("JOB_TRANSPORT", "pubsub")
    monkeypatch.setenv("PUBSUB_TASKS_TOPIC", "custom-tasks")
    monkeypatch.setenv("PUBSUB_TASKS_SUBSCRIPTION", "custom-sub")
    monkeypatch.setenv("PUBSUB_DEAD_LETTER_TOPIC", "custom-dlq")
    monkeypatch.setenv("PUBSUB_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("PUBSUB_ACK_DEADLINE_SECONDS", "120")
    monkeypatch.setenv("PUBSUB_ACK_EXTENSION_SECONDS", "90")

    custom = AppSettings()
    assert custom.job_transport == "pubsub"
    assert custom.pubsub_tasks_topic == "custom-tasks"
    assert custom.pubsub_tasks_subscription == "custom-sub"
    assert custom.pubsub_dead_letter_topic == "custom-dlq"
    assert custom.pubsub_max_attempts == 5
    assert custom.pubsub_ack_deadline_seconds == 120
    assert custom.pubsub_ack_extension_seconds == 90


def test_invalid_job_transport_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that unsupported job transport values fail validation."""
    monkeypatch.setenv("JOB_TRANSPORT", "kafka_unsupported")
    with pytest.raises(ValidationError):
        AppSettings()


def test_llm_and_embedding_settings_and_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify LLM and embedding configuration fields and environment overrides."""
    default_settings = AppSettings()
    assert default_settings.llm_provider == "in_memory"
    assert default_settings.embedding_provider == "in_memory"
    assert default_settings.gemini_model == "gemini-2.5-pro"
    assert default_settings.gemini_fast_model == "gemini-2.5-flash"
    assert default_settings.gemini_embedding_model == "text-embedding-004"
    assert default_settings.gemini_temperature == 0.2
    assert default_settings.gemini_max_output_tokens == 8192
    assert default_settings.gemini_request_timeout_seconds == 60.0
    assert default_settings.gemini_max_retries == 3
    assert default_settings.gemini_initial_retry_delay_seconds == 1.0
    assert default_settings.gemini_max_retry_delay_seconds == 10.0

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "env-test-key-12345")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom-pro")
    monkeypatch.setenv("GEMINI_FAST_MODEL", "gemini-custom-flash")
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "custom-embedding-001")
    monkeypatch.setenv("GEMINI_TEMPERATURE", "0.7")
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "4096")
    monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "45.0")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "5")
    monkeypatch.setenv("GEMINI_INITIAL_RETRY_DELAY_SECONDS", "0.5")
    monkeypatch.setenv("GEMINI_MAX_RETRY_DELAY_SECONDS", "20.0")

    custom = AppSettings()
    assert custom.llm_provider == "gemini"
    assert custom.embedding_provider == "gemini"
    assert custom.gemini_api_key == "env-test-key-12345"
    assert custom.gemini_model == "gemini-custom-pro"
    assert custom.gemini_fast_model == "gemini-custom-flash"
    assert custom.gemini_embedding_model == "custom-embedding-001"
    assert custom.gemini_temperature == 0.7
    assert custom.gemini_max_output_tokens == 4096
    assert custom.gemini_request_timeout_seconds == 45.0
    assert custom.gemini_max_retries == 5
    assert custom.gemini_initial_retry_delay_seconds == 0.5
    assert custom.gemini_max_retry_delay_seconds == 20.0


def test_qdrant_and_search_settings_and_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Qdrant, Tavily, and arXiv configuration fields and environment overrides."""
    default_settings = AppSettings()
    assert default_settings.vector_store_provider == "in_memory"
    assert default_settings.search_provider == "in_memory"
    assert default_settings.academic_search_provider == "in_memory"
    assert default_settings.qdrant_distance == "Cosine"
    assert default_settings.qdrant_request_timeout_seconds == 30.0
    assert default_settings.qdrant_max_retries == 3
    assert default_settings.tavily_request_timeout_seconds == 15.0
    assert default_settings.tavily_max_retries == 3
    assert default_settings.arxiv_request_timeout_seconds == 20.0
    assert default_settings.arxiv_max_retries == 3

    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "qdrant")
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("ACADEMIC_SEARCH_PROVIDER", "arxiv")
    monkeypatch.setenv("QDRANT_DISTANCE", "Dot")
    monkeypatch.setenv("QDRANT_REQUEST_TIMEOUT_SECONDS", "45.0")
    monkeypatch.setenv("QDRANT_MAX_RETRIES", "5")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-override")
    monkeypatch.setenv("TAVILY_REQUEST_TIMEOUT_SECONDS", "25.0")
    monkeypatch.setenv("TAVILY_MAX_RETRIES", "4")
    monkeypatch.setenv("ARXIV_REQUEST_TIMEOUT_SECONDS", "35.0")
    monkeypatch.setenv("ARXIV_MAX_RETRIES", "5")

    custom = AppSettings()
    assert custom.vector_store_provider == "qdrant"
    assert custom.search_provider == "tavily"
    assert custom.academic_search_provider == "arxiv"
    assert custom.qdrant_distance == "Dot"
    assert custom.qdrant_request_timeout_seconds == 45.0
    assert custom.qdrant_max_retries == 5
    assert custom.tavily_api_key == "tvly-test-override"
    assert custom.tavily_request_timeout_seconds == 25.0
    assert custom.tavily_max_retries == 4
    assert custom.arxiv_request_timeout_seconds == 35.0
    assert custom.arxiv_max_retries == 5
