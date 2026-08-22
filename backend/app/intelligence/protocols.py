"""Provider-neutral protocols for intelligence agents, search, LLM, and vector memory."""

from typing import Protocol, runtime_checkable

from app.adapters.llm.base import LLMClientProtocol
from app.adapters.search.base import SearchClientProtocol
from app.common.evidence import EvidenceRecord


@runtime_checkable
class VectorMemoryProtocol(Protocol):
    """Protocol for high-level semantic evidence storage and retrieval."""

    async def upsert_evidence(self, records: list[EvidenceRecord]) -> int:
        """Embed and index evidence records into semantic vector memory."""
        ...

    async def similarity_search(
        self,
        query: str,
        limit: int = 10,
        run_id: str | None = None,
        min_score: float = 0.0,
    ) -> list[EvidenceRecord]:
        """Perform semantic similarity search over stored evidence records."""
        ...


__all__ = [
    "LLMClientProtocol",
    "SearchClientProtocol",
    "VectorMemoryProtocol",
]
