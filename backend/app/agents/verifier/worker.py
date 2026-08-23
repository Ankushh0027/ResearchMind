"""VerifierWorker adapter executing TaskType.VERIFICATION and TaskType.CONFLICT_DETECTION."""

import time
import uuid
from typing import Any

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.common.errors import (
    ContradictionDetectionError,
    EvidenceValidationError,
    ResearchMindError,
    UngroundedCitationError,
    VerificationError,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.contradiction import (
    ContradictionDetectionResult,
    ContradictionDetector,
    ContradictionDetectorProtocol,
)
from app.intelligence.evidence import EvidenceRecord
from app.intelligence.models import ContradictionItem
from app.intelligence.protocols import VectorMemoryProtocol
from app.intelligence.verifier import (
    VerificationResult,
    VerifierAgent,
    VerifierProtocol,
)
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol

SUPPORTED_VERIFIER_TASK_TYPES = {
    TaskType.VERIFICATION,
    TaskType.CONFLICT_DETECTION,
}


class VerifierWorker(WorkerProtocol):
    """WorkerProtocol adapter executing contradiction detection and claim-evidence grounding verification."""

    def __init__(
        self,
        verifier_agent: VerifierProtocol | None = None,
        contradiction_detector: ContradictionDetectorProtocol | None = None,
        vector_memory: VectorMemoryProtocol | None = None,
        worker_id: str = "verifier-worker-01",
    ) -> None:
        self.verifier_agent = verifier_agent or VerifierAgent()
        self.contradiction_detector = contradiction_detector or ContradictionDetector()
        self.vector_memory = vector_memory
        self.worker_id = worker_id

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Execute verification or contradiction detection subtask and return structured results."""
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
        if request.agent_role != AgentRole.VERIFIER:
            err = AgentError(
                error_code="UNSUPPORTED_ROLE",
                error_type="ValueError",
                message=f"VerifierWorker expects AgentRole.VERIFIER, got '{request.agent_role}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 3. Validate task type
        if request.task_type not in SUPPORTED_VERIFIER_TASK_TYPES:
            err = AgentError(
                error_code="UNSUPPORTED_TASK_TYPE",
                error_type="ValueError",
                message=f"VerifierWorker does not support task type '{request.task_type}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        start_time = time.perf_counter()

        # 4. Extract and validate claims, evidence records, and contradiction items
        try:
            claims = self._parse_claims(request, clean_run_id)
            evidence_records = self._parse_evidence_records(request, clean_run_id)
            contradictions = self._parse_contradictions(request, clean_run_id)

            # Optional fallback: retrieve evidence from VectorMemory if pool is empty
            if not evidence_records and self.vector_memory is not None:
                search_query = (
                    request.input_data.get("query") or request.goal_context or ""
                ).strip()
                if search_query:
                    evidence_records = await self.vector_memory.similarity_search(
                        query=search_query,
                        run_id=clean_run_id,
                        min_score=-1.0,
                    )

            output_data: dict[str, Any] = {}

            # 5. Execute CONFLICT_DETECTION
            if request.task_type == TaskType.CONFLICT_DETECTION:
                contra_res: ContradictionDetectionResult = (
                    await self.contradiction_detector.detect_contradictions(
                        claims=claims,
                        run_id=clean_run_id,
                    )
                )
                output_data = {
                    "contradictions": [
                        c.model_dump() for c in contra_res.contradictions
                    ],
                    "contradiction_ids": [c.item_id for c in contra_res.contradictions],
                    "claims_evaluated": contra_res.claims_evaluated,
                    "total_contradictions": contra_res.total_contradictions,
                    "has_contradictions": contra_res.has_contradictions,
                    "run_id": clean_run_id,
                    "task_type": TaskType.CONFLICT_DETECTION.value,
                }

            # 6. Execute VERIFICATION
            elif request.task_type == TaskType.VERIFICATION:
                # If contradictions were not passed, run contradiction detection automatically
                effective_contradictions = contradictions
                if effective_contradictions is None and claims:
                    contra_eval = (
                        await self.contradiction_detector.detect_contradictions(
                            claims=claims,
                            run_id=clean_run_id,
                        )
                    )
                    effective_contradictions = list(contra_eval.contradictions)

                verif_res: VerificationResult = await self.verifier_agent.verify_claims(
                    claims=claims,
                    evidence_pool=evidence_records,
                    run_id=clean_run_id,
                    contradictions=effective_contradictions,
                )

                output_data = {
                    "audits": [a.model_dump() for a in verif_res.audits],
                    "citations": [c.model_dump() for c in verif_res.citations],
                    "claim_to_citation_map": verif_res.claim_to_citation_map,
                    "overall_status": verif_res.overall_status.value,
                    "verified_count": verif_res.verified_count,
                    "unverified_count": verif_res.unverified_count,
                    "contradicted_count": verif_res.contradicted_count,
                    "average_confidence": verif_res.average_confidence,
                    "total_audits": len(verif_res.audits),
                    "total_citations": len(verif_res.citations),
                    "run_id": clean_run_id,
                    "task_type": TaskType.VERIFICATION.value,
                }

        except EvidenceValidationError as e:
            err = AgentError(
                error_code="EVIDENCE_VALIDATION_ERROR",
                error_type="EvidenceValidationError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except UngroundedCitationError as e:
            err = AgentError(
                error_code="UNGROUNDED_CITATION_ERROR",
                error_type="UngroundedCitationError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except ContradictionDetectionError as e:
            err = AgentError(
                error_code="CONTRADICTION_DETECTION_ERROR",
                error_type="ContradictionDetectionError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except VerificationError as e:
            err = AgentError(
                error_code="VERIFICATION_ERROR",
                error_type="VerificationError",
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
                error_code="UNEXPECTED_VERIFIER_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=True,
            )
            return self._build_error_envelope(request, err)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        response_id = f"resp_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"
        envelope_id = f"env_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"

        agent_response = AgentResponse(
            response_id=response_id,
            request_id=request.request_id,
            run_id=clean_run_id,
            subtask_id=request.subtask_id,
            agent_role=AgentRole.VERIFIER,
            output_data=output_data,
            execution_time_ms=duration_ms,
            token_usage=TokenUsage(
                prompt_tokens=40, completion_tokens=130, total_tokens=170
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

    def _parse_claims(self, request: AgentRequest, run_id: str) -> list[ExtractedClaim]:
        """Extract and validate ExtractedClaim items from input_data."""
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

    def _parse_contradictions(
        self, request: AgentRequest, run_id: str
    ) -> list[ContradictionItem] | None:
        """Extract and validate ContradictionItem items from input_data if provided."""
        raw_contradictions = request.input_data.get("contradictions")
        if raw_contradictions is None:
            return None

        items: list[ContradictionItem] = []
        if isinstance(raw_contradictions, list):
            for item in raw_contradictions:
                if isinstance(item, ContradictionItem):
                    cnt = item
                elif isinstance(item, dict):
                    cnt = ContradictionItem.model_validate(item)
                else:
                    continue

                if cnt.run_id and cnt.run_id != run_id:
                    raise EvidenceValidationError(
                        f"Contradiction '{cnt.item_id}' has run_id '{cnt.run_id}' "
                        f"which does not match request run_id '{run_id}'"
                    )
                items.append(cnt)

        return items

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


__all__ = ["VerifierWorker", "SUPPORTED_VERIFIER_TASK_TYPES"]
