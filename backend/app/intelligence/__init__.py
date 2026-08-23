"""Intelligence layer protocols, evaluation models, planner, evidence schemas, sanitization, and research dossiers."""

from app.common.evidence import VerificationAudit
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
from app.intelligence.evaluator import (
    EvaluatorAgent,
    EvaluatorProtocol,
    generate_eval_id,
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
from app.intelligence.reporter import (
    ReporterAgent,
    ReporterProtocol,
    generate_dossier_id,
)
from app.intelligence.sanitization import (
    MAX_RAW_TEXT_BYTES,
    REDACTED_REPLACEMENT,
    ContentBoundarySanitizer,
    UntrustedContentEnvelope,
)
from app.intelligence.verifier import (
    VerificationResult,
    VerifierAgent,
    VerifierProtocol,
    generate_audit_id,
    generate_citation_key,
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
    "EvaluatorAgent",
    "EvaluatorProtocol",
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
    "ReporterAgent",
    "ReporterProtocol",
    "ResearchDossier",
    "SearchClientProtocol",
    "SourceProvenance",
    "ThematicAnalysisResult",
    "UntrustedContentEnvelope",
    "VectorMemoryProtocol",
    "VerificationAudit",
    "VerificationResult",
    "VerifierAgent",
    "VerifierProtocol",
    "compute_sha256_hash",
    "generate_audit_id",
    "generate_citation_key",
    "generate_claim_id",
    "generate_contradiction_id",
    "generate_dossier_id",
    "generate_eval_id",
    "generate_evidence_id",
    "generate_finding_id",
    "generate_source_id",
]
