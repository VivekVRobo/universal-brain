"""
Cellular Architecture Integration & Unit Verification Tests

Asserts:
- Kernel Capability Service (ALN-008, ALN-009, ALN-018)
- Total Awareness Causal Event Store (ALN-016, ALN-021)
- Deterministic Ambiguity Taxonomy (ALN-004a)
- Constraint Preservation Gate (ALN-006)
- 3-Tier Budget Gatekeeper & Circuit Breaker (COST_CONTROL_POLICY)
"""

from uuid import uuid4
import pytest

from universal_brain.alignment.contract import (
    AlignmentContract,
    Constraint,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
    AcceptanceCriterion,
)
from universal_brain.alignment.engine import AlignmentEngine, AmbiguityClassifier
from universal_brain.executive.budget import (
    BudgetGatekeeper,
    BudgetTier,
    TokenUsage,
)
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.errors import (
    BudgetExhaustedError,
    CapabilityDeniedError,
    ConstraintWeakenedError,
)
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import (
    ActionClass,
    EventType,
    RelationType,
)


# -----------------------------------------------------------------------------
# 1. Capability Service Tests (ALN-008, ALN-009, ALN-018)
# -----------------------------------------------------------------------------


def test_capability_service_issue_and_verify():
    """Verify that capability tokens grant scoped access and reject unauthorized actions."""
    service = CapabilityService()
    project_id = uuid4()
    task_id = uuid4()

    # 1. Issue valid A1 token
    token = service.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=1,
        action_class=ActionClass.A1,
        target_resource="./workspace/controller.cpp",
        allowed_operations=["read", "write"],
    )

    # 2. Verify valid usage passes
    assert service.verify_token(
        token=token,
        target_resource="./workspace/controller.cpp",
        required_operation="write",
        current_contract_version=1,
    ) is True

    # 3. Denied if resource out of scope
    with pytest.raises(CapabilityDeniedError, match="outside authorized scope"):
        service.verify_token(
            token=token,
            target_resource="/etc/shadow",
            required_operation="write",
            current_contract_version=1,
        )

    # 4. Denied if contract version is stale (ALN-015)
    with pytest.raises(CapabilityDeniedError, match="stale"):
        service.verify_token(
            token=token,
            target_resource="./workspace/controller.cpp",
            required_operation="write",
            current_contract_version=2,  # Contract changed!
        )


def test_aln008_a2_requires_operator_approval():
    """Verify that A2 tokens cannot be issued autonomously without operator authorization."""
    service = CapabilityService()
    with pytest.raises(CapabilityDeniedError, match="A2 consequential actions require fresh operator authorization"):
        service.issue_token(
            project_id=uuid4(),
            task_id=uuid4(),
            contract_version=1,
            action_class=ActionClass.A2,
            target_resource="production_deploy",
            allowed_operations=["deploy"],
            issued_by_operator=False,  # Autonomous attempt blocked!
        )


def test_aln018_a3_strictly_prohibited():
    """Verify that A3 physical actuator control is permanently blocked."""
    service = CapabilityService()
    with pytest.raises(CapabilityDeniedError, match="A3 actions are strictly prohibited"):
        service.issue_token(
            project_id=uuid4(),
            task_id=uuid4(),
            contract_version=1,
            action_class=ActionClass.A3,
            target_resource="/dev/actuator",
            allowed_operations=["motor_enable"],
            issued_by_operator=True,
        )


# -----------------------------------------------------------------------------
# 2. Causal Event Store Tests (ALN-016, ALN-021)
# -----------------------------------------------------------------------------


def test_event_store_lineage_and_outbox():
    """Verify causal DAG lineage tracing and outbox batch draining."""
    store = EventStore()
    project_id = uuid4()

    # Step 1: User Input
    e1 = store.append_event(
        event_type=EventType.USER_INPUT,
        actor_id="operator",
        payload={"text": "Build robot"},
        project_id=project_id,
    )

    # Step 2: Contract Created (caused by e1)
    e2 = store.append_event(
        event_type=EventType.CONTRACT_CREATED,
        actor_id="executive",
        payload={"contract_id": str(uuid4())},
        project_id=project_id,
        caused_by_event_id=e1.event_id,
    )

    # Step 3: Tool Called (caused by e2)
    e3 = store.append_event(
        event_type=EventType.TOOL_CALLED,
        actor_id="coder_agent",
        payload={"tool": "file_write"},
        project_id=project_id,
        caused_by_event_id=e2.event_id,
    )

    # Verify cryptographic integrity
    assert store.verify_chain_integrity() is True

    # Trace backward causal walk: 'Why did e3 happen?'
    lineage = store.trace_causal_lineage(e3.event_id)
    assert len(lineage) == 3
    assert lineage[0].event_id == e1.event_id  # Originating root cause
    assert lineage[1].event_id == e2.event_id
    assert lineage[2].event_id == e3.event_id

    # Verify outbox batching
    assert len(store._outbox) == 3
    batch = store.drain_outbox(max_batch_size=2)
    assert len(batch) == 2
    assert len(store._outbox) == 1


# -----------------------------------------------------------------------------
# 3. Deterministic Ambiguity & Constraint Preservation (ALN-004a, ALN-006)
# -----------------------------------------------------------------------------


def test_aln004a_deterministic_ambiguity_classification():
    """Verify that ambiguity classifier deterministically classifies impact without an LLM."""
    assert AmbiguityClassifier.classify("Should we delete the database table?") == "high"
    assert AmbiguityClassifier.classify("Can we modify permissions with chmod 777?") == "high"
    assert AmbiguityClassifier.classify("Which ROS2 distro should we target: Humble or Iron?") == "medium"
    assert AmbiguityClassifier.classify("What naming convention for internal variables: camelCase or snake_case?") == "low"


def test_aln006_constraint_weakening_prevention():
    """Verify that agents cannot drop or silently weaken explicit constraints."""
    inp = OriginalInput(exact_content_ref="User ref")
    req = Requirement(
        requirement_id="REQ-01",
        statement="Clean build",
        source_input_ids=[inp.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="build",
    )
    c1 = Constraint(constraint_id="C-01", statement="Must run in local Docker", authority="explicit_user")
    perm = PermissionsCeiling(action_ceiling=ActionClass.A1)
    crit = AcceptanceCriterion(criterion_id="AC-1", statement="Pass", evidence_type="log", verifier="det")

    v1_contract = AlignmentContract.create_draft(
        objective="Sandbox App",
        requirements=[req],
        constraints=[c1],
        permissions=perm,
        acceptance_criteria=[crit],
        original_inputs=[inp],
    )

    # Attempt to amend without operator authority and drop constraint C-01
    with pytest.raises(ConstraintWeakenedError, match="were removed without operator authorization"):
        AlignmentEngine.amend_contract(
            current_contract=v1_contract,
            reason="Drop constraint autonomously",
            authority_event_id=uuid4(),
            updated_constraints=[],  # Dropped!
            is_operator_authorized=False,
        )


# -----------------------------------------------------------------------------
# 4. Budget Gatekeeper Tests (COST_CONTROL_POLICY)
# -----------------------------------------------------------------------------


def test_budget_exhaustion_circuit_breaker():
    """Verify 3-tier budget calculation, model auto-downgrade, and hard circuit breaker."""
    gatekeeper = BudgetGatekeeper(monthly_budget_usd=10.00)

    # Initial state: Normal
    assert gatekeeper.get_tier() == BudgetTier.NORMAL

    # Consume $7.50 (75% -> Tier 1 Soft Warning)
    gatekeeper.cumulative_spend_usd = 7.50
    assert gatekeeper.get_tier() == BudgetTier.SOFT_WARNING

    # Consume $8.80 (88% -> Tier 2 Downgrade)
    gatekeeper.cumulative_spend_usd = 8.80
    assert gatekeeper.get_tier() == BudgetTier.DOWNGRADE
    # Non-critical tasks downgraded
    assert gatekeeper.select_optimized_model("claude-3-5-sonnet", is_critical_task=False) == "claude-3-5-haiku"
    # Critical tasks retain frontier model
    assert gatekeeper.select_optimized_model("claude-3-5-sonnet", is_critical_task=True) == "claude-3-5-sonnet"

    # Consume $10.05 (100.5% -> Tier 3 Hard Circuit Breaker)
    gatekeeper.cumulative_spend_usd = 10.05
    assert gatekeeper.get_tier() == BudgetTier.EXHAUSTED

    # A0 is allowed
    gatekeeper.check_authorization("A0")

    # A1 or A2 raises BudgetExhaustedError
    with pytest.raises(BudgetExhaustedError, match="Monthly budget ceiling"):
        gatekeeper.check_authorization("A1")
