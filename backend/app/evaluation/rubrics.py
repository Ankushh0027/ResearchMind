"""Deterministic rubric scoring engine, claim matching heuristics, and citation analysis."""

import string

from app.evaluation.models import (
    GoldenScenario,
    GroundTruthFact,
)
from app.intelligence.models import ResearchDossier

# Formal rubric weight constants
GROUNDEDNESS_WEIGHT: float = 0.40
SCOPE_WEIGHT: float = 0.35
NEUTRALITY_WEIGHT: float = 0.25

# Basic English stopwords for deterministic token filtering
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
        "this",
        "these",
        "those",
        "or",
        "but",
        "than",
        "then",
        "so",
        "such",
        "can",
        "could",
        "should",
        "would",
        "which",
        "what",
        "when",
        "where",
        "who",
        "how",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "too",
        "very",
    }
)

_PUNCTUATION_TABLE = str.maketrans("", "", string.punctuation)


def normalize_text(text: str) -> str:
    """Normalize text by lowercasing, stripping punctuation, and collapsing whitespace."""
    if not text or not isinstance(text, str):
        return ""
    clean = text.lower().translate(_PUNCTUATION_TABLE)
    return " ".join(clean.split())


def tokenize(text: str, filter_stopwords: bool = True) -> set[str]:
    """Tokenize normalized text into distinct words, optionally filtering stopwords."""
    norm = normalize_text(text)
    if not norm:
        return set()
    tokens = norm.split()
    if filter_stopwords:
        return {t for t in tokens if len(t) > 2 and t not in _STOPWORDS}
    return set(tokens)


def compute_token_overlap(text_a: str, text_b: str) -> float:
    """Compute token Jaccard similarity coefficient between two text snippets."""
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a.intersection(tokens_b)
    union = tokens_a.union(tokens_b)
    if not union:
        return 0.0
    return len(intersection) / len(union)


def compute_inclusion_coefficient(needle: str, haystack: str) -> float:
    """Compute the proportion of tokens in needle that appear in haystack (inclusion/coverage)."""
    tokens_needle = tokenize(needle)
    tokens_haystack = tokenize(haystack)
    if not tokens_needle:
        return 0.0
    return len(tokens_needle.intersection(tokens_haystack)) / len(tokens_needle)


def match_claim(finding_text: str, fact: GroundTruthFact) -> float:
    """Match a finding narrative against an expected GroundTruthFact returning a score in [0.0, 1.0]."""
    if not finding_text:
        return 0.0

    norm_finding = normalize_text(finding_text)
    norm_claim = fact.normalized_claim or normalize_text(fact.claim)

    # 1. Exact normalized substring match
    if norm_claim and norm_claim in norm_finding:
        return 1.0

    # 2. Token overlap & inclusion similarity
    overlap = compute_token_overlap(finding_text, fact.claim)
    inclusion = compute_inclusion_coefficient(fact.claim, finding_text)

    # 3. Keyword matching boost
    keyword_score = 0.0
    if fact.keywords:
        matched_kw = sum(
            1 for kw in fact.keywords if normalize_text(kw) in norm_finding
        )
        keyword_score = matched_kw / len(fact.keywords)

    combined = max(overlap, 0.6 * inclusion + 0.4 * keyword_score)

    # Thresholding for meaningful semantic alignment
    if combined >= 0.45:
        return min(1.0, combined * 1.5)
    if combined >= 0.25:
        return combined
    return 0.0


def calculate_groundedness(
    dossier: ResearchDossier, scenario: GoldenScenario
) -> tuple[float, list[str]]:
    """Evaluate factual groundedness of findings against expected scenario facts."""
    feedback: list[str] = []
    if not dossier.key_findings:
        feedback.append("Dossier contains no key findings.")
        return 0.0, feedback

    expected_facts = [f for f in scenario.ground_truth_facts if f.is_required]
    if not expected_facts:
        expected_facts = list(scenario.ground_truth_facts)

    if not expected_facts:
        return 1.0, feedback

    # Aggregate finding narratives
    all_findings_text = " ".join(
        f"{kf.title} {kf.narrative}" for kf in dossier.key_findings
    )
    if dossier.executive_summary:
        all_findings_text += f" {dossier.executive_summary}"

    matched_facts_count = 0.0
    unmatched_facts: list[str] = []

    for fact in expected_facts:
        best_match = 0.0
        for kf in dossier.key_findings:
            score = match_claim(f"{kf.title} {kf.narrative}", fact)
            if score > best_match:
                best_match = score

        # Also check executive summary
        summary_score = match_claim(dossier.executive_summary, fact)
        best_match = max(best_match, summary_score)

        if best_match >= 0.50:
            matched_facts_count += best_match
        else:
            unmatched_facts.append(fact.claim)

    groundedness = min(1.0, matched_facts_count / len(expected_facts))

    if unmatched_facts:
        feedback.append(
            f"Missing {len(unmatched_facts)} required ground truth facts (e.g. '{unmatched_facts[0]}')."
        )

    return max(0.0, min(1.0, groundedness)), feedback


def calculate_scope(
    dossier: ResearchDossier, scenario: GoldenScenario
) -> tuple[float, list[str]]:
    """Evaluate goal inquiry scope and required topic completeness."""
    feedback: list[str] = []
    if not scenario.required_topics:
        return 1.0, feedback

    combined_text = " ".join(
        [
            dossier.goal_query,
            dossier.executive_summary,
            dossier.methodology_summary,
            dossier.markdown_report,
        ]
        + [f"{kf.title} {kf.narrative}" for kf in dossier.key_findings]
    )
    norm_combined = normalize_text(combined_text)
    combined_tokens = tokenize(combined_text)

    matched_topics = 0
    missing_topics: list[str] = []

    for topic in scenario.required_topics:
        norm_topic = normalize_text(topic)
        topic_tokens = tokenize(topic)

        # Match either exact substring or significant token overlap/inclusion
        inc = compute_inclusion_coefficient(topic, combined_text)
        if (
            norm_topic in norm_combined
            or (topic_tokens and topic_tokens.issubset(combined_tokens))
            or inc >= 0.40
        ):
            matched_topics += 1
        else:
            missing_topics.append(topic)

    score = matched_topics / len(scenario.required_topics)
    if missing_topics:
        feedback.append(f"Omitted required subtopics: {', '.join(missing_topics)}.")

    return max(0.0, min(1.0, score)), feedback


def calculate_neutrality(
    dossier: ResearchDossier, scenario: GoldenScenario
) -> tuple[float, float, float, list[str]]:
    """Evaluate contradiction detection, handling of conflicting claims, and neutrality.

    Returns:
        (neutrality_score, contradiction_precision, contradiction_recall, feedback)
    """
    feedback: list[str] = []
    expected_pairs = scenario.contradiction_pairs

    if not expected_pairs:
        # If no contradictions expected, perfect score if no spurious contradictions flagged
        precision = 1.0 if not dossier.contradictions else 0.8
        recall = 1.0
        return precision, precision, recall, feedback

    if not dossier.contradictions:
        feedback.append(
            f"Failed to identify {len(expected_pairs)} expected contradiction pairs."
        )
        return 0.0, 0.0, 0.0, feedback

    # Match dossier contradictions against expected contradiction pairs
    matched_expected = 0
    for pair in expected_pairs:
        pair_matched = False
        norm_topic = normalize_text(pair.topic)
        for item in dossier.contradictions:
            item_text = f"{item.description} {item.divergence_analysis}"
            norm_item = normalize_text(item_text)

            inc_a = compute_inclusion_coefficient(pair.claim_a, item_text)
            inc_b = compute_inclusion_coefficient(pair.claim_b, item_text)
            inc_desc = compute_inclusion_coefficient(pair.description, item_text)
            inc_topic = compute_inclusion_coefficient(pair.topic, item_text)

            if (
                (inc_a >= 0.20 and inc_b >= 0.20)
                or inc_desc >= 0.30
                or inc_topic >= 0.40
                or (norm_topic and norm_topic in norm_item)
            ):
                pair_matched = True
                break
        if pair_matched:
            matched_expected += 1

    recall = matched_expected / len(expected_pairs)
    precision = min(
        1.0,
        matched_expected / max(1, len(dossier.contradictions)),
    )
    score = 0.60 * recall + 0.40 * precision

    if matched_expected < len(expected_pairs):
        feedback.append(
            f"Detected {matched_expected}/{len(expected_pairs)} expected factual contradictions."
        )

    return (
        max(0.0, min(1.0, score)),
        max(0.0, min(1.0, precision)),
        max(0.0, min(1.0, recall)),
        feedback,
    )


def calculate_citation_metrics(
    dossier: ResearchDossier, scenario: GoldenScenario
) -> tuple[float, float, list[str]]:
    """Compute citation precision and citation recall against benchmark expectations.

    Returns:
        (citation_precision, citation_recall, feedback)
    """
    feedback: list[str] = []
    expected_citations = scenario.expected_citations

    dossier_citations = dossier.citations
    if not expected_citations:
        precision = 1.0 if dossier_citations else 1.0
        recall = 1.0
        return precision, recall, feedback

    if not dossier_citations:
        feedback.append("Dossier contains no citations.")
        return 0.0, 0.0, feedback

    # Extract source identifiers (URLs, titles, citation keys)
    cited_urls = {
        cit.source_url.strip().lower() for cit in dossier_citations if cit.source_url
    }
    cited_titles = {cit.title.strip().lower() for cit in dossier_citations if cit.title}
    cited_keys = {
        cit.citation_key.strip().lower()
        for cit in dossier_citations
        if cit.citation_key
    }

    matched_expected = 0
    for exp in expected_citations:
        exp_norm = exp.strip().lower()
        # Match URL substring or exact match
        url_match = any(exp_norm in u or u in exp_norm for u in cited_urls)
        # Match title by high token overlap
        title_match = any(
            compute_token_overlap(exp_norm, t) >= 0.50 for t in cited_titles
        )
        # Match citation key
        key_match = exp_norm in cited_keys

        if url_match or title_match or key_match:
            matched_expected += 1

    recall = matched_expected / len(expected_citations)
    # Precision is ratio of matched expected citations to total citations in dossier
    total_cited = len(dossier_citations)
    precision = min(1.0, matched_expected / max(1, total_cited))

    return (
        max(0.0, min(1.0, precision)),
        max(0.0, min(1.0, recall)),
        feedback,
    )


def calculate_composite_score(
    groundedness: float, scope: float, neutrality: float
) -> float:
    """Calculate normalized composite score using formal rubric weights."""
    composite = (
        GROUNDEDNESS_WEIGHT * groundedness
        + SCOPE_WEIGHT * scope
        + NEUTRALITY_WEIGHT * neutrality
    )
    return max(0.0, min(1.0, composite))


__all__ = [
    "GROUNDEDNESS_WEIGHT",
    "NEUTRALITY_WEIGHT",
    "SCOPE_WEIGHT",
    "calculate_citation_metrics",
    "calculate_composite_score",
    "calculate_groundedness",
    "calculate_neutrality",
    "calculate_scope",
    "compute_token_overlap",
    "match_claim",
    "normalize_text",
    "tokenize",
]
