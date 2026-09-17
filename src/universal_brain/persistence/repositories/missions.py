"""
Universal Brain - Mission & Autonomy Repositories

Implements M7 Section 115:
Provides transactional CRUD, optimistic concurrency control,
epoch fencing, and state queries for all M7 persistence models.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, select, update

from universal_brain.autonomy.errors import (
    AgentFencedError,
    MissionStateError,
    MissionVersionConflictError,
    SchedulerFencedError,
)
from universal_brain.autonomy.schemas import (
    AgentCell,
    AgentLease,
    BlackboardEntry,
    Commitment,
    Mission,
    MissionCheckpoint,
    MissionPlan,
    WakeupRecord,
)
from universal_brain.persistence.models import (
    AgentCellORM,
    AgentLeaseORM,
    BlackboardEntryORM,
    EscalationORM,
    LoopFingerprintORM,
    MissionCheckpointORM,
    MissionCommitmentORM,
    MissionORM,
    MissionPlanORM,
    MissionSchedulerLeaseORM,
    ResourceLeaseORM,
    WakeupRecordORM,
)
from universal_brain.persistence.repositories.base import BaseRepository


class MissionRepository(BaseRepository[MissionORM]):
    """Manages canonical Mission lifecycle and optimistic versioning (M7 Sections 7-10)."""

    async def create_mission(self, mission: Mission) -> MissionORM:
        try:
            orm = MissionORM(
                mission_id=mission.mission_id,
                project_id=mission.project_id,
                title=mission.title,
                goal=mission.goal,
                description=mission.description,
                contract_id=mission.contract_id,
                contract_version=mission.contract_version,
                priority=mission.priority,
                risk_class=mission.risk_class,
                maximum_action_class=mission.maximum_action_class.value if hasattr(mission.maximum_action_class, "value") else str(mission.maximum_action_class),
                maximum_autonomy_level=mission.maximum_autonomy_level.value if hasattr(mission.maximum_autonomy_level, "value") else str(mission.maximum_autonomy_level),
                status=mission.status.value if hasattr(mission.status, "value") else str(mission.status),
                created_by=mission.created_by,
                created_at=mission.created_at,
                updated_at=mission.updated_at,
                deadline=mission.deadline,
                time_horizon=mission.time_horizon,
                budget_ceiling=mission.budget_ceiling,
                budget_spent=mission.budget_spent,
                completion_criteria=mission.completion_criteria,
                failure_criteria=mission.failure_criteria,
                current_plan_id=mission.current_plan_id,
                current_plan_version=mission.current_plan_version,
                mission_version=mission.mission_version,
                kernel_epoch_created=mission.kernel_epoch_created,
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_mission(self, mission_id: UUID) -> Optional[MissionORM]:
        try:
            stmt = select(MissionORM).where(MissionORM.mission_id == mission_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def list_active_missions(self) -> List[MissionORM]:
        try:
            stmt = select(MissionORM).where(
                MissionORM.status.in_(["ACTIVE", "READY", "WAITING_EXTERNAL", "BLOCKED", "ESCALATED"])
            ).order_by(MissionORM.priority.desc())
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as e:
            raise self._translate_exception(e) from e

    async def list_project_missions(self, project_id: UUID) -> List[MissionORM]:
        try:
            stmt = select(MissionORM).where(MissionORM.project_id == project_id).order_by(MissionORM.created_at.desc())
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as e:
            raise self._translate_exception(e) from e

    async def update_mission_status_with_version(
        self,
        mission_id: UUID,
        expected_version: int,
        new_status: str,
        current_plan_id: Optional[UUID] = None,
        current_plan_version: Optional[int] = None,
        budget_spent: Optional[float] = None,
    ) -> MissionORM:
        """Atomic version-guarded state transition (M7 Section 10)."""
        try:
            updates: Dict[str, Any] = {
                "status": new_status,
                "mission_version": expected_version + 1,
                "updated_at": datetime.now(timezone.utc),
            }
            if current_plan_id is not None:
                updates["current_plan_id"] = current_plan_id
            if current_plan_version is not None:
                updates["current_plan_version"] = current_plan_version
            if budget_spent is not None:
                updates["budget_spent"] = budget_spent

            stmt = (
                update(MissionORM)
                .where(and_(MissionORM.mission_id == mission_id, MissionORM.mission_version == expected_version))
                .values(**updates)
            )
            result = await self.session.execute(stmt)
            if result.rowcount == 0:
                # Determine if missing or conflict
                existing = await self.get_mission(mission_id)
                if existing:
                    raise MissionVersionConflictError(
                        f"Optimistic concurrency failure: mission {mission_id} is at version {existing.mission_version}, expected {expected_version}",
                        mission_id=str(mission_id),
                    )
                raise MissionStateError(f"Mission {mission_id} does not exist.")

            await self.session.flush()
            updated_mission = await self.get_mission(mission_id)
            assert updated_mission is not None
            return updated_mission
        except Exception as e:
            if isinstance(e, (MissionVersionConflictError, MissionStateError)):
                raise
            raise self._translate_exception(e) from e


class MissionPlanRepository(BaseRepository[MissionPlanORM]):
    """Manages immutable plan history for missions (M7 Sections 13-15)."""

    async def save_plan(self, plan: MissionPlan) -> MissionPlanORM:
        try:
            digest = plan.plan_digest or plan.calculate_digest()
            orm = MissionPlanORM(
                plan_id=plan.plan_id,
                mission_id=plan.mission_id,
                plan_version=plan.plan_version,
                task_dag_id=plan.task_dag_id,
                assumptions=plan.assumptions,
                risks=plan.risks,
                external_dependencies=plan.external_dependencies,
                resource_estimates=plan.resource_estimates,
                budget_estimate=plan.budget_estimate,
                milestones=plan.milestones,
                replan_triggers=plan.replan_triggers,
                created_by=plan.created_by,
                created_at=plan.created_at,
                plan_digest=digest,
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_plan(self, plan_id: UUID) -> Optional[MissionPlanORM]:
        try:
            stmt = select(MissionPlanORM).where(MissionPlanORM.plan_id == plan_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_latest_plan(self, mission_id: UUID) -> Optional[MissionPlanORM]:
        try:
            stmt = select(MissionPlanORM).where(MissionPlanORM.mission_id == mission_id).order_by(MissionPlanORM.plan_version.desc()).limit(1)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e


class MissionSchedulerLeaseRepository(BaseRepository[MissionSchedulerLeaseORM]):
    """Epoch-fenced authoritative mission scheduler lease management (M7 Section 19)."""

    async def acquire_or_renew_lease(
        self,
        mission_id: UUID,
        scheduler_instance_id: str,
        kernel_epoch: int,
        duration_seconds: int = 60,
    ) -> MissionSchedulerLeaseORM:
        try:
            now = datetime.now(timezone.utc)
            expires = now + timedelta(seconds=duration_seconds)

            stmt = select(MissionSchedulerLeaseORM).where(MissionSchedulerLeaseORM.mission_id == mission_id)
            res = await self.session.execute(stmt)
            existing = res.scalar_one_or_none()

            if existing:
                if existing.kernel_epoch > kernel_epoch:
                    raise SchedulerFencedError(
                        f"Scheduler {scheduler_instance_id} fenced by higher kernel epoch {existing.kernel_epoch} > {kernel_epoch}"
                    )
                existing.scheduler_instance_id = scheduler_instance_id
                existing.kernel_epoch = kernel_epoch
                existing.lease_generation += 1
                existing.heartbeat = now
                existing.expires_at = expires
                await self.session.flush()
                return existing
            else:
                orm = MissionSchedulerLeaseORM(
                    lease_id=UUID(int=now.microsecond or 1),
                    mission_id=mission_id,
                    scheduler_instance_id=scheduler_instance_id,
                    kernel_epoch=kernel_epoch,
                    lease_generation=1,
                    acquired_at=now,
                    expires_at=expires,
                    heartbeat=now,
                )
                self.session.add(orm)
                await self.session.flush()
                return orm
        except Exception as e:
            if isinstance(e, SchedulerFencedError):
                raise
            raise self._translate_exception(e) from e

    async def get_lease(self, mission_id: UUID) -> Optional[MissionSchedulerLeaseORM]:
        try:
            stmt = select(MissionSchedulerLeaseORM).where(MissionSchedulerLeaseORM.mission_id == mission_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def release_lease(self, mission_id: UUID) -> None:
        try:
            stmt = select(MissionSchedulerLeaseORM).where(MissionSchedulerLeaseORM.mission_id == mission_id)
            res = await self.session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                await self.session.delete(existing)
                await self.session.flush()
        except Exception as e:
            raise self._translate_exception(e) from e


class AgentCellRepository(BaseRepository[AgentCellORM]):
    """Manages ephemeral agent cells (M7 Section 21)."""

    async def register_agent(self, agent: AgentCell) -> AgentCellORM:
        try:
            orm = AgentCellORM(
                agent_id=agent.agent_id,
                mission_id=agent.mission_id,
                role=agent.role.value if hasattr(agent.role, "value") else str(agent.role),
                status=agent.status,
                assigned_task_ids=[str(tid) for tid in agent.assigned_task_ids],
                agent_version=agent.agent_version,
                created_at=agent.created_at,
                expires_at=agent.expires_at,
                current_lease_id=agent.current_lease_id,
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_agent(self, agent_id: UUID) -> Optional[AgentCellORM]:
        try:
            stmt = select(AgentCellORM).where(AgentCellORM.agent_id == agent_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def list_mission_agents(self, mission_id: UUID) -> List[AgentCellORM]:
        try:
            stmt = select(AgentCellORM).where(AgentCellORM.mission_id == mission_id)
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as e:
            raise self._translate_exception(e) from e


class AgentLeaseRepository(BaseRepository[AgentLeaseORM]):
    """Manages bounded AgentLeases with split-agent fencing (M7 Sections 25-28)."""

    async def save_lease(self, lease: AgentLease) -> AgentLeaseORM:
        try:
            orm = AgentLeaseORM(
                lease_id=lease.lease_id,
                agent_id=lease.agent_id,
                mission_id=lease.mission_id,
                task_scope=[str(t) for t in lease.task_scope],
                lease_generation=lease.lease_generation,
                kernel_epoch=lease.kernel_epoch,
                granted_at=lease.granted_at,
                expires_at=lease.expires_at,
                capability_ceiling=lease.capability_ceiling.value if hasattr(lease.capability_ceiling, "value") else str(lease.capability_ceiling),
                tool_scope=lease.tool_scope,
                max_turns=lease.max_turns,
                turns_used=lease.turns_used,
                max_spend=lease.max_spend,
                spend_used=lease.spend_used,
                status=lease.status.value if hasattr(lease.status, "value") else str(lease.status),
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_lease(self, lease_id: UUID) -> Optional[AgentLeaseORM]:
        try:
            stmt = select(AgentLeaseORM).where(AgentLeaseORM.lease_id == lease_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_active_lease_for_task(self, mission_id: UUID, task_id: UUID) -> Optional[AgentLeaseORM]:
        try:
            now = datetime.now(timezone.utc)
            stmt = select(AgentLeaseORM).where(
                and_(
                    AgentLeaseORM.mission_id == mission_id,
                    AgentLeaseORM.status == "ACTIVE",
                    AgentLeaseORM.expires_at > now,
                )
            )
            res = await self.session.execute(stmt)
            leases = res.scalars().all()
            for l in leases:
                if str(task_id) in (l.task_scope or []):
                    return l
            return None
        except Exception as e:
            raise self._translate_exception(e) from e

    async def fence_stale_leases(self, current_epoch: int) -> int:
        """Revokes all active agent leases belonging to older kernel epochs (M7 Section 27)."""
        try:
            stmt = (
                update(AgentLeaseORM)
                .where(and_(AgentLeaseORM.status == "ACTIVE", AgentLeaseORM.kernel_epoch < current_epoch))
                .values(status="REVOKED")
            )
            res = await self.session.execute(stmt)
            await self.session.flush()
            return res.rowcount
        except Exception as e:
            raise self._translate_exception(e) from e


class CommitmentRepository(BaseRepository[MissionCommitmentORM]):
    """Manages accountability commitments from agent cells (M7 Sections 38-40)."""

    async def save_commitment(self, commitment: Commitment) -> MissionCommitmentORM:
        try:
            orm = MissionCommitmentORM(
                commitment_id=commitment.commitment_id,
                mission_id=commitment.mission_id,
                task_id=commitment.task_id,
                agent_id=commitment.agent_id,
                statement=commitment.statement,
                expected_evidence=commitment.expected_evidence,
                created_at=commitment.created_at,
                expires_at=commitment.expires_at,
                status=commitment.status.value if hasattr(commitment.status, "value") else str(commitment.status),
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_commitment(self, commitment_id: UUID) -> Optional[MissionCommitmentORM]:
        try:
            stmt = select(MissionCommitmentORM).where(MissionCommitmentORM.commitment_id == commitment_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def list_mission_commitments(self, mission_id: UUID) -> List[MissionCommitmentORM]:
        try:
            stmt = select(MissionCommitmentORM).where(MissionCommitmentORM.mission_id == mission_id)
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as e:
            raise self._translate_exception(e) from e

    async def update_status(self, commitment_id: UUID, new_status: str) -> None:
        try:
            stmt = update(MissionCommitmentORM).where(MissionCommitmentORM.commitment_id == commitment_id).values(status=new_status)
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            raise self._translate_exception(e) from e


class BlackboardRepository(BaseRepository[BlackboardEntryORM]):
    """Manages structured claims and facts on the Mission Blackboard (M7 Sections 50-56)."""

    async def save_entry(self, entry: BlackboardEntry) -> BlackboardEntryORM:
        try:
            orm = BlackboardEntryORM(
                entry_id=entry.entry_id,
                mission_id=entry.mission_id,
                entry_type=entry.entry_type.value if hasattr(entry.entry_type, "value") else str(entry.entry_type),
                statement=entry.statement,
                source_agent_id=entry.source_agent_id,
                source_event_id=entry.source_event_id,
                evidence_refs=entry.evidence_refs,
                status=entry.status.value if hasattr(entry.status, "value") else str(entry.status),
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                entry_version=entry.entry_version,
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_entry(self, entry_id: UUID) -> Optional[BlackboardEntryORM]:
        try:
            stmt = select(BlackboardEntryORM).where(BlackboardEntryORM.entry_id == entry_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def list_entries(self, mission_id: UUID) -> List[BlackboardEntryORM]:
        try:
            stmt = select(BlackboardEntryORM).where(BlackboardEntryORM.mission_id == mission_id).order_by(BlackboardEntryORM.created_at.asc())
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as e:
            raise self._translate_exception(e) from e

    async def update_entry_status(self, entry_id: UUID, new_status: str) -> None:
        try:
            stmt = update(BlackboardEntryORM).where(BlackboardEntryORM.entry_id == entry_id).values(status=new_status, updated_at=datetime.now(timezone.utc))
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            raise self._translate_exception(e) from e


class WakeupRepository(BaseRepository[WakeupRecordORM]):
    """Manages durable, crash-resilient mission wakeups (M7 Sections 64-70)."""

    async def schedule_wakeup(self, wakeup: WakeupRecord) -> WakeupRecordORM:
        try:
            orm = WakeupRecordORM(
                wakeup_id=wakeup.wakeup_id,
                mission_id=wakeup.mission_id,
                task_id=wakeup.task_id,
                trigger_type=wakeup.trigger_type.value if hasattr(wakeup.trigger_type, "value") else str(wakeup.trigger_type),
                trigger_condition=wakeup.trigger_condition,
                due_at=wakeup.due_at,
                created_at=wakeup.created_at,
                fired_at=wakeup.fired_at,
                status=wakeup.status.value if hasattr(wakeup.status, "value") else str(wakeup.status),
                idempotency_key=wakeup.idempotency_key,
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def claim_wakeup(self, wakeup_id: UUID) -> bool:
        """Atomic claim preventing duplicate execution across ticks (M7 Section 69)."""
        try:
            stmt = (
                update(WakeupRecordORM)
                .where(and_(WakeupRecordORM.wakeup_id == wakeup_id, WakeupRecordORM.status == "PENDING"))
                .values(status="CLAIMED")
            )
            res = await self.session.execute(stmt)
            await self.session.flush()
            return res.rowcount > 0
        except Exception as e:
            raise self._translate_exception(e) from e

    async def fire_wakeup(self, wakeup_id: UUID) -> None:
        try:
            now = datetime.now(timezone.utc)
            stmt = (
                update(WakeupRecordORM)
                .where(WakeupRecordORM.wakeup_id == wakeup_id)
                .values(status="FIRED", fired_at=now)
            )
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_overdue_wakeups(self, now: datetime) -> List[WakeupRecordORM]:
        try:
            stmt = select(WakeupRecordORM).where(
                and_(WakeupRecordORM.status == "PENDING", WakeupRecordORM.due_at <= now)
            ).order_by(WakeupRecordORM.due_at.asc())
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as e:
            raise self._translate_exception(e) from e

    async def cancel_mission_wakeups(self, mission_id: UUID) -> None:
        try:
            stmt = (
                update(WakeupRecordORM)
                .where(and_(WakeupRecordORM.mission_id == mission_id, WakeupRecordORM.status == "PENDING"))
                .values(status="CANCELLED")
            )
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            raise self._translate_exception(e) from e


class MissionCheckpointRepository(BaseRepository[MissionCheckpointORM]):
    """Manages canonical logical recovery summaries (M7 Section 86)."""

    async def save_checkpoint(self, cp: MissionCheckpoint) -> MissionCheckpointORM:
        try:
            digest = cp.checkpoint_digest or cp.calculate_digest()
            orm = MissionCheckpointORM(
                checkpoint_id=cp.checkpoint_id,
                mission_id=cp.mission_id,
                mission_version=cp.mission_version,
                plan_id=cp.plan_id,
                plan_version=cp.plan_version,
                completed_criteria=cp.completed_criteria,
                task_state_digest=cp.task_state_digest,
                progress_digest=cp.progress_digest,
                blackboard_digest=cp.blackboard_digest,
                commitment_digest=cp.commitment_digest,
                dependency_digest=cp.dependency_digest,
                budget_state=cp.budget_state.value if hasattr(cp.budget_state, "value") else str(cp.budget_state),
                open_escalations=cp.open_escalations,
                open_wakeups=cp.open_wakeups,
                created_at=cp.created_at,
                checkpoint_digest=digest,
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def get_latest_checkpoint(self, mission_id: UUID) -> Optional[MissionCheckpointORM]:
        try:
            stmt = select(MissionCheckpointORM).where(MissionCheckpointORM.mission_id == mission_id).order_by(MissionCheckpointORM.created_at.desc()).limit(1)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            raise self._translate_exception(e) from e


class EscalationRepository(BaseRepository[EscalationORM]):
    """Manages operator escalations (M7 Sections 76-79)."""

    async def create_escalation(
        self,
        mission_id: UUID,
        reason: str,
        required_operator_action: str,
        severity: str = "HIGH",
        evidence_refs: Optional[List[str]] = None,
    ) -> EscalationORM:
        try:
            orm = EscalationORM(
                escalation_id=UUID(int=datetime.now(timezone.utc).microsecond or 1),
                mission_id=mission_id,
                severity=severity,
                reason=reason,
                required_operator_action=required_operator_action,
                evidence_refs=evidence_refs or [],
                created_at=datetime.now(timezone.utc),
                status="OPEN",
            )
            self.session.add(orm)
            await self.session.flush()
            return orm
        except Exception as e:
            raise self._translate_exception(e) from e

    async def resolve_escalation(self, escalation_id: UUID) -> None:
        try:
            stmt = (
                update(EscalationORM)
                .where(EscalationORM.escalation_id == escalation_id)
                .values(status="RESOLVED", resolved_at=datetime.now(timezone.utc))
            )
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            raise self._translate_exception(e) from e

    async def list_open_escalations(self, mission_id: UUID) -> List[EscalationORM]:
        try:
            stmt = select(EscalationORM).where(
                and_(EscalationORM.mission_id == mission_id, EscalationORM.status == "OPEN")
            )
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as e:
            raise self._translate_exception(e) from e


class LoopFingerprintRepository(BaseRepository[LoopFingerprintORM]):
    """Persisted anti-loop fingerprint tracking across restarts (M7 Section 48)."""

    async def record_fingerprint(self, mission_id: UUID, task_id: UUID, fingerprint_hash: str) -> int:
        try:
            now = datetime.now(timezone.utc)
            stmt = select(LoopFingerprintORM).where(
                and_(
                    LoopFingerprintORM.mission_id == mission_id,
                    LoopFingerprintORM.task_id == task_id,
                    LoopFingerprintORM.fingerprint_hash == fingerprint_hash,
                )
            )
            res = await self.session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                existing.occurrence_count += 1
                existing.last_seen_at = now
                await self.session.flush()
                return existing.occurrence_count
            else:
                orm = LoopFingerprintORM(
                    fingerprint_id=UUID(int=now.microsecond or 1),
                    mission_id=mission_id,
                    task_id=task_id,
                    fingerprint_hash=fingerprint_hash,
                    occurrence_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                self.session.add(orm)
                await self.session.flush()
                return 1
        except Exception as e:
            raise self._translate_exception(e) from e
