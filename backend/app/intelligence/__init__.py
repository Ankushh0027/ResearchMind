"""Intelligence layer protocols, evaluation models, planner, evidence schemas, sanitization, and research dossiers."""

from app.intelligence.analyst import (
    AnalystAgent,
    AnalystProtocol,
    ThematicAnalysisResult,
    generate_finding_id,
)
from app.intelligence.claims import (
    ClaimExtractionResult,
    ClaimExtractorProtocol,
    DeterministicClaimExtractor,
    ExtractedClaim,
    generate_claim_id,
)
from app.intelligence.contradiction import (
    ContradictionDetectionResult,
    ContradictionDetector,
    ContradictionDetectorProtocol,
    generate_contradiction_id,
)
from app.intelligence.evidence import (
    EvidenceRecord,
    SourceProvenance,
    compute_sha256_hash,
    generate_evidence_id,
    generate_source_id,
)
from app.intelligence.ingestion import (
    EvidenceIngestionPipeline,
    IngestionResult,
    RawDocument,
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
    "AnalystAgent",
    "AnalystProtocol",
    "CitationReference",
    "ClaimExtractionResult",
    "ClaimExtractorProtocol",
    "ContentBoundarySanitizer",
    "ContradictionDetectionResult",
    "ContradictionDetector",
    "ContradictionDetectorProtocol",
    "ContradictionItem",
    "DeterministicClaimExtractor",
    "EvaluationReport",
    "EvaluationRubricScore",
    "EvidenceIngestionPipeline",
    "EvidenceRecord",
    "ExtractedClaim",
    "IngestionResult",
    "KeyFinding",
    "LLMClientProtocol",
    "MAX_RAW_TEXT_BYTES",
    "PlannedDecomposition",
    "PlannedSubtask",
    "PlannerAgent",
    "PlannerError",
    "REDACTED_REPLACEMENT",
    "RawDocument",
    "ResearchDossier",
    "SearchClientProtocol",
    "SourceProvenance",
    "ThematicAnalysisResult",
    "UntrustedContentEnvelope",
    "VectorMemoryProtocol",
    "compute_sha256_hash",
    "generate_claim_id",
    "generate_contradiction_id",
    "generate_evidence_id",
    "generate_finding_id",
    "generate_source_id",
]
