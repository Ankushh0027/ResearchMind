"""EvaluatorWorker adapter executing TaskType.EVALUATION using EvaluatorAgent."""

import time
import uuid

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.common.errors import (
    EvaluationError,
    EvidenceValidationError,
    ResearchMindError,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.evaluator import (
    EvaluatorAgent,
    EvaluatorProtocol,
)
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    KeyFinding,
)
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol

SUPPORTED_EVALUATOR_TASK_TYPES = {
    TaskType.EVALUATION,
}


class EvaluatorWorker(WorkerProtocol):
    """WorkerProtocol adapter evaluating synthesized research quality, groundedness, and rubric scores."""

    def __init__(
        self,
        evaluator_agent: EvaluatorProtocol | None = None,
        worker_id: str = "evaluator-worker-01",
    ) -> None:
        self.evaluator_agent = evaluator_agent or EvaluatorAgent()
        self.worker_id = worker_id

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Execute quality evaluation and return formal EvaluationReport envelope."""
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
        if request.agent_role != AgentRole.EVALUATOR:
            err = AgentError(
                error_code="UNSUPPORTED_ROLE",
                error_type="ValueError",
                message=f"EvaluatorWorker expects AgentRole.EVALUATOR, got '{request.agent_role}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 3. Validate task type
        if request.task_type not in SUPPORTED_EVALUATOR_TASK_TYPES:
            err = AgentError(
                error_code="UNSUPPORTED_TASK_TYPE",
                error_type="ValueError",
                message=f"EvaluatorWorker does not support task type '{request.task_type}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        start_time = time.perf_counter()

        # 4. Extract and validate inputs
        try:
            if "goal_query" in request.input_data:
                goal_query = str(request.input_data["goal_query"]).strip()
            elif "query" in request.input_data:
                goal_query = str(request.input_data["query"]).strip()
            else:
                goal_query = (request.goal_context or "").strip()

            if not goal_query:
                raise EvaluationError(
                    "goal_query must not be empty or whitespace only",
                    code="EMPTY_GOAL_QUERY",
                )

            findings = self._parse_findings(request, clean_run_id)
            claims = self._parse_claims(request, clean_run_id)
            citations = self._parse_citations(request, clean_run_id)
            contradictions = self._parse_contradictions(request, clean_run_id)
            plan_id = str(request.input_data.get("plan_id") or "plan_default")

            # 5. Delegate evaluation to EvaluatorAgent
            eval_report: EvaluationReport = (
                await self.evaluator_agent.evaluate_research(
                    goal_query=goal_query,
                    findings=findings,
                    claims=claims,
                    citations=citations,
                    contradictions=contradictions,
                    run_id=clean_run_id,
                    plan_id=plan_id,
                )
            )

        except EvidenceValidationError as e:
            err = AgentError(
                error_code="EVALUATION_INPUT_VALIDATION_ERROR",
                error_type="EvidenceValidationError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except EvaluationError as e:
            err = AgentError(
                error_code="EVALUATION_ERROR",
                error_type="EvaluationError",
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
                error_code="UNEXPECTED_EVALUATOR_ERROR",
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
            agent_role=AgentRole.EVALUATOR,
            output_data=eval_report.model_dump(),
            execution_time_ms=duration_ms,
            token_usage=TokenUsage(
                prompt_tokens=50, completion_tokens=150, total_tokens=200
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

    def _parse_findings(self, request: AgentRequest, run_id: str) -> list[KeyFinding]:
        """Extract and validate KeyFinding items from input_data."""
        raw_findings = request.input_data.get("findings")
        if not raw_findings:
            return []

        findings: list[KeyFinding] = []
        if isinstance(raw_findings, list):
            for item in raw_findings:
                if isinstance(item, KeyFinding):
                    fnd = item
                elif isinstance(item, dict):
                    fnd = KeyFinding.model_validate(item)
                else:
                    continue

                if fnd.run_id and fnd.run_id != run_id:
                    raise EvidenceValidationError(
                        f"Finding '{fnd.finding_id}' run_id '{fnd.run_id}' does not match '{run_id}'"
                    )
                findings.append(fnd)

        return findings

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
                        f"Claim '{clm.claim_id}' run_id '{clm.run_id}' does not match '{run_id}'"
                    )
                claims.append(clm)

        return claims

    def _parse_citations(
        self, request: AgentRequest, run_id: str
    ) -> list[CitationReference]:
        """Extract and validate CitationReference items from input_data."""
        raw_citations = request.input_data.get("citations")
        if not raw_citations:
            return []

        citations: list[CitationReference] = []
        if isinstance(raw_citations, list):
            for item in raw_citations:
                if isinstance(item, CitationReference):
                    cit = item
                elif isinstance(item, dict):
                    cit = CitationReference.model_validate(item)
                else:
                    continue

                if cit.run_id and cit.run_id != run_id:
                    raise EvidenceValidationError(
                        f"Citation '{cit.citation_key}' run_id '{cit.run_id}' does not match '{run_id}'"
                    )
                citations.append(cit)

        return citations

    def _parse_contradictions(
        self, request: AgentRequest, run_id: str
    ) -> list[ContradictionItem]:
        """Extract and validate ContradictionItem items from input_data."""
        raw_contradictions = request.input_data.get("contradictions")
        if not raw_contradictions:
            return []

        contradictions: list[ContradictionItem] = []
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
                        f"Contradiction '{cnt.item_id}' run_id '{cnt.run_id}' does not match '{run_id}'"
                    )
                contradictions.append(cnt)

        return contradictions

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


__all__ = ["EvaluatorWorker", "SUPPORTED_EVALUATOR_TASK_TYPES"]
