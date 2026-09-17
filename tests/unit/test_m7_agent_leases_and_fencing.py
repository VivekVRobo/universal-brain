"""
Universal Brain - Unit Tests: M7 Agent Leases, Roles & Split-Agent Fencing

Verifies M7 Sections 22-29, 127-129, and Invariants M7-INV-03, M7-INV-04, M7-INV-05, M7-INV-06:
- Role Registry profiles and capability separation;
- Ephemeral lease issuance with turn and spend boundaries;
- Multi-dimensional fencing (epoch, generation, version, task scope).
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from universal_brain.autonomy.errors import (
    AgentFencedError,
    AgentLeaseExpiredError,
    MissionBudgetExceededError,
    MissionVersionConflictError,
)
from universal_brain.autonomy.leases import AgentLeaseController
from universal_brain.autonomy.roles import AgentRoleRegistry
from universal_brain.autonomy.schemas import AgentLeaseStatus, AgentRole
from universal_brain.kernel.events import ActionClass


def test_agent_role_registry_and_capability_separation():
    """Verifies that roles define functional guidelines without granting permissions (M7-INV-03)."""
    builder_profile = AgentRoleRegistry.get_profile(AgentRole.BUILDER)
    assert builder_profile.role == AgentRole.BUILDER
    assert "workspace_sandbox" in builder_profile.allowed_tool_categories
    assert builder_profile.maximum_recommended_action_class == ActionClass.A1

    verifier_profile = AgentRoleRegistry.get_profile(AgentRole.VERIFIER)
    assert verifier_profile.role == AgentRole.VERIFIER
    assert "test_runner" in verifier_profile.allowed_tool_categories
    assert verifier_profile.maximum_recommended_action_class == ActionClass.A0


def test_agent_lease_issuance_and_usage_accounting():
    """Verifies bounded execution quotas on agent leases (M7 Section 25)."""
    controller = AgentLeaseController()
    agent_id = uuid4()
    mission_id = uuid4()
    task_id = uuid4()

    lease = controller.grant_lease(
        agent_id=agent_id,
        mission_id=mission_id,
        task_scope=[task_id],
        capability_ceiling=ActionClass.A1,
        kernel_epoch=1,
        lease_generation=1,
        duration_minutes=30,
        max_turns=5,
        max_spend=2.0,
    )
    assert lease.status == AgentLeaseStatus.ACTIVE
    assert lease.turns_used == 0

    # Record turn usage
    controller.record_usage(lease.lease_id, turns=2, spend=0.50)
    assert lease.turns_used == 2
    assert lease.spend_used == 0.50
    assert lease.status == AgentLeaseStatus.ACTIVE

    # Completes when turn limit reached
    controller.record_usage(lease.lease_id, turns=3, spend=0.50)
    assert lease.turns_used == 5
    assert lease.status == AgentLeaseStatus.COMPLETED

    # Spend ceiling exceeded raises MissionBudgetExceededError
    with pytest.raises(MissionBudgetExceededError):
        controller.record_usage(lease.lease_id, turns=1, spend=5.0)


def test_agent_lease_fencing_generation_epoch_and_version():
    """
    Verifies multi-dimensional fencing of stale agents (M7-INV-04, M7-INV-05, M7-INV-06).
    """
    controller = AgentLeaseController()
    agent_id = uuid4()
    mission_id = uuid4()
    task_id = uuid4()

    # Agent A receives lease generation 3 under Kernel Epoch 1
    lease = controller.grant_lease(
        agent_id=agent_id,
        mission_id=mission_id,
        task_scope=[task_id],
        kernel_epoch=1,
        lease_generation=3,
    )

    # 1. Valid authorization under matching generation, epoch, version, and task
    valid = controller.validate_lease_authority(
        lease_id=lease.lease_id,
        task_id=task_id,
        current_kernel_epoch=1,
        current_lease_generation=3,
        mission_version=5,
        expected_mission_version=5,
    )
    assert valid.lease_id == lease.lease_id

    # 2. Split-Agent Generation Fencing (M7-INV-05): Task reassigned to generation 4
    with pytest.raises(AgentFencedError, match="stale generation"):
        controller.validate_lease_authority(
            lease_id=lease.lease_id,
            task_id=task_id,
            current_kernel_epoch=1,
            current_lease_generation=4,  # newer generation!
            mission_version=5,
            expected_mission_version=5,
        )

    # 3. Kernel Reboot Epoch Fencing (M7-INV-06): Kernel rebooted to epoch 2
    lease2 = controller.grant_lease(
        agent_id=agent_id,
        mission_id=mission_id,
        task_scope=[task_id],
        kernel_epoch=1,
        lease_generation=3,
    )
    with pytest.raises(AgentFencedError, match="older kernel epoch"):
        controller.validate_lease_authority(
            lease_id=lease2.lease_id,
            task_id=task_id,
            current_kernel_epoch=2,  # newer epoch!
            current_lease_generation=3,
            mission_version=5,
            expected_mission_version=5,
        )

    # 4. Mission Version Fencing: Concurrent mission update occurred
    lease3 = controller.grant_lease(
        agent_id=agent_id,
        mission_id=mission_id,
        task_scope=[task_id],
        kernel_epoch=1,
        lease_generation=3,
    )
    with pytest.raises(MissionVersionConflictError):
        controller.validate_lease_authority(
            lease_id=lease3.lease_id,
            task_id=task_id,
            current_kernel_epoch=1,
            current_lease_generation=3,
            mission_version=6,  # mission advanced!
            expected_mission_version=5,
        )

    # 5. Task Scope Confinement: Unassigned task ID
    lease4 = controller.grant_lease(
        agent_id=agent_id,
        mission_id=mission_id,
        task_scope=[task_id],
        kernel_epoch=1,
        lease_generation=3,
    )
    with pytest.raises(AgentFencedError, match="not in authorized task scope"):
        controller.validate_lease_authority(
            lease_id=lease4.lease_id,
            task_id=uuid4(),  # foreign task
            current_kernel_epoch=1,
            current_lease_generation=3,
            mission_version=5,
            expected_mission_version=5,
        )
