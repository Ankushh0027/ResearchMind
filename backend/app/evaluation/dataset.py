"""Curated golden benchmark dataset across scientific, biomedical, financial, and technical domains."""

from app.common.enums import VerificationStatus
from app.evaluation.models import (
    ContradictionPair,
    GoldenScenario,
    GroundTruthFact,
)
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    KeyFinding,
    ResearchDossier,
)

# 1. Academic & Quantum Computing Scenario
SCENARIO_QUANTUM_ERROR_MITIGATION = GoldenScenario(
    scenario_id="scenario_academic_quantum_01",
    domain="academic",
    research_question=(
        "Evaluate the viability of zero-noise extrapolation and probabilistic error cancellation "
        "in superconducting quantum processors compared to fault-tolerant surface codes."
    ),
    required_topics=(
        "zero-noise extrapolation",
        "probabilistic error cancellation",
        "fault-tolerant surface codes",
        "decoherence physical qubit overhead",
    ),
    optional_topics=(
        "randomized compiling",
        "quantum volume benchmarks",
    ),
    ground_truth_facts=(
        GroundTruthFact(
            fact_id="q_fact_01",
            claim="Zero-noise extrapolation scales error mitigation without physical qubit overhead by amplifying pulse noise and extrapolating to the zero-noise limit.",
            normalized_claim="zero-noise extrapolation scales error mitigation without physical qubit overhead",
            is_required=True,
            supporting_citation_keys=("https://arxiv.org/abs/quantum-zne-benchmark",),
            keywords=("zero-noise", "extrapolation", "pulse noise", "overhead"),
        ),
        GroundTruthFact(
            fact_id="q_fact_02",
            claim="Probabilistic error cancellation requires exponential sampling overhead as circuit depth grows.",
            normalized_claim="probabilistic error cancellation requires exponential sampling overhead circuit depth",
            is_required=True,
            supporting_citation_keys=("https://arxiv.org/abs/pec-sampling-overhead",),
            keywords=("probabilistic", "cancellation", "exponential sampling", "depth"),
        ),
        GroundTruthFact(
            fact_id="q_fact_03",
            claim="Surface codes require physical-to-logical qubit ratios exceeding 1000:1 for fault-tolerant error thresholds.",
            normalized_claim="surface codes require physical to logical qubit ratios exceeding 1000 1",
            is_required=True,
            supporting_citation_keys=("https://arxiv.org/abs/surface-code-thresholds",),
            keywords=("surface codes", "physical-to-logical", "1000:1", "threshold"),
        ),
    ),
    expected_citations=(
        "https://arxiv.org/abs/quantum-zne-benchmark",
        "https://arxiv.org/abs/pec-sampling-overhead",
        "https://arxiv.org/abs/surface-code-thresholds",
    ),
    contradiction_pairs=(
        ContradictionPair(
            pair_id="q_contra_01",
            topic="ZNE Depth Scalability",
            claim_a="Zero-noise extrapolation maintains low error rates up to 100 gate depths in superconducting qubits.",
            claim_b="Zero-noise extrapolation fails exponentially beyond 30 gate depths due to non-Markovian noise drift.",
            description="Conflicting empirical limits on zero-noise extrapolation circuit depth bounds.",
        ),
    ),
    minimum_quality_threshold=0.85,
)

# 2. Biomedical & Gene Delivery Scenario
SCENARIO_BIOMEDICAL_MRNA_DELIVERY = GoldenScenario(
    scenario_id="scenario_biomedical_mrna_02",
    domain="biomedical",
    research_question=(
        "Compare lipid nanoparticle (LNP) encapsulated mRNA delivery with adeno-associated virus (AAV) "
        "vectors in targeted hepatic gene editing therapies."
    ),
    required_topics=(
        "lipid nanoparticle LNP delivery",
        "adeno-associated virus AAV vector",
        "hepatic immunogenicity",
        "repeat dosing and durability",
    ),
    optional_topics=(
        "electroporation ex-vivo",
        "viral capsid engineering",
    ),
    ground_truth_facts=(
        GroundTruthFact(
            fact_id="bio_fact_01",
            claim="Lipid nanoparticles enable transient expression and permit repeat redosing without neutralizing antibody formation.",
            normalized_claim="lipid nanoparticles enable transient expression repeat redosing neutralizing antibody",
            is_required=True,
            supporting_citation_keys=("https://doi.org/10.1038/lnp-gene-delivery",),
            keywords=(
                "lipid nanoparticles",
                "transient",
                "repeat redosing",
                "antibodies",
            ),
        ),
        GroundTruthFact(
            fact_id="bio_fact_02",
            claim="Adeno-associated virus vectors provide sustained transgene expression but induce robust neutralizing humoral immunity preventing redosing.",
            normalized_claim="adeno-associated virus vectors sustained transgene humoral immunity preventing redosing",
            is_required=True,
            supporting_citation_keys=("https://doi.org/10.1016/aav-immunogenicity",),
            keywords=("aav", "sustained", "humoral immunity", "redosing"),
        ),
        GroundTruthFact(
            fact_id="bio_fact_03",
            claim="Ionizable cationic lipids in LNPs facilitate endosomal escape in hepatocytes under acidic pH.",
            normalized_claim="ionizable cationic lipids in lnps facilitate endosomal escape hepatocytes",
            is_required=True,
            supporting_citation_keys=("https://doi.org/10.1038/lnp-gene-delivery",),
            keywords=("ionizable", "cationic", "endosomal escape", "hepatocytes"),
        ),
    ),
    expected_citations=(
        "https://doi.org/10.1038/lnp-gene-delivery",
        "https://doi.org/10.1016/aav-immunogenicity",
    ),
    contradiction_pairs=(
        ContradictionPair(
            pair_id="bio_contra_01",
            topic="Hepatic Tolerability Margins",
            claim_a="LNP hepatic accumulation causes acute transient liver enzyme elevation and hepatocyte apoptosis.",
            claim_b="LNP formulations show negligible hepatic toxicity and zero elevation in ALT/AST at therapeutic dosing.",
            description="Divergent safety data regarding hepatotoxicity of ionizable lipid nanoparticles.",
        ),
    ),
    minimum_quality_threshold=0.85,
)

# 3. Financial & Economic Settlement Scenario
SCENARIO_FINANCIAL_CBDC_SETTLEMENT = GoldenScenario(
    scenario_id="scenario_financial_cbdc_03",
    domain="financial",
    research_question=(
        "Analyze the liquidity, settlement finality, and monetary policy transmission trade-offs "
        "between wholesale Central Bank Digital Currencies (wCBDCs) and fiat-backed stablecoins in cross-border settlement."
    ),
    required_topics=(
        "wholesale CBDC settlement",
        "fiat-backed stablecoins",
        "liquidity fragmentation",
        "counterparty credit risk",
    ),
    optional_topics=(
        "automated market makers",
        "capital flow management",
    ),
    ground_truth_facts=(
        GroundTruthFact(
            fact_id="fin_fact_01",
            claim="Wholesale CBDCs eliminate credit risk by providing direct central bank money settlement finality in real time.",
            normalized_claim="wholesale cbdcs eliminate credit risk direct central bank money settlement finality",
            is_required=True,
            supporting_citation_keys=("https://bis.org/publ/wcbdc-settlement",),
            keywords=(
                "wholesale cbdc",
                "credit risk",
                "central bank money",
                "finality",
            ),
        ),
        GroundTruthFact(
            fact_id="fin_fact_02",
            claim="Fiat-backed stablecoins introduce commercial bank counterparty risk and reserve asset insolvency exposure.",
            normalized_claim="fiat-backed stablecoins commercial bank counterparty risk reserve insolvency",
            is_required=True,
            supporting_citation_keys=("https://fsb.org/stablecoin-regulation-report",),
            keywords=("stablecoins", "counterparty risk", "insolvency", "reserves"),
        ),
        GroundTruthFact(
            fact_id="fin_fact_03",
            claim="Cross-currency PvP settlement across disparate national wCBDCs requires multi-central bank interoperability protocols.",
            normalized_claim="cross-currency pvp settlement disparate national wcbdcs multi-central bank interoperability",
            is_required=True,
            supporting_citation_keys=("https://bis.org/publ/wcbdc-settlement",),
            keywords=("pvp settlement", "wcbdc", "interoperability", "cross-currency"),
        ),
    ),
    expected_citations=(
        "https://bis.org/publ/wcbdc-settlement",
        "https://fsb.org/stablecoin-regulation-report",
    ),
    contradiction_pairs=(
        ContradictionPair(
            pair_id="fin_contra_01",
            topic="Cross-Border Liquidity Depth",
            claim_a="Private stablecoins provide superior 24/7 liquidity pool depth for low-volume currency corridors.",
            claim_b="Private stablecoins experience rapid liquidity evaporation and decoupling during market stress events.",
            description="Disagreement over whether private stablecoins provide resilient liquidity in cross-border settlement.",
        ),
    ),
    minimum_quality_threshold=0.85,
)

# 4. Technical & Systems Architecture Scenario
SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT = GoldenScenario(
    scenario_id="scenario_technical_rag_04",
    domain="technical",
    research_question=(
        "Assess latency, compute economics, and needle-in-a-haystack recall trade-offs "
        "between hybrid dense-sparse RAG architectures and monolithic long-context window LLMs."
    ),
    required_topics=(
        "hybrid dense sparse RAG",
        "monolithic long-context LLMs",
        "time to first token TTFT latency",
        "compute inference economics",
    ),
    optional_topics=(
        "graph RAG indexing",
        "speculative decoding",
    ),
    ground_truth_facts=(
        GroundTruthFact(
            fact_id="tech_fact_01",
            claim="Hybrid RAG combines dense semantic embeddings with BM25 keyword matching to mitigate dense retrieval blind spots.",
            normalized_claim="hybrid rag combines dense semantic embeddings with bm25 keyword matching",
            is_required=True,
            supporting_citation_keys=("https://arxiv.org/abs/hybrid-rag-retrieval",),
            keywords=("hybrid rag", "dense embeddings", "bm25", "keyword matching"),
        ),
        GroundTruthFact(
            fact_id="tech_fact_02",
            claim="Monolithic long-context LLMs experience linear or quadratic attention compute overhead and positional degradation in middle document positions.",
            normalized_claim="monolithic long-context llms experience attention compute overhead positional degradation",
            is_required=True,
            supporting_citation_keys=(
                "https://arxiv.org/abs/lost-in-the-middle-long-context",
            ),
            keywords=(
                "long-context",
                "attention",
                "lost in the middle",
                "positional degradation",
            ),
        ),
        GroundTruthFact(
            fact_id="tech_fact_03",
            claim="RAG architectures reduce per-query inference costs by up to 70% on large enterprise document archives.",
            normalized_claim="rag architectures reduce per-query inference costs by up to 70 percent",
            is_required=True,
            supporting_citation_keys=("https://arxiv.org/abs/hybrid-rag-retrieval",),
            keywords=("rag", "inference costs", "70%", "economics"),
        ),
    ),
    expected_citations=(
        "https://arxiv.org/abs/hybrid-rag-retrieval",
        "https://arxiv.org/abs/lost-in-the-middle-long-context",
    ),
    contradiction_pairs=(
        ContradictionPair(
            pair_id="tech_contra_01",
            topic="Multi-Hop Synthesis Recall",
            claim_a="Long-context window models match RAG accuracy on complex multi-hop cross-document reasoning tasks.",
            claim_b="Long-context window models degrade significantly when relevant evidence is scattered across multiple distant segments.",
            description="Contradictory findings regarding long-context LLM retrieval precision under distributed evidence.",
        ),
    ),
    minimum_quality_threshold=0.85,
)

GOLDEN_BENCHMARK_SUITE: tuple[GoldenScenario, ...] = (
    SCENARIO_QUANTUM_ERROR_MITIGATION,
    SCENARIO_BIOMEDICAL_MRNA_DELIVERY,
    SCENARIO_FINANCIAL_CBDC_SETTLEMENT,
    SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT,
)


def get_scenario_by_id(scenario_id: str) -> GoldenScenario | None:
    """Retrieve a GoldenScenario by its unique scenario_id."""
    for s in GOLDEN_BENCHMARK_SUITE:
        if s.scenario_id == scenario_id:
            return s
    return None


def create_standard_golden_dossiers() -> dict[str, ResearchDossier]:
    """Generate canonical passing reference dossiers for all golden benchmark scenarios."""
    dossiers: dict[str, ResearchDossier] = {}

    # 1. Quantum Error Mitigation
    dossiers[SCENARIO_QUANTUM_ERROR_MITIGATION.scenario_id] = ResearchDossier(
        dossier_id="dossier_quantum_01",
        run_id="run_quantum_01",
        goal_query=SCENARIO_QUANTUM_ERROR_MITIGATION.research_question,
        methodology_summary="Decomposed query into zero-noise extrapolation, probabilistic error cancellation, and surface codes.",
        executive_summary="Zero-noise extrapolation scales error mitigation without physical qubit overhead by amplifying pulse noise. Surface codes require physical-to-logical qubit ratios exceeding 1000:1.",
        key_findings=(
            KeyFinding(
                finding_id="kf_q1",
                title="Zero-Noise Extrapolation Scaling",
                narrative="Zero-noise extrapolation scales error mitigation without physical qubit overhead by amplifying pulse noise and extrapolating to zero limit.",
            ),
            KeyFinding(
                finding_id="kf_q2",
                title="PEC Exponential Sampling",
                narrative="Probabilistic error cancellation requires exponential sampling overhead as circuit depth grows.",
            ),
            KeyFinding(
                finding_id="kf_q3",
                title="Fault-Tolerant Surface Code Thresholds",
                narrative="Surface codes require physical-to-logical qubit ratios exceeding 1000:1 for fault-tolerant error thresholds.",
            ),
        ),
        citations=(
            CitationReference(
                citation_key="[CIT-01]",
                evidence_id="ev1",
                source_url="https://arxiv.org/abs/quantum-zne-benchmark",
                title="ZNE Benchmark",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-02]",
                evidence_id="ev2",
                source_url="https://arxiv.org/abs/pec-sampling-overhead",
                title="PEC Sampling Overhead",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-03]",
                evidence_id="ev3",
                source_url="https://arxiv.org/abs/surface-code-thresholds",
                title="Surface Code Thresholds",
                domain="arxiv.org",
            ),
        ),
        contradictions=(
            ContradictionItem(
                item_id="contra_q1",
                description="ZNE Depth Scalability divergence across experiments.",
                conflicting_claim_ids=("c1", "c2"),
                divergence_analysis="One group observed stability up to 100 gate depths while another found failure beyond 30 gate depths.",
            ),
        ),
        confidence_rating=0.92,
        verification_status=VerificationStatus.VERIFIED,
        markdown_report="""
        # Quantum Error Mitigation vs Fault-Tolerant Surface Codes
        ## Zero-Noise Extrapolation
        Scales error mitigation without physical qubit overhead.
        ## Probabilistic Error Cancellation
        Exhibits sampling overhead.
        ## Fault-Tolerant Surface Codes
        Requires 1000:1 qubit overhead to surpass decoherence physical qubit overhead.
        """,
    )

    # 2. Biomedical mRNA Delivery
    dossiers[SCENARIO_BIOMEDICAL_MRNA_DELIVERY.scenario_id] = ResearchDossier(
        dossier_id="dossier_biomedical_02",
        run_id="run_biomedical_02",
        goal_query=SCENARIO_BIOMEDICAL_MRNA_DELIVERY.research_question,
        methodology_summary="Analyzed lipid nanoparticle LNP delivery vs adeno-associated virus AAV vector.",
        executive_summary="Lipid nanoparticles enable transient expression and permit repeat redosing without neutralizing antibody formation. Ionizable cationic lipids facilitate endosomal escape in hepatocytes.",
        key_findings=(
            KeyFinding(
                finding_id="kf_b1",
                title="LNP Redosing & Humoral Response",
                narrative="Lipid nanoparticles enable transient expression and permit repeat redosing without neutralizing antibody formation.",
            ),
            KeyFinding(
                finding_id="kf_b2",
                title="AAV Transgene Durability & Immunity",
                narrative="Adeno-associated virus vectors provide sustained transgene expression but induce robust neutralizing humoral immunity preventing redosing.",
            ),
            KeyFinding(
                finding_id="kf_b3",
                title="Ionizable Cationic Lipids",
                narrative="Ionizable cationic lipids in LNPs facilitate endosomal escape in hepatocytes under acidic pH.",
            ),
        ),
        citations=(
            CitationReference(
                citation_key="[CIT-B1]",
                evidence_id="ev_b1",
                source_url="https://doi.org/10.1038/lnp-gene-delivery",
                title="LNP Gene Delivery",
                domain="doi.org",
            ),
            CitationReference(
                citation_key="[CIT-B2]",
                evidence_id="ev_b2",
                source_url="https://doi.org/10.1016/aav-immunogenicity",
                title="AAV Immunogenicity",
                domain="doi.org",
            ),
        ),
        contradictions=(
            ContradictionItem(
                item_id="contra_b1",
                description="Hepatic Tolerability Margins of ionizable LNPs.",
                conflicting_claim_ids=("cb1", "cb2"),
                divergence_analysis="Certain pre-clinical models show transient liver enzyme elevation whereas others show zero elevation at therapeutic dosing.",
            ),
        ),
        confidence_rating=0.91,
        verification_status=VerificationStatus.VERIFIED,
        markdown_report="""
        # LNP mRNA vs AAV Vectors
        ## Lipid Nanoparticle LNP Delivery
        Enables repeat dosing and durability without hepatic immunogenicity.
        ## Adeno-Associated Virus AAV Vector
        Provides durability but limited repeat dosing due to neutralizing antibodies.
        """,
    )

    # 3. Financial CBDC Settlement
    dossiers[SCENARIO_FINANCIAL_CBDC_SETTLEMENT.scenario_id] = ResearchDossier(
        dossier_id="dossier_financial_03",
        run_id="run_financial_03",
        goal_query=SCENARIO_FINANCIAL_CBDC_SETTLEMENT.research_question,
        methodology_summary="Analyzed wholesale CBDC settlement, fiat-backed stablecoins, and liquidity fragmentation.",
        executive_summary="Wholesale CBDCs eliminate credit risk through central bank money finality, whereas stablecoins introduce counterparty credit risk.",
        key_findings=(
            KeyFinding(
                finding_id="kf_f1",
                title="Wholesale CBDC Settlement Finality",
                narrative="Wholesale CBDCs eliminate credit risk by providing direct central bank money settlement finality in real time.",
            ),
            KeyFinding(
                finding_id="kf_f2",
                title="Stablecoin Insolvency Exposure",
                narrative="Fiat-backed stablecoins introduce commercial bank counterparty risk and reserve asset insolvency exposure.",
            ),
            KeyFinding(
                finding_id="kf_f3",
                title="Cross-Currency PvP Interoperability",
                narrative="Cross-currency PvP settlement across disparate national wCBDCs requires multi-central bank interoperability protocols.",
            ),
        ),
        citations=(
            CitationReference(
                citation_key="[CIT-F1]",
                evidence_id="ev_f1",
                source_url="https://bis.org/publ/wcbdc-settlement",
                title="wCBDC Settlement",
                domain="bis.org",
            ),
            CitationReference(
                citation_key="[CIT-F2]",
                evidence_id="ev_f2",
                source_url="https://fsb.org/stablecoin-regulation-report",
                title="Stablecoin Regulation",
                domain="fsb.org",
            ),
        ),
        contradictions=(
            ContradictionItem(
                item_id="contra_f1",
                description="Cross-Border Liquidity Depth and resiliency of stablecoins.",
                conflicting_claim_ids=("cf1", "cf2"),
                divergence_analysis="Proponents highlight 24/7 liquidity pool depth while detractors observe severe liquidity evaporation during stress.",
            ),
        ),
        confidence_rating=0.90,
        verification_status=VerificationStatus.VERIFIED,
        markdown_report="""
        # Cross-Border Wholesale CBDC vs Stablecoins
        ## Wholesale CBDC Settlement
        Addresses liquidity fragmentation and mitigates counterparty credit risk.
        ## Fiat-Backed Stablecoins
        Subject to commercial reserve asset risk.
        """,
    )

    # 4. Technical RAG vs Long-Context
    dossiers[SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT.scenario_id] = ResearchDossier(
        dossier_id="dossier_technical_04",
        run_id="run_technical_04",
        goal_query=SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT.research_question,
        methodology_summary="Evaluated hybrid dense sparse RAG and monolithic long-context LLMs.",
        executive_summary="Hybrid RAG combines dense embeddings with BM25 keyword matching to reduce per-query inference costs by up to 70%.",
        key_findings=(
            KeyFinding(
                finding_id="kf_t1",
                title="Hybrid Dense-Sparse RAG Architecture",
                narrative="Hybrid RAG combines dense semantic embeddings with BM25 keyword matching to mitigate dense retrieval blind spots.",
            ),
            KeyFinding(
                finding_id="kf_t2",
                title="Long-Context Attention Compute Overhead",
                narrative="Monolithic long-context LLMs experience linear or quadratic attention compute overhead and positional degradation in middle document positions.",
            ),
            KeyFinding(
                finding_id="kf_t3",
                title="Inference Cost Economics",
                narrative="RAG architectures reduce per-query inference costs by up to 70% on large enterprise document archives.",
            ),
        ),
        citations=(
            CitationReference(
                citation_key="[CIT-T1]",
                evidence_id="ev_t1",
                source_url="https://arxiv.org/abs/hybrid-rag-retrieval",
                title="Hybrid RAG Retrieval",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-T2]",
                evidence_id="ev_t2",
                source_url="https://arxiv.org/abs/lost-in-the-middle-long-context",
                title="Lost in the Middle",
                domain="arxiv.org",
            ),
        ),
        contradictions=(
            ContradictionItem(
                item_id="contra_t1",
                description="Multi-Hop Synthesis Recall in long-context models.",
                conflicting_claim_ids=("ct1", "ct2"),
                divergence_analysis="Contradictory findings regarding long-context LLM retrieval precision under distributed evidence.",
            ),
        ),
        confidence_rating=0.93,
        verification_status=VerificationStatus.VERIFIED,
        markdown_report="""
        # Hybrid RAG vs Monolithic Long-Context LLMs
        ## Hybrid Dense-Sparse RAG
        Combines semantic vectors and BM25 to mitigate dense retrieval blind spots.
        ## Long-Context Attention Compute Overhead
        Exhibits quadratic attention scaling and lost-in-the-middle degradation.
        """,
    )

    return dossiers


__all__ = [
    "GOLDEN_BENCHMARK_SUITE",
    "SCENARIO_BIOMEDICAL_MRNA_DELIVERY",
    "SCENARIO_FINANCIAL_CBDC_SETTLEMENT",
    "SCENARIO_QUANTUM_ERROR_MITIGATION",
    "SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT",
    "create_standard_golden_dossiers",
    "get_scenario_by_id",
]
