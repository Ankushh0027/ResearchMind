"""Integration tests executing the offline golden benchmark suite against synthesized research dossiers."""

import time

from app.common.enums import VerificationStatus
from app.evaluation.dataset import (
    GOLDEN_BENCHMARK_SUITE,
    SCENARIO_BIOMEDICAL_MRNA_DELIVERY,
    SCENARIO_FINANCIAL_CBDC_SETTLEMENT,
    SCENARIO_QUANTUM_ERROR_MITIGATION,
    SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT,
)
from app.evaluation.harness import run_benchmark
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    KeyFinding,
    ResearchDossier,
)


def _build_quantum_dossier() -> ResearchDossier:
    return ResearchDossier(
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


def _build_biomedical_dossier() -> ResearchDossier:
    return ResearchDossier(
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


def _build_financial_dossier() -> ResearchDossier:
    return ResearchDossier(
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


def _build_technical_dossier() -> ResearchDossier:
    return ResearchDossier(
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
                divergence_analysis="Some benchmarks claim parity while others reveal degraded multi-hop reasoning across distant segments.",
            ),
        ),
        confidence_rating=0.94,
        verification_status=VerificationStatus.VERIFIED,
        markdown_report="""
        # Hybrid Dense-Sparse RAG vs Monolithic Long-Context LLMs
        ## Hybrid Dense Sparse RAG
        Reduces time to first token TTFT latency and optimizes compute inference economics.
        ## Monolithic Long-Context LLMs
        Subject to quadratic attention bottlenecks.
        """,
    )


class TestEvaluationBenchmarkSuite:
    """Execute end-to-end evaluation harness against full benchmark dataset."""

    def test_full_golden_benchmark_execution_with_good_dossiers(self) -> None:
        dossiers = {
            SCENARIO_QUANTUM_ERROR_MITIGATION.scenario_id: _build_quantum_dossier(),
            SCENARIO_BIOMEDICAL_MRNA_DELIVERY.scenario_id: _build_biomedical_dossier(),
            SCENARIO_FINANCIAL_CBDC_SETTLEMENT.scenario_id: _build_financial_dossier(),
            SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT.scenario_id: _build_technical_dossier(),
        }

        scorecard = run_benchmark(
            dossiers=dossiers,
            scenarios=GOLDEN_BENCHMARK_SUITE,
            minimum_threshold=0.85,
        )

        assert scorecard.total_scenarios == 4
        assert scorecard.passed_scenarios == 4
        assert scorecard.failed_scenarios == 0
        assert scorecard.average_composite_score >= 0.85
        assert scorecard.average_groundedness >= 0.85
        assert scorecard.average_scope >= 0.85
        assert scorecard.average_neutrality >= 0.85
        assert scorecard.regression_gate_passed is True

    def test_benchmark_regression_detection_with_degraded_dossiers(self) -> None:
        # Provide only 1 good dossier and 3 degraded dossiers
        dossiers = {
            SCENARIO_QUANTUM_ERROR_MITIGATION.scenario_id: _build_quantum_dossier(),
            SCENARIO_BIOMEDICAL_MRNA_DELIVERY.scenario_id: ResearchDossier(
                dossier_id="dossier_degraded",
                run_id="run_deg",
                goal_query="Vague query",
                methodology_summary="None",
                executive_summary="Degraded",
                key_findings=(),
                citations=(),
                contradictions=(),
                confidence_rating=0.1,
                verification_status=VerificationStatus.UNVERIFIED,
                markdown_report="# Incomplete",
            ),
        }

        scorecard = run_benchmark(
            dossiers=dossiers,
            scenarios=GOLDEN_BENCHMARK_SUITE,
            minimum_threshold=0.85,
        )

        assert scorecard.total_scenarios == 4
        assert scorecard.passed_scenarios == 1
        assert scorecard.failed_scenarios == 3
        assert scorecard.regression_gate_passed is False

    def test_benchmark_determinism_across_multiple_runs(self) -> None:
        dossiers = {
            SCENARIO_QUANTUM_ERROR_MITIGATION.scenario_id: _build_quantum_dossier(),
            SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT.scenario_id: _build_technical_dossier(),
        }
        scenarios = (
            SCENARIO_QUANTUM_ERROR_MITIGATION,
            SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT,
        )

        scorecard_1 = run_benchmark(dossiers=dossiers, scenarios=scenarios)
        scorecard_2 = run_benchmark(dossiers=dossiers, scenarios=scenarios)
        scorecard_3 = run_benchmark(dossiers=dossiers, scenarios=scenarios)

        assert (
            scorecard_1.average_composite_score
            == scorecard_2.average_composite_score
            == scorecard_3.average_composite_score
        )
        assert (
            scorecard_1.average_groundedness
            == scorecard_2.average_groundedness
            == scorecard_3.average_groundedness
        )
        assert (
            scorecard_1.average_scope
            == scorecard_2.average_scope
            == scorecard_3.average_scope
        )
        assert (
            scorecard_1.regression_gate_passed
            == scorecard_2.regression_gate_passed
            == scorecard_3.regression_gate_passed
        )

    def test_benchmark_performance_is_subsecond(self) -> None:
        dossiers = {
            SCENARIO_QUANTUM_ERROR_MITIGATION.scenario_id: _build_quantum_dossier(),
            SCENARIO_BIOMEDICAL_MRNA_DELIVERY.scenario_id: _build_biomedical_dossier(),
            SCENARIO_FINANCIAL_CBDC_SETTLEMENT.scenario_id: _build_financial_dossier(),
            SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT.scenario_id: _build_technical_dossier(),
        }

        start = time.perf_counter()
        scorecard = run_benchmark(dossiers=dossiers, scenarios=GOLDEN_BENCHMARK_SUITE)
        duration = time.perf_counter() - start

        assert scorecard.total_scenarios == 4
        assert duration < 1.0  # Must execute in under 1 second
