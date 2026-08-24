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
