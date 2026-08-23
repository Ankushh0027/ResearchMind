"""AnalystWorker adapter executing TaskType.SYNTHESIS using DeterministicClaimExtractor and AnalystAgent."""

import time
import uuid
from typing import Any

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.common.errors import (
    AnalysisError,
    EvidenceValidationError,
    ResearchMindError,
    UngroundedClaimError,
    UngroundedFindingError,
)
from app.intelligence.analyst import (
    AnalystAgent,
    AnalystProtocol,
    ThematicAnalysisResult,
)
from app.intelligence.claims import (
    ClaimExtractorProtocol,
    DeterministicClaimExtractor,
    ExtractedClaim,
)
from app.intelligence.evidence import EvidenceRecord
from app.intelligence.models import KeyFinding
from app.intelligence.protocols import VectorMemoryProtocol
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol

SUPPORTED_ANALYST_TASK_TYPES = {
    TaskType.SYNTHESIS,
}


class AnalystWorker(WorkerProtocol):
    """WorkerProtocol adapter synthesizing evidence into grounded ExtractedClaim and KeyFinding records."""

    def __init__(
        self,
        claim_extractor: ClaimExtractorProtocol | None = None,
        analyst_agent: AnalystProtocol | None = None,
        vector_memory: VectorMemoryProtocol | None = None,
        worker_id: str = "analyst-worker-01",
    ) -> None:
        self.claim_extractor = claim_extractor or DeterministicClaimExtractor()
        self.analyst_agent = analyst_agent or AnalystAgent()
        self.vector_memory = vector_memory
        self.worker_id = worker_id

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Execute evidence synthesis and return grounded claims and key findings."""
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
        if request.agent_role != AgentRole.ANALYST:
            err = AgentError(
                error_code="UNSUPPORTED_ROLE",
                error_type="ValueError",
                message=f"AnalystWorker expects AgentRole.ANALYST, got '{request.agent_role}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 3. Validate task type
        if request.task_type not in SUPPORTED_ANALYST_TASK_TYPES:
            err = AgentError(
                error_code="UNSUPPORTED_TASK_TYPE",
                error_type="ValueError",
                message=f"AnalystWorker expects TaskType.SYNTHESIS, got '{request.task_type}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        start_time = time.perf_counter()

        # 4. Extract and validate input evidence records and/or pre-extracted claims
        try:
            evidence_records = self._parse_evidence_records(request, clean_run_id)
            direct_claims = self._parse_direct_claims(request, clean_run_id)

            # If no direct evidence records but vector memory is configured, attempt retrieval
            if (
                not evidence_records
                and not direct_claims
                and self.vector_memory is not None
            ):
                search_query = (
                    request.input_data.get("query") or request.goal_context or ""
                ).strip()
                if search_query:
                    evidence_records = await self.vector_memory.similarity_search(
                        query=search_query,
                        run_id=clean_run_id,
                        min_score=-1.0,
                    )

            # 5. Extract grounded claims from evidence records if not directly provided
            extracted_claims: list[ExtractedClaim] = list(direct_claims)
            if evidence_records and not direct_claims:
                extraction_res = await self.claim_extractor.extract_claims(
                    evidence_records=evidence_records,
                    run_id=clean_run_id,
                )
                extracted_claims = list(extraction_res.claims)

            # 6. Synthesize thematic findings via AnalystAgent
            research_goal = (
                request.input_data.get("research_goal") or request.goal_context or ""
            ).strip()

            thematic_res: ThematicAnalysisResult = (
                await self.analyst_agent.analyze_claims(
                    claims=extracted_claims,
                    run_id=clean_run_id,
                    research_goal=research_goal,
                )
            )
            findings: list[KeyFinding] = list(thematic_res.findings)

        except EvidenceValidationError as e:
            err = AgentError(
                error_code="EVIDENCE_VALIDATION_ERROR",
                error_type="EvidenceValidationError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except UngroundedClaimError as e:
            err = AgentError(
                error_code="UNGROUNDED_CLAIM_ERROR",
                error_type="UngroundedClaimError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except UngroundedFindingError as e:
            err = AgentError(
                error_code="UNGROUNDED_FINDING_ERROR",
                error_type="UngroundedFindingError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except AnalysisError as e:
            err = AgentError(
                error_code="ANALYSIS_ERROR",
                error_type="AnalysisError",
                message=str(e),
                is_retryable=False,
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
                error_code="UNEXPECTED_ANALYST_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=True,
            )
            return self._build_error_envelope(request, err)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 7. Serialize output
        serialized_claims = [c.model_dump() for c in extracted_claims]
        serialized_findings = [f.model_dump() for f in findings]

        output_data: dict[str, Any] = {
            "claims": serialized_claims,
            "findings": serialized_findings,
            "claim_ids": [c.claim_id for c in extracted_claims],
            "finding_ids": [f.finding_id for f in findings],
            "total_claims": len(extracted_claims),
            "total_findings": len(findings),
            "evidence_ids_covered": list(thematic_res.evidence_ids_covered),
            "run_id": clean_run_id,
        }

        response_id = f"resp_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"
        envelope_id = f"env_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"

        agent_response = AgentResponse(
            response_id=response_id,
            request_id=request.request_id,
            run_id=clean_run_id,
            subtask_id=request.subtask_id,
            agent_role=AgentRole.ANALYST,
            output_data=output_data,
            execution_time_ms=duration_ms,
            token_usage=TokenUsage(
                prompt_tokens=45, completion_tokens=140, total_tokens=185
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

    def _parse_evidence_records(
        self, request: AgentRequest, run_id: str
    ) -> list[EvidenceRecord]:
        """Extract and validate EvidenceRecord items from input_data."""
        raw_evidence = request.input_data.get("evidence_records")
        if not raw_evidence:
            return []

        records: list[EvidenceRecord] = []
        if isinstance(raw_evidence, list):
            for item in raw_evidence:
                if isinstance(item, EvidenceRecord):
                    rec = item
                elif isinstance(item, dict):
                    rec = EvidenceRecord.model_validate(item)
                else:
                    continue

                if rec.run_id != run_id:
                    raise EvidenceValidationError(
                        f"Evidence record '{rec.evidence_id}' has run_id '{rec.run_id}' "
                        f"which does not match request run_id '{run_id}'"
                    )
                records.append(rec)

        return records

    def _parse_direct_claims(
        self, request: AgentRequest, run_id: str
    ) -> list[ExtractedClaim]:
        """Extract and validate pre-extracted ExtractedClaim items from input_data."""
        raw_claims = request.input_data.get("claims")
        if not raw_claims:
            return []

        claims: list[ExtractedClaim] = []
        if isinstance(raw_claims, list):
            for item in raw_claims:
                if isinstance(item, ExtractedClaim):
                    clm = item
                elif isinstance(item, dict):
                    clm = ExtractedClaim.model_validate(item)
                else:
                    continue

                if clm.run_id != run_id:
                    raise EvidenceValidationError(
                        f"Claim '{clm.claim_id}' has run_id '{clm.run_id}' "
                        f"which does not match request run_id '{run_id}'"
                    )
                claims.append(clm)

        return claims

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


__all__ = ["AnalystWorker", "SUPPORTED_ANALYST_TASK_TYPES"]
