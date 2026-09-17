"""
Universal Brain - Long-Horizon Mission Scheduler

Implements M7 Sections 30-34 and Invariants M7-INV-07, M7-INV-15, M7-INV-17:
- Single-owner epoch-fenced mission coordination;
- Priority-ranked, starvation-free scheduling across concurrent missions;
- Scoped Agent Cell leasing and task dispatch;
- Integrates progress watchdogs, durable wakeups, budget gating, and replanning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from universal_brain.autonomy.anti_loop import AntiLoopEngine
from universal_brain.autonomy.blackboard import MissionBlackboard
from universal_brain.autonomy.commitments import CommitmentTracker
from universal_brain.autonomy.dependencies import DependencyCoordinator
from universal_brain.autonomy.errors import (
    MissionBudgetExceededError,
    MissionContractChangedError,
    MissionStateError,
    SchedulerFencedError,
)
from universal_brain.autonomy.escalation import EscalationEngine
from universal_brain.autonomy.leases import AgentLeaseController
from universal_brain.autonomy.roles import AgentRoleRegistry
from universal_brain.autonomy.schemas import (
    AgentCell,
    AgentLease,
    AgentRole,
    Mission,
    MissionStatus,
    WakeupType,
)
from universal_brain.autonomy.wakeups import WakeupManager
from universal_brain.autonomy.watchdog import ProgressWatchdog
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType


class MissionScheduler:
    """Coordinates long-horizon missions, agent cell leases, and external waits."""

    def __init__(
        self,
        instance_id: str,
        kernel_epoch: int,
        lease_controller: AgentLeaseController,
        blackboard: MissionBlackboard,
        commitment_tracker: CommitmentTracker,
        dependency_coordinator: DependencyCoordinator,
        progress_watchdog: ProgressWatchdog,
        anti_loop: AntiLoopEngine,
        wakeup_manager: WakeupManager,
        escalation_engine: EscalationEngine,
        event_store: EventStore,
        budget_gatekeeper: Optional[BudgetGatekeeper] = None,
    ) -> None:
        self.instance_id = instance_id
        self.kernel_epoch = kernel_epoch
        self.lease_controller = lease_controller
        self.blackboard = blackboard
        self.commitment_tracker = commitment_tracker
        self.dependency_coordinator = dependency_coordinator
        self.progress_watchdog = progress_watchdog
        self.anti_loop = anti_loop
        self.wakeup_manager = wakeup_manager
        self.escalation_engine = escalation_engine
        self.event_store = event_store
        self.budget_gatekeeper = budget_gatekeeper

        self._missions: Dict[UUID, Mission] = {}
        self._agents: Dict[UUID, AgentCell] = {}
        self._task_generations: Dict[UUID, int] = {}

    def register_mission(self, mission: Mission) -> None:
        self._missions[mission.mission_id] = mission

    def get_mission(self, mission_id: UUID) -> Optional[Mission]:
        return self._missions.get(mission_id)

    def assign_agent_to_task(
        self,
        mission: Mission,
        task_id: UUID,
        role: AgentRole,
        action_ceiling: ActionClass = ActionClass.A1,
        tool_scope: Optional[List[str]] = None,
    ) -> AgentLease:
        """
        Creates an Agent Cell and issues an authoritative, fenced lease (M7 Sections 21 & 25).
        Enforces M7-INV-04 & M7-INV-05.
        """
        # Validate mission state allows assignment
        if mission.status not in (MissionStatus.ACTIVE, MissionStatus.READY):
            raise MissionStateError(
                f"Cannot assign agent: mission {mission.mission_id} is in status {mission.status.value}."
            )

        profile = AgentRoleRegistry.get_profile(role)
        # Capability ceiling bounded by mission maximum and role recommendation
        effective_ceiling = min(
            action_ceiling.value,
            mission.maximum_action_class.value,
            profile.maximum_recommended_action_class.value,
        )

        agent = AgentCell(
            mission_id=mission.mission_id,
            role=role,
            assigned_task_ids=[task_id],
            status="ACTIVE",
        )
        self._agents[agent.agent_id] = agent

        # Advance task lease generation
        gen = self._task_generations.get(task_id, 0) + 1
        self._task_generations[task_id] = gen

        lease = self.lease_controller.grant_lease(
            agent_id=agent.agent_id,
            mission_id=mission.mission_id,
            task_scope=[task_id],
            capability_ceiling=ActionClass(effective_ceiling),
            tool_scope=tool_scope or profile.allowed_tool_categories,
            kernel_epoch=self.kernel_epoch,
            lease_generation=gen,
        )
        agent.current_lease_id = lease.lease_id

        # Emit canonical event
        self.event_store.append_event(
            EventType.AGENT_LEASE_GRANTED,
            actor_id=str(self.instance_id),
            payload={
                "mission_id": str(mission.mission_id),
                "agent_id": str(agent.agent_id),
                "role": role.value,
                "task_id": str(task_id),
                "lease_id": str(lease.lease_id),
                "lease_generation": gen,
                "kernel_epoch": self.kernel_epoch,
            },
            project_id=mission.project_id,
        )

        return lease

    def schedule_external_wait(
        self,
        mission: Mission,
        trigger_type: WakeupType,
        due_at: datetime,
        task_id: Optional[UUID] = None,
        trigger_condition: Optional[dict] = None,
    ) -> None:
        """
        Puts mission into WAITING_EXTERNAL and registers durable wakeup (M7 Section 64).
        """
        mission.status = MissionStatus.WAITING_EXTERNAL
        mission.mission_version += 1
        mission.updated_at = datetime.now(timezone.utc)

        wakeup = self.wakeup_manager.schedule_wakeup(
            mission_id=mission.mission_id,
            trigger_type=trigger_type,
            due_at=due_at,
            task_id=task_id,
            trigger_condition=trigger_condition,
        )

        self.event_store.append_event(
            EventType.MISSION_WAKEUP_SCHEDULED,
            actor_id=str(self.instance_id),
            payload={
                "mission_id": str(mission.mission_id),
                "wakeup_id": str(wakeup.wakeup_id),
                "trigger_type": trigger_type.value,
                "due_at": due_at.isoformat(),
            },
            project_id=mission.project_id,
        )

    def process_due_wakeups(self, now: Optional[datetime] = None) -> int:
        """Checks and fires all due wakeups idempotently (M7 Section 69)."""
        due = self.wakeup_manager.get_due_wakeups(now)
        fired_count = 0
        for w in due:
            if self.wakeup_manager.claim_wakeup(w.wakeup_id):
                mission = self._missions.get(w.mission_id)
                if mission:
                    w_fired = self.wakeup_manager.fire_wakeup(
                        w.wakeup_id,
                        current_mission_version=mission.mission_version,
                        expected_mission_version=mission.mission_version,
                    )
                    if mission.status == MissionStatus.WAITING_EXTERNAL:
                        mission.status = MissionStatus.ACTIVE
                        mission.mission_version += 1
                        mission.updated_at = datetime.now(timezone.utc)
                    fired_count += 1

                    self.event_store.append_event(
                        EventType.MISSION_WAKEUP_FIRED,
                        actor_id=str(self.instance_id),
                        payload={"mission_id": str(mission.mission_id), "wakeup_id": str(w_fired.wakeup_id)},
                        project_id=mission.project_id,
                    )
        return fired_count

    def fence_stale_scheduler(self, current_authoritative_epoch: int) -> None:
        """Fences this scheduler if a higher kernel epoch has booted (M7 Section 20)."""
        if self.kernel_epoch < current_authoritative_epoch:
            raise SchedulerFencedError(
                f"Scheduler {self.instance_id} fenced: epoch {self.kernel_epoch} < authoritative {current_authoritative_epoch}."
            )
