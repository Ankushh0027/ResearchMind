"""High-level VectorMemory adapter implementing VectorMemoryProtocol.

Orchestrates evidence-level chunking, batch dense vector embedding generation, in-memory vector
storage indexing, and nearest-neighbor semantic retrieval with strict run_id multi-tenant isolation
and deterministic deduplicated evidence ranking.
"""

from typing import Any

from app.common.errors import (
    EmptyVectorQueryError,
    EvidenceValidationError,
)
from app.intelligence.evidence import EvidenceRecord
from app.intelligence.protocols import VectorMemoryProtocol
from app.rag.chunking import DeterministicTextChunker, TextChunk, TextChunker
from app.rag.embeddings import (
    DEFAULT_EMBEDDING_DIMENSION,
    MockEmbeddingModel,
)
from app.rag.protocols import (
    EmbeddingModelProtocol,
    VectorPoint,
    VectorStoreProtocol,
)
from app.rag.store import DEFAULT_STORE_DIMENSION, InMemoryVectorStore

DEFAULT_COLLECTION_NAME = "research_evidence"


class VectorMemory(VectorMemoryProtocol):
    """Semantic vector memory adapter providing evidence-level indexing and similarity search."""

    def __init__(
        self,
        vector_store: VectorStoreProtocol | None = None,
        embedding_model: EmbeddingModelProtocol | None = None,
        chunker: TextChunker | None = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        if not collection_name or not collection_name.strip():
            raise EvidenceValidationError(
                "collection_name must not be empty or whitespace only"
            )
        self.collection_name = collection_name.strip()

        # Wire dependencies or instantiate provider-neutral defaults
        self.embedding_model: EmbeddingModelProtocol = (
            embedding_model
            if embedding_model is not None
            else MockEmbeddingModel(dimension=DEFAULT_EMBEDDING_DIMENSION)
        )

        dim = self.embedding_model.dimension
        self.vector_store: VectorStoreProtocol = (
            vector_store
            if vector_store is not None
            else InMemoryVectorStore(
                dimension=dim if dim > 0 else DEFAULT_STORE_DIMENSION
            )
        )

        self.chunker: TextChunker = (
            chunker if chunker is not None else DeterministicTextChunker()
        )

        # Internal evidence registry mapping evidence_id -> EvidenceRecord
        self._evidence_registry: dict[str, EvidenceRecord] = {}

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        """Retrieve a stored EvidenceRecord by its identifier."""
        return self._evidence_registry.get(evidence_id.strip())

    def count_evidence(self, run_id: str | None = None) -> int:
        """Return the count of indexed EvidenceRecords, optionally filtered by run_id."""
        if run_id is None:
            return len(self._evidence_registry)
        clean_run = run_id.strip()
        return sum(
            1 for ev in self._evidence_registry.values() if ev.run_id == clean_run
        )

    async def upsert_evidence(self, records: list[EvidenceRecord]) -> int:
        """Chunk, embed, and index a batch of EvidenceRecords into semantic vector memory."""
        if records is None or not isinstance(records, list):
            raise TypeError("records must be a list of EvidenceRecord instances")

        if not records:
            return 0

        all_chunks: list[TextChunk] = []

        for record in records:
            if not isinstance(record, EvidenceRecord):
                raise TypeError(f"Expected EvidenceRecord, got {type(record).__name__}")

            # Store in registry
            self._evidence_registry[record.evidence_id] = record

            # Chunk evidence text
            chunks = self.chunker.chunk_text(
                text=record.normalized_content,
                evidence_id=record.evidence_id,
                run_id=record.run_id,
                metadata=record.metadata,
            )
            all_chunks.extend(chunks)

        if not all_chunks:
            return len(records)

        # Generate batch dense embeddings
        texts_to_embed = [chunk.text for chunk in all_chunks]
        vectors = await self.embedding_model.embed_batch(texts_to_embed)

        # Assemble VectorPoint instances
        points: list[VectorPoint] = []
        for chunk, vec in zip(all_chunks, vectors, strict=True):
            payload: dict[str, Any] = {
                "run_id": chunk.run_id,
                "evidence_id": chunk.evidence_id,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "total_chunks": chunk.total_chunks,
                "start_char_idx": chunk.start_char_idx,
                "end_char_idx": chunk.end_char_idx,
                "text": chunk.text,
            }
            if chunk.metadata:
                payload.update(chunk.metadata)

            points.append(
                VectorPoint(
                    point_id=chunk.chunk_id,
                    vector=vec,
                    payload=payload,
                )
            )

        # Upsert into vector store
        await self.vector_store.upsert_vectors(self.collection_name, points)
        return len(records)

    async def similarity_search(
        self,
        query: str,
        limit: int = 10,
        run_id: str | None = None,
        min_score: float = 0.0,
    ) -> list[EvidenceRecord]:
        """Perform semantic similarity search over stored evidence records with run_id isolation."""
        if not query or not query.strip():
            raise EmptyVectorQueryError("query must not be empty or whitespace only")

        if limit <= 0:
            raise EvidenceValidationError(
                f"limit must be a positive integer, got {limit}",
                {"limit": limit},
            )

        clean_query = query.strip()
        query_vector = await self.embedding_model.embed_text(clean_query)

        filter_metadata: dict[str, Any] | None = None
        if run_id and run_id.strip():
            filter_metadata = {"run_id": run_id.strip()}

        # Fetch enough chunk results to yield 'limit' distinct parent evidence records
        search_limit = max(limit * 4, 20)
        raw_results = await self.vector_store.search_vectors(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=search_limit,
            filter_metadata=filter_metadata,
        )

        deduplicated_records: list[EvidenceRecord] = []
        seen_evidence_ids: set[str] = set()

        for result in raw_results:
            if result.score < min_score:
                continue

            ev_id = result.payload.get("evidence_id")
            if not ev_id or ev_id in seen_evidence_ids:
                continue

            record = self._evidence_registry.get(ev_id)
            if record is not None:
                seen_evidence_ids.add(ev_id)
                deduplicated_records.append(record)
                if len(deduplicated_records) >= limit:
                    break

        return deduplicated_records

    async def clear(self) -> None:
        """Clear all stored evidence records and vector points."""
        self._evidence_registry.clear()
        await self.vector_store.delete_collection(self.collection_name)


__all__ = [
    "DEFAULT_COLLECTION_NAME",
    "VectorMemory",
]
