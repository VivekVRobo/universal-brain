"""
Universal Brain - Unit Tests: M7 Deadlock Detection & Durable Wakeups

Verifies M7 Sections 59-70, 130-131, 135-136, and Invariant M7-INV-08:
- Graph cycle detection (DependencyDeadlockError);
- Circular resource contention detection (ResourceDeadlockError);
- Durable wakeup scheduling, atomic claim, and exactly-once execution.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from universal_brain.autonomy.dependencies import DependencyCoordinator
from universal_brain.autonomy.errors import (
    DependencyDeadlockError,
    MissionVersionConflictError,
    ResourceDeadlockError,
)
from universal_brain.autonomy.schemas import WakeupStatus, WakeupType
from universal_brain.autonomy.wakeups import WakeupManager


def test_dependency_deadlock_cycle_detection():
    """Verifies cycle detection on circular task dependencies (M7 Section 61)."""
    coord = DependencyCoordinator()

    # Linear dependency graph: Task C -> Task B -> Task A (Valid DAG)
    coord.add_dependency(blocked_node="task_b", required_node="task_a")
    coord.add_dependency(blocked_node="task_c", required_node="task_b")
    coord.check_for_deadlocks()  # Should pass cleanly

    # Adding circular edge: Task A -> Task C creates cycle: A -> C -> B -> A
    with pytest.raises(DependencyDeadlockError, match="DEPENDENCY_DEADLOCK"):
        coord.add_dependency(blocked_node="task_a", required_node="task_c")


def test_resource_deadlock_hold_and_wait_detection():
    """Verifies hold-and-wait deadlock detection on scarce exclusive resources (M7 Section 62)."""
    coord = DependencyCoordinator()

    # Agent 1 holds Resource X
    coord.register_resource_hold("agent_1", "gpu_cluster_01")
    # Agent 2 holds Resource Y
    coord.register_resource_hold("agent_2", "sandbox_workspace_a")

    # Agent 1 waits for Resource Y
    coord.register_resource_wait("agent_1", "sandbox_workspace_a")

    # Agent 2 waits for Resource X (creates circular hold-and-wait)
    with pytest.raises(ResourceDeadlockError, match="RESOURCE_DEADLOCK"):
        coord.register_resource_wait("agent_2", "gpu_cluster_01")


def test_durable_wakeup_manager_lifecycle_and_single_claim():
    """Verifies atomic claim and version verification on durable wakeups (M7-INV-08)."""
    wm = WakeupManager()
    mission_id = uuid4()
    now = datetime.now(timezone.utc)
    due_time = now - timedelta(seconds=10)  # Already due

    wakeup = wm.schedule_wakeup(
        mission_id=mission_id,
        trigger_type=WakeupType.TIME,
        due_at=due_time,
        idempotency_key="timer_wake_001",
    )
    assert wakeup.status == WakeupStatus.PENDING

    # Idempotent re-scheduling returns existing pending wakeup
    dup = wm.schedule_wakeup(
        mission_id=mission_id,
        trigger_type=WakeupType.TIME,
        due_at=due_time,
        idempotency_key="timer_wake_001",
    )
    assert dup.wakeup_id == wakeup.wakeup_id

    # Overdue retrieval finds it
    due_list = wm.get_due_wakeups(now)
    assert len(due_list) == 1
    assert due_list[0].wakeup_id == wakeup.wakeup_id

    # First claim succeeds
    claimed1 = wm.claim_wakeup(wakeup.wakeup_id)
    assert claimed1 is True

    # Duplicate concurrent claim fails (at-least-once physical, exactly-once logical)
    claimed2 = wm.claim_wakeup(wakeup.wakeup_id)
    assert claimed2 is False

    # Firing with matching mission version succeeds
    fired = wm.fire_wakeup(
        wakeup.wakeup_id,
        current_mission_version=4,
        expected_mission_version=4,
    )
    assert fired.status == WakeupStatus.FIRED
    assert fired.fired_at is not None
