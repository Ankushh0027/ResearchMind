# Retrieval-Augmented Generation (RAG) Architecture

This document describes the indexing, chunking, embedding, and hybrid retrieval strategy utilized by ResearchMind.

---

## 1. Document Ingestion & Chunking Strategy

1. **Extraction**: Raw content is extracted from HTML web pages, PDF whitepapers, and uploaded reference files into clean markdown representations.
2. **Semantic Chunking**: Documents are split into semantic chunks (300-500 tokens) with 50-token overlap, preserving header hierarchy and code block integrity.
3. **Metadata Enrichment**: Each chunk is annotated with:
   - `run_id`: Multi-tenant session identifier.
   - `source_url`: Full citation URL.
   - `title`: Document title.
   - `chunk_index`: Position within original document.
   - `created_at`: Ingestion timestamp.

---

## 2. Vector Indexing with Qdrant & Gemini Embeddings

- **Embedding Model**: Google `text-embedding-004` (768-dimensional dense vectors).
- **Vector Database**: **Qdrant** cluster (managed cloud or local container).
- **Index Configuration**: Cosine distance with HNSW indexing for sub-millisecond retrieval.
- **Payload Filtering**: Every query enforces a hard payload filter on `run_id` to guarantee cross-run data isolation.

---

## 3. Hybrid Retrieval & Re-ranking

```
Inquiry Query
     │
     ├──► Dense Vector Search (Qdrant semantic similarity)
     └──► Sparse Keyword Search (BM25 / lexical exact match)
                 │
                 ▼
          Reciprocal Rank Fusion (RRF)
                 │
                 ▼
          Re-ranking & Deduplication
                 │
                 ▼
          Top-K Grounded Context -> Analyst & Verifier Agents
```

- **Dense + Sparse Fusion**: Mitigates out-of-vocabulary failures for specialized technical terms, acronyms, and product codes.
- **Context Compression**: The RAG agent trims redundant text before injecting snippets into prompt contexts, optimizing token efficiency.
