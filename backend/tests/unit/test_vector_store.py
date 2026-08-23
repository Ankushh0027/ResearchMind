"""Unit tests for Phase 3.3.5 InMemoryVectorStore and Cosine Similarity."""

import math
from typing import Any

import pytest

from app.common.errors import (
    EvidenceValidationError,
    VectorDimensionMismatchError,
)
from app.rag.protocols import (
    VectorPoint,
    VectorStoreProtocol,
)
from app.rag.store import (
    DEFAULT_STORE_DIMENSION,
    InMemoryVectorStore,
    compute_cosine_similarity,
)


def _make_point(
    point_id: str,
    vector: tuple[float, ...],
    run_id: str = "run_01",
    evidence_id: str = "ev_01",
    extra_payload: dict[str, Any] | None = None,
) -> VectorPoint:
    payload: dict[str, Any] = {"run_id": run_id, "evidence_id": evidence_id}
    if extra_payload:
        payload.update(extra_payload)
    return VectorPoint(point_id=point_id, vector=vector, payload=payload)


def test_cosine_similarity_computation() -> None:
    """Verify compute_cosine_similarity across standard geometric angles."""
    # Identical vectors: sim = 1.0
    v1 = (1.0, 0.0, 0.0)
    assert math.isclose(compute_cosine_similarity(v1, v1), 1.0, rel_tol=1e-5)

    # Orthogonal vectors: sim = 0.0
    v2 = (0.0, 1.0, 0.0)
    assert math.isclose(compute_cosine_similarity(v1, v2), 0.0, abs_tol=1e-5)

    # Opposite vectors: sim = -1.0
    v3 = (-1.0, 0.0, 0.0)
    assert math.isclose(compute_cosine_similarity(v1, v3), -1.0, rel_tol=1e-5)

    # Zero vector handling
    v_zero = (0.0, 0.0, 0.0)
    assert compute_cosine_similarity(v1, v_zero) == 0.0

    # Dimension mismatch
    with pytest.raises(ValueError):
        compute_cosine_similarity((1.0, 2.0), (1.0, 2.0, 3.0))


def test_vector_store_protocol_compliance() -> None:
    """Verify InMemoryVectorStore complies with VectorStoreProtocol."""
    store = InMemoryVectorStore(dimension=4)
    assert isinstance(store, VectorStoreProtocol)
    assert store.dimension == 4


def test_default_initialization() -> None:
    """Verify default store initialization with DEFAULT_STORE_DIMENSION."""
    store = InMemoryVectorStore()
    assert store.dimension == DEFAULT_STORE_DIMENSION


def test_invalid_dimension_rejected() -> None:
    """Verify negative, zero, or non-integer dimension is rejected."""
    with pytest.raises(EvidenceValidationError):
        InMemoryVectorStore(dimension=0)

    with pytest.raises(EvidenceValidationError):
        InMemoryVectorStore(dimension=-10)

    with pytest.raises(EvidenceValidationError):
        InMemoryVectorStore(dimension="64")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upsert_and_retrieve_vectors() -> None:
    """Verify upsert_vectors inserts points into collection cleanly."""
    store = InMemoryVectorStore(dimension=3)
    p1 = _make_point("p1", (0.1, 0.2, 0.3))
    p2 = _make_point("p2", (0.4, 0.5, 0.6))

    count = await store.upsert_vectors("test_coll", [p1, p2])
    assert count == 2
    assert store.count("test_coll") == 2
    assert store.has_collection("test_coll") is True
    assert store.get_point("test_coll", "p1") == p1
    assert store.get_point("test_coll", "p2") == p2


@pytest.mark.asyncio
async def test_idempotent_upsert_overwrites_existing_point() -> None:
    """Verify upserting a point with an existing point_id replaces the point."""
    store = InMemoryVectorStore(dimension=2)
    p1_initial = _make_point("p1", (0.1, 0.2), extra_payload={"version": 1})
    p1_updated = _make_point("p1", (0.9, 0.8), extra_payload={"version": 2})

    await store.upsert_vectors("test_coll", [p1_initial])
    assert store.count("test_coll") == 1
    assert store.get_point("test_coll", "p1").payload["version"] == 1  # type: ignore[union-attr]

    await store.upsert_vectors("test_coll", [p1_updated])
    assert store.count("test_coll") == 1
    assert store.get_point("test_coll", "p1").payload["version"] == 2  # type: ignore[union-attr]
    assert store.get_point("test_coll", "p1").vector == (0.9, 0.8)  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_dimension_mismatch_during_upsert_rejected() -> None:
    """Verify points with mismatched dimension raise VectorDimensionMismatchError."""
    store = InMemoryVectorStore(dimension=3)
    bad_point = _make_point("p_bad", (0.1, 0.2, 0.3, 0.4))  # Dimension 4

    with pytest.raises(VectorDimensionMismatchError) as exc_info:
        await store.upsert_vectors("coll", [bad_point])

    assert exc_info.value.expected_dimension == 3
    assert exc_info.value.actual_dimension == 4
    assert exc_info.value.entity_id == "p_bad"


@pytest.mark.asyncio
async def test_search_vectors_ranking() -> None:
    """Verify search_vectors returns points ranked in descending order of cosine similarity."""
    store = InMemoryVectorStore(dimension=2)
    # Target query: (1.0, 0.0)
    p_exact = _make_point("p_exact", (1.0, 0.0))  # sim = 1.0
    p_diag = _make_point("p_diag", (1.0, 1.0))  # sim ~ 0.707
    p_ortho = _make_point("p_ortho", (0.0, 1.0))  # sim = 0.0
    p_oppo = _make_point("p_oppo", (-1.0, 0.0))  # sim = -1.0

    await store.upsert_vectors("coll", [p_oppo, p_diag, p_ortho, p_exact])

    results = await store.search_vectors("coll", query_vector=(1.0, 0.0), limit=4)

    assert len(results) == 4
    assert [r.point_id for r in results] == [
        "p_exact",
        "p_diag",
        "p_ortho",
        "p_oppo",
    ]
    assert math.isclose(results[0].score, 1.0, rel_tol=1e-4)
    assert math.isclose(results[1].score, 0.707106, rel_tol=1e-4)
    assert math.isclose(results[2].score, 0.0, abs_tol=1e-4)
    assert math.isclose(results[3].score, -1.0, rel_tol=1e-4)


@pytest.mark.asyncio
async def test_deterministic_tie_breaking_by_point_id() -> None:
    """Verify multiple points with identical similarity scores break ties deterministically by point_id ascending."""
    store = InMemoryVectorStore(dimension=2)
    # All points have identical vector (0.0, 1.0)
    p_c = _make_point("point_C", (0.0, 1.0))
    p_a = _make_point("point_A", (0.0, 1.0))
    p_b = _make_point("point_B", (0.0, 1.0))

    await store.upsert_vectors("coll", [p_c, p_a, p_b])

    results = await store.search_vectors("coll", query_vector=(0.0, 1.0), limit=10)

    assert len(results) == 3
    assert [r.point_id for r in results] == ["point_A", "point_B", "point_C"]


@pytest.mark.asyncio
async def test_metadata_filtering_and_run_isolation() -> None:
    """Verify search_vectors filters strictly on metadata payload fields for run isolation."""
    store = InMemoryVectorStore(dimension=2)
    p_run1_a = _make_point("p1", (1.0, 0.0), run_id="run_A")
    p_run1_b = _make_point("p2", (0.9, 0.1), run_id="run_A")
    p_run2_a = _make_point("p3", (1.0, 0.0), run_id="run_B")
    p_run2_b = _make_point("p4", (0.9, 0.1), run_id="run_B")

    await store.upsert_vectors("coll", [p_run1_a, p_run1_b, p_run2_a, p_run2_b])

    # Search filtering on run_A
    res_run_a = await store.search_vectors(
        "coll",
        query_vector=(1.0, 0.0),
        limit=10,
        filter_metadata={"run_id": "run_A"},
    )
    assert len(res_run_a) == 2
    assert all(r.payload["run_id"] == "run_A" for r in res_run_a)
    assert {r.point_id for r in res_run_a} == {"p1", "p2"}

    # Search filtering on run_B
    res_run_b = await store.search_vectors(
        "coll",
        query_vector=(1.0, 0.0),
        limit=10,
        filter_metadata={"run_id": "run_B"},
    )
    assert len(res_run_b) == 2
    assert all(r.payload["run_id"] == "run_B" for r in res_run_b)
    assert {r.point_id for r in res_run_b} == {"p3", "p4"}


@pytest.mark.asyncio
async def test_limit_parameter_truncation() -> None:
    """Verify limit parameter restricts count of returned results."""
    store = InMemoryVectorStore(dimension=2)
    pts = [_make_point(f"p_{i}", (float(i), 1.0)) for i in range(10)]
    await store.upsert_vectors("coll", pts)

    res = await store.search_vectors("coll", query_vector=(1.0, 1.0), limit=3)
    assert len(res) == 3


@pytest.mark.asyncio
async def test_search_non_existent_or_empty_collection() -> None:
    """Verify searching a non-existent or empty collection returns an empty list without error."""
    store = InMemoryVectorStore(dimension=2)
    res_non_existent = await store.search_vectors(
        "non_existent", query_vector=(1.0, 0.0)
    )
    assert res_non_existent == []

    await store.upsert_vectors("empty_coll", [])
    res_empty = await store.search_vectors("empty_coll", query_vector=(1.0, 0.0))
    assert res_empty == []


@pytest.mark.asyncio
async def test_delete_collection() -> None:
    """Verify delete_collection removes the named collection from memory."""
    store = InMemoryVectorStore(dimension=2)
    p = _make_point("p1", (1.0, 0.0))
    await store.upsert_vectors("to_delete", [p])
    assert store.has_collection("to_delete") is True

    await store.delete_collection("to_delete")
    assert store.has_collection("to_delete") is False
    assert store.get_point("to_delete", "p1") is None

    # Deleting non-existent collection is a no-op
    await store.delete_collection("never_existed")


@pytest.mark.asyncio
async def test_invalid_query_vector_rejected() -> None:
    """Verify query vector dimension mismatch and invalid values raise EvidenceValidationError."""
    store = InMemoryVectorStore(dimension=3)

    # Dimension mismatch
    with pytest.raises(EvidenceValidationError) as exc_dim:
        await store.search_vectors("coll", query_vector=(1.0, 2.0))
    assert "Vector dimension mismatch" in str(exc_dim.value)

    # NaN in query
    with pytest.raises(EvidenceValidationError) as exc_nan:
        await store.search_vectors("coll", query_vector=(1.0, float("nan"), 3.0))
    assert "NaN" in str(exc_nan.value)

    # Infinite in query
    with pytest.raises(EvidenceValidationError) as exc_inf:
        await store.search_vectors("coll", query_vector=(1.0, float("inf"), 3.0))
    assert "infinite" in str(exc_inf.value)


@pytest.mark.asyncio
async def test_invalid_search_parameters() -> None:
    """Verify empty collection name and limit <= 0 are rejected."""
    store = InMemoryVectorStore(dimension=2)
    with pytest.raises(EvidenceValidationError):
        await store.search_vectors("", query_vector=(1.0, 0.0))

    with pytest.raises(EvidenceValidationError):
        await store.search_vectors("coll", query_vector=(1.0, 0.0), limit=0)

    with pytest.raises(EvidenceValidationError):
        await store.search_vectors("coll", query_vector=(1.0, 0.0), limit=-5)


@pytest.mark.asyncio
async def test_invalid_upsert_arguments() -> None:
    """Verify invalid point types and collection names in upsert are rejected."""
    store = InMemoryVectorStore(dimension=2)

    with pytest.raises(EvidenceValidationError):
        await store.upsert_vectors("", [_make_point("p1", (1.0, 0.0))])

    with pytest.raises(TypeError):
        await store.upsert_vectors("coll", None)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        await store.upsert_vectors("coll", ["not_a_vector_point"])  # type: ignore[list-item]
