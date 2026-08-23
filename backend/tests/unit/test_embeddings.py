"""Unit tests for Phase 3.3.4 Evidence Embedding Domain & Provider-Neutral Embedding Boundary."""

import math
from typing import Any

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel
from app.common.errors import EvidenceValidationError
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.rag.chunking import TextChunk
from app.rag.embeddings import (
    DEFAULT_EMBEDDING_DIMENSION,
    EmbeddingRecord,
    MockEmbeddingModel,
    generate_embedding_id,
    validate_dense_vector,
)
from app.rag.protocols import EmbeddingModelProtocol


def _make_sample_chunk(
    text: str = "Quantum coherence achieved at room temperature.",
    chunk_id: str = "chk_sample_01",
    evidence_id: str = "ev_sample_01",
    run_id: str = "run_alpha_01",
    metadata: dict[str, Any] | None = None,
) -> TextChunk:
    return TextChunk(
        chunk_id=chunk_id,
        evidence_id=evidence_id,
        run_id=run_id,
        text=text,
        chunk_index=0,
        total_chunks=1,
        start_offset=0,
        end_offset=len(text),
        metadata=metadata or {"section": "Abstract"},
    )


def _make_sample_evidence(
    content: str = "Quantum coherence achieved at room temperature.",
    evidence_id: str = "ev_sample_01",
    run_id: str = "run_alpha_01",
) -> EvidenceRecord:
    provenance = SourceProvenance.from_content(
        raw_content=content,
        title="Quantum Physics Report",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )
    return EvidenceRecord.create(
        evidence_id=evidence_id,
        run_id=run_id,
        normalized_content=content,
        provenance=provenance,
    )


def test_a_valid_embedding_record() -> None:
    """Test A: Valid EmbeddingRecord initializes cleanly with expected fields."""
    vec = (0.1, 0.2, 0.3, 0.4)
    rec = EmbeddingRecord(
        embedding_id="emb_001",
        chunk_id="chk_001",
        evidence_id="ev_001",
        run_id="run_001",
        vector=vec,
        dimension=4,
        model_name="mock-model",
        metadata={"tokens": 12},
    )
    assert rec.embedding_id == "emb_001"
    assert rec.chunk_id == "chk_001"
    assert rec.evidence_id == "ev_001"
    assert rec.run_id == "run_001"
    assert rec.vector == vec
    assert rec.dimension == 4
    assert rec.dimensions == 4
    assert rec.model_name == "mock-model"
    assert rec.metadata["tokens"] == 12


def test_b_frozen_immutable_model() -> None:
    """Test B: EmbeddingRecord is frozen and mutation attempts raise ValidationError."""
    rec = EmbeddingRecord(
        embedding_id="emb_001",
        chunk_id="chk_001",
        evidence_id="ev_001",
        run_id="run_001",
        vector=(0.5, 0.5),
        dimension=2,
    )
    with pytest.raises(ValidationError):
        rec.model_name = "mutated-model"

    with pytest.raises(ValidationError):
        rec.dimension = 3


def test_c_extra_attributes_rejected() -> None:
    """Test C: Extra/unapproved attributes are rejected strictly (extra='forbid')."""
    with pytest.raises(ValidationError):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(0.5, 0.5),
            dimension=2,
            unauthorized_field="malicious_payload",  # type: ignore[call-arg]
        )


def test_d_empty_vector_rejected() -> None:
    """Test D: Empty vector is strictly rejected."""
    with pytest.raises((EvidenceValidationError, ValidationError)):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(),
            dimension=0,
        )


def test_e_zero_dimensions_rejected() -> None:
    """Test E: Dimension <= 0 is rejected."""
    with pytest.raises(ValidationError):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(0.1, 0.2),
            dimension=0,
        )


def test_f_dimension_mismatch_rejected() -> None:
    """Test F: Declared dimension not matching vector length raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(0.1, 0.2, 0.3),
            dimension=4,  # Length is 3, declared is 4
        )
    assert "Vector length (3) does not match declared dimension (4)" in str(
        exc_info.value
    )


def test_g_nan_rejected() -> None:
    """Test G: Vectors containing NaN are strictly rejected."""
    nan_vec = (0.1, float("nan"), 0.3)
    with pytest.raises(EvidenceValidationError) as exc_info:
        validate_dense_vector(nan_vec)
    assert "NaN" in str(exc_info.value)

    with pytest.raises((EvidenceValidationError, ValidationError)):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=nan_vec,
            dimension=3,
        )


def test_h_positive_infinity_rejected() -> None:
    """Test H: Vectors containing positive infinity are rejected."""
    inf_vec = (0.1, float("inf"), 0.3)
    with pytest.raises(EvidenceValidationError) as exc_info:
        validate_dense_vector(inf_vec)
    assert "infinite" in str(exc_info.value)

    with pytest.raises((EvidenceValidationError, ValidationError)):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=inf_vec,
            dimension=3,
        )


def test_i_negative_infinity_rejected() -> None:
    """Test I: Vectors containing negative infinity are rejected."""
    neg_inf_vec = (0.1, float("-inf"), 0.3)
    with pytest.raises(EvidenceValidationError) as exc_info:
        validate_dense_vector(neg_inf_vec)
    assert "infinite" in str(exc_info.value)

    with pytest.raises((EvidenceValidationError, ValidationError)):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=neg_inf_vec,
            dimension=3,
        )


def test_j_numeric_vector_accepted() -> None:
    """Test J: Integers and floats in vector are normalized to finite floats."""
    raw_vec = [1, 2.5, -3]
    val = validate_dense_vector(raw_vec, expected_dimension=3)
    assert val == (1.0, 2.5, -3.0)


def test_k_non_numeric_vector_rejected() -> None:
    """Test K: Non-numeric elements (e.g. strings, booleans, dicts) are rejected."""
    with pytest.raises(EvidenceValidationError):
        validate_dense_vector([0.1, "invalid_str", 0.3])  # type: ignore[list-item]

    with pytest.raises(EvidenceValidationError):
        validate_dense_vector([0.1, True, 0.3])


def test_l_chunk_id_preserved() -> None:
    """Test L: chunk_id is faithfully preserved in EmbeddingRecord."""
    rec = EmbeddingRecord(
        embedding_id="emb_001",
        chunk_id="chk_custom_12345",
        evidence_id="ev_001",
        run_id="run_001",
        vector=(0.1, 0.2),
        dimension=2,
    )
    assert rec.chunk_id == "chk_custom_12345"


def test_m_evidence_id_preserved() -> None:
    """Test M: evidence_id is faithfully preserved in EmbeddingRecord."""
    rec = EmbeddingRecord(
        embedding_id="emb_001",
        chunk_id="chk_001",
        evidence_id="ev_molecular_genetics_99",
        run_id="run_001",
        vector=(0.1, 0.2),
        dimension=2,
    )
    assert rec.evidence_id == "ev_molecular_genetics_99"


def test_n_run_id_preserved() -> None:
    """Test N: run_id is faithfully preserved for multi-tenant isolation."""
    rec = EmbeddingRecord(
        embedding_id="emb_001",
        chunk_id="chk_001",
        evidence_id="ev_001",
        run_id="run_tenant_isolated_alpha",
        vector=(0.1, 0.2),
        dimension=2,
    )
    assert rec.run_id == "run_tenant_isolated_alpha"


def test_o_metadata_preserved() -> None:
    """Test O: Metadata dictionary is passed and preserved without loss."""
    meta = {"source_domain": "nature.com", "layer": 3, "score": 0.98}
    rec = EmbeddingRecord(
        embedding_id="emb_001",
        chunk_id="chk_001",
        evidence_id="ev_001",
        run_id="run_001",
        vector=(0.1, 0.2),
        dimension=2,
        metadata=meta,
    )
    assert rec.metadata == meta


def test_p_embedding_id_distinct_from_chunk_id_and_evidence_id() -> None:
    """Test P: embedding_id represents independent vector identity and cannot equal chunk_id or evidence_id."""
    with pytest.raises(ValidationError) as exc_1:
        EmbeddingRecord(
            embedding_id="chk_001",  # Same as chunk_id
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(0.1, 0.2),
            dimension=2,
        )
    assert "must not equal chunk_id" in str(exc_1.value)

    with pytest.raises(ValidationError) as exc_2:
        EmbeddingRecord(
            embedding_id="ev_001",  # Same as evidence_id
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(0.1, 0.2),
            dimension=2,
        )
    assert "must not equal evidence_id" in str(exc_2.value)


def test_q_serialization_and_deserialization_roundtrip() -> None:
    """Test Q: EmbeddingRecord serializes to JSON and deserializes identically."""
    rec = EmbeddingRecord(
        embedding_id="emb_roundtrip_01",
        chunk_id="chk_01",
        evidence_id="ev_01",
        run_id="run_01",
        vector=(0.123456, -0.654321, 0.987654),
        dimension=3,
        model_name="mock-model-v2",
        metadata={"key": "val"},
    )
    json_str = rec.model_dump_json()
    reconstructed = EmbeddingRecord.model_validate_json(json_str)

    assert reconstructed == rec
    assert reconstructed.vector == rec.vector


def test_r_provider_neutral_protocol_can_be_implemented_by_test_double() -> None:
    """Test R: EmbeddingModelProtocol is @runtime_checkable and supports custom test doubles."""

    class CustomEmbeddingDouble(EmbeddingModelProtocol):
        @property
        def dimension(self) -> int:
            return 3

        async def embed_text(self, _text: str) -> tuple[float, ...]:
            return (0.1, 0.2, 0.3)

        async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
            return [(0.1, 0.2, 0.3) for _ in texts]

    double = CustomEmbeddingDouble()
    assert isinstance(double, EmbeddingModelProtocol)
    assert double.dimension == 3


def test_s_upstream_text_chunk_is_not_mutated() -> None:
    """Test S: Creating an EmbeddingRecord from a TextChunk never mutates the upstream TextChunk."""
    chunk = _make_sample_chunk(text="Original immutable chunk text.")
    original_dict = chunk.model_dump()

    emb = EmbeddingRecord.from_chunk(
        chunk=chunk,
        vector=(0.1, 0.2, 0.3, 0.4),
        model_name="mock-model",
    )

    assert emb.chunk_id == chunk.chunk_id
    assert emb.evidence_id == chunk.evidence_id
    assert emb.run_id == chunk.run_id
    assert chunk.model_dump() == original_dict


def test_t_upstream_evidence_record_is_not_mutated() -> None:
    """Test T: Upstream EvidenceRecord is never altered by chunking and embedding."""
    ev = _make_sample_evidence(content="Factual evidence string.")
    orig_content = ev.normalized_content
    orig_hash = ev.content_hash

    chunk = _make_sample_chunk(
        text=ev.normalized_content, evidence_id=ev.evidence_id, run_id=ev.run_id
    )
    emb = EmbeddingRecord.from_chunk(chunk=chunk, vector=(0.5, 0.5))

    assert ev.normalized_content == orig_content
    assert ev.content_hash == orig_hash
    assert emb.evidence_id == ev.evidence_id


def test_u_invalid_model_identifier_rejected() -> None:
    """Test U: Empty or whitespace-only model_name is rejected."""
    with pytest.raises(ValidationError):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(0.1, 0.2),
            dimension=2,
            model_name="",
        )

    with pytest.raises(ValidationError):
        EmbeddingRecord(
            embedding_id="emb_001",
            chunk_id="chk_001",
            evidence_id="ev_001",
            run_id="run_001",
            vector=(0.1, 0.2),
            dimension=2,
            model_name="   ",
        )


def test_v_repeated_valid_construction_preserves_vector_exactly() -> None:
    """Test V: Repeated construction with identical vector components preserves floats exactly."""
    vec = (0.123456789, -0.987654321, 0.0)
    rec1 = EmbeddingRecord(
        embedding_id="emb_1",
        chunk_id="chk_1",
        evidence_id="ev_1",
        run_id="run_1",
        vector=vec,
        dimension=3,
    )
    rec2 = EmbeddingRecord(
        embedding_id="emb_2",
        chunk_id="chk_1",
        evidence_id="ev_1",
        run_id="run_1",
        vector=vec,
        dimension=3,
    )
    assert rec1.vector == rec2.vector == vec


@pytest.mark.asyncio
async def test_mock_embedding_model_properties_and_determinism() -> None:
    """Verify MockEmbeddingModel complies with EmbeddingModelProtocol and produces unit-normalized vectors."""
    model = MockEmbeddingModel(dimension=DEFAULT_EMBEDDING_DIMENSION)
    assert isinstance(model, EmbeddingModelProtocol)
    assert model.dimension == DEFAULT_EMBEDDING_DIMENSION

    text = "Photosynthesis electron transport chain."
    v1 = await model.embed_text(text)
    v2 = await model.embed_text(text)

    assert v1 == v2
    assert len(v1) == DEFAULT_EMBEDDING_DIMENSION
    # Check L2 unit norm
    l2_norm = math.sqrt(sum(x * x for x in v1))
    assert math.isclose(l2_norm, 1.0, rel_tol=1e-3)


@pytest.mark.asyncio
async def test_mock_embedding_model_batch_and_chunk() -> None:
    """Verify embed_batch and embed_chunk methods on MockEmbeddingModel."""
    model = MockEmbeddingModel(dimension=32)
    texts = ["First document", "Second document", "Third document"]
    batch_vecs = await model.embed_batch(texts)

    assert len(batch_vecs) == 3
    assert all(len(v) == 32 for v in batch_vecs)

    chunk = _make_sample_chunk(text="Chunk text for embedding record.")
    emb_record = await model.embed_chunk(chunk)

    assert emb_record.chunk_id == chunk.chunk_id
    assert emb_record.evidence_id == chunk.evidence_id
    assert emb_record.run_id == chunk.run_id
    assert emb_record.dimension == 32
    assert len(emb_record.vector) == 32


@pytest.mark.asyncio
async def test_mock_embedding_model_rejection_of_empty_inputs() -> None:
    """Verify MockEmbeddingModel rejects empty or whitespace-only text."""
    model = MockEmbeddingModel()
    with pytest.raises(EvidenceValidationError):
        await model.embed_text("")

    with pytest.raises(EvidenceValidationError):
        await model.embed_text("   \t\n  ")


def test_mock_embedding_model_invalid_init_parameters() -> None:
    """Verify MockEmbeddingModel rejects invalid dimensions and model names."""
    with pytest.raises(EvidenceValidationError):
        MockEmbeddingModel(dimension=0)

    with pytest.raises(EvidenceValidationError):
        MockEmbeddingModel(dimension=-5)

    with pytest.raises(EvidenceValidationError):
        MockEmbeddingModel(model_name="")


def test_generate_embedding_id_utility() -> None:
    """Verify generate_embedding_id produces unique prefixed identifiers."""
    id1 = generate_embedding_id()
    id2 = generate_embedding_id()
    assert id1 != id2
    assert id1.startswith("emb_")
