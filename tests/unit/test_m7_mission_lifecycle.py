"""
Universal Brain - Unit Tests: M7 Mission Lifecycle & Optimistic Concurrency

Verifies M7 Sections 7-12, 123-126:
- Mission creation and contract binding;
- State machine transition rules and guard validation;
- Optimistic concurrency control (MissionVersionConflictError);
- Idempotency deduplication.
"""

from datetime import datetime, timezone
from uuid import uuid4
import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    AlignmentContract,
    ContractStatus,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.autonomy.errors import (
    MissionStateError,
    MissionVersionConflictError,
)
from universal_brain.autonomy.mission import MissionController, MissionStateMachine
from universal_brain.autonomy.schemas import (
    AutonomyLevel,
    Mission,
    MissionPlan,
    MissionStatus,
)
from universal_brain.kernel.events import ActionClass


def create_test_contract(status: str = "active") -> AlignmentContract:
    orig = OriginalInput(exact_content_ref="ref_01")
    req = Requirement(
        requirement_id="REQ-01",
        statement="Test statement",
        source_input_ids=[orig.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="unit_test",
    )
    crit = AcceptanceCriterion(
        criterion_id="CRIT-01",
        statement="Test crit",
        evidence_type="test_output",
        verifier="deterministic",
    )
    contract = AlignmentContract(
        version=1,
        objective="Test Objective",
        original_inputs=[orig],
        requirements=[req],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[crit],
        status=ContractStatus.ACTIVE if status == "active" else ContractStatus.DRAFT,
    )
    return contract


def test_mission_state_machine_transitions_and_guards():
    """Verifies legitimate and illegal mission lifecycle transitions (M7 Sections 8 & 9)."""
    contract = create_test_contract(status="active")
    mission = Mission(
        project_id=uuid4(),
        title="Orbital Transfer",
        goal="Calculate optimal Hohmann transfer window",
        contract_id=contract.contract_id,
        contract_version=1,
        completion_criteria=[{"criterion_id": "CRIT-01", "mandatory": True}],
        status=MissionStatus.DRAFT,
    )

    # DRAFT -> PROPOSED -> VALIDATING -> READY -> ACTIVE
    MissionStateMachine.validate_transition(MissionStatus.DRAFT, MissionStatus.PROPOSED)
    MissionStateMachine.validate_transition(MissionStatus.PROPOSED, MissionStatus.VALIDATING)
    MissionStateMachine.validate_transition(MissionStatus.VALIDATING, MissionStatus.READY)
    MissionStateMachine.validate_transition(MissionStatus.READY, MissionStatus.ACTIVE, contract=contract)

    # Illegal transition: DRAFT -> COMPLETED
    with pytest.raises(MissionStateError):
        MissionStateMachine.validate_transition(MissionStatus.DRAFT, MissionStatus.COMPLETED)

    # Illegal transition: COMPLETED -> ACTIVE (terminal)
    with pytest.raises(MissionStateError):
        MissionStateMachine.validate_transition(MissionStatus.COMPLETED, MissionStatus.ACTIVE)

    # Guard: ACTIVE -> COMPLETED fails if mandatory criterion missing
    with pytest.raises(MissionStateError, match="missing mandatory criteria"):
        MissionStateMachine.validate_transition(
            MissionStatus.ACTIVE,
            MissionStatus.COMPLETED,
            mission=mission,
            verified_criteria=[],
        )

    # Guard: ACTIVE -> COMPLETED succeeds when verified
    MissionStateMachine.validate_transition(
        MissionStatus.ACTIVE,
        MissionStatus.COMPLETED,
        mission=mission,
        verified_criteria=["CRIT-01"],
    )


def test_mission_controller_optimistic_concurrency_and_idempotency():
    """Verifies optimistic concurrency conflict prevention and idempotency (M7 Sections 10 & 11)."""
    controller = MissionController()
    contract = create_test_contract(status="active")
    mission = Mission(
        project_id=uuid4(),
        title="Mars Rover Mission",
        goal="Deploy scientific payload",
        contract_id=contract.contract_id,
        contract_version=1,
        status=MissionStatus.READY,
        mission_version=1,
    )

    # 1. Successful transition with version matching
    updated = controller.transition(
        mission=mission,
        target_status=MissionStatus.ACTIVE,
        expected_version=1,
        contract=contract,
        idempotency_key="cmd_activate_001",
    )
    assert updated.status == MissionStatus.ACTIVE
    assert updated.mission_version == 2

    # 2. Idempotent re-execution returns identical mission without error
    idem = controller.transition(
        mission=mission,
        target_status=MissionStatus.ACTIVE,
        expected_version=1,
        idempotency_key="cmd_activate_001",
    )
    assert idem.status == MissionStatus.ACTIVE
    assert idem.mission_version == 2

    # 3. Concurrent stale writer with expected_version=1 fails with MissionVersionConflictError
    with pytest.raises(MissionVersionConflictError):
        controller.transition(
            mission=mission,
            target_status=MissionStatus.PAUSED,
            expected_version=1,  # Stale version! Current is 2
        )


def test_mission_plan_digest_determinism():
    """Verifies canonical plan serialization and digest calculation (M7 Sections 13-15)."""
    m_id = uuid4()
    plan1 = MissionPlan(
        mission_id=m_id,
        plan_version=1,
        budget_estimate=15.5,
        milestones=[{"name": "M1_recon", "target_day": 1}],
        replan_triggers=["budget_spike", "worker_failure"],
    )
    plan2 = MissionPlan(
        mission_id=m_id,
        plan_version=1,
        budget_estimate=15.5,
        milestones=[{"name": "M1_recon", "target_day": 1}],
        replan_triggers=["worker_failure", "budget_spike"],  # order inverted
    )

    d1 = plan1.calculate_digest()
    d2 = plan2.calculate_digest()
    assert d1 == d2
    assert len(d1) == 64
