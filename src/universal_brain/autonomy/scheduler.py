"""Long-horizon mission scheduler backed by canonical event projections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.anti_loop import AntiLoopEngine
from universal_brain.autonomy.blackboard import MissionBlackboard
from universal_brain.autonomy.commitments import CommitmentTracker
from universal_brain.autonomy.dependencies import DependencyCoordinator
from universal_brain.autonomy.errors import MissionStateError, SchedulerFencedError
from universal_brain.autonomy.escalation import EscalationEngine
from universal_brain.autonomy.leases import AgentLeaseController
from universal_brain.autonomy.roles import AgentRoleRegistry
from universal_brain.autonomy.schemas import (
    AgentCell,
    AgentLease,
    AgentRole,
    Mission,
    MissionStatus,
    WakeupRecord,
    WakeupType,
)
from universal_brain.autonomy.wakeups import WakeupManager
from universal_brain.autonomy.watchdog import ProgressWatchdog
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType


_MISSION_STATE_EVENTS = {
    EventType.MISSION_CREATED,
    EventType.MISSION_ACTIVATED,
    EventType.MISSION_PAUSED,
    EventType.MISSION_RESUMED,
    EventType.MISSION_CANCELLED,
    EventType.MISSION_COMPLETED,
    EventType.MISSION_FAILED,
    EventType.MISSION_WAKEUP_SCHEDULED,
    EventType.MISSION_WAKEUP_FIRED,
}


class MissionScheduler:
    """Coordinates missions while keeping RAM as a replayable projection."""

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
        self.rehydrate_from_events()

    def rehydrate_from_events(self) -> None:
        """Reconstruct scheduler mission/agent/lease/wakeup projections."""
        self._missions.clear()
        self._agents.clear()
        self._task_generations.clear()
        self.lease_controller._leases.clear()
        self.wakeup_manager._wakeups.clear()

        for event in self.event_store.get_all_events():
            if event.event_type in _MISSION_STATE_EVENTS:
                raw_mission = event.payload.get("mission")
                if isinstance(raw_mission, dict):
                    mission = Mission.model_validate(raw_mission)
                    self._missions[mission.mission_id] = mission

                raw_wakeup = event.payload.get("wakeup")
                if isinstance(raw_wakeup, dict):
                    wakeup = WakeupRecord.model_validate(raw_wakeup)
                    self.wakeup_manager._wakeups[wakeup.wakeup_id] = wakeup

            if event.event_type == EventType.AGENT_LEASE_GRANTED:
                raw_agent = event.payload.get("agent")
                raw_lease = event.payload.get("lease")
                if not isinstance(raw_agent, dict) or not isinstance(raw_lease, dict):
                    continue
                agent = AgentCell.model_validate(raw_agent)
                lease = AgentLease.model_validate(raw_lease)
                self._agents[agent.agent_id] = agent
                self.lease_controller._leases[lease.lease_id] = lease
                for task_id in lease.task_scope:
                    self._task_generations[task_id] = max(
                        self._task_generations.get(task_id, 0),
                        lease.lease_generation,
                    )

    def register_mission(self, mission: Mission) -> None:
        """Durably register a mission before exposing it in scheduler RAM."""
        self.event_store.append_event(
            EventType.MISSION_CREATED,
            actor_id=str(self.instance_id),
            payload={"mission": mission.model_dump(mode="json")},
            project_id=mission.project_id,
            contract_version=mission.contract_version,
        )
        self._missions[mission.mission_id] = mission

    def get_mission(self, mission_id: UUID) -> Optional[Mission]:
        return self._missions.get(mission_id)

    @staticmethod
    def _apply_mission_state(target: Mission, source: Mission) -> Mission:
        """Preserve caller-held mission identity after canonical commit succeeds."""
        for field_name in Mission.model_fields:
            setattr(target, field_name, getattr(source, field_name))
        return target

    def assign_agent_to_task(
        self,
        mission: Mission,
        task_id: UUID,
        role: AgentRole,
        action_ceiling: ActionClass = ActionClass.A1,
        tool_scope: Optional[List[str]] = None,
    ) -> AgentLease:
        if mission.status not in (MissionStatus.ACTIVE, MissionStatus.READY):
            raise MissionStateError(
                f"Cannot assign agent: mission {mission.mission_id} "
                f"is in status {mission.status.value}."
            )

        profile = AgentRoleRegistry.get_profile(role)
        effective_ceiling = min(
            action_ceiling.value,
            mission.maximum_action_class.value,
            profile.maximum_recommended_action_class.value,
        )

        generation = self._task_generations.get(task_id, 0) + 1
        agent = AgentCell(
            mission_id=mission.mission_id,
            role=role,
            assigned_task_ids=[task_id],
            status="ACTIVE",
        )

        lease = self.lease_controller.grant_lease(
            agent_id=agent.agent_id,
            mission_id=mission.mission_id,
            task_scope=[task_id],
            capability_ceiling=ActionClass(effective_ceiling),
            tool_scope=tool_scope or profile.allowed_tool_categories,
            kernel_epoch=self.kernel_epoch,
            lease_generation=generation,
        )
        agent = agent.model_copy(update={"current_lease_id": lease.lease_id})

        try:
            self.event_store.append_event(
                EventType.AGENT_LEASE_GRANTED,
                actor_id=str(self.instance_id),
                payload={
                    "mission_id": str(mission.mission_id),
                    "agent_id": str(agent.agent_id),
                    "role": role.value,
                    "task_id": str(task_id),
                    "lease_id": str(lease.lease_id),
                    "lease_generation": generation,
                    "kernel_epoch": self.kernel_epoch,
                    "agent": agent.model_dump(mode="json"),
                    "lease": lease.model_dump(mode="json"),
                },
                project_id=mission.project_id,
                task_id=task_id,
                contract_version=mission.contract_version,
            )
        except Exception:
            self.lease_controller._leases.pop(lease.lease_id, None)
            raise

        self._agents[agent.agent_id] = agent
        self._task_generations[task_id] = generation
        return lease

    def schedule_external_wait(
        self,
        mission: Mission,
        trigger_type: WakeupType,
        due_at: datetime,
        task_id: Optional[UUID] = None,
        trigger_condition: Optional[dict] = None,
    ) -> None:
        previous = self._missions.get(mission.mission_id, mission)
        updated = mission.model_copy(
            update={
                "status": MissionStatus.WAITING_EXTERNAL,
                "mission_version": mission.mission_version + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        wakeup = self.wakeup_manager.schedule_wakeup(
            mission_id=mission.mission_id,
            trigger_type=trigger_type,
            due_at=due_at,
            task_id=task_id,
            trigger_condition=trigger_condition,
        )

        try:
            self.event_store.append_event(
                EventType.MISSION_WAKEUP_SCHEDULED,
                actor_id=str(self.instance_id),
                payload={
                    "mission_id": str(mission.mission_id),
                    "mission": updated.model_dump(mode="json"),
                    "wakeup": wakeup.model_dump(mode="json"),
                },
                project_id=mission.project_id,
                task_id=task_id,
                contract_version=mission.contract_version,
            )
        except Exception:
            self.wakeup_manager._wakeups.pop(wakeup.wakeup_id, None)
            self._missions[mission.mission_id] = previous
            raise

        committed = self._apply_mission_state(mission, updated)
        self._missions[mission.mission_id] = committed

    def process_due_wakeups(self, now: Optional[datetime] = None) -> int:
        due = self.wakeup_manager.get_due_wakeups(now)
        fired_count = 0

        for wakeup in due:
            mission = self._missions.get(wakeup.mission_id)
            if mission is None:
                continue

            previous_wakeup = wakeup.model_copy(deep=True)
            if not self.wakeup_manager.claim_wakeup(wakeup.wakeup_id):
                continue

            fired = self.wakeup_manager.fire_wakeup(
                wakeup.wakeup_id,
                current_mission_version=mission.mission_version,
                expected_mission_version=mission.mission_version,
            )

            updated = mission
            if mission.status == MissionStatus.WAITING_EXTERNAL:
                updated = mission.model_copy(
                    update={
                        "status": MissionStatus.ACTIVE,
                        "mission_version": mission.mission_version + 1,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )

            try:
                self.event_store.append_event(
                    EventType.MISSION_WAKEUP_FIRED,
                    actor_id=str(self.instance_id),
                    payload={
                        "mission_id": str(mission.mission_id),
                        "mission": updated.model_dump(mode="json"),
                        "wakeup": fired.model_dump(mode="json"),
                    },
                    project_id=mission.project_id,
                    task_id=wakeup.task_id,
                    contract_version=mission.contract_version,
                )
            except Exception:
                self.wakeup_manager._wakeups[wakeup.wakeup_id] = previous_wakeup
                raise

            committed = self._apply_mission_state(mission, updated)
            self._missions[mission.mission_id] = committed
            fired_count += 1

        return fired_count

    def fence_stale_scheduler(self, current_authoritative_epoch: int) -> None:
        if self.kernel_epoch < current_authoritative_epoch:
            raise SchedulerFencedError(
                f"Scheduler {self.instance_id} fenced: epoch {self.kernel_epoch} "
                f"< authoritative {current_authoritative_epoch}."
            )
