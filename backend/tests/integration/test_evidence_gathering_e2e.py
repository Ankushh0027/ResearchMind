"""Integration test verifying complete search, ingestion, Qdrant indexing, and retrieval flow."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.search.arxiv import ArxivSearchAdapter
from app.adapters.search.tavily import TavilySearchAdapter
from app.agents.researcher.worker import ResearcherWorker
from app.common.enums import AgentRole, TaskStatus, TaskType
from app.intelligence.ingestion import EvidenceIngestionPipeline
from app.orchestration.contracts import AgentRequest
from app.rag.embeddings import MockEmbeddingModel
from app.rag.memory import VectorMemory
from app.rag.qdrant import QdrantVectorStore
from tests.unit.test_qdrant_store import FakeQdrantClient


class TestEvidenceGatheringE2E:
    """End-to-end integration test proving search -> ingestion -> Qdrant vector memory -> retrieval."""

    @pytest.mark.asyncio
    async def test_tavily_search_to_qdrant_indexing_and_retrieval(self) -> None:
        """Verify web search results pass through untrusted envelope quarantine, chunking, Qdrant indexing, and semantic search."""
        # 1. Setup mock Tavily HTTP response
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Quantum Error Correction Principles",
                    "url": "https://example.org/quantum-ecc",
                    "content": "Surface codes provide a high threshold for fault-tolerant quantum computation with 2D nearest-neighbor coupling.",
                    "score": 0.95,
                    "published_date": "2026-01-10",
                },
                {
                    "title": "Superconducting Qubits Scaling",
                    "url": "https://example.org/superconducting",
                    "content": "Transmon qubits remain the leading modality for scalable multi-qubit quantum processors.",
                    "score": 0.88,
                    "published_date": "2026-02-15",
                },
            ]
        }
        mock_http.post = AsyncMock(return_value=mock_response)

        search_adapter = TavilySearchAdapter(
            api_key="tvly-mock-key",
            client=mock_http,
        )

        # 2. Setup VectorMemory with QdrantVectorStore and MockEmbeddingModel
        fake_qdrant = FakeQdrantClient()
        vector_store = QdrantVectorStore(dimension=32, client=fake_qdrant)
        embedding_model = MockEmbeddingModel(dimension=32)
        vector_memory = VectorMemory(
            vector_store=vector_store,
            embedding_model=embedding_model,
            collection_name="e2e_evidence",
        )
        ingestion_pipeline = EvidenceIngestionPipeline(vector_memory=vector_memory)

        # 3. Setup ResearcherWorker
        researcher = ResearcherWorker(
            search_client=search_adapter,
            ingestion_pipeline=ingestion_pipeline,
            vector_memory=vector_memory,
        )

        # 4. Dispatch AgentRequest
        run_id = "run_e2e_qdrant_001"
        request = AgentRequest(
            request_id="req_001",
            run_id=run_id,
            subtask_id="subtask_search_01",
            agent_role=AgentRole.RESEARCHER,
            task_type=TaskType.WEB_SEARCH,
            goal_context="Research fault-tolerant quantum error correction",
            idempotency_key="idemp_001",
            input_data={
                "queries": ["quantum error correction fault tolerance"],
                "max_results_per_query": 2,
                "index_in_vector_memory": True,
            },
        )

        envelope = await researcher.execute(request)

        # 5. Validate execution envelope
        assert envelope.status == TaskStatus.COMPLETED
        assert envelope.response is not None
        output = envelope.response.output_data
        assert output["total_evidence_gathered"] == 2
        assert output["quarantined_count"] == 0

        # 6. Verify evidence was indexed in Qdrant store
        assert "e2e_evidence" in fake_qdrant.collections
        assert len(fake_qdrant.collections["e2e_evidence"]) > 0

        # 7. Perform semantic retrieval from VectorMemory
        retrieved = await vector_memory.similarity_search(
            query="fault-tolerant surface codes",
            limit=2,
            run_id=run_id,
            min_score=-1.0,
        )

        assert len(retrieved) >= 1
        all_contents = [r.normalized_content for r in retrieved]
        all_urls = [r.provenance.source_url for r in retrieved]
        assert any(
            "Surface codes provide a high threshold" in content
            for content in all_contents
        )
        assert "https://example.org/quantum-ecc" in all_urls
        assert all(r.run_id == run_id for r in retrieved)

    @pytest.mark.asyncio
    async def test_arxiv_search_to_qdrant_indexing_and_isolation(self) -> None:
        """Verify academic search results are ingested into Qdrant with multi-tenant run_id isolation."""
        # 1. Setup mock arXiv HTTP response
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>http://arxiv.org/abs/2601.99999v1</id>
            <title>State-of-the-Art Autonomous Multi-Agent Orchestration</title>
            <summary>We present a verified DAG execution engine with deterministic state transitions.</summary>
            <author><name>Dr. Ada Lovelace</name></author>
            <published>2026-01-20T00:00:00Z</published>
          </entry>
        </feed>
        """
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = sample_xml
        mock_http.get = AsyncMock(return_value=mock_response)

        arxiv_adapter = ArxivSearchAdapter(client=mock_http)

        # 2. Setup VectorMemory with QdrantVectorStore
        fake_qdrant = FakeQdrantClient()
        vector_store = QdrantVectorStore(dimension=32, client=fake_qdrant)
        embedding_model = MockEmbeddingModel(dimension=32)
        vector_memory = VectorMemory(
            vector_store=vector_store,
            embedding_model=embedding_model,
            collection_name="arxiv_evidence",
        )

        researcher = ResearcherWorker(
            academic_search_client=arxiv_adapter,
            vector_memory=vector_memory,
        )

        run_a = "run_alpha"
        req_a = AgentRequest(
            request_id="req_alpha",
            run_id=run_a,
            subtask_id="sub_a",
            agent_role=AgentRole.RESEARCHER,
            task_type=TaskType.ACADEMIC_SEARCH,
            goal_context="Research multi-agent execution engines",
            idempotency_key="idemp_alpha",
            input_data={"queries": ["autonomous multi-agent"]},
        )

        envelope_a = await researcher.execute(req_a)
        assert envelope_a.status == TaskStatus.COMPLETED

        # Verify retrieval with run_a isolation
        results_a = await vector_memory.similarity_search(
            "multi-agent orchestration", run_id=run_a
        )
        assert len(results_a) == 1
        assert "DAG execution engine" in results_a[0].normalized_content

        # Verify retrieval with different run_id returns nothing (multi-tenant isolation)
        results_b = await vector_memory.similarity_search(
            "multi-agent orchestration", run_id="run_beta"
        )
        assert len(results_b) == 0
