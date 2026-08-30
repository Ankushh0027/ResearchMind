"""Application configuration and settings contracts using Pydantic Settings."""

import json as _json
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Core application environment configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
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
    worker_concurrency: int = Field(
        default=2,
        ge=1,
        le=64,
        alias="WORKER_CONCURRENCY",
        description="Number of concurrent asynchronous job consumer workers",
    )
    max_orchestration_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        alias="MAX_ORCHESTRATION_CONCURRENCY",
        description="Maximum parallel DAG subtask execution concurrency per run",
    )
    graceful_shutdown_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        alias="GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS",
        description="Timeout in seconds for draining in-flight jobs during shutdown",
    )

    # Gemini & AI Model Configuration
    llm_provider: Literal["in_memory", "mock", "gemini"] = Field(
        default="in_memory",
        alias="LLM_PROVIDER",
        description="Active LLM provider backend (in_memory/mock or gemini)",
    )
    embedding_provider: Literal["in_memory", "mock", "gemini"] = Field(
        default="in_memory",
        alias="EMBEDDING_PROVIDER",
        description="Active Embedding provider backend (in_memory/mock or gemini)",
    )
    vector_store_provider: Literal["in_memory", "mock", "qdrant"] = Field(
        default="in_memory",
        alias="VECTOR_STORE_PROVIDER",
        description="Active vector store backend (in_memory/mock or qdrant)",
    )
    search_provider: Literal["in_memory", "mock", "tavily", "arxiv"] = Field(
        default="in_memory",
        alias="SEARCH_PROVIDER",
        description="Active general search provider backend (in_memory/mock, tavily, or arxiv)",
    )
    academic_search_provider: Literal["in_memory", "mock", "arxiv", "tavily"] = Field(
        default="in_memory",
        alias="ACADEMIC_SEARCH_PROVIDER",
        description="Active academic search provider backend (in_memory/mock, arxiv, or tavily)",
    )
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
        ge=0.0,
        le=2.0,
        alias="GEMINI_TEMPERATURE",
        description="Sampling temperature for deterministic agent reasoning",
    )
    gemini_max_output_tokens: int = Field(
        default=8192,
        gt=0,
        alias="GEMINI_MAX_OUTPUT_TOKENS",
        description="Maximum tokens allowed in model responses",
    )
    gemini_request_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
        alias="GEMINI_REQUEST_TIMEOUT_SECONDS",
        description="Request timeout in seconds for Gemini API operations",
    )
    gemini_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        alias="GEMINI_MAX_RETRIES",
        description="Maximum retry attempts on transient Gemini API errors",
    )
    gemini_initial_retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.01,
        le=60.0,
        alias="GEMINI_INITIAL_RETRY_DELAY_SECONDS",
        description="Initial delay in seconds before exponential retry backoff",
    )
    gemini_max_retry_delay_seconds: float = Field(
        default=10.0,
        ge=0.1,
        le=300.0,
        alias="GEMINI_MAX_RETRY_DELAY_SECONDS",
        description="Maximum delay in seconds between retry attempts",
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

    # Job Transport & Distributed Messaging
    job_transport: Literal["in_memory", "pubsub"] = Field(
        default="in_memory",
        alias="JOB_TRANSPORT",
        description="Active job messaging transport backend",
    )
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
    pubsub_dead_letter_topic: str = Field(
        default="researchmind-agent-tasks-dlq",
        alias="PUBSUB_DEAD_LETTER_TOPIC",
        description="Pub/Sub dead-letter topic for unrecoverable or retry-exhausted jobs",
    )
    pubsub_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        alias="PUBSUB_MAX_ATTEMPTS",
        description="Max allowed execution attempts before moving to DLQ",
    )
    pubsub_ack_deadline_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        alias="PUBSUB_ACK_DEADLINE_SECONDS",
        description="Pub/Sub message ack deadline lease in seconds",
    )
    pubsub_ack_extension_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        alias="PUBSUB_ACK_EXTENSION_SECONDS",
        description="Ack deadline extension period in seconds per heartbeat",
    )
    pubsub_emulator_host: str | None = Field(
        default=None,
        alias="PUBSUB_EMULATOR_HOST",
        description="Host and port for local Pub/Sub emulator (e.g. localhost:8085)",
    )

    # Persistence & State Store Configuration
    persistence_backend: Literal["in_memory", "firestore"] = Field(
        default="in_memory",
        alias="PERSISTENCE_BACKEND",
        description="Active state and checkpoint persistence backend",
    )
    firestore_emulator_host: str | None = Field(
        default=None,
        alias="FIRESTORE_EMULATOR_HOST",
        description="Host and port for local Firestore emulator (e.g. localhost:8080)",
    )
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
    qdrant_distance: Literal["Cosine", "Euclid", "Dot"] = Field(
        default="Cosine",
        alias="QDRANT_DISTANCE",
        description="Distance metric for vector similarity indexing",
    )
    qdrant_request_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        alias="QDRANT_REQUEST_TIMEOUT_SECONDS",
        description="Timeout in seconds for Qdrant operations",
    )
    qdrant_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        alias="QDRANT_MAX_RETRIES",
        description="Maximum retries on transient Qdrant operations",
    )
    qdrant_initial_retry_delay_seconds: float = Field(
        default=0.5,
        ge=0.01,
        le=60.0,
        alias="QDRANT_INITIAL_RETRY_DELAY_SECONDS",
        description="Initial exponential backoff delay base for Qdrant operations",
    )
    qdrant_max_retry_delay_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=300.0,
        alias="QDRANT_MAX_RETRY_DELAY_SECONDS",
        description="Maximum backoff delay between Qdrant retries",
    )

    # Search & Evidence Gathering Configuration
    tavily_api_key: str = Field(
        default="",
        alias="TAVILY_API_KEY",
        description="API key for Tavily Web Search API",
    )
    tavily_api_url: str = Field(
        default="https://api.tavily.com/search",
        alias="TAVILY_API_URL",
        description="Tavily Search API endpoint URL",
    )
    tavily_request_timeout_seconds: float = Field(
        default=15.0,
        ge=1.0,
        le=300.0,
        alias="TAVILY_REQUEST_TIMEOUT_SECONDS",
        description="Request timeout in seconds for Tavily API queries",
    )
    tavily_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        alias="TAVILY_MAX_RETRIES",
        description="Maximum retries on transient Tavily search errors",
    )
    tavily_initial_retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.01,
        le=60.0,
        alias="TAVILY_INITIAL_RETRY_DELAY_SECONDS",
        description="Initial exponential backoff delay base for Tavily retries",
    )
    tavily_max_retry_delay_seconds: float = Field(
        default=10.0,
        ge=0.1,
        le=300.0,
        alias="TAVILY_MAX_RETRY_DELAY_SECONDS",
        description="Maximum backoff delay between Tavily retries",
    )
    arxiv_api_url: str = Field(
        default="https://export.arxiv.org/api/query",
        alias="ARXIV_API_URL",
        description="Public arXiv search and harvest API endpoint URL",
    )
    arxiv_request_timeout_seconds: float = Field(
        default=20.0,
        ge=1.0,
        le=300.0,
        alias="ARXIV_REQUEST_TIMEOUT_SECONDS",
        description="Request timeout in seconds for arXiv API queries",
    )
    arxiv_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        alias="ARXIV_MAX_RETRIES",
        description="Maximum retries on transient arXiv queries",
    )
    arxiv_initial_retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.01,
        le=60.0,
        alias="ARXIV_INITIAL_RETRY_DELAY_SECONDS",
        description="Initial exponential backoff delay base for arXiv retries",
    )
    arxiv_max_retry_delay_seconds: float = Field(
        default=10.0,
        ge=0.1,
        le=300.0,
        alias="ARXIV_MAX_RETRY_DELAY_SECONDS",
        description="Maximum backoff delay between arXiv retries",
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

    # -------------------------------------------------------------------------
    # Phase 6.5 — API Security, Authentication & Request Protection
    # -------------------------------------------------------------------------

    # API-Key Authentication
    api_auth_enabled: bool = Field(
        default=False,
        alias="API_AUTH_ENABLED",
        description=(
            "Enable API-key authentication for protected endpoints. "
            "Defaults to False so the test suite and local development remain "
            "deterministic without requiring a real key."
        ),
    )
    api_key: str = Field(
        default="",
        alias="API_KEY",
        description=(
            "Shared API key for Bearer-token authentication. "
            "Never hardcode or log this value. "
            "Only used when API_AUTH_ENABLED=true."
        ),
    )
    api_keys_json: str = Field(
        default="",
        alias="API_KEYS_JSON",
        description=(
            "JSON map or list of API keys to tenant identities for multi-tenant deployments. "
            'Example: \'{"key1": "tenant-1", "key2": "tenant-2"}\''
        ),
    )
    audit_logging_enabled: bool = Field(
        default=True,
        alias="AUDIT_LOGGING_ENABLED",
        description="Enable structured security audit logging for authentication and access events.",
    )

    # CORS Configuration
    # Stored as a raw string so pydantic-settings passes the env var through
    # without attempting JSON parsing on a comma-delimited value.
    cors_allowed_origins_raw: str = Field(
        default="http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000",
        alias="CORS_ALLOWED_ORIGINS",
        description=(
            "Comma-delimited or JSON-array list of allowed CORS origins. "
            "Wildcard '*' is disallowed when credentials are enabled."
        ),
    )

    @model_validator(mode="after")
    def _parse_cors_origins(self) -> "AppSettings":
        """Parse cors_allowed_origins_raw and store result on the model."""
        raw = self.cors_allowed_origins_raw.strip()
        if raw.startswith("["):
            try:
                parsed: list[Any] = _json.loads(raw)
                self._cors_origins = tuple(
                    str(o).strip() for o in parsed if str(o).strip()
                )
            except _json.JSONDecodeError:
                self._cors_origins = (raw,) if raw else ()
        else:
            self._cors_origins = tuple(o.strip() for o in raw.split(",") if o.strip())
        return self

    @property
    def cors_allowed_origins(self) -> tuple[str, ...]:
        """Return the parsed CORS allowed origins as a tuple of strings."""
        # Populated by _parse_cors_origins model_validator.
        return getattr(
            self,
            "_cors_origins",
            (
                "http://localhost:3000",
                "http://localhost:8080",
                "http://127.0.0.1:3000",
            ),
        )

    # Rate Limiting
    rate_limit_enabled: bool = Field(
        default=False,
        alias="RATE_LIMIT_ENABLED",
        description=(
            "Enable in-process sliding-window rate limiting on research submission endpoints. "
            "NOTE: This limiter is process-local and NOT distributed across multiple instances. "
            "For multi-instance production deployments, replace with a Redis-backed implementation "
            "via the RateLimiterProtocol interface."
        ),
    )
    rate_limit_requests: int = Field(
        default=60,
        ge=1,
        le=10000,
        alias="RATE_LIMIT_REQUESTS",
        description="Maximum number of requests allowed per rate-limit window per client IP.",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        alias="RATE_LIMIT_WINDOW_SECONDS",
        description="Sliding window duration in seconds for rate limiting.",
    )

    # Request Size Limits
    max_research_goal_length: int = Field(
        default=4000,
        ge=10,
        le=100000,
        alias="MAX_RESEARCH_GOAL_LENGTH",
        description=(
            "Maximum character length for research goal queries submitted to /api/v1/runs. "
            "Requests exceeding this limit are rejected with HTTP 422."
        ),
    )
    max_request_body_bytes: int = Field(
        default=1_048_576,  # 1 MiB
        ge=64,
        le=104_857_600,  # 100 MiB upper safety cap
        alias="MAX_REQUEST_BODY_BYTES",
        description=(
            "Maximum allowed request body size in bytes. "
            "Requests exceeding this limit are rejected at the ASGI middleware boundary "
            "with HTTP 413 before consuming the full body stream."
        ),
    )

    # Phase 6.6 — Durable Artifact Storage (GCS / In-Memory)
    artifact_storage_provider: Literal["in_memory", "gcs"] = Field(
        default="in_memory",
        alias="ARTIFACT_STORAGE_PROVIDER",
        description="Underlying storage provider for durable research artifacts ('in_memory' or 'gcs').",
    )
    gcs_bucket: str = Field(
        default="researchmind-artifacts",
        alias="GCS_BUCKET",
        description="Google Cloud Storage bucket name for persistent artifact storage.",
    )
    gcs_project: str | None = Field(
        default=None,
        alias="GCS_PROJECT",
        description="Google Cloud Platform project ID for GCS operations (defaults to GCP_PROJECT_ID if None).",
    )
    gcs_prefix: str = Field(
        default="artifacts",
        alias="GCS_PREFIX",
        description="Object path prefix for research artifacts in GCS.",
    )
    gcs_artifact_retention_days: int | None = Field(
        default=None,
        alias="GCS_ARTIFACT_RETENTION_DAYS",
        description="Optional retention lifecycle in days for research artifacts.",
    )
    gcs_signed_url_expiration_seconds: int = Field(
        default=3600,
        ge=60,
        le=604800,
        alias="GCS_SIGNED_URL_EXPIRATION_SECONDS",
        description="Expiration duration in seconds for GCS signed download URLs (default 1 hour).",
    )

    # Phase 6.7 — Distributed OpenTelemetry Tracing & Observability
    otel_enabled: bool = Field(
        default=False,
        alias="OTEL_ENABLED",
        description="Enable OpenTelemetry distributed tracing and metrics export.",
    )
    otel_service_name: str = Field(
        default="researchmind",
        alias="OTEL_SERVICE_NAME",
        description="OpenTelemetry logical service name for resource identification.",
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317",
        alias="OTEL_EXPORTER_OTLP_ENDPOINT",
        description="OTLP collector gRPC/HTTP endpoint URL.",
    )
    otel_sampling_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        alias="OTEL_SAMPLING_RATIO",
        description="Trace sampling ratio between 0.0 (none) and 1.0 (all).",
    )
    log_pii_scrubbing_enabled: bool = Field(
        default=True,
        alias="LOG_PII_SCRUBBING_ENABLED",
        description="Enable automated regex sanitization of credentials and PII in logs.",
    )

    # Phase 6.9 — Autonomous Self-Correction & Refinement Loop
    max_refinement_loops: int = Field(
        default=2,
        ge=0,
        le=5,
        alias="MAX_REFINEMENT_LOOPS",
        description="Maximum iterative refinement and self-correction cycles.",
    )
    refinement_enabled: bool = Field(
        default=True,
        alias="REFINEMENT_ENABLED",
        description="Enable autonomous self-correction and inquiry refinement when evaluation score < 0.85.",
    )

    # Phase 7.1 — Production Reliability, Worker Leases & Automatic Failure Recovery
    worker_lease_enabled: bool = Field(
        default=True,
        alias="WORKER_LEASE_ENABLED",
        description="Enable worker lease ownership and heartbeat renewal during job processing.",
    )
    worker_heartbeat_interval_seconds: float = Field(
        default=10.0,
        ge=0.5,
        le=300.0,
        alias="WORKER_HEARTBEAT_INTERVAL_SECONDS",
        description="Interval in seconds between worker lease heartbeat renewals.",
    )
    worker_lease_duration_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=600.0,
        alias="WORKER_LEASE_DURATION_SECONDS",
        description="Lease TTL duration in seconds granted to active worker before expiration.",
    )
    worker_max_recovery_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        alias="WORKER_MAX_RECOVERY_ATTEMPTS",
        description="Maximum number of failure recovery attempts before marking a run permanently FAILED.",
    )
    supervisor_scan_interval_seconds: float = Field(
        default=15.0,
        ge=0.5,
        le=300.0,
        alias="SUPERVISOR_SCAN_INTERVAL_SECONDS",
        description="Polling interval in seconds for the background lease supervisor reaper.",
    )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return a cached singleton instance of AppSettings."""
    return AppSettings()
