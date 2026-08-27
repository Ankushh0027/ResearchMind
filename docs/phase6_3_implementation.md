# Phase 6.3 Implementation Document: Live Intelligence Adapters

## Executive Summary

Phase 6.3 integrates production-ready Google Gemini Large Language Model (LLM) and Dense Vector Embedding adapters into the ResearchMind autonomous multi-agent platform. This replaces development-only mock intelligence layers with enterprise-grade adapters while maintaining strict backward compatibility with existing agent protocols, deterministic in-memory implementations for local test suites, and robust resilience patterns.

---

## Architecture & Adapter Boundaries

ResearchMind enforces clean separation between agent reasoning orchestration and underlying AI provider APIs through provider-agnostic protocols:

```
+-------------------------------------------------------------------------------+
|                           ResearchMind Multi-Agent DAG                        |
|   (PlannerWorker, ResearcherWorker, AnalystWorker, VerifierWorker, ...)       |
+---------------------------------------+---------------------------------------+
                                        |
                   +--------------------+--------------------+
                   |                                         |
                   v                                         v
     [ LLMClientProtocol ]                       [ EmbeddingModelProtocol ]
     - generate_text()                           - embed_text()
     - generate_structured()                     - embed_batch()
                   |                             - embed_chunk()
        +----------+----------+                              |
        |                     |                   +----------+----------+
        v                     v                   v                     v
[ MockLLMClient ]     [ GeminiLLMClient ] [ MockEmbeddingModel ] [ GeminiEmbeddingModel ]
  (Unit/Local Tests)    (Google GenAI SDK)  (Unit/Local Tests)     (Google GenAI SDK)
```

### Protocol Contracts

1. **`LLMClientProtocol`** (`app.adapters.llm.base`):
   - `generate_text(request: LLMRequest) -> LLMResponse`: Generates unstructured text or tool invocations with token metadata.
   - `generate_structured(system_prompt: str, user_prompt: str, response_schema: type[T], temperature: float) -> T`: Generates structured outputs guaranteed to deserialize and validate into the specified Pydantic schema `T`.

2. **`EmbeddingModelProtocol`** (`app.rag.protocols`):
   - `dimension: int`: Exposes vector dimensionality (e.g. 768 for `text-embedding-004`).
   - `embed_text(text: str) -> tuple[float, ...]`: Generates a dense float vector for a single text.
   - `embed_batch(texts: list[str]) -> list[tuple[float, ...]]`: Generates dense float vectors for a batch of strings.
   - `embed_chunk(chunk: TextChunk) -> EmbeddingRecord`: Embeds an upstream `TextChunk` into an immutable `EmbeddingRecord`.

---

## Configuration & Environment Variables

All adapter settings are environment-driven using Pydantic Settings (`app.config.settings.AppSettings`).

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `LLM_PROVIDER` | `Literal["in_memory", "mock", "gemini"]` | `in_memory` | Active LLM inference provider backend. |
| `EMBEDDING_PROVIDER` | `Literal["in_memory", "mock", "gemini"]` | `in_memory` | Active embedding model backend. |
| `GEMINI_API_KEY` | `str` | `""` | Google AI Studio or Vertex AI Gemini API key. |
| `GEMINI_MODEL` | `str` | `gemini-2.5-pro` | Default reasoning model for agent decomposition and synthesis. |
| `GEMINI_FAST_MODEL` | `str` | `gemini-2.5-flash` | Fast model for extraction and triage tasks. |
| `GEMINI_EMBEDDING_MODEL` | `str` | `text-embedding-004` | Model for generating 768-dimensional dense vector embeddings. |
| `GEMINI_TEMPERATURE` | `float` | `0.2` | Sampling temperature for deterministic agent reasoning. |
| `GEMINI_MAX_OUTPUT_TOKENS`| `int` | `8192` | Maximum output tokens per inference call. |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | `float` | `60.0` | Timeout per HTTP/gRPC API invocation. |
| `GEMINI_MAX_RETRIES` | `int` | `3` | Maximum retry attempts on transient network or provider errors. |
| `GEMINI_INITIAL_RETRY_DELAY_SECONDS` | `float` | `1.0` | Initial exponential backoff delay base. |
| `GEMINI_MAX_RETRY_DELAY_SECONDS` | `float` | `10.0` | Maximum bounded backoff delay between retries. |

---

## Reliability & Retry Policy

### Transient vs. Permanent Error Classification

The adapter implements strict failure classification to avoid infinite loops on unrecoverable errors:

* **Retryable Errors** (Exponential Backoff with Full Jitter):
  * HTTP `429` (Rate Limit / `RESOURCE_EXHAUSTED` / Quota)
  * HTTP `500` (Internal Server Error)
  * HTTP `502` (Bad Gateway)
  * HTTP `503` (Service Unavailable)
  * HTTP `504` (Gateway Timeout)
  * `asyncio.TimeoutError` / `TimeoutError` (Deadline Exceeded)
  * Transient network disconnects (`CONNECTION_RESET`, `TEMPORARY`)

* **Non-Retryable Errors** (Fail Fast Immediately):
  * HTTP `400` / `INVALID_ARGUMENT` / Malformed prompt
  * HTTP `401` / `UNAUTHENTICATED` / Invalid API Key
  * HTTP `403` / `PERMISSION_DENIED`
  * HTTP `404` / `NOT_FOUND`
  * Pydantic `ValidationError` / Input schema mismatches

### Bounded Backoff Formula

$$\text{delay} = \min(\text{max\_delay}, \text{initial\_delay} \times 2^{\text{attempt}}) \times \text{uniform}(0.8, 1.2)$$

---

## Structured Output Handling

ResearchMind agents (Planner, Analyst, Verifier, Evaluator, Reporter) consume typed Pydantic models. The `GeminiLLMClient.generate_structured()` method guarantees type safety:

1. **Native Structured Generation**: Utilizes the Google GenAI SDK `response_schema=response_schema` and `response_mime_type="application/json"` parameters.
2. **Multi-tier Response Resolution**:
   - Schema instance directly returned.
   - Parsed SDK dictionary payload (`response.parsed`) validated via `model_validate()`.
   - Raw JSON string (`response.text`) deserialized and validated via `model_validate_json()`.
3. **Strict Error Propagation**: If the model produces invalid or incomplete JSON, `ValueError` is raised with the validation error details.

---

## Token Accounting

Token usage metadata is extracted directly from Google GenAI responses:

* `prompt_tokens`: extracted from `usage_metadata.prompt_token_count`
* `completion_tokens`: extracted from `usage_metadata.candidates_token_count`
* `total_tokens`: extracted from `usage_metadata.total_token_count` or calculated as `prompt + completion`

If usage metadata is absent (e.g. mock responses or partial streaming), fields safely default to `0` without breaking downstream aggregation.

---

## Dense Embedding Generation

* **Model**: Google `text-embedding-004`.
* **Dimension**: 768 (strictly enforced by `validate_dense_vector`).
* **Batch Ingestion**: Supports batches of text chunks, preserving order and mapping chunk IDs to `EmbeddingRecord` objects.
* **Integrity Validation**: Rejects `NaN`, `Inf`, and dimension mismatches with typed `EvidenceValidationError` and `VectorDimensionMismatchError`.

---

## Security & Secret Handling

* **Zero Hardcoded Secrets**: Secrets are never hardcoded in source, committed files, or tests.
* **Safe Key Masking**: The `_mask_api_key()` helper formats keys as `AIza...cret` or `***` for all logger outputs.
* **Isolated Environment Loading**: In tests, mock clients or fake keys are injected without making network calls.
* **Gitignore Protections**: `.env`, `.env.*` (except `.env.example`), and credential JSON files are ignored.

---

## Quality Gates & Verification

Local and CI verification requirements:

1. **Pytest**: 540+ passing unit and integration tests (`python -m pytest`).
2. **Ruff Linter**: Zero lint issues (`ruff check .`).
3. **Ruff Formatter**: Strict formatting (`ruff format --check .`).
4. **Mypy**: Strict type-checking (`mypy --python-version 3.12 backend/app backend/tests`).

---

## Limitations & Next Steps

* **Current Scope (Phase 6.3)**: Real Gemini LLM and Embedding adapters enabled with full fallback mocks.
* **Upcoming (Phase 6.4)**: Real Qdrant vector database persistence and live web/search tool adapters.
