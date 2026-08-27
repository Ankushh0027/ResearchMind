# ResearchMind Phase 6.4 — Live Vector Database & Real Evidence Gathering Implementation

## 1. Architecture Overview

Phase 6.4 introduces production-ready vector database persistence and real-world evidence gathering adapters into ResearchMind, replacing mock vector indexing and search infrastructure with high-performance cloud providers while maintaining 100% backward compatibility with deterministic in-memory implementations.

```
+-----------------------------------------------------------------------------------+
|                              Researcher Worker                                    |
|                                                                                   |
|  +---------------------------+             +----------------------------------+   |
|  |    SearchClientProtocol   |             |   EvidenceIngestionPipeline      |   |
|  | +-----------------------+ |             |  +----------------------------+  |   |
|  | |  TavilySearchAdapter  | |             |  |  SSRF URL Safety Check     |  |   |
|  | |  ArxivSearchAdapter   | |             |  |  Content Boundary Wrap     |  |   |
|  | |  MockSearchClient     | |             |  |  UntrustedContentEnvelope  |  |   |
|  | +-----------------------+ |             |  +----------------------------+  |   |
|  +---------------------------+             +----------------------------------+   |
+-------------------------------------------------------------|---------------------+
                                                              |
                                                              v
+-----------------------------------------------------------------------------------+
|                              Vector Memory Layer                                  |
|                                                                                   |
|  +--------------------------------+        +----------------------------------+   |
|  |    EmbeddingModelProtocol      |        |       VectorStoreProtocol        |   |
|  |  +--------------------------+  |        |  +----------------------------+  |   |
|  |  | GeminiEmbeddingModel     |  |        |  | QdrantVectorStore          |  |   |
|  |  | MockEmbeddingModel       |  |        |  | InMemoryVectorStore        |  |   |
|  |  +--------------------------+  |        |  +----------------------------+  |   |
|  +--------------------------------+        +----------------------------------+   |
+-----------------------------------------------------------------------------------+
```

---

## 2. Provider Interfaces & Contracts

The implementation strictly preserves the provider-neutral protocols:

### Vector Store Protocol (`VectorStoreProtocol`)
```python
class VectorStoreProtocol(Protocol):
    async def upsert_vectors(
        self, collection_name: str, points: list[VectorPoint]
    ) -> int: ...

    async def search_vectors(
        self,
        collection_name: str,
        query_vector: tuple[float, ...] | list[float],
        limit: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]: ...

    async def delete_collection(self, collection_name: str) -> None: ...
```

### Search Client Protocol (`SearchClientProtocol`)
```python
class SearchClientProtocol(Protocol):
    async def search(self, query: SearchQuery) -> list[SearchHit]: ...
```

---

## 3. Qdrant Collection & Schema Design

`QdrantVectorStore` manages dense vector indexing in Qdrant:

* **Collection Name**: Configurable per environment via `QDRANT_COLLECTION_NAME` (default: `"research_evidence"`).
* **Vector Dimensionality**: 768 dimensions by default (`QDRANT_VECTOR_SIZE`), matching `text-embedding-004`.
* **Distance Metric**: `Distance.COSINE` (configurable: `Cosine`, `Euclid`, `Dot`).
* **Point Identifiers**: String UUIDs or deterministic UUID5 generation for custom string identifiers (`_to_valid_qdrant_id`).
* **Auto-Provisioning**: Automatic collection verification and creation on first write (`ensure_collection`).

---

## 4. Payload Metadata Architecture

Every vector point indexed into Qdrant stores rich, multi-tenant provenance metadata:

| Field | Type | Description |
| :--- | :--- | :--- |
| `point_id` | `str` | Original chunk or entity identifier |
| `run_id` | `str` | Tenant / session isolation identifier |
| `evidence_id` | `str` | Parent EvidenceRecord UUID |
| `chunk_id` | `str` | Unique chunk identifier |
| `chunk_index` | `int` | Sequential chunk index within parent |
| `total_chunks`| `int` | Total number of chunks in parent document |
| `start_char_idx` | `int` | Character start offset in raw document |
| `end_char_idx` | `int` | Character end offset in raw document |
| `text` | `str` | Chunk text content |
| `trust_tier` | `str` | Source trust level classification |

---

## 5. Search Provider Architecture

### Tavily Web Search Adapter (`TavilySearchAdapter`)
* Dispatches requests to Tavily Search API (`POST https://api.tavily.com/search`).
* Normalizes JSON results into `SearchHit` models with titles, snippets, relevance scores, extracted domain names, and publication dates.
* Automatic API key masking to prevent credential leakage in logs.

### arXiv Academic Search Adapter (`ArxivSearchAdapter`)
* Public arXiv Atom XML API integration (`GET https://export.arxiv.org/api/query`).
* XML Atom parser extracting entry ID, alternate URLs, titles, abstracts, authors, and publication dates.
* Graceful handling of malformed XML or empty response feeds.

---

## 6. Retry & Timeout Policies

All live network adapters implement bounded exponential backoff with full jitter:

* **Qdrant**: Default 30.0s timeout, 3 retries, initial delay 0.5s, max delay 5.0s.
* **Tavily**: Default 15.0s timeout, 3 retries, initial delay 1.0s, max delay 10.0s.
* **arXiv**: Default 20.0s timeout, 3 retries, initial delay 1.0s, max delay 10.0s.
* **Classification**: Retries HTTP 429, 500, 502, 503, 504, `TimeoutError`, and network errors. Fails fast on 400, 401, 403, and 404.

---

## 7. Configuration Reference

```ini
# Vector Store
VECTOR_STORE_PROVIDER=in_memory|mock|qdrant
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
QDRANT_COLLECTION_NAME=research_evidence
QDRANT_VECTOR_SIZE=768
QDRANT_DISTANCE=Cosine
QDRANT_REQUEST_TIMEOUT_SECONDS=30.0
QDRANT_MAX_RETRIES=3

# Search Providers
SEARCH_PROVIDER=in_memory|mock|tavily|arxiv
ACADEMIC_SEARCH_PROVIDER=in_memory|mock|arxiv|tavily
TAVILY_API_KEY=tvly-...
TAVILY_API_URL=https://api.tavily.com/search
TAVILY_REQUEST_TIMEOUT_SECONDS=15.0
TAVILY_MAX_RETRIES=3
ARXIV_API_URL=https://export.arxiv.org/api/query
ARXIV_REQUEST_TIMEOUT_SECONDS=20.0
ARXIV_MAX_RETRIES=3
```

---

## 8. Security & SSRF Protection

1. **SSRF Boundary (`validate_url_safety`)**: Blocks localhost, loopback (`127.0.0.0/8`, `::1`), private RFC1918 networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`, `fe80::/10`), and cloud metadata IP addresses (`169.254.169.254`, `metadata.google.internal`).
2. **Untrusted Content Envelope**: All external search results are wrapped in `UntrustedContentEnvelope` with control tokens and hazardous injection prompts quarantined before entering LLM reasoning context.

---

## 9. Local Development with In-Memory Providers

Local testing and CI require no live external services:

```bash
# In .env or test environments:
VECTOR_STORE_PROVIDER=in_memory
SEARCH_PROVIDER=in_memory
ACADEMIC_SEARCH_PROVIDER=in_memory
```

---

## 10. Production Deployment Configuration

For production deployment:

```bash
VECTOR_STORE_PROVIDER=qdrant
QDRANT_URL=https://your-qdrant-cluster.qdrant.tech:6333
QDRANT_API_KEY=your_qdrant_api_key

SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your_tavily_api_key

ACADEMIC_SEARCH_PROVIDER=arxiv
```

---

## 11. Migration from Phase 6.3

Phase 6.4 is fully backward-compatible with Phase 6.3:
* Existing code using `InMemoryVectorStore` and `MockSearchClient` continues to work with zero code changes.
* `VectorMemory` seamlessly accepts `QdrantVectorStore` or `InMemoryVectorStore`.
* `ResearcherWorker` dynamically wires search adapters through `create_search_client` and `create_academic_search_client`.

---

## 12. Known Limitations & Roadmap

* **Phase 6.5**: API authentication (Bearer tokens / JWT), global rate limiting, CORS tightening, and request size limits.
* **Phase 6.6**: Durable Cloud Storage (GCS) artifact archiving.
* **Phase 6.7**: Distributed OpenTelemetry tracing and structured metrics.
