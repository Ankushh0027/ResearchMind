"""ResearcherWorker adapter executing web search, academic search, and document analysis tasks."""

import time
import uuid
from typing import Any

from app.adapters.search.base import (
    SearchClientProtocol,
    SearchHit,
    SearchQuery,
)
from app.adapters.search.mock_search import MockSearchClient
from app.common.enums import AgentRole, SourceTrustLevel, TaskStatus, TaskType
from app.common.errors import (
    EvidenceIngestionError,
    EvidenceValidationError,
    ResearchMindError,
)
from app.intelligence.evidence import EvidenceRecord
from app.intelligence.ingestion import (
    EvidenceIngestionPipeline,
    RawDocument,
)
from app.intelligence.protocols import VectorMemoryProtocol
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol
from app.rag.memory import VectorMemory

SUPPORTED_RESEARCHER_TASK_TYPES = {
    TaskType.WEB_SEARCH,
    TaskType.ACADEMIC_SEARCH,
    TaskType.DOC_ANALYSIS,
}


class ResearcherWorker(WorkerProtocol):
    """WorkerProtocol adapter executing research tasks and ingesting evidence into VectorMemory."""

    def __init__(
        self,
        search_client: SearchClientProtocol | None = None,
        academic_search_client: SearchClientProtocol | None = None,
        ingestion_pipeline: EvidenceIngestionPipeline | None = None,
        vector_memory: VectorMemoryProtocol | None = None,
        worker_id: str = "researcher-worker-01",
    ) -> None:
        self.search_client = search_client or MockSearchClient()
        self.academic_search_client = academic_search_client or self.search_client
        self.vector_memory: VectorMemoryProtocol = vector_memory or VectorMemory()
        self.ingestion_pipeline = ingestion_pipeline or EvidenceIngestionPipeline(
            vector_memory=self.vector_memory
        )
        self.worker_id = worker_id

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Execute research subtask and return sanitized, indexed evidence in WorkerResponseEnvelope."""
        # 1. Validate run_id
        if not request.run_id or not request.run_id.strip():
            err = AgentError(
                error_code="INVALID_RUN_ID",
                error_type="EvidenceValidationError",
                message="run_id must not be empty or whitespace only",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        clean_run_id = request.run_id.strip()

        # 2. Validate agent role
        if request.agent_role != AgentRole.RESEARCHER:
            err = AgentError(
                error_code="UNSUPPORTED_ROLE",
                error_type="ValueError",
                message=f"ResearcherWorker expects AgentRole.RESEARCHER, got '{request.agent_role}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 3. Validate task type
        if request.task_type not in SUPPORTED_RESEARCHER_TASK_TYPES:
            err = AgentError(
                error_code="UNSUPPORTED_TASK_TYPE",
                error_type="ValueError",
                message=f"ResearcherWorker does not support task type '{request.task_type}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        start_time = time.perf_counter()

        # 4. Extract and validate queries / documents based on task_type
        raw_documents_to_ingest: list[RawDocument] = []
        max_results = int(request.input_data.get("max_results_per_query", 5))

        try:
            if request.task_type in (TaskType.WEB_SEARCH, TaskType.ACADEMIC_SEARCH):
                queries = self._extract_queries(request)
                if not queries:
                    err = AgentError(
                        error_code="INVALID_RESEARCHER_INPUT",
                        error_type="ValueError",
                        message="Search queries must not be empty",
                        is_retryable=False,
                    )
                    return self._build_error_envelope(request, err)

                client = (
                    self.academic_search_client
                    if request.task_type == TaskType.ACADEMIC_SEARCH
                    else self.search_client
                )
                trust_level = (
                    SourceTrustLevel.PEER_REVIEWED
                    if request.task_type == TaskType.ACADEMIC_SEARCH
                    else SourceTrustLevel.GENERAL_WEB
                )
                source_type = (
                    "academic_paper"
                    if request.task_type == TaskType.ACADEMIC_SEARCH
                    else "web"
                )

                for query_str in queries:
                    search_query = SearchQuery(
                        query=query_str,
                        max_results=max_results,
                    )
                    hits: list[SearchHit] = await client.search(search_query)

                    for hit in hits:
                        raw_doc = RawDocument(
                            source_url=hit.url,
                            title=hit.title,
                            raw_text=hit.snippet if hit.snippet.strip() else hit.title,
                            domain=hit.domain,
                            authors=hit.authors,
                            publication_date=hit.publication_date,
                            trust_level=trust_level,
                            source_type=source_type,
                            metadata={"query": query_str, "score": hit.score},
                        )
                        raw_documents_to_ingest.append(raw_doc)

            elif request.task_type == TaskType.DOC_ANALYSIS:
                raw_documents_to_ingest = self._extract_documents(request)
                if not raw_documents_to_ingest:
                    err = AgentError(
                        error_code="INVALID_RESEARCHER_INPUT",
                        error_type="ValueError",
                        message="No valid documents provided for DOC_ANALYSIS",
                        is_retryable=False,
                    )
                    return self._build_error_envelope(request, err)

        except TimeoutError as e:
            err = AgentError(
                error_code="SEARCH_TIMEOUT",
                error_type="TimeoutError",
                message=f"Search adapter timed out: {e}",
                is_retryable=True,
            )
            return self._build_error_envelope(request, err)
        except ResearchMindError as e:
            err = AgentError(
                error_code="RESEARCH_MIND_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except Exception as e:
            err = AgentError(
                error_code="SEARCH_ADAPTER_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=True,
            )
            return self._build_error_envelope(request, err)

        # 5. Ingest through EvidenceIngestionPipeline (Sanitization, Hashing, Dedup)
        ingested_records: list[EvidenceRecord] = []
        quarantined_count = 0
        duplicate_count = 0

        try:
            for raw_doc in raw_documents_to_ingest:
                ingestion_res = await self.ingestion_pipeline.ingest_document(
                    raw_doc,
                    run_id=clean_run_id,
                )
                ingested_records.append(ingestion_res.evidence_record)
                if ingestion_res.is_quarantined:
                    quarantined_count += 1
                if ingestion_res.is_duplicate:
                    duplicate_count += 1

            # 6. Upsert unique evidence records into VectorMemory
            should_index = request.input_data.get("index_in_vector_memory", True)
            if should_index and ingested_records:
                await self.vector_memory.upsert_evidence(ingested_records)

        except EvidenceValidationError as e:
            err = AgentError(
                error_code="EVIDENCE_VALIDATION_ERROR",
                error_type="EvidenceValidationError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except EvidenceIngestionError as e:
            err = AgentError(
                error_code="EVIDENCE_INGESTION_ERROR",
                error_type="EvidenceIngestionError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except Exception as e:
            err = AgentError(
                error_code="UNEXPECTED_RESEARCHER_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=True,
            )
            return self._build_error_envelope(request, err)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 7. Serialize output
        serialized_records = [r.model_dump() for r in ingested_records]
        evidence_ids = [r.evidence_id for r in ingested_records]

        output_data: dict[str, Any] = {
            "evidence_records": serialized_records,
            "evidence_ids": evidence_ids,
            "total_evidence_gathered": len(ingested_records),
            "quarantined_count": quarantined_count,
            "duplicate_count": duplicate_count,
            "task_type": request.task_type.value,
        }

        response_id = f"resp_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"
        envelope_id = f"env_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"

        agent_response = AgentResponse(
            response_id=response_id,
            request_id=request.request_id,
            run_id=clean_run_id,
            subtask_id=request.subtask_id,
            agent_role=AgentRole.RESEARCHER,
            output_data=output_data,
            execution_time_ms=duration_ms,
            token_usage=TokenUsage(
                prompt_tokens=30, completion_tokens=100, total_tokens=130
            ),
            error=None,
        )

        return WorkerResponseEnvelope(
            envelope_id=envelope_id,
            dispatch_id=f"disp_{request.request_id}",
            run_id=clean_run_id,
            subtask_id=request.subtask_id,
            status=TaskStatus.COMPLETED,
            response=agent_response,
            error=None,
            worker_id=self.worker_id,
        )

    def _extract_queries(self, request: AgentRequest) -> list[str]:
        """Extract and clean search queries from AgentRequest input payload."""
        queries: list[str] = []
        has_explicit_queries = False

        if "queries" in request.input_data or "search_queries" in request.input_data:
            has_explicit_queries = True
            raw_queries = request.input_data.get("queries") or request.input_data.get(
                "search_queries"
            )
            if isinstance(raw_queries, (list, tuple)):
                for q in raw_queries:
                    if isinstance(q, str) and q.strip():
                        queries.append(q.strip())
            elif isinstance(raw_queries, str) and raw_queries.strip():
                queries.append(raw_queries.strip())

        if "query" in request.input_data:
            has_explicit_queries = True
            single_query = request.input_data.get("query")
            if isinstance(single_query, str) and single_query.strip():
                queries.append(single_query.strip())

        if (
            not queries
            and not has_explicit_queries
            and request.goal_context
            and request.goal_context.strip()
        ):
            queries.append(request.goal_context.strip())

        # Deduplicate preserving order
        seen: set[str] = set()
        clean_queries: list[str] = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                clean_queries.append(q)

        return clean_queries

    def _extract_documents(self, request: AgentRequest) -> list[RawDocument]:
        """Extract RawDocument instances from input_data for DOC_ANALYSIS."""
        docs: list[RawDocument] = []
        raw_docs = request.input_data.get("raw_documents") or request.input_data.get(
            "documents"
        )

        if isinstance(raw_docs, list):
            for item in raw_docs:
                if isinstance(item, RawDocument):
                    docs.append(item)
                elif isinstance(item, dict):
                    source_url = (
                        item.get("source_url")
                        or item.get("url")
                        or "https://document.internal/doc1"
                    )
                    title = item.get("title") or "Internal Document"
                    raw_text = (
                        item.get("raw_text")
                        or item.get("text")
                        or item.get("content")
                        or ""
                    )
                    if raw_text.strip():
                        docs.append(
                            RawDocument(
                                source_url=source_url,
                                title=title,
                                raw_text=raw_text,
                                domain=item.get("domain", "document.internal"),
                                authors=tuple(item.get("authors", ())),
                                trust_level=SourceTrustLevel.OFFICIAL_DOC,
                                source_type="documentation",
                                metadata=item.get("metadata", {}),
                            )
                        )

        single_text = request.input_data.get("raw_text") or request.input_data.get(
            "content"
        )
        if isinstance(single_text, str) and single_text.strip():
            docs.append(
                RawDocument(
                    source_url=request.input_data.get(
                        "source_url", "https://document.internal/single"
                    ),
                    title=request.input_data.get("title", "Provided Document"),
                    raw_text=single_text.strip(),
                    domain="document.internal",
                    trust_level=SourceTrustLevel.OFFICIAL_DOC,
                    source_type="documentation",
                )
            )

        return docs

    def _build_error_envelope(
        self, request: AgentRequest, error: AgentError
    ) -> WorkerResponseEnvelope:
        """Construct a standardized failure WorkerResponseEnvelope."""
        run_id = (
            request.run_id
            if request.run_id and request.run_id.strip()
            else "unknown_run"
        )
        envelope_id = f"env_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{run_id}:{request.request_id}').hex[:12]}"
        response_id = f"resp_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{run_id}:{request.request_id}').hex[:12]}"

        agent_response = AgentResponse(
            response_id=response_id,
            request_id=request.request_id,
            run_id=run_id,
            subtask_id=request.subtask_id,
            agent_role=request.agent_role,
            output_data={},
            execution_time_ms=0,
            token_usage=TokenUsage(),
            error=error,
        )

        return WorkerResponseEnvelope(
            envelope_id=envelope_id,
            dispatch_id=f"disp_{request.request_id}",
            run_id=run_id,
            subtask_id=request.subtask_id,
            status=TaskStatus.FAILED,
            response=agent_response,
            error=error,
            worker_id=self.worker_id,
        )


__all__ = ["ResearcherWorker", "SUPPORTED_RESEARCHER_TASK_TYPES"]
