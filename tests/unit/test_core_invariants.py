"""
Core Invariant Verification Tests

Asserts:
- ALN-001: Requirement must trace to original input.
- ALN-004 / ALN-004a: High-impact open ambiguities block contract activation.
- ALN-010: Completion / active contract requires acceptance criteria.
- ALN-016: Tamper-evident SHA-256 hash chaining and self-verification.
- Event DAG: Directed causal edges prevent self-referential loops.
"""

from uuid import uuid4
import pytest
from pydantic import ValidationError

from universal_brain.kernel.events import (
    EventEnvelope,
    EventEdge,
    EventType,
    ActionClass,
    RelationType,
)
from universal_brain.alignment.contract import (
    AlignmentContract,
    ContractStatus,
    AmbiguityImpact,
    RequirementPriority,
    RequirementKind,
    OriginalInput,
    Requirement,
    Constraint,
    Assumption,
    Ambiguity,
    AcceptanceCriterion,
    PermissionsCeiling,
)


def test_aln016_hash_chain_integrity():
    """Verify that events calculate deterministic hashes and form an unbroken chain."""
    # 1. Create Genesis event
    genesis = EventEnvelope.create(
        event_type=EventType.USER_INPUT,
        actor_id="operator-vivek",
        payload={"utterance": "Initialize Humanoid Controller"},
        prev_event_hash="",
    )
    assert len(genesis.event_hash) == 64
    assert genesis.prev_event_hash == ""

    # 2. Create Second event linked to Genesis
    event_2 = EventEnvelope.create(
        event_type=EventType.INTENT_PARSED,
        actor_id="universal-executive",
        payload={"goal": "Build ROS2 controller"},
        prev_event_hash=genesis.event_hash,
    )
    assert event_2.prev_event_hash == genesis.event_hash
    assert len(event_2.event_hash) == 64

    # 3. Assert tampering with payload invalidates hash integrity
    with pytest.raises(ValidationError):
        EventEnvelope(
            event_id=event_2.event_id,
            timestamp=event_2.timestamp,
            event_type=event_2.event_type,
            actor_id=event_2.actor_id,
            project_id=event_2.project_id,
            task_id=event_2.task_id,
            contract_version=event_2.contract_version,
            payload={"tampered": True},  # Tampered!
            prev_event_hash=event_2.prev_event_hash,
            event_hash=event_2.event_hash,  # Old hash no longer matches
        )


def test_event_edge_self_loop_prevention():
    """Verify that event edges cannot be self-referential."""
    same_id = uuid4()
    with pytest.raises(ValidationError, match="source_event_id and target_event_id cannot be equal"):
        EventEdge(
            source_event_id=same_id,
            target_event_id=same_id,
            relation_type=RelationType.CAUSED_BY,
        )


def test_aln001_requirement_provenance():
    """Verify that requirements must cite at least one original input source."""
    with pytest.raises(ValidationError, match="Requirement must have at least one source_input_id"):
        Requirement(
            requirement_id="REQ-001",
            statement="Must support ROS2 Humble",
            source_input_ids=[],  # Violates ALN-001
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            verification_method="colcon test",
        )


def test_aln004_aln004a_high_impact_ambiguity_blocks_activation():
    """Verify that active status is blocked if any high-impact ambiguity remains open."""
    input_item = OriginalInput(exact_content_ref="User utterance hash")
    req = Requirement(
        requirement_id="REQ-001",
        statement="Write controller",
        source_input_ids=[input_item.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="unit tests",
    )
    perm = PermissionsCeiling(action_ceiling=ActionClass.A1)
    crit = AcceptanceCriterion(
        criterion_id="AC-001",
        statement="Passes compilation",
        evidence_type="build_log",
        verifier="deterministic",
    )
    high_ambiguity = Ambiguity(
        ambiguity_id="AMB-001",
        question="Which physical CAN bus transceiver?",
        impact=AmbiguityImpact.HIGH,  # High impact per ALN-004a
        resolution_status="open",
    )

    # 1. Draft with high-impact open ambiguity is permitted
    draft_contract = AlignmentContract.create_draft(
        objective="Humanoid Bringup",
        requirements=[req],
        permissions=perm,
        acceptance_criteria=[crit],
        original_inputs=[input_item],
        ambiguities=[high_ambiguity],
    )
    assert draft_contract.status == ContractStatus.DRAFT

    # 2. Attempting to activate with open high-impact ambiguity must raise ValidationError
    with pytest.raises(ValidationError, match="Cannot activate contract: open high-impact ambiguity"):
        draft_contract.activate()

    # 3. When resolved or marked answered, activation succeeds
    resolved_ambiguity = high_ambiguity.model_copy(update={"resolution_status": "answered"})
    resolved_draft = draft_contract.model_copy(update={"ambiguities": [resolved_ambiguity]})
    active_contract = resolved_draft.activate()
    assert active_contract.status == ContractStatus.ACTIVE


def test_aln010_active_contract_requires_acceptance_criterion():
    """Verify that activating a contract requires at least one acceptance criterion."""
    input_item = OriginalInput(exact_content_ref="User utterance hash")
    req = Requirement(
        requirement_id="REQ-001",
        statement="Write controller",
        source_input_ids=[input_item.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="unit tests",
    )
    perm = PermissionsCeiling(action_ceiling=ActionClass.A1)

    draft = AlignmentContract.create_draft(
        objective="Controller",
        requirements=[req],
        permissions=perm,
        acceptance_criteria=[],  # Missing acceptance criteria!
        original_inputs=[input_item],
    )

    with pytest.raises(ValidationError, match="Active contract must have at least one acceptance criterion"):
        draft.activate()
