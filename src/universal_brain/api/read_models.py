"""Truthful CQRS read-model derivation from canonical runtime state.

This module deliberately does not manufacture demo state. A value is returned
only when it can be derived from EventStore/action state that the runtime
actually holds. Missing evidence is represented as None/UNKNOWN.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from universal_brain.alignment.contract import AlignmentContract, ContractStatus
from universal_brain.autonomy.schemas import Mission
from universal_brain.api.schemas import InvariantItem
from universal_brain.kernel.errors import HashChainTamperError
from universal_brain.kernel.events import EventEnvelope, EventType
from universal_brain.kernel.event_store import EventStore


_CONTRACT_EVENTS = {EventType.CONTRACT_CREATED, EventType.CONTRACT_UPDATED}

_MISSION_EVENTS = {
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


def latest_mission(event_store: EventStore, mission_id: UUID) -> Mission | None:
    """Return the latest fully materialized mission snapshot from canonical events."""
    for event in reversed(event_store.get_all_events()):
        if event.event_type not in _MISSION_EVENTS:
            continue
        raw = (event.payload or {}).get("mission")
        if not isinstance(raw, dict):
            continue
        try:
            mission = Mission.model_validate(raw)
        except Exception:
            continue
        if mission.mission_id == mission_id:
            return mission
    return None


def _contract_from_event(event: EventEnvelope) -> AlignmentContract | None:
    payload = event.payload or {}
    raw = payload.get("contract")
    if not isinstance(raw, dict):
        return None
    try:
        return AlignmentContract.model_validate(raw)
    except Exception:
        return None


def latest_active_contract(
    event_store: EventStore,
    *,
    project_id: UUID | None = None,
) -> tuple[AlignmentContract, datetime] | None:
    """Return the newest fully materialized active contract in canonical events."""
    for event in reversed(event_store.get_all_events()):
        if event.event_type not in _CONTRACT_EVENTS:
            continue
        if project_id is not None and event.project_id != project_id:
            continue
        contract = _contract_from_event(event)
        if contract is not None and contract.status == ContractStatus.ACTIVE:
            return contract, event.timestamp
    return None


def observed_contract_version(
    event_store: EventStore,
    *,
    project_id: UUID | None = None,
) -> int | None:
    """Return the highest contract version actually observed in canonical events."""
    versions: list[int] = []
    for event in event_store.get_all_events():
        if event.event_type not in _CONTRACT_EVENTS:
            continue
        if project_id is not None and event.project_id != project_id:
            continue
        contract = _contract_from_event(event)
        if contract is not None:
            versions.append(contract.version)
            continue
        raw_version = (event.payload or {}).get("version")
        if isinstance(raw_version, int):
            versions.append(raw_version)
        elif isinstance(event.contract_version, int):
            versions.append(event.contract_version)
    return max(versions) if versions else None


def latest_model_identity(event_store: EventStore) -> str | None:
    """Return a model identity only when a canonical model-selection event records it."""
    for event in reversed(event_store.get_all_events()):
        if event.event_type != EventType.MODEL_SELECTED:
            continue
        payload = event.payload or {}
        for key in ("model_id", "model", "selected_model"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def project_observations(event_store: EventStore) -> dict[UUID, dict[str, Any]]:
    """Aggregate project metadata conservatively from canonical events."""
    grouped: dict[UUID, list[EventEnvelope]] = defaultdict(list)
    for event in event_store.get_all_events():
        if event.project_id is not None:
            grouped[event.project_id].append(event)

    observations: dict[UUID, dict[str, Any]] = {}
    for project_id, events in grouped.items():
        events = sorted(events, key=lambda item: item.timestamp)
        full_contract = latest_active_contract(event_store, project_id=project_id)
        title: str | None = full_contract[0].objective if full_contract else None

        if not title:
            for event in reversed(events):
                payload = event.payload or {}
                if event.event_type == EventType.INTENT_PARSED:
                    candidate = payload.get("primary_goal") or payload.get("goal")
                    if isinstance(candidate, str) and candidate.strip():
                        title = candidate.strip()
                        break
                if event.event_type == EventType.USER_INPUT:
                    utterance = payload.get("utterance") or payload.get("query")
                    if isinstance(utterance, str) and utterance.strip():
                        title = utterance.strip().splitlines()[0][:120]
                        break

        task_ids = {
            event.task_id
            for event in events
            if event.event_type == EventType.TASK_ASSIGNED and event.task_id is not None
        }
        observations[project_id] = {
            "title": title or f"Project {str(project_id)[:8]}",
            "status": full_contract[0].status.value if full_contract else "observed",
            "current_contract_version": observed_contract_version(
                event_store, project_id=project_id
            ),
            "created_at": events[0].timestamp,
            # Assignment count is observable; liveness/completion is not.
            "observed_task_assignments": len(task_ids),
        }
    return observations


_INVARIANT_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("ALN-001", "Requirement Provenance", "Tasks must cite at least one input requirement"),
    (
        "ALN-004a",
        "Deterministic Ambiguity Taxonomy",
        "High-impact ambiguity blocks execution until clarified",
    ),
    (
        "ALN-006",
        "Constraint Preservation Gate",
        "Explicit constraints cannot be silently weakened",
    ),
    (
        "ALN-008",
        "Capability Authority Gate",
        "State-changing tools require fresh scoped capability authority",
    ),
    (
        "ALN-010",
        "Completion Evidence Rule",
        "Completion requires acceptance criteria and deterministic proof",
    ),
    (
        "ALN-014",
        "Health Gatekeeper",
        "Critical health/storage state disables unsafe writes",
    ),
    (
        "ALN-016",
        "Tamper-Evident Hash Chain",
        "Canonical events preserve cryptographic hash-chain integrity",
    ),
    (
        "ALN-018",
        "Actuator Deny Rule",
        "Physical actuator control remains subject to consequential-action policy",
    ),
    (
        "ALN-021",
        "Total Awareness Causal DAG",
        "State changes preserve causal lineage",
    ),
)


def evaluate_runtime_invariants(event_store: EventStore) -> list[InvariantItem]:
    """Return only runtime-verifiable invariant status; otherwise UNKNOWN.

    Static unit tests are not runtime proofs. The console therefore does not turn
    implementation coverage into a live PASS claim.
    """
    now = datetime.now(timezone.utc)
    statuses: dict[str, tuple[str, int]] = {}

    if event_store.event_count == 0:
        statuses["ALN-016"] = ("UNKNOWN", 0)
    else:
        try:
            event_store.verify_chain_integrity()
            statuses["ALN-016"] = ("PASS", event_store.event_count)
        except HashChainTamperError:
            statuses["ALN-016"] = ("FAIL", event_store.event_count)

    return [
        InvariantItem(
            invariant_id=invariant_id,
            name=name,
            description=description,
            status=statuses.get(invariant_id, ("UNKNOWN", 0))[0],
            proofs_count=statuses.get(invariant_id, ("UNKNOWN", 0))[1],
            last_evaluated_at=now,
        )
        for invariant_id, name, description in _INVARIANT_CATALOG
    ]
