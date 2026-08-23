"""ReporterWorker adapter executing TaskType.REPORTING using ReporterAgent."""

import time
import uuid

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.common.errors import (
    EvidenceValidationError,
    ReportingError,
    ResearchMindError,
    UngroundedCitationError,
)
from app.intelligence.claims import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    KeyFinding,
    ResearchDossier,
)
from app.intelligence.reporter import (
    ReporterAgent,
    ReporterProtocol,
)
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol

SUPPORTED_REPORTER_TASK_TYPES = {
    TaskType.REPORTING,
}


class ReporterWorker(WorkerProtocol):
    """WorkerProtocol adapter compiling verified research findings into publication-ready ResearchDossier deliverables."""

    def __init__(
        self,
        reporter_agent: ReporterProtocol | None = None,
        worker_id: str = "reporter-worker-01",
    ) -> None:
        self.reporter_agent = reporter_agent or ReporterAgent()
        self.worker_id = worker_id

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Compile verified findings and evaluation into a structured ResearchDossier envelope."""
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
        if request.agent_role != AgentRole.REPORTER:
            err = AgentError(
                error_code="UNSUPPORTED_ROLE",
                error_type="ValueError",
                message=f"ReporterWorker expects AgentRole.REPORTER, got '{request.agent_role}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 3. Validate task type
        if request.task_type not in SUPPORTED_REPORTER_TASK_TYPES:
            err = AgentError(
                error_code="UNSUPPORTED_TASK_TYPE",
                error_type="ValueError",
                message=f"ReporterWorker does not support task type '{request.task_type}'",
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
                raise ReportingError("goal_query must not be empty", code="EMPTY_GOAL")

            findings = self._parse_findings(request, clean_run_id)
            claims = self._parse_claims(request, clean_run_id)
            citations = self._parse_citations(request, clean_run_id)
            contradictions = self._parse_contradictions(request, clean_run_id)
            evaluation = self._parse_evaluation(request, clean_run_id)

            methodology_summary = str(
                request.input_data.get("methodology_summary") or ""
            )
            limitations = request.input_data.get("limitations")
            if limitations is not None and not isinstance(limitations, list):
                limitations = None

            # 5. Delegate compilation to ReporterAgent
            dossier: ResearchDossier = await self.reporter_agent.compile_dossier(
                goal_query=goal_query,
                findings=findings,
                claims=claims,
                citations=citations,
                contradictions=contradictions,
                run_id=clean_run_id,
                evaluation=evaluation,
                methodology_summary=methodology_summary,
                limitations=limitations,
            )

        except EvidenceValidationError as e:
            err = AgentError(
                error_code="REPORT_INPUT_VALIDATION_ERROR",
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
        except ReportingError as e:
            err = AgentError(
                error_code="REPORT_GENERATION_ERROR",
                error_type="ReportingError",
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
                error_code="UNEXPECTED_REPORTER_ERROR",
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
            agent_role=AgentRole.REPORTER,
            output_data=dossier.model_dump(),
            execution_time_ms=duration_ms,
            token_usage=TokenUsage(
                prompt_tokens=60, completion_tokens=250, total_tokens=310
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

    def _parse_evaluation(
        self, request: AgentRequest, run_id: str
    ) -> EvaluationReport | None:
        """Extract and validate EvaluationReport from input_data if provided."""
        raw_eval = request.input_data.get("evaluation")
        if not raw_eval:
            return None

        if isinstance(raw_eval, EvaluationReport):
            eval_report = raw_eval
        elif isinstance(raw_eval, dict):
            eval_report = EvaluationReport.model_validate(raw_eval)
        else:
            return None

        if eval_report.run_id != run_id:
            raise EvidenceValidationError(
                f"Evaluation report run_id '{eval_report.run_id}' does not match '{run_id}'"
            )

        return eval_report

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


__all__ = ["ReporterWorker", "SUPPORTED_REPORTER_TASK_TYPES"]
