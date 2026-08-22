"""Unit tests for agent contracts, dispatch payloads, and response envelopes."""

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TaskDispatchPayload,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.state.models import SubtaskNode


def test_agent_request_creation_and_serialization() -> None:
    """Verify AgentRequest fields, idempotency key, and JSON serialization."""
    req = AgentRequest(
        request_id="req_01",
        run_id="run_100",
        subtask_id="task_01",
        agent_role=AgentRole.RESEARCHER,
        task_type=TaskType.WEB_SEARCH,
        goal_context="Investigate KV-cache compression algorithms",
        input_data={"queries": ["streamingllm kv cache compression"]},
        idempotency_key="idem_hash_abc123",
        attempt_number=1,
    )
    assert req.idempotency_key == "idem_hash_abc123"
    assert req.attempt_number == 1
    assert req.schema_version == "1.0.0"

    raw_json = req.model_dump_json()
    restored = AgentRequest.model_validate_json(raw_json)
    assert restored.request_id == req.request_id
    assert restored.input_data["queries"] == ["streamingllm kv cache compression"]


def test_agent_response_success_and_error() -> None:
    """Verify AgentResponse success status and token tracking."""
    token_usage = TokenUsage(prompt_tokens=500, completion_tokens=150, total_tokens=650)

    # 1. Success response
    success_resp = AgentResponse(
        response_id="resp_01",
        request_id="req_01",
        run_id="run_100",
        subtask_id="task_01",
        agent_role=AgentRole.RESEARCHER,
        output_data={"evidence_collected_count": 4},
        execution_time_ms=1250,
        token_usage=token_usage,
    )
    assert success_resp.is_success is True
    assert success_resp.token_usage.total_tokens == 650

    # 2. Error response
    err = AgentError(
        error_code="RATE_LIMIT_EXCEEDED",
        error_type="QuotaError",
        message="Gemini API rate limit exceeded",
        is_retryable=True,
    )
    error_resp = AgentResponse(
        response_id="resp_02",
        request_id="req_01",
        run_id="run_100",
        subtask_id="task_01",
        agent_role=AgentRole.RESEARCHER,
        output_data={},
        execution_time_ms=200,
        error=err,
    )
    assert error_resp.is_success is False
    assert error_resp.error is not None
    assert error_resp.error.is_retryable is True


def test_task_dispatch_payload() -> None:
    """Verify TaskDispatchPayload encapsulates the subtask node."""
    subtask = SubtaskNode(
        subtask_id="sub_01",
        task_type=TaskType.SYNTHESIS,
        objective="Synthesize benchmark claims",
        assigned_role=AgentRole.ANALYST,
    )
    dispatch = TaskDispatchPayload(
        dispatch_id="disp_01",
        run_id="run_100",
        subtask=subtask,
        plan_version=2,
        attempt=1,
        idempotency_key="idem_sub_01",
        timeout_seconds=90,
    )
    assert dispatch.plan_version == 2
    assert dispatch.subtask.subtask_id == "sub_01"
    assert dispatch.timeout_seconds == 90


def test_worker_response_envelope() -> None:
    """Verify WorkerResponseEnvelope correlates back to dispatch."""
    resp = AgentResponse(
        response_id="resp_10",
        request_id="req_10",
        run_id="run_100",
        subtask_id="sub_01",
        agent_role=AgentRole.ANALYST,
        output_data={"claims_count": 2},
    )
    envelope = WorkerResponseEnvelope(
        envelope_id="env_01",
        dispatch_id="disp_01",
        run_id="run_100",
        subtask_id="sub_01",
        status=TaskStatus.COMPLETED,
        response=resp,
        worker_id="cloud-run-worker-99",
    )
    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.worker_id == "cloud-run-worker-99"
    assert envelope.response is not None
