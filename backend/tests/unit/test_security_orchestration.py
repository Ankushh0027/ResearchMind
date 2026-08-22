"""Unit tests for security boundary and permission enforcement during task dispatch."""

import pytest

from app.common.enums import AgentRole, TaskType, ToolPermission
from app.common.errors import PermissionDeniedError
from app.orchestration.executor import DAGExecutor
from app.security.permissions import SecurityPolicy
from app.state.models import SubtaskNode


def test_security_policy_enforcement_on_subtask_dispatch() -> None:
    """Verify DAGExecutor._enforce_security_policy checks assigned role permissions."""
    executor = DAGExecutor()

    # Researcher has LLM_REASONING -> valid
    valid_node = SubtaskNode(
        subtask_id="t_sec_ok",
        task_type=TaskType.WEB_SEARCH,
        objective="Valid task",
        assigned_role=AgentRole.RESEARCHER,
    )
    # Should not raise
    executor._enforce_security_policy(valid_node)


def test_permission_denied_for_unauthorized_role_tool() -> None:
    """Verify unauthorized role-tool interaction is blocked by SecurityPolicy."""
    # Planner does NOT have WEB_SEARCH or STORAGE_WRITE permissions
    with pytest.raises(PermissionDeniedError):
        SecurityPolicy.enforce_permission(AgentRole.PLANNER, ToolPermission.WEB_SEARCH)

    with pytest.raises(PermissionDeniedError):
        SecurityPolicy.enforce_permission(
            AgentRole.PLANNER, ToolPermission.STORAGE_WRITE
        )
