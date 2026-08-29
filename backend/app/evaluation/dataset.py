"""Curated golden benchmark dataset across scientific, biomedical, financial, and technical domains."""

from app.evaluation.models import (
    ContradictionPair,
    GoldenScenario,
    GroundTruthFact,
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


__all__ = [
    "GOLDEN_BENCHMARK_SUITE",
    "SCENARIO_BIOMEDICAL_MRNA_DELIVERY",
    "SCENARIO_FINANCIAL_CBDC_SETTLEMENT",
    "SCENARIO_QUANTUM_ERROR_MITIGATION",
    "SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT",
    "get_scenario_by_id",
]
