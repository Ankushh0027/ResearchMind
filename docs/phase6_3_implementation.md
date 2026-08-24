# Phase 6.3: Live Intelligence Adapters Implementation

## Overview

Phase 6.3 introduces production-ready, provider-agnostic live adapters for **Google Gemini Large Language Models (LLM)** and **Google Gemini Embeddings**, while preserving all existing protocols (`LLMClientProtocol` and `EmbeddingModelProtocol`), dependency injection, and deterministic in-memory mock implementations for local testing and zero-configuration development.

---

## Architecture & Provider Boundaries

```
+-------------------------------------------------------------------------+
|                  ResearchMind Intelligence Architecture                  |
+-------------------------------------------------------------------------+
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │             Agents & Intelligence Pipelines            │
       │   Planner, Analyst, Verifier, Evaluator, Reporter, RAG │
       └────────────────────────────┬───────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
       ┌─────────────────────────┐     ┌─────────────────────────┐
       │    LLMClientProtocol    │     │ EmbeddingModelProtocol  │
       │  generate_text()        │     │  embed_text()           │
       │  generate_structured()  │     │  embed_batch()          │
       └────────────┬────────────┘     └────────────┬────────────┘
                    │                               │
          ┌─────────┴─────────┐           ┌─────────┴─────────┐
          ▼                   ▼           ▼                   ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  MockLLMClient   │ │GeminiLLM     │ │MockEmbedding │ │Gemini        │
│  (local/testing) │ │Client (Live) │ │Model (local) │ │EmbeddingModel│
└──────────────────┘ └───────┬──────┘ └──────────────┘ └───────┬──────┘
                             │                                 │
                             ▼                                 ▼
                     ┌───────────────┐                 ┌───────────────┐
                     │ Google GenAI  │                 │ Google GenAI  │
                     │ Models API    │                 │ Embeddings    │
                     └───────────────┘                 └───────────────┘
```

---

## 1. Gemini LLM Adapter (`app.adapters.llm.gemini.GeminiLLMClient`)

The `GeminiLLMClient` implements `LLMClientProtocol` and interfaces with Google's modern `google-genai` SDK:

- **Unstructured Text Generation (`generate_text`)**:
  - Submits user prompt with system instructions, temperature, and token bounds.
  - Returns standardized `LLMResponse` envelope with extracted token counts and metadata.
- **Structured Pydantic Generation (`generate_structured`)**:
  - Configures `response_mime_type="application/json"` and binds `response_schema`.
  - Deserializes and validates the model response directly into the target Pydantic schema (e.g. `PlannedDecomposition`, `ExtractedClaim`, `KeyFinding`).
- **Resilience & Exponential Retry Backoff**:
  - Bounded retry loop (`max_retries`, default 3).
  - Handles transient status codes (429 Rate Limit / Quota Exhausted, 500 Internal Error, 502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout) and transport/connection timeouts.
  - Exponential delay with random jitter: `delay = min(max_delay, initial_delay * (2 ** attempt)) * uniform(0.8, 1.2)`.
  - Non-retryable errors (e.g., 400 Bad Request, schema validation errors, input errors) fail immediately without retrying.
  - Task cancellation (`asyncio.CancelledError`) cleanly interrupts sleep and aborts in-flight operations.
- **Credential Protection**:
  - Never logs or exposes raw `GEMINI_API_KEY` values in logs, exceptions, or error envelopes.
  - Masking helper `_mask_api_key` sanitizes keys to `AIza...cret`.

---

## 2. Gemini Embedding Adapter (`app.rag.gemini.GeminiEmbeddingModel`)

The `GeminiEmbeddingModel` implements `EmbeddingModelProtocol` for dense semantic vector generation:

- **Dimensionality**: Configured for 768 dimensions (`text-embedding-004`).
- **Single & Batch Generation**:
  - `embed_text(text: str) -> tuple[float, ...]`: Embeds a single query or document.
  - `embed_batch(texts: list[str]) -> list[tuple[float, ...]]`: Batches multiple text strings in a single provider call.
  - `embed_chunk(chunk: TextChunk) -> EmbeddingRecord`: Builds immutable `EmbeddingRecord` maintaining provenance (`chunk_id`, `evidence_id`, `run_id`).
- **Strict Vector Validation**:
  - Validates components are non-empty, finite numeric floats (no `NaN`, no `Inf`), and match declared dimension.
- **Retry Handling**: Exponential backoff with jitter on 429 quota exhaustion and 5xx server errors.

---

## 3. Configuration Contract

Environment configuration in `app.config.settings.AppSettings`:

| Setting Variable | Type | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | `Literal["in_memory", "mock", "gemini"]` | `"in_memory"` | Active LLM client implementation |
| `EMBEDDING_PROVIDER` | `Literal["in_memory", "mock", "gemini"]` | `"in_memory"` | Active Embedding model implementation |
| `GEMINI_API_KEY` | `str` | `""` | Google Gemini API Key |
| `GEMINI_MODEL` | `str` | `"gemini-2.5-pro"` | Default reasoning LLM model |
| `GEMINI_FAST_MODEL` | `str` | `"gemini-2.5-flash"` | Fast extraction/triage LLM model |
| `GEMINI_EMBEDDING_MODEL` | `str` | `"text-embedding-004"` | Dense vector embedding model |
| `GEMINI_TEMPERATURE` | `float` | `0.2` | Sampling temperature |
| `GEMINI_MAX_OUTPUT_TOKENS` | `int` | `8192` | Max token budget per response |
| `GEMINI_MAX_RETRIES` | `int` | `3` | Maximum retry attempts for transient errors |
| `GEMINI_INITIAL_RETRY_DELAY_SECONDS` | `float` | `1.0` | Initial exponential backoff delay |
| `GEMINI_MAX_RETRY_DELAY_SECONDS` | `float` | `10.0` | Cap on exponential backoff delay |

---

## 4. Factory & Dependency Injection

- **`create_llm_client(settings, client)`**:
  - `LLM_PROVIDER=in_memory` or `"mock"` → `MockLLMClient`
  - `LLM_PROVIDER=gemini` → `GeminiLLMClient`
- **`create_embedding_model(settings, client)`**:
  - `EMBEDDING_PROVIDER=in_memory` or `"mock"` → `MockEmbeddingModel`
  - `EMBEDDING_PROVIDER=gemini` → `GeminiEmbeddingModel`

---

## 5. Testing & Verification

Unit and integration test suites run entirely without making real external network calls:
- `backend/tests/unit/test_gemini_llm.py` (11 unit tests covering generation, structured output, retries, 429 backoff, 500/503, non-retryable errors, cancellation, and secret masking).
- `backend/tests/unit/test_gemini_embeddings.py` (7 unit tests covering text, batch, chunk embedding, validation, and transient retries).
- `backend/tests/unit/test_intelligence_factory.py` (5 factory tests).
- `backend/tests/integration/test_gemini_agents_e2e.py` (2 integration tests verifying PlannerAgent and AgentWorkerRouter with Gemini adapter).
