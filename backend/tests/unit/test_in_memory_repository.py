import pytest

from app.common.enums import RunStage
from app.orchestration.events import RunStartedEvent
from app.persistence.in_memory import (
    InMemoryEventRepository,
    InMemoryRunRepository,
)
from app.persistence.protocols import RunRecord
from app.state.models import ResearchGoal


@pytest.fixture
def run_repo() -> InMemoryRunRepository:
    return InMemoryRunRepository()


@pytest.fixture
def sample_goal() -> ResearchGoal:
    return ResearchGoal(
        goal_id="goal_inmem_01",
        query="Investigate distributed consensus mechanisms",
    )


@pytest.mark.asyncio
async def test_in_memory_run_repo_crud(
    run_repo: InMemoryRunRepository, sample_goal: ResearchGoal
) -> None:
    """Test 1: Verify standard create, get, and list operations."""
    record1 = RunRecord(run_id="run_01", goal=sample_goal)
    record2 = RunRecord(run_id="run_02", goal=sample_goal)

    created1 = await run_repo.create_run(record1)
    assert created1.run_id == "run_01"

    created2 = await run_repo.create_run(record2)
    assert created2.run_id == "run_02"

    # Duplicate create raises ValueError
    with pytest.raises(ValueError, match="already exists"):
        await run_repo.create_run(record1)

    # Get run
    fetched = await run_repo.get_run("run_01")
    assert fetched is not None
    assert fetched.run_id == "run_01"

    missing = await run_repo.get_run("nonexistent_run")
    assert missing is None

    # List runs
    runs = await run_repo.list_runs(limit=10)
    assert len(runs) == 2
    assert {r.run_id for r in runs} == {"run_01", "run_02"}


@pytest.mark.asyncio
async def test_in_memory_run_repo_optimistic_locking(
    run_repo: InMemoryRunRepository, sample_goal: ResearchGoal
) -> None:
    """Test 2: Verify optimistic concurrency version checks."""
    record = RunRecord(run_id="run_opt_01", goal=sample_goal, version=1)
    await run_repo.create_run(record)

    # Valid update with matching expected_version
    updated = record.with_updates(status=RunStage.RESEARCHING)
    await run_repo.update_run(updated, expected_version=1)

    latest = await run_repo.get_run("run_opt_01")
    assert latest is not None
    assert latest.version == 2
    assert latest.status == RunStage.RESEARCHING

    # Conflicting update with stale expected_version
    stale_update = record.with_updates(status=RunStage.FAILED)
    with pytest.raises(ValueError, match="Optimistic lock conflict"):
        await run_repo.update_run(stale_update, expected_version=1)

    # Nonexistent run update raises KeyError
    nonexistent = RunRecord(run_id="ghost_run", goal=sample_goal)
    with pytest.raises(KeyError, match="not found"):
        await run_repo.update_run(nonexistent)


@pytest.mark.asyncio
async def test_in_memory_run_repo_pagination(
    run_repo: InMemoryRunRepository, sample_goal: ResearchGoal
) -> None:
    """Test 3: Verify pagination with limit and offset."""
    for i in range(10):
        await run_repo.create_run(
            RunRecord(run_id=f"run_page_{i:02d}", goal=sample_goal)
        )

    page1 = await run_repo.list_runs(limit=4, offset=0)
    assert len(page1) == 4

    page2 = await run_repo.list_runs(limit=4, offset=4)
    assert len(page2) == 4

    page3 = await run_repo.list_runs(limit=4, offset=8)
    assert len(page3) == 2

    # Verify no overlapping items between pages
    ids_p1 = {r.run_id for r in page1}
    ids_p2 = {r.run_id for r in page2}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_in_memory_event_repo() -> None:
    """Test 4: Verify InMemoryEventRepository emit and get_events filtering."""
    event_repo = InMemoryEventRepository()
    ev1 = RunStartedEvent(run_id="run_ev_01", plan_id="plan_01", total_tasks=3)
    ev2 = RunStartedEvent(run_id="run_ev_01", plan_id="plan_01_retry", total_tasks=3)
    ev3 = RunStartedEvent(run_id="run_ev_02", plan_id="plan_02", total_tasks=5)

    await event_repo.emit_event(ev1)
    await event_repo.emit_event(ev2)
    await event_repo.emit_event(ev3)

    run1_events = await event_repo.get_events("run_ev_01")
    assert len(run1_events) == 2

    run1_tail = await event_repo.get_events("run_ev_01", after_index=1)
    assert len(run1_tail) == 1
    assert run1_tail[0] == ev2

    run2_events = await event_repo.get_events("run_ev_02")
    assert len(run2_events) == 1

    empty_events = await event_repo.get_events("nonexistent")
    assert empty_events == []
