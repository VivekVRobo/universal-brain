"""
Universal Brain - Unit Tests: M7 Blackboard & Multi-Agent Coordination

Verifies M7 Sections 50-56, 137, and Invariants M7-INV-13, M7-INV-14:
- Structured blackboard coordination replacing chat logs;
- Evidence-based verification of facts;
- Automatic conflict detection upon contradictory assertions;
- Verifier arbitration without arbitrary timestamp selection.
"""

from uuid import uuid4
import pytest

from universal_brain.autonomy.blackboard import MissionBlackboard
from universal_brain.autonomy.commitments import CommitmentTracker
from universal_brain.autonomy.errors import MissionStateError
from universal_brain.autonomy.schemas import (
    BlackboardEntryType,
    BlackboardStatus,
    CommitmentStatus,
)


def test_blackboard_structured_coordination_and_verification():
    """Verifies structured posting and evidence verification (M7-INV-13)."""
    bb = MissionBlackboard()
    mission_id = uuid4()
    researcher_id = uuid4()

    entry = bb.post_entry(
        mission_id=mission_id,
        entry_type=BlackboardEntryType.FACT,
        statement="Target orbit requires Delta-V of 3.84 km/s",
        source_agent_id=researcher_id,
    )
    assert entry.status == BlackboardStatus.PROPOSED
    assert len(bb.get_verified_facts(mission_id)) == 0

    # Verification fails without evidence
    with pytest.raises(MissionStateError):
        bb.verify_entry(entry.entry_id, evidence_refs=[])

    # Verification succeeds with cryptographic evidence refs
    verified = bb.verify_entry(entry.entry_id, evidence_refs=["sha256/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"])
    assert verified.status == BlackboardStatus.VERIFIED
    assert len(bb.get_verified_facts(mission_id)) == 1


def test_blackboard_conflict_detection_and_arbitration():
    """
    Verifies that contradictory claims trigger CONFLICT_DETECTED and formal arbitration (M7-INV-14).
    """
    bb = MissionBlackboard()
    mission_id = uuid4()
    agent_a = uuid4()
    agent_b = uuid4()

    # Agent A asserts Fact X
    e1 = bb.post_entry(
        mission_id=mission_id,
        entry_type=BlackboardEntryType.FACT,
        statement="Sensor telemetry indicates trajectory is stable",
        source_agent_id=agent_a,
    )
    assert e1.status == BlackboardStatus.PROPOSED

    # Agent B asserts NOT Fact X
    e2 = bb.post_entry(
        mission_id=mission_id,
        entry_type=BlackboardEntryType.FACT,
        statement="NOT Sensor telemetry indicates trajectory is stable",
        source_agent_id=agent_b,
    )

    # Both entries transition to CONFLICTED
    assert e1.status == BlackboardStatus.CONFLICTED
    assert e2.status == BlackboardStatus.CONFLICTED

    conflicts = bb.get_conflicts(mission_id)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.resolution_status == "UNRESOLVED"
    assert e1.entry_id in c.entry_ids
    assert e2.entry_id in c.entry_ids

    # Independent Verifier resolves conflict based on hard telemetry evidence
    resolved = bb.resolve_conflict(
        conflict_id=c.conflict_id,
        winning_entry_id=e1.entry_id,
        verifier_evidence="sha256/telemetry_doppler_radar_verification_proof",
    )
    assert resolved.resolution_status == "RESOLVED"
    assert e1.status == BlackboardStatus.VERIFIED
    assert e2.status == BlackboardStatus.REJECTED


def test_commitment_tracker_evidence_requirement():
    """Verifies that commitments cannot be marked satisfied without evidence (M7 Sections 38-40)."""
    tracker = CommitmentTracker()
    mission_id = uuid4()
    task_id = uuid4()
    agent_id = uuid4()

    comm = tracker.create_commitment(
        mission_id=mission_id,
        task_id=task_id,
        agent_id=agent_id,
        statement="Produce compiled binary for orbit optimizer",
        expected_evidence="sha256/binary_digest",
    )
    assert comm.status == CommitmentStatus.OPEN

    # Fails with empty or short evidence digest
    with pytest.raises(MissionStateError):
        tracker.satisfy_commitment(comm.commitment_id, verified_evidence_digest="")

    # Satisfied with authentic digest
    sat = tracker.satisfy_commitment(
        comm.commitment_id,
        verified_evidence_digest="a" * 64,
    )
    assert sat.status == CommitmentStatus.SATISFIED
