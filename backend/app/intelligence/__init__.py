"""Intelligence layer protocols, evaluation models, planner, evidence schemas, and research dossiers."""

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

__all__ = [
    "CitationReference",
    "ContradictionItem",
    "EvaluationReport",
    "EvaluationRubricScore",
    "EvidenceRecord",
    "KeyFinding",
    "LLMClientProtocol",
    "PlannedDecomposition",
    "PlannedSubtask",
    "PlannerAgent",
    "PlannerError",
    "ResearchDossier",
    "SearchClientProtocol",
    "SourceProvenance",
    "VectorMemoryProtocol",
    "compute_sha256_hash",
    "generate_evidence_id",
    "generate_source_id",
]
