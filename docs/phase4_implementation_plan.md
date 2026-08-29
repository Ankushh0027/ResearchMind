1# Phase 4 — Agent Worker Mesh & End-to-End Orchestration Implementation Plan

## 1. Objective

Phase 4 bridges the core **DAG Orchestration Engine** (`app.orchestration.*`) and the **Intelligence Core / RAG Memory Substrate** (`app.intelligence.*`, `app.rag.*`) into a cohesive, fully operational autonomous research system.

```
DAGScheduler / DAGExecutor (app.orchestration)
                   │
                   ▼ (Dispatches AgentRequest via WorkerProtocol)
          AgentWorkerRouter (app.orchestration.worker)
                   │
    ┌──────────────┼──────────────┬──────────────┬──────────────┬──────────────┐
    ▼              ▼              ▼              ▼              ▼              ▼
PlannerWorker ResearcherWorker AnalystWorker VerifierWorker EvaluatorWorker ReporterWorker
(app.agents)   (app.agents)   (app.agents)   (app.agents)   (app.agents)   (app.agents)
    │              │              │              │              │              │
    ▼              ▼              ▼              ▼              ▼              ▼
PlannerAgent   SearchAdapter   ClaimExtractor  Contradiction  EvaluatorAgent ReporterAgent
               + Ingestion     + AnalystAgent  + VerifierAgent
               + VectorMemory
                   │
                   ▼
       Verified ResearchDossier (Publication-Grade Deliverable)
```

By encapsulating each intelligence component within a standardized `WorkerProtocol` adapter, Phase 4 enables `DAGExecutor` to schedule, dispatch, isolate, checkpoint, retry, and cancel multi-agent research workflows with cryptographic provenance and strict multi-tenant `run_id` isolation.

---

## 2. Architecture & Runtime Flow

### End-to-End Execution Flow

```
User Inquiry / Research Goal
          │
          ▼
1. [PlannerWorker] (TaskType.DECOMPOSITION)
   └── Generates subtasks and dependency edges via PlannerAgent
          │
          ▼
2. [DAGScheduler & DAGExecutor]
   └── Builds directed acyclic graph (DAG); schedules runnable root nodes
          │
          ▼
3. [Parallel ResearcherWorkers] (TaskType.WEB_SEARCH / ACADEMIC_SEARCH / DOC_ANALYSIS)
   ├── Query search/document adapters (MockSearchClient)
   ├── Sanitize untrusted content via ContentBoundarySanitizer
   ├── Ingest via EvidenceIngestionPipeline (SHA-256 hash & provenance)
   ├── Chunk & embed into VectorMemory (InMemoryVectorStore)
   └── Output immutable EvidenceRecord collection
          │
          ▼
4. [AnalystWorker] (TaskType.SYNTHESIS)
   ├── Retrieve evidence from VectorMemory or input dependencies
   ├── Extract grounded factual assertions via DeterministicClaimExtractor
   ├── Synthesize thematic findings via AnalystAgent
   └── Output ExtractedClaim and KeyFinding collections
          │
          ▼
5. [VerifierWorker] (TaskType.VERIFICATION / CONFLICT_DETECTION)
   ├── Cross-examine claims and detect divergence via ContradictionDetector
   ├── Cross-reference claims against primary evidence pool via VerifierAgent
   ├── Generate deterministic VerificationAudit records
   └── Map publication-grade CitationReference items ([CIT-01], [CIT-02])
          │
          ▼
6. [EvaluatorWorker] (TaskType.EVALUATION)
   ├── Self-critique synthesis completeness against original user goal
   ├── Calculate quantitative rubrics (groundedness, completeness, contradiction rate, diversity)
   └── Emit formal EvaluationReport (passed/failed, overall quality rating)
          │
          ▼
7. [ReporterWorker] (TaskType.REPORTING)
   ├── Assemble findings, claims, citations, contradictions, and evaluations
   ├── Format publication-grade Markdown text and structured JSON deliverable
   └── Emit final immutable ResearchDossier
```

### Component Data Boundaries

| Producer Step | Output Contract | Consumer Step | Passed via Payload Key |
| :--- | :--- | :--- | :--- |
| **PlannerWorker** | `PlannedDecomposition` (`subtasks`) | `DAGScheduler` / `DAGExecutor` | `output_data["planned_subtasks"]` |
| **ResearcherWorker** | `tuple[EvidenceRecord, ...]` | `VectorMemory` / `AnalystWorker` | `output_data["evidence_records"]` |
| **AnalystWorker** | `tuple[ExtractedClaim, ...]`, `tuple[KeyFinding, ...]` | `VerifierWorker` / `EvaluatorWorker` | `output_data["claims"]`, `output_data["findings"]` |
| **VerifierWorker** | `VerificationResult` (`audits`, `citations`, `claim_to_citation_map`) | `EvaluatorWorker` / `ReporterWorker` | `output_data["verification_result"]` |
| **EvaluatorWorker** | `EvaluationReport` | `ReporterWorker` | `output_data["evaluation_report"]` |
| **ReporterWorker** | `ResearchDossier` (Markdown + JSON) | Storage / API Deliverable | `output_data["research_dossier"]` |

---

## 3. Phase 4.1 — Specialized Agent Workers (`app.agents.*`)

Each specialized agent worker implements `WorkerProtocol`:
```python
@runtime_checkable
class WorkerProtocol(Protocol):
    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope: ...
```

---

### 3.1 `PlannerWorker` (`app.agents.planner`)
* **Agent Role**: `AgentRole.PLANNER`
* **Supported Task Types**: `TaskType.DECOMPOSITION`
* **Wrapped Core**: `PlannerAgent` (`app.intelligence.planner`)
* **Input Contract (`AgentRequest.input_data`)**:
  * `research_goal`: str (or fallback to `request.goal_context`)
  * `constraints`: dict[str, Any] (optional `max_subtasks`, `domains_allowed`, `depth`)
* **Output Contract (`AgentResponse.output_data`)**:
  * `plan_id`: str
  * `planned_subtasks`: list[dict[str, Any]] (serialized `PlannedSubtask` records)
  * `total_subtasks`: int
* **Failure & Retry Behavior**:
  * Empty goal: Non-retryable `AgentError(error_code="INVALID_PLANNER_INPUT", is_retryable=False)`.
  * LLM/Agent internal failure: Retryable `AgentError(error_code="PLANNING_FAILED", is_retryable=True)`.
* **Security & Isolation**: Enforces `request.run_id` on output plans.
* **Test Requirements**:
  * Valid decomposition into subtasks.
  * Empty goal validation error handling.
  * Deterministic plan ID propagation.
  * Retryability flag accuracy.

---

### 3.2 `ResearcherWorker` (`app.agents.researcher`)
* **Agent Role**: `AgentRole.RESEARCHER`
* **Supported Task Types**: `TaskType.WEB_SEARCH`, `TaskType.ACADEMIC_SEARCH`, `TaskType.DOC_ANALYSIS`
* **Wrapped Core**: `SearchClientProtocol` (`app.adapters.search`), `EvidenceIngestionPipeline` (`app.intelligence.ingestion`), `VectorMemory` (`app.rag.memory`)
* **Input Contract (`AgentRequest.input_data`)**:
  * `queries`: list[str] (search queries to execute)
  * `raw_documents`: list[dict[str, Any]] (optional direct documents for `DOC_ANALYSIS`)
  * `max_results_per_query`: int (default `5`)
  * `index_in_vector_memory`: bool (default `True`)
* **Output Contract (`AgentResponse.output_data`)**:
  * `evidence_records`: list[dict[str, Any]] (serialized `EvidenceRecord` items)
  * `total_evidence_gathered`: int
  * `quarantined_count`: int
  * `duplicate_count`: int
* **Failure & Retry Behavior**:
  * Search backend timeout: Retryable `AgentError(error_code="SEARCH_TIMEOUT", is_retryable=True)`.
  * Malformed document: Sanitized or skipped; non-retryable if input is invalid.
* **Security & Isolation**:
  * Passes all search text through `ContentBoundarySanitizer`.
  * Sets `is_untrusted = True` and `is_quarantined = True` on hostile injection patterns.
  * Enforces `request.run_id` across vector memory indexing and record provenance.
* **Test Requirements**:
  * Search execution and evidence record generation.
  * Ingestion deduplication by content hash.
  * Prompt injection neutralization and quarantine flagging.
  * Strict multi-tenant `run_id` isolation in `VectorMemory`.

---

### 3.3 `AnalystWorker` (`app.agents.analyst`)
* **Agent Role**: `AgentRole.ANALYST`
* **Supported Task Types**: `TaskType.SYNTHESIS`
* **Wrapped Core**: `DeterministicClaimExtractor` (`app.intelligence.claims`), `AnalystAgent` (`app.intelligence.analyst`)
* **Input Contract (`AgentRequest.input_data`)**:
  * `evidence_records`: list[dict[str, Any]] (or retrieved from dependency tasks)
  * `research_goal`: str (or `request.goal_context`)
* **Output Contract (`AgentResponse.output_data`)**:
  * `claims`: list[dict[str, Any]] (serialized `ExtractedClaim` items)
  * `findings`: list[dict[str, Any]] (serialized `KeyFinding` items)
  * `total_claims`: int
  * `total_findings`: int
* **Failure & Retry Behavior**:
  * Empty evidence list: Handled gracefully (0 claims, 0 findings) or raises `INVALID_ANALYST_INPUT`.
* **Security & Isolation**:
  * Validates every `EvidenceRecord.run_id == request.run_id`.
  * Propagates `is_untrusted` and `is_quarantined` flags to extracted claims.
* **Test Requirements**:
  * Grounded claim extraction from evidence records.
  * Thematic finding clustering and synthesis.
  * Mismatched `run_id` rejection.
  * Security flag inheritance.

---

### 3.4 `VerifierWorker` (`app.agents.verifier`)
* **Agent Role**: `AgentRole.VERIFIER`
* **Supported Task Types**: `TaskType.VERIFICATION`, `TaskType.CONFLICT_DETECTION`
* **Wrapped Core**: `ContradictionDetector` (`app.intelligence.contradiction`), `VerifierAgent` (`app.intelligence.verifier`)
* **Input Contract (`AgentRequest.input_data`)**:
  * `claims`: list[dict[str, Any]]
  * `evidence_records`: list[dict[str, Any]]
  * `findings`: list[dict[str, Any]] (optional)
* **Output Contract (`AgentResponse.output_data`)**:
  * `verification_result`: dict[str, Any] (serialized `VerificationResult`)
  * `contradictions`: list[dict[str, Any]] (serialized `ContradictionItem` items)
  * `citations`: list[dict[str, Any]] (serialized `CitationReference` items)
  * `verified_count`: int
  * `contradicted_count`: int
  * `overall_status`: str (`VERIFIED`, `CONTRADICTED`, `PARTIALLY_VERIFIED`, `UNVERIFIED`)
* **Failure & Retry Behavior**:
  * Ungrounded claims: Not an agent crash; classified as `UNVERIFIED` in audit.
  * Mismatched run_id: Non-retryable `AgentError(error_code="RUN_ID_MISMATCH", is_retryable=False)`.
* **Security & Isolation**:
  * Rejects ungrounded citations (`UngroundedCitationError`).
  * Enforces `request.run_id` across claims, evidence, and contradictions.
* **Test Requirements**:
  * Positive verification of grounded claims.
  * Contradiction detection and severity ranking.
  * Publication-grade citation mapping (`[CIT-01]`, `[CIT-02]`).
  * Mismatched `run_id` rejection.

---

### 3.5 `EvaluatorWorker` (`app.agents.evaluator`)
* **Agent Role**: `AgentRole.EVALUATOR`
* **Supported Task Types**: `TaskType.EVALUATION`
* **Wrapped Core**: `EvaluatorAgent` (`app.intelligence.evaluator`)
* **Input Contract (`AgentRequest.input_data`)**:
  * `goal_query`: str (or `request.goal_context`)
  * `findings`: list[dict[str, Any]]
  * `claims`: list[dict[str, Any]]
  * `citations`: list[dict[str, Any]]
  * `contradictions`: list[dict[str, Any]]
  * `plan_id`: str (optional, default `"plan_default"`)
* **Output Contract (`AgentResponse.output_data`)**:
  * `evaluation_report`: dict[str, Any] (serialized `EvaluationReport`)
  * `passed`: bool
  * `overall_score`: float
  * `rubric_scores`: list[dict[str, Any]]
* **Failure & Retry Behavior**:
  * Empty goal: Non-retryable error.
* **Security & Isolation**: Enforces `request.run_id` consistency.
* **Test Requirements**:
  * Multi-dimensional rubric calculation.
  * Pass / fail thresholding.
  * Empty/invalid input handling.

---

### 3.6 `ReporterWorker` (`app.agents.reporter`)
* **Agent Role**: `AgentRole.REPORTER`
* **Supported Task Types**: `TaskType.REPORTING`
* **Wrapped Core**: `ReporterAgent` (`app.intelligence.reporter`)
* **Input Contract (`AgentRequest.input_data`)**:
  * `goal_query`: str (or `request.goal_context`)
  * `findings`: list[dict[str, Any]]
  * `claims`: list[dict[str, Any]]
  * `citations`: list[dict[str, Any]]
  * `contradictions`: list[dict[str, Any]]
  * `evaluation`: dict[str, Any] | None (optional serialized `EvaluationReport`)
  * `methodology_summary`: str (optional)
  * `limitations`: list[str] (optional)
* **Output Contract (`AgentResponse.output_data`)**:
  * `research_dossier`: dict[str, Any] (serialized `ResearchDossier`)
  * `markdown_report`: str
  * `dossier_id`: str
  * `verification_status`: str
  * `confidence_rating`: float
* **Failure & Retry Behavior**:
  * Invalid schema: Non-retryable `AgentError`.
* **Security & Isolation**: Enforces `request.run_id` on final dossier.
* **Test Requirements**:
  * Publication-ready Markdown formatting.
  * Complete bibliography and citation cross-referencing.
  * Structured `ResearchDossier` validation.

---

## 4. Phase 4.2 — Worker Router & Security Dispatcher (`app.orchestration.worker`)

### `AgentWorkerRouter` (implements `WorkerProtocol`)

```python
class AgentWorkerRouter(WorkerProtocol):
    """Role- and TaskType-based worker dispatcher with SecurityPolicy validation."""

    def __init__(
        self,
        security_policy: SecurityPolicy | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.security_policy = security_policy or SecurityPolicy.default_policy()
        self.cancellation_token = cancellation_token
        self._role_workers: dict[AgentRole, WorkerProtocol] = {}
        self._task_workers: dict[TaskType, WorkerProtocol] = {}

    def register_worker(
        self,
        worker: WorkerProtocol,
        role: AgentRole | None = None,
        task_type: TaskType | None = None,
    ) -> None: ...

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope: ...
```

### Dispatch Workflow:
1. **Cancellation Check**: If `cancellation_token.is_cancelled`, return `TaskStatus.CANCELLED`.
2. **Security & Permission Check**:
   - Check if `request.agent_role` has permission for `request.task_type` via `SecurityPolicy.validate_task_permission(agent_role, task_type)`.
   - If unauthorized, return `TaskStatus.FAILED` with `AgentError(error_code="PERMISSION_DENIED", is_retryable=False)`.
3. **Route Lookup**:
   - Prefer worker registered for specific `TaskType`, fall back to worker registered for `AgentRole`.
   - If no worker registered, return `TaskStatus.FAILED` with `AgentError(error_code="UNSUPPORTED_ROLE_OR_TASK", is_retryable=False)`.
4. **Execution & Error Mapping**:
   - Execute delegated worker.
   - Catch domain exceptions (`ResearchMindError`, `EvidenceValidationError`, `SecurityError`) and map to structured `AgentError` with appropriate `is_retryable` flag.
   - Return clean `WorkerResponseEnvelope`.

---

## 5. Phase 4.3 — End-to-End Runtime Integration

### Integration with `DAGExecutor` & `DAGScheduler`:
* `DAGExecutor` is initialized with `AgentWorkerRouter` containing all registered specialized workers.
* When a research run is triggered:
  1. `PlannerWorker` executes `TaskType.DECOMPOSITION` $\rightarrow$ emits subtasks.
  2. `DAGExecutor` dynamically populates or executes the resulting DAG of `SubtaskNode` records.
  3. Parallel `ResearcherWorker` instances execute concurrently up to `max_concurrency`.
  4. State is checkpointed at each state transition via `save_checkpoint(snapshot)`.
  5. Intermediate outputs (`evidence_records`, `claims`, `findings`) flow forward into downstream dependent tasks (`Analyst`, `Verifier`, `Evaluator`, `Reporter`).
  6. Final step emits `ResearchDossier` and sets `FSMState` to `RunStage.COMPLETED`.

### Reliability Invariants Verified:
* **Checkpoint & Resume**: Simulate failure at step $N$, load latest checkpoint via `load_latest_checkpoint(run_id)`, and resume execution without re-running completed tasks.
* **Cooperative Cancellation**: Signal cancellation token mid-flight; running tasks terminate cleanly without orphaned coroutines.
* **Transient Retries**: Transient search or LLM failures retry with exponential backoff up to `max_attempts`.
* **Multi-Tenant Isolation**: Two concurrent research runs (`run_A` and `run_B`) run simultaneously without cross-run data contamination.

---

## 6. Contracts & Data Models

Phase 4 strictly preserves and reuses existing contracts without modification or replacement:

| Module | Schema / Contract | Role in Phase 4 |
| :--- | :--- | :--- |
| `app.orchestration.contracts` | `AgentRequest` | Standardized input dispatched to workers |
| `app.orchestration.contracts` | `AgentResponse` | Detailed execution result returned by agent |
| `app.orchestration.contracts` | `WorkerResponseEnvelope` | Standardized execution envelope returned to orchestrator |
| `app.orchestration.contracts` | `AgentError` | Machine-readable error with retryability flag |
| `app.orchestration.protocols` | `WorkerProtocol` | Standard worker interface (`execute(request)`) |
| `app.common.enums` | `AgentRole`, `TaskType`, `TaskStatus`, `RunStage`, `VerificationStatus`, `SourceTrustLevel` | Standard domain enumerations |
| `app.security.policy` | `SecurityPolicy` | Role-to-tool permission gatekeeper |
| `app.state.snapshot` | `CheckpointSnapshot` | Cryptographic state snapshot for recovery |
| `app.common.evidence` | `EvidenceRecord`, `SourceProvenance` | Immutable evidence tracking with SHA-256 hash |
| `app.intelligence.claims` | `ExtractedClaim` | Grounded factual claim schema |
| `app.intelligence.models` | `KeyFinding` | Synthesized thematic research finding |
| `app.intelligence.models` | `ContradictionItem` | Cross-source contradiction record |
| `app.common.evidence` | `VerificationAudit` | Claim grounding audit record |
| `app.intelligence.models` | `CitationReference` | Publication-grade source citation mapping |
| `app.intelligence.models` | `EvaluationReport`, `EvaluationRubricScore` | Multi-dimensional quality audit |
| `app.intelligence.models` | `ResearchDossier` | Complete final publication deliverable |

---

## 7. Security Requirements

1. **Strict Multi-Tenant Isolation**: Every worker validates that all incoming input entities match `request.run_id`. Mismatches raise `EvidenceValidationError` and are non-retryable.
2. **Prompt Injection as Passive Data**: All raw web/document text is processed through `ContentBoundarySanitizer` and wrapped in `<evidence_snippet>` envelopes. Injection tokens are redacted to `[REDACTED_CONTROL_TOKEN]`.
3. **Role-Based Tool Authorization**: `AgentWorkerRouter` enforces `SecurityPolicy.validate_task_permission` before worker dispatch.
4. **Deterministic Identification**: All generated IDs (`plan_id`, `evidence_id`, `clm_id`, `fnd_id`, `cnt_id`, `aud_id`, `[CIT-XX]`, `eval_id`, `dos_id`) use deterministic UUID5 or stable sequential numbering.
5. **Frozen Immutability**: All request, response, and domain models enforce `ConfigDict(frozen=True, extra="forbid")`.

---

## 8. Error & Retry Model

```
Exception Type                      Mapped Error Code               is_retryable  TaskStatus
─────────────────────────────────────────────────────────────────────────────────────────────
SecurityError / PermissionDenied    PERMISSION_DENIED               False         FAILED
EvidenceValidationError             VALIDATION_ERROR / RUN_MISMATCH False         FAILED
EmptyGoalQuery / EmptyContent       INVALID_INPUT                   False         FAILED
UngroundedCitationError             UNGROUNDED_CITATION             False         FAILED
RAGError / VectorDimensionMismatch  RAG_STORAGE_ERROR               False         FAILED
TimeoutError / NetworkTimeout       TIMEOUT                         True          FAILED (Retry)
RateLimitExceeded                   RATE_LIMITED                    True          FAILED (Retry)
TransientWorkerError                WORKER_TRANSIENT_FAILURE        True          FAILED (Retry)
CancelledError                      CANCELLED                       False         CANCELLED
```

---

## 9. Testing Strategy

### Unit Tests per Worker:
* `test_planner_worker.py`: Valid decomposition, empty goal error, idempotency.
* `test_researcher_worker.py`: Search execution, evidence ingestion, vector indexing, prompt injection handling, run_id isolation.
* `test_analyst_worker.py`: Grounded claim extraction, finding synthesis, run_id validation.
* `test_verifier_worker.py`: Grounding audits, contradiction detection, citation formatting.
* `test_evaluator_worker.py`: Rubric calculation, pass/fail thresholds.
* `test_reporter_worker.py`: Markdown rendering, dossier compilation.

### Router & Security Tests:
* `test_worker_router.py`: Role/Task dispatch, permission checks, fallback behavior, error mapping, cancellation.

### End-to-End Orchestration Tests:
* `test_orchestrated_pipeline_e2e.py`:
  * Complete happy path: Goal $\rightarrow$ Planner $\rightarrow$ Researchers $\rightarrow$ Analyst $\rightarrow$ Verifier $\rightarrow$ Evaluator $\rightarrow$ Reporter $\rightarrow$ `ResearchDossier`.
  * Checkpoint persistence & crash recovery resume test.
  * Mid-flight cooperative cancellation test.
  * Multi-run concurrent isolation test (`run_A` vs `run_B`).
  * Injected failure & retry backoff test.

Target: **100% test pass rate with zero regressions across all 345 existing tests.**

---

## 10. Proposed Implementation Order

```
Phase 4.1: Specialized Agent Workers
  ├── 4.1.1: PlannerWorker (app.agents.planner) + tests
  ├── 4.1.2: ResearcherWorker (app.agents.researcher) + tests
  ├── 4.1.3: AnalystWorker (app.agents.analyst) + tests
  ├── 4.1.4: VerifierWorker (app.agents.verifier) + tests
  ├── 4.1.5: EvaluatorWorker (app.agents.evaluator) + tests
  └── 4.1.6: ReporterWorker (app.agents.reporter) + tests

Phase 4.2: Worker Router & Security Dispatcher
  └── 4.2.1: AgentWorkerRouter (app.orchestration.worker) + tests

Phase 4.3: End-to-End Runtime Pipeline Integration
  └── 4.3.1: DAGExecutor + Worker Mesh E2E Lifecycle Tests (test_orchestrated_pipeline_e2e.py)
```

---

## 11. Explicit Scope Boundaries

Phase 4 will **NOT** implement:
* Real external LLM API calls (OpenAI / Google Gemini API).
* External cloud vector databases (Qdrant / Chroma / Pinecone).
* Real web network scraping or browser automation.
* FastAPI HTTP route handlers or WebSocket/SSE gateway endpoints (reserved for Phase 5).
* Frontend web UI components.

All implementations remain **hermetic, offline, and deterministic**, relying on the approved mock adapters (`MockSearchClient`, `MockLLMClient`, `MockEmbeddingModel`, `InMemoryVectorStore`).

---

## 12. Definition of Done

1. All 6 specialized agent workers implemented under `app.agents.*` implementing `WorkerProtocol`.
2. `AgentWorkerRouter` implemented under `app.orchestration.worker` with `SecurityPolicy` validation.
3. Complete end-to-end multi-agent research workflow successfully executes via `DAGExecutor`.
4. Checkpoint persistence, crash recovery resume, retry backoff, and cancellation verified by tests.
5. Strict multi-tenant `run_id` isolation verified with zero cross-run data leakage.
6. 100% of new unit and integration tests pass offline.
7. Zero regressions across existing 345 test cases.
8. `ruff check .` returns 0 errors.
9. `ruff format --check .` returns 0 unformatted files.
10. `mypy --python-version 3.12 backend/app backend/tests` returns 0 type errors.
11. GitHub Actions CI passes with status `success` (GREEN).
