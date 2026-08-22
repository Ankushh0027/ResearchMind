"""Least-privilege tool permission matrix and access policy enforcement."""

from typing import Final

from app.common.enums import AgentRole, ToolPermission
from app.common.errors import PermissionDeniedError

# Explicit capability assignment matrix per agent role
ROLE_TOOL_PERMISSIONS: Final[dict[AgentRole, frozenset[ToolPermission]]] = {
    AgentRole.PLANNER: frozenset(
        {
            ToolPermission.LLM_REASONING,
        }
    ),
    AgentRole.RESEARCHER: frozenset(
        {
            ToolPermission.WEB_SEARCH,
            ToolPermission.ACADEMIC_SEARCH,
            ToolPermission.DOC_EXTRACT,
            ToolPermission.VECTOR_SEARCH,
            ToolPermission.VECTOR_UPSERT,
            ToolPermission.LLM_REASONING,
        }
    ),
    AgentRole.ANALYST: frozenset(
        {
            ToolPermission.VECTOR_SEARCH,
            ToolPermission.LLM_REASONING,
        }
    ),
    AgentRole.VERIFIER: frozenset(
        {
            ToolPermission.VECTOR_SEARCH,
            ToolPermission.WEB_SEARCH,
            ToolPermission.DOC_EXTRACT,
            ToolPermission.LLM_REASONING,
        }
    ),
    AgentRole.EVALUATOR: frozenset(
        {
            ToolPermission.LLM_REASONING,
        }
    ),
    AgentRole.REPORTER: frozenset(
        {
            ToolPermission.STORAGE_WRITE,
            ToolPermission.LLM_REASONING,
        }
    ),
    AgentRole.SYSTEM: frozenset(
        {
            ToolPermission.WEB_SEARCH,
            ToolPermission.ACADEMIC_SEARCH,
            ToolPermission.DOC_EXTRACT,
            ToolPermission.VECTOR_SEARCH,
            ToolPermission.VECTOR_UPSERT,
            ToolPermission.STORAGE_READ,
            ToolPermission.STORAGE_WRITE,
            ToolPermission.LLM_REASONING,
        }
    ),
}


class SecurityPolicy:
    """Enforces least-privilege security boundaries on agent tool executions."""

    @classmethod
    def get_permissions(cls, role: AgentRole) -> frozenset[ToolPermission]:
        """Return the allowed tool permission set for a given agent role."""
        return ROLE_TOOL_PERMISSIONS.get(role, frozenset())

    @classmethod
    def has_permission(cls, role: AgentRole, permission: ToolPermission) -> bool:
        """Check if an agent role has the requested tool permission."""
        allowed = cls.get_permissions(role)
        return permission in allowed

    @classmethod
    def enforce_permission(cls, role: AgentRole, permission: ToolPermission) -> None:
        """Raise PermissionDeniedError if the role lacks the required tool permission."""
        if not cls.has_permission(role, permission):
            raise PermissionDeniedError(
                agent_role=str(role),
                tool_permission=str(permission),
                reason=f"Role '{role}' is not granted '{permission}' by least-privilege policy",
            )
