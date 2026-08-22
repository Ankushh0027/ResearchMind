"""Domain enums for ResearchMind multi-agent workflow."""

from enum import Enum


class StrEnum(str, Enum):
    """String-backed Enum base class for clean JSON serialization."""

    def __str__(self) -> str:
        return str(self.value)


class AgentRole(StrEnum):
    """Role identifiers for specialized autonomous agents."""

    PLANNER = "planner"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    VERIFIER = "verifier"
    EVALUATOR = "evaluator"
    REPORTER = "reporter"
    SYSTEM = "system"


class TaskType(StrEnum):
    """Specific task execution types dispatched across the agent mesh."""

    DECOMPOSITION = "decomposition"
    WEB_SEARCH = "web_search"
    ACADEMIC_SEARCH = "academic_search"
    DOC_ANALYSIS = "doc_analysis"
    SYNTHESIS = "synthesis"
    VERIFICATION = "verification"
    CONFLICT_DETECTION = "conflict_detection"
    EVALUATION = "evaluation"
    REPORTING = "reporting"


class RunStage(StrEnum):
    """Lifecycle stages of an end-to-end research session."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PLANNING = "PLANNING"
    RESEARCHING = "RESEARCHING"
    ANALYZING = "ANALYZING"
    VERIFYING = "VERIFYING"
    EVALUATING = "EVALUATING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStatus(StrEnum):
    """Execution status for individual subtask nodes."""

    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class VerificationStatus(StrEnum):
    """Verification classification for factual claims."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"


class ToolPermission(StrEnum):
    """Granular tool capabilities governed by security policy."""

    WEB_SEARCH = "tool:web_search"
    ACADEMIC_SEARCH = "tool:academic_search"
    DOC_EXTRACT = "tool:doc_extract"
    VECTOR_SEARCH = "tool:vector_search"
    VECTOR_UPSERT = "tool:vector_upsert"
    STORAGE_READ = "tool:storage_read"
    STORAGE_WRITE = "tool:storage_write"
    LLM_REASONING = "tool:llm_reasoning"


class SourceTrustLevel(StrEnum):
    """Trust hierarchy for external evidence sources."""

    TRUSTED_PRIMARY = "trusted_primary"
    PEER_REVIEWED = "peer_reviewed"
    OFFICIAL_DOC = "official_doc"
    GENERAL_WEB = "general_web"
    UNVERIFIED_USER_UPLOAD = "unverified_user_upload"


class EdgeType(StrEnum):
    """Dependency relationship between task nodes in the execution graph."""

    DATA = "data"
    SEQUENCE = "sequence"
