"""Intelligence layer protocols, evaluation models, planner, evidence schemas, sanitization, and research dossiers."""

from app.intelligence.evidence import (
    EvidenceRecord,
    SourceProvenance,
    compute_sha256_hash,
    generate_evidence_id,
    generate_source_id,
)
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    EvaluationRubricScore,
    KeyFinding,
    ResearchDossier,
)
from app.intelligence.planner import (
    PlannedDecomposition,
    PlannedSubtask,
    PlannerAgent,
    PlannerError,
)
from app.intelligence.protocols import (
    LLMClientProtocol,
    SearchClientProtocol,
    VectorMemoryProtocol,
)
from app.intelligence.sanitization import (
    MAX_RAW_TEXT_BYTES,
    REDACTED_REPLACEMENT,
    ContentBoundarySanitizer,
    UntrustedContentEnvelope,
)

__all__ = [
    "CitationReference",
    "ContentBoundarySanitizer",
    "ContradictionItem",
    "EvaluationReport",
    "EvaluationRubricScore",
    "EvidenceRecord",
    "KeyFinding",
    "LLMClientProtocol",
    "MAX_RAW_TEXT_BYTES",
    "PlannedDecomposition",
    "PlannedSubtask",
    "PlannerAgent",
    "PlannerError",
    "REDACTED_REPLACEMENT",
    "ResearchDossier",
    "SearchClientProtocol",
    "SourceProvenance",
    "UntrustedContentEnvelope",
    "VectorMemoryProtocol",
    "compute_sha256_hash",
    "generate_evidence_id",
    "generate_source_id",
]
