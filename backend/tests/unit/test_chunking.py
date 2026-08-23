"""Unit tests for Phase 3.3.3 Deterministic Evidence Chunking."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel
from app.common.errors import EvidenceValidationError
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.rag.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_CHUNKS,
    DeterministicTextChunker,
    TextChunk,
    TextChunker,
)


def _make_sample_evidence(
    content: str = "Empirical benchmark confirms linear scaling across 100 nodes.",
    evidence_id: str = "ev_sample_12345",
    run_id: str = "run_alpha_01",
    metadata: dict[str, Any] | None = None,
) -> EvidenceRecord:
    provenance = SourceProvenance.from_content(
        raw_content=content,
        title="Scalability in Distributed Systems",
        source_url="https://arxiv.org/abs/2601.12345",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )
    return EvidenceRecord.create(
        evidence_id=evidence_id,
        run_id=run_id,
        normalized_content=content,
        provenance=provenance,
        metadata=metadata or {"topic": "distributed_systems"},
    )


def test_a_default_configuration() -> None:
    """Test A: Default configuration uses default chunk_size and chunk_overlap from plan."""
    chunker = DeterministicTextChunker()
    assert chunker.chunk_size == DEFAULT_CHUNK_SIZE
    assert chunker.chunk_overlap == DEFAULT_CHUNK_OVERLAP
    assert chunker.max_chunks_per_document == DEFAULT_MAX_CHUNKS
    assert chunker._step == DEFAULT_CHUNK_SIZE - DEFAULT_CHUNK_OVERLAP


def test_b_custom_chunk_size_and_overlap() -> None:
    """Test B: Chunker properly initializes with custom valid chunk_size and chunk_overlap."""
    chunker = DeterministicTextChunker(chunk_size=200, chunk_overlap=50)
    assert chunker.chunk_size == 200
    assert chunker.chunk_overlap == 50
    assert chunker._step == 150


def test_c_invalid_chunk_size_zero() -> None:
    """Test C: chunk_size == 0 is strictly rejected with EvidenceValidationError."""
    with pytest.raises(EvidenceValidationError) as exc_info:
        DeterministicTextChunker(chunk_size=0)
    assert "chunk_size must be a positive integer" in str(exc_info.value)


def test_d_invalid_negative_chunk_size() -> None:
    """Test D: Negative chunk_size is strictly rejected with EvidenceValidationError."""
    with pytest.raises(EvidenceValidationError) as exc_info:
        DeterministicTextChunker(chunk_size=-100)
    assert "chunk_size must be a positive integer" in str(exc_info.value)


def test_e_invalid_negative_overlap() -> None:
    """Test E: Negative chunk_overlap is strictly rejected with EvidenceValidationError."""
    with pytest.raises(EvidenceValidationError) as exc_info:
        DeterministicTextChunker(chunk_size=100, chunk_overlap=-10)
    assert "chunk_overlap must be non-negative" in str(exc_info.value)


def test_f_invalid_overlap_greater_or_equal_to_chunk_size() -> None:
    """Test F: chunk_overlap >= chunk_size is strictly rejected."""
    with pytest.raises(EvidenceValidationError) as exc_1:
        DeterministicTextChunker(chunk_size=100, chunk_overlap=100)
    assert "strictly less than chunk_size" in str(exc_1.value)

    with pytest.raises(EvidenceValidationError) as exc_2:
        DeterministicTextChunker(chunk_size=100, chunk_overlap=150)
    assert "strictly less than chunk_size" in str(exc_2.value)


def test_g_short_text_produces_one_chunk() -> None:
    """Test G: Text shorter than chunk_size produces exactly one chunk spanning the entire text."""
    chunker = DeterministicTextChunker(chunk_size=100, chunk_overlap=20)
    text = "Short evidence statement."
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text == text
    assert chunk.start_offset == 0
    assert chunk.end_offset == len(text)
    assert chunk.chunk_index == 0
    assert chunk.total_chunks == 1


def test_h_exact_size_text_produces_one_chunk() -> None:
    """Test H: Text whose length exactly equals chunk_size produces exactly one chunk."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=10)
    text = "a" * 50
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].start_offset == 0
    assert chunks[0].end_offset == 50
    assert chunks[0].total_chunks == 1


def test_i_text_larger_than_chunk_size_produces_multiple_chunks() -> None:
    """Test I: Text larger than chunk_size produces multiple contiguous overlapping chunks."""
    chunker = DeterministicTextChunker(chunk_size=100, chunk_overlap=20)
    text = "0123456789" * 15  # 150 characters
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    assert len(chunks) == 2
    assert chunks[0].chunk_index == 0
    assert chunks[0].start_offset == 0
    assert chunks[0].end_offset == 100
    assert len(chunks[0].text) == 100

    assert chunks[1].chunk_index == 1
    assert chunks[1].start_offset == 80
    assert chunks[1].end_offset == 150
    assert len(chunks[1].text) == 70

    for c in chunks:
        assert c.total_chunks == 2


def test_j_overlap_integrity_between_adjacent_chunks() -> None:
    """Test J: Overlap region between adjacent chunks is identical text."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=15)
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz"
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    assert len(chunks) >= 2

    # Verify overlap between chunk 0 and chunk 1
    overlap_len = 15
    chunk_0_tail = chunks[0].text[-overlap_len:]
    chunk_1_head = chunks[1].text[:overlap_len]
    assert chunk_0_tail == chunk_1_head
    assert chunks[0].end_offset - chunks[1].start_offset == overlap_len


def test_k_zero_overlap_produces_disjoint_chunks() -> None:
    """Test K: chunk_overlap = 0 produces non-overlapping contiguous chunks."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=0)
    text = "x" * 125
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    assert len(chunks) == 3
    assert (chunks[0].start_offset, chunks[0].end_offset) == (0, 50)
    assert (chunks[1].start_offset, chunks[1].end_offset) == (50, 100)
    assert (chunks[2].start_offset, chunks[2].end_offset) == (100, 125)


def test_l_deterministic_output_across_repeated_calls() -> None:
    """Test L: Multiple chunking invocations on the same evidence return identical chunks."""
    chunker = DeterministicTextChunker(chunk_size=80, chunk_overlap=20)
    ev = _make_sample_evidence(
        content="Deterministic sliding window chunking test string." * 5
    )

    res1 = chunker.chunk_evidence(ev)
    res2 = chunker.chunk_evidence(ev)

    assert len(res1) == len(res2)
    for c1, c2 in zip(res1, res2, strict=True):
        assert c1.chunk_id == c2.chunk_id
        assert c1.text == c2.text
        assert c1.start_offset == c2.start_offset
        assert c1.end_offset == c2.end_offset
        assert c1.metadata == c2.metadata


def test_m_stable_chunk_ids() -> None:
    """Test M: Chunk IDs follow stable format chk_{evidence_id}_{chunk_index}."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=10)
    ev = _make_sample_evidence(
        content="Content for stable ID testing across index sequence." * 3,
        evidence_id="ev_fixed_999",
    )

    chunks = chunker.chunk_evidence(ev)
    for idx, c in enumerate(chunks):
        assert c.chunk_id == f"chk_ev_fixed_999_{idx}"


def test_n_chunk_ids_contain_evidence_id() -> None:
    """Test N: Chunk IDs explicitly embed parent evidence_id."""
    chunker = DeterministicTextChunker(chunk_size=40, chunk_overlap=10)
    ev = _make_sample_evidence(
        content="Testing explicit evidence identifier embedding.",
        evidence_id="ev_custom_id_42",
    )

    chunks = chunker.chunk_evidence(ev)
    for c in chunks:
        assert "ev_custom_id_42" in c.chunk_id
        assert c.evidence_id == "ev_custom_id_42"


def test_o_run_id_preserved_on_all_chunks() -> None:
    """Test O: run_id is faithfully preserved on all resulting TextChunk instances."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=10)
    ev = _make_sample_evidence(
        content="Strict tenant isolation requires run_id preservation." * 2,
        run_id="run_tenant_99",
    )

    chunks = chunker.chunk_evidence(ev)
    for c in chunks:
        assert c.run_id == "run_tenant_99"


def test_p_evidence_id_preserved_on_all_chunks() -> None:
    """Test P: evidence_id is faithfully preserved on all resulting TextChunk instances."""
    chunker = DeterministicTextChunker()
    ev = _make_sample_evidence(evidence_id="ev_bio_marker_007")

    chunks = chunker.chunk_evidence(ev)
    for c in chunks:
        assert c.evidence_id == "ev_bio_marker_007"


def test_q_correct_chunk_index_sequence() -> None:
    """Test Q: chunk_index starts at 0 and increments sequentially."""
    chunker = DeterministicTextChunker(chunk_size=30, chunk_overlap=10)
    ev = _make_sample_evidence(
        content="Zero-based sequential indexing verification string." * 3
    )

    chunks = chunker.chunk_evidence(ev)
    for expected_idx, c in enumerate(chunks):
        assert c.chunk_index == expected_idx


def test_r_correct_start_end_offsets_match_original_text() -> None:
    """Test R: Offsets match original text slicing exactly without offset drift."""
    chunker = DeterministicTextChunker(chunk_size=45, chunk_overlap=15)
    text = "The quick brown fox jumps over the lazy dog repeatedly until text length grows."
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    for c in chunks:
        assert text[c.start_offset : c.end_offset] == c.text
        assert c.end_offset - c.start_offset == len(c.text)
        assert c.start_char_idx == c.start_offset
        assert c.end_char_idx == c.end_offset


def test_s_final_partial_chunk_handling() -> None:
    """Test S: Trailing partial chunk is bounded properly by end of text."""
    chunker = DeterministicTextChunker(chunk_size=100, chunk_overlap=20)
    text = "a" * 110  # Step is 80. Chunk 0: [0:100], Chunk 1: [80:110] (length 30)
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    assert len(chunks) == 2
    assert len(chunks[0].text) == 100
    assert len(chunks[1].text) == 30
    assert chunks[1].end_offset == 110


def test_t_unicode_multibyte_text_handling() -> None:
    """Test T: Multilingual and multibyte Unicode text slices accurately without character corruption."""
    chunker = DeterministicTextChunker(chunk_size=30, chunk_overlap=10)
    unicode_text = "量子计算 🧬 CRISPR-Cas9 α-helix 蛋白質 🔬 神经网络" * 3
    ev = _make_sample_evidence(content=unicode_text)

    chunks = chunker.chunk_evidence(ev)
    assert len(chunks) > 1
    for c in chunks:
        assert unicode_text[c.start_offset : c.end_offset] == c.text
        assert len(c.text) == c.end_offset - c.start_offset


def test_u_newline_and_whitespace_preservation() -> None:
    """Test U: Embedded newlines and tabs within content are preserved without hidden normalization."""
    chunker = DeterministicTextChunker(chunk_size=60, chunk_overlap=15)
    text = "Line 1: Header\n\nLine 2: Data item\n\tIndented item\nLine 3: Summary\n"
    ev = _make_sample_evidence(content=text)

    chunks = chunker.chunk_evidence(ev)
    for c in chunks:
        assert text[c.start_offset : c.end_offset] == c.text


def test_v_metadata_preservation() -> None:
    """Test V: Evidence metadata dictionary is carried into TextChunk metadata."""
    chunker = DeterministicTextChunker()
    meta = {"source": "Nature 2026", "author": "Dr. Turing", "tags": ["math", "logic"]}
    ev = _make_sample_evidence(
        content="Turing machine completeness proof.", metadata=meta
    )

    chunks = chunker.chunk_evidence(ev)
    for c in chunks:
        assert c.metadata["source"] == "Nature 2026"
        assert c.metadata["author"] == "Dr. Turing"
        assert c.metadata["tags"] == ["math", "logic"]


def test_w_provenance_metadata_cannot_be_overwritten() -> None:
    """Test W: Malicious metadata cannot overwrite core chunk provenance attributes."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=10)
    # Attempting to supply conflicting metadata keys
    malicious_meta = {
        "evidence_id": "malicious_spoofed_ev",
        "run_id": "malicious_spoofed_run",
        "chunk_index": 999,
        "start_offset": -50,
        "end_offset": 9999,
    }
    ev = _make_sample_evidence(
        content="Testing metadata collision protection against spoofed provenance keys.",
        evidence_id="ev_authentic_01",
        run_id="run_authentic_01",
        metadata=malicious_meta,
    )

    chunks = chunker.chunk_evidence(ev)
    for idx, c in enumerate(chunks):
        # Attribute invariants
        assert c.evidence_id == "ev_authentic_01"
        assert c.run_id == "run_authentic_01"
        assert c.chunk_index == idx
        # Metadata values reflect chunk truth
        assert c.metadata["evidence_id"] == "ev_authentic_01"
        assert c.metadata["run_id"] == "run_authentic_01"
        assert c.metadata["chunk_index"] == idx


def test_x_empty_content_rejected() -> None:
    """Test X: Empty string input is rejected with EvidenceValidationError."""
    chunker = DeterministicTextChunker()
    with pytest.raises(EvidenceValidationError) as exc_info:
        chunker.chunk_text(text="", evidence_id="ev_01", run_id="run_01")
    assert "Evidence text must not be empty" in str(exc_info.value)


def test_y_whitespace_only_content_rejected() -> None:
    """Test Y: Whitespace-only string input is rejected with EvidenceValidationError."""
    chunker = DeterministicTextChunker()
    with pytest.raises(EvidenceValidationError) as exc_info:
        chunker.chunk_text(text="   \n\t  \r  ", evidence_id="ev_01", run_id="run_01")
    assert "Evidence text must not be empty" in str(exc_info.value)


def test_z_no_cross_run_leakage() -> None:
    """Test Z: Chunking two separate evidence records from different runs produces strict run separation."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=10)
    ev_run_a = _make_sample_evidence(
        content="Content for Run Alpha", run_id="run_A", evidence_id="ev_A"
    )
    ev_run_b = _make_sample_evidence(
        content="Content for Run Beta", run_id="run_B", evidence_id="ev_B"
    )

    chunks_a = chunker.chunk_evidence(ev_run_a)
    chunks_b = chunker.chunk_evidence(ev_run_b)

    assert all(c.run_id == "run_A" for c in chunks_a)
    assert all(c.run_id == "run_B" for c in chunks_b)
    assert all(c.evidence_id == "ev_A" for c in chunks_a)
    assert all(c.evidence_id == "ev_B" for c in chunks_b)


def test_distinct_evidence_records_with_same_content_have_distinct_chunk_ids() -> None:
    """Same text in two different EvidenceRecords produces distinct chunk IDs."""
    chunker = DeterministicTextChunker(chunk_size=40, chunk_overlap=10)
    content = "Identical factual statement across two distinct papers."
    ev_1 = _make_sample_evidence(
        content=content, evidence_id="ev_paper_1", run_id="run_1"
    )
    ev_2 = _make_sample_evidence(
        content=content, evidence_id="ev_paper_2", run_id="run_1"
    )

    chunks_1 = chunker.chunk_evidence(ev_1)
    chunks_2 = chunker.chunk_evidence(ev_2)

    assert len(chunks_1) == len(chunks_2)
    for c1, c2 in zip(chunks_1, chunks_2, strict=True):
        assert c1.text == c2.text
        assert c1.chunk_id != c2.chunk_id
        assert c1.evidence_id == "ev_paper_1"
        assert c2.evidence_id == "ev_paper_2"


def test_json_serialization_roundtrip() -> None:
    """TextChunk cleanly serializes to JSON and deserializes identically."""
    chunker = DeterministicTextChunker(chunk_size=50, chunk_overlap=10)
    ev = _make_sample_evidence(content="Testing Pydantic JSON roundtrip serialization.")

    chunks = chunker.chunk_evidence(ev)
    for c in chunks:
        json_str = c.model_dump_json()
        reconstructed = TextChunk.model_validate_json(json_str)
        assert reconstructed == c


def test_text_chunk_immutability_and_forbid_extra() -> None:
    """TextChunk is frozen and forbids extra fields."""
    chunk = TextChunk(
        chunk_id="chk_ev_1_0",
        evidence_id="ev_1",
        run_id="run_1",
        text="Sample text",
        chunk_index=0,
        total_chunks=1,
        start_offset=0,
        end_offset=11,
        metadata={},
    )

    with pytest.raises(ValidationError):
        chunk.text = "Mutated text"

    with pytest.raises(ValidationError):
        TextChunk(
            chunk_id="chk_ev_1_0",
            evidence_id="ev_1",
            run_id="run_1",
            text="Sample text",
            chunk_index=0,
            total_chunks=1,
            start_offset=0,
            end_offset=11,
            extra_injected_field="illegal",  # type: ignore[call-arg]
        )


def test_text_chunker_alias_compatibility() -> None:
    """TextChunker is an alias of DeterministicTextChunker."""
    assert TextChunker is DeterministicTextChunker
    chunker = TextChunker(chunk_size=100, chunk_overlap=20)
    assert isinstance(chunker, DeterministicTextChunker)


def test_invalid_type_arguments() -> None:
    """Invalid types for chunker methods or init raise appropriate TypeError or EvidenceValidationError."""
    with pytest.raises(TypeError):
        DeterministicTextChunker(chunk_size="100")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        DeterministicTextChunker(chunk_overlap="20")  # type: ignore[arg-type]

    chunker = DeterministicTextChunker()
    with pytest.raises(TypeError):
        chunker.chunk_evidence(None)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        chunker.chunk_text(None, evidence_id="ev_1", run_id="run_1")  # type: ignore[arg-type]


def test_max_chunks_limit_enforcement() -> None:
    """Exceeding max_chunks_per_document raises EvidenceValidationError."""
    chunker = DeterministicTextChunker(
        chunk_size=10, chunk_overlap=5, max_chunks_per_document=5
    )
    text = "0123456789" * 10  # 100 characters, step 5 -> 19 chunks
    with pytest.raises(EvidenceValidationError) as exc_info:
        chunker.chunk_text(text=text, evidence_id="ev_1", run_id="run_1")
    assert "exceeding max_chunks_per_document" in str(exc_info.value)
