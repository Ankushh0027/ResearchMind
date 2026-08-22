"""Unit tests for domain enums and string representations."""

import pytest

from app.common.enums import (
    AgentRole,
    EdgeType,
    RunStage,
    SourceTrustLevel,
    TaskStatus,
    TaskType,
    ToolPermission,
    VerificationStatus,
)


def test_agent_role_values() -> None:
    """Verify all defined agent roles are present and serialized properly."""
    expected_roles = {
        "planner",
        "researcher",
        "analyst",
        "verifier",
        "evaluator",
        "reporter",
        "system",
    }
    actual_roles = {role.value for role in AgentRole}
    assert expected_roles == actual_roles
    assert str(AgentRole.PLANNER) == "planner"


def test_task_type_values() -> None:
    """Verify all defined task types."""
    assert TaskType.DECOMPOSITION.value == "decomposition"
    assert TaskType.WEB_SEARCH.value == "web_search"
    assert TaskType.SYNTHESIS.value == "synthesis"
    assert TaskType.VERIFICATION.value == "verification"


def test_run_stage_values() -> None:
    """Verify standard lifecycle stages."""
    assert RunStage.CREATED.value == "CREATED"
    assert RunStage.RUNNING.value == "RUNNING"
    assert RunStage.COMPLETED.value == "COMPLETED"
    assert RunStage.FAILED.value == "FAILED"
    assert RunStage.RETRYING.value == "RETRYING"


def test_task_status_values() -> None:
    """Verify task statuses."""
    assert TaskStatus.PENDING.value == "PENDING"
    assert TaskStatus.IN_PROGRESS.value == "IN_PROGRESS"
    assert TaskStatus.COMPLETED.value == "COMPLETED"


def test_verification_status_values() -> None:
    """Verify claim verification classifications."""
    assert VerificationStatus.VERIFIED.value == "VERIFIED"
    assert VerificationStatus.CONTRADICTED.value == "CONTRADICTED"
    assert VerificationStatus.INSUFFICIENT_EVIDENCE.value == "INSUFFICIENT_EVIDENCE"


def test_tool_permission_values() -> None:
    """Verify tool permission string prefixes."""
    for perm in ToolPermission:
        assert perm.value.startswith("tool:")


def test_source_trust_level_values() -> None:
    """Verify source trust tiers."""
    assert SourceTrustLevel.TRUSTED_PRIMARY.value == "trusted_primary"
    assert SourceTrustLevel.PEER_REVIEWED.value == "peer_reviewed"
    assert SourceTrustLevel.UNVERIFIED_USER_UPLOAD.value == "unverified_user_upload"


def test_edge_type_values() -> None:
    """Verify edge types."""
    assert EdgeType.DATA.value == "data"
    assert EdgeType.SEQUENCE.value == "sequence"


def test_invalid_enum_lookup() -> None:
    """Verify that invalid strings raise ValueError when converted to enum."""
    with pytest.raises(ValueError):
        AgentRole("nonexistent_role")
