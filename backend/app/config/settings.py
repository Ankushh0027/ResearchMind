"""Application configuration and settings contracts using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Core application environment configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application Environment
    app_env: Literal["development", "test", "staging", "production"] = Field(
        default="development",
        alias="APP_ENV",
        description="Target runtime environment",
    )
    debug: bool = Field(
        default=False,
        alias="DEBUG",
        description="Enable debug mode and verbose tracing",
    )
    app_name: str = Field(
        default="ResearchMind",
        alias="APP_NAME",
        description="Application identifier",
    )
    api_v1_prefix: str = Field(
        default="/api/v1",
        alias="API_V1_PREFIX",
        description="Base prefix for REST API endpoints",
    )
    host: str = Field(
        default="0.0.0.0",
        alias="HOST",
        description="HTTP server host bind address",
    )
    port: int = Field(
        default=8080,
        alias="PORT",
        description="HTTP server port",
    )

    # Gemini & AI Model Configuration
    gemini_api_key: str = Field(
        default="",
        alias="GEMINI_API_KEY",
        description="API key for Google Gemini model inference",
    )
    gemini_model: str = Field(
        default="gemini-2.5-pro",
        alias="GEMINI_MODEL",
        description="Default Gemini LLM model identifier for multi-agent reasoning",
    )
    gemini_fast_model: str = Field(
        default="gemini-2.5-flash",
        alias="GEMINI_FAST_MODEL",
        description="Fast Gemini model identifier for extraction and triage",
    )
    gemini_embedding_model: str = Field(
        default="text-embedding-004",
        alias="GEMINI_EMBEDDING_MODEL",
        description="Model identifier for vector embeddings",
    )
    gemini_temperature: float = Field(
        default=0.2,
        alias="GEMINI_TEMPERATURE",
        description="Sampling temperature for deterministic agent reasoning",
    )
    gemini_max_output_tokens: int = Field(
        default=8192,
        alias="GEMINI_MAX_OUTPUT_TOKENS",
        description="Maximum tokens allowed in model responses",
    )

    # Google Cloud Platform Configuration
    gcp_project_id: str = Field(
        default="researchmind-dev",
        alias="GCP_PROJECT_ID",
        description="GCP Project ID",
    )
    gcp_region: str = Field(
        default="us-central1",
        alias="GCP_REGION",
        description="GCP default compute and service region",
    )
    gcp_credentials_file: str | None = Field(
        default=None,
        alias="GOOGLE_APPLICATION_CREDENTIALS",
        description="Path to GCP service account key for local development",
    )

    # Pub/Sub Orchestration & Task Distribution
    pubsub_tasks_topic: str = Field(
        default="researchmind-agent-tasks",
        alias="PUBSUB_TASKS_TOPIC",
        description="Pub/Sub topic for dispatching asynchronous subtasks",
    )
    pubsub_tasks_subscription: str = Field(
        default="researchmind-agent-tasks-sub",
        alias="PUBSUB_TASKS_SUBSCRIPTION",
        description="Pub/Sub subscription for asynchronous worker task ingestion",
    )
    pubsub_events_topic: str = Field(
        default="researchmind-workflow-events",
        alias="PUBSUB_EVENTS_TOPIC",
        description="Pub/Sub topic for streaming workflow state and progress events",
    )

    # Firestore State & Run Persistence
    firestore_database: str = Field(
        default="(default)",
        alias="FIRESTORE_DATABASE",
        description="Firestore database instance identifier",
    )
    firestore_runs_collection: str = Field(
        default="research_runs",
        alias="FIRESTORE_RUNS_COLLECTION",
        description="Firestore collection name for research session state",
    )
    firestore_tasks_collection: str = Field(
        default="research_tasks",
        alias="FIRESTORE_TASKS_COLLECTION",
        description="Firestore collection name for task tree records",
    )

    # Cloud Storage (GCS) Configuration
    gcs_bucket_artifacts: str = Field(
        default="researchmind-artifacts-dev",
        alias="GCS_BUCKET_ARTIFACTS",
        description="GCS bucket name for storing final research reports and raw sources",
    )
    gcs_bucket_uploads: str = Field(
        default="researchmind-uploads-dev",
        alias="GCS_BUCKET_UPLOADS",
        description="GCS bucket name for user uploaded reference documents",
    )

    # Qdrant Vector Search Configuration
    qdrant_url: str = Field(
        default="http://localhost:6333",
        alias="QDRANT_URL",
        description="Qdrant vector database endpoint URL",
    )
    qdrant_api_key: str | None = Field(
        default=None,
        alias="QDRANT_API_KEY",
        description="Qdrant API key for managed cloud cluster",
    )
    qdrant_collection_name: str = Field(
        default="research_evidence",
        alias="QDRANT_COLLECTION_NAME",
        description="Default Qdrant collection name for vector index",
    )
    qdrant_vector_size: int = Field(
        default=768,
        alias="QDRANT_VECTOR_SIZE",
        description="Dimensionality of embeddings stored in Qdrant",
    )

    # Logging & Observability
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
        description="Standard logger severity filter level",
    )
    log_format: Literal["json", "text"] = Field(
        default="json",
        alias="LOG_FORMAT",
        description="Output log format for Cloud Logging or terminal debugging",
    )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return a cached singleton instance of AppSettings."""
    return AppSettings()
