"""
Universal Brain - Unit Tests: M7 Progress Watchdog & Anti-Loop Engine

Verifies M7 Sections 41-49, 133-134, and Invariants M7-INV-09, M7-INV-10:
- Progress digest computation over verified indicators;
- Progress != Activity distinction (NoProgressError);
- Deterministic operation fingerprinting;
- Loop boundary enforcement and persistence across restarts (AutonomyLoopError).
"""

from uuid import uuid4
import pytest

from universal_brain.autonomy.anti_loop import AntiLoopEngine
from universal_brain.autonomy.errors import AutonomyLoopError, NoProgressError
from universal_brain.autonomy.progress import MissionProgressLedger
from universal_brain.autonomy.watchdog import ProgressWatchdog


def test_progress_ledger_digest_determinism():
    """Verifies that progress_digest advances only upon verified state changes (M7-INV-09)."""
    mission_id = uuid4()
    ledger = MissionProgressLedger(mission_id)

    # Initial snapshot: 1 task completed
    s1 = ledger.record_progress(
        mission_version=1,
        verified_criteria=["CRIT-01"],
        completed_tasks=["task_01"],
    )
    assert len(s1.progress_digest) == 64

    # Activity that changes nothing produces identical digest
    s2 = ledger.record_progress(
        mission_version=1,
        verified_criteria=["CRIT-01"],
        completed_tasks=["task_01"],
    )
    assert s1.progress_digest == s2.progress_digest
    assert ledger.has_advanced(s1.progress_digest, s2.progress_digest) is False

    # New verified evidence hash advances digest
    s3 = ledger.record_progress(
        mission_version=2,
        verified_criteria=["CRIT-01"],
        completed_tasks=["task_01", "task_02"],
        verified_evidence_hashes=["b" * 64],
    )
    assert s1.progress_digest != s3.progress_digest
    assert ledger.has_advanced(s1.progress_digest, s3.progress_digest) is True


def test_progress_watchdog_detects_no_progress_loops():
    """Verifies that repetitive operations without progress trigger NoProgressError (M7 Section 45)."""
    watchdog = ProgressWatchdog(max_operations_without_progress=2)
    mission_id = uuid4()
    stagnant_digest = "a" * 64

    # Baseline observation: sets initial digest
    watchdog.observe_activity(mission_id, stagnant_digest)
    # 1st stagnant operation
    watchdog.observe_activity(mission_id, stagnant_digest)

    # 2nd stagnant operation breaches threshold (max_ops=2) and raises NoProgressError
    with pytest.raises(NoProgressError):
        watchdog.observe_activity(mission_id, stagnant_digest)

    # When digest advances, counter resets cleanly
    advancing_digest = "b" * 64
    watchdog.observe_activity(mission_id, advancing_digest)
    watchdog.observe_activity(mission_id, advancing_digest)  # 1st repeat on new digest is fine


def test_anti_loop_engine_deterministic_fingerprint_and_persistence():
    """Verifies operation fingerprinting and restart persistence (M7-INV-10 & Section 48)."""
    engine = AntiLoopEngine(max_identical_operations=3)
    mission_id = uuid4()
    task_id = uuid4()

    # Attempt 1 & 2
    c1 = engine.record_attempt(
        mission_id=mission_id,
        task_id=task_id,
        operation_type="BUILD_WORKSPACE",
        target="src/orbital.py",
        input_digest="hash_v1",
        failure_class="SYNTAX_ERROR",
    )
    assert c1 == 1

    c2 = engine.record_attempt(
        mission_id=mission_id,
        task_id=task_id,
        operation_type="BUILD_WORKSPACE",
        target="src/orbital.py",
        input_digest="hash_v1",
        failure_class="SYNTAX_ERROR",
    )
    assert c2 == 2

    # Attempt 3 breaches threshold and trips AutonomyLoopError
    with pytest.raises(AutonomyLoopError, match="AUTONOMY_LOOP_DETECTED"):
        engine.record_attempt(
            mission_id=mission_id,
            task_id=task_id,
            operation_type="BUILD_WORKSPACE",
            target="src/orbital.py",
            input_digest="hash_v1",
            failure_class="SYNTAX_ERROR",
        )

    # Test Reboot Persistence Simulation:
    # A new engine instance loads persisted counts from database
    new_engine = AntiLoopEngine(max_identical_operations=3)
    fp = AntiLoopEngine.compute_fingerprint(
        mission_id=mission_id,
        task_id=task_id,
        operation_type="BUILD_WORKSPACE",
        target="src/orbital.py",
        input_digest="hash_v1",
        failure_class="SYNTAX_ERROR",
    )
    new_engine.load_persisted_count(mission_id, fp, count=2)

    # Next attempt immediately trips AutonomyLoopError without resetting
    with pytest.raises(AutonomyLoopError):
        new_engine.record_attempt(
            mission_id=mission_id,
            task_id=task_id,
            operation_type="BUILD_WORKSPACE",
            target="src/orbital.py",
            input_digest="hash_v1",
            failure_class="SYNTAX_ERROR",
        )
