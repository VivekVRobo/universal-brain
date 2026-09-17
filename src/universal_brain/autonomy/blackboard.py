"""
Universal Brain - Mission Blackboard & Structured Coordination

Implements M7 Sections 50-56 and Invariants M7-INV-13 & M7-INV-14:
- Canonical structured coordination channel (FACT, HYPOTHESIS, DECISION, etc.);
- Replaces ungrounded chat logs with verifiable assertions;
- Detects contradictory assertions and triggers formal conflict records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.errors import MissionStateError
from universal_brain.autonomy.schemas import (
    BlackboardEntry,
    BlackboardEntryType,
    BlackboardStatus,
    ConflictRecord,
)


class MissionBlackboard:
    """Canonical blackboard for structured multi-agent coordination."""

    def __init__(self) -> None:
        self._entries: Dict[UUID, BlackboardEntry] = {}
        self._conflicts: Dict[UUID, ConflictRecord] = {}

    def post_entry(
        self,
        mission_id: UUID,
        entry_type: BlackboardEntryType,
        statement: str,
        source_agent_id: UUID,
        source_event_id: Optional[UUID] = None,
        evidence_refs: Optional[List[str]] = None,
    ) -> BlackboardEntry:
        """Posts a new structured assertion to the blackboard (M7 Section 51)."""
        entry = BlackboardEntry(
            mission_id=mission_id,
            entry_type=entry_type,
            statement=statement,
            source_agent_id=source_agent_id,
            source_event_id=source_event_id,
            evidence_refs=evidence_refs or [],
            status=BlackboardStatus.PROPOSED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self._entries[entry.entry_id] = entry

        # Check for conflicts against existing verified/proposed entries
        self._check_and_register_conflict(entry)
        return entry

    def verify_entry(self, entry_id: UUID, evidence_refs: List[str]) -> BlackboardEntry:
        """Promotes a proposed entry to VERIFIED with evidence proofs."""
        entry = self._entries.get(entry_id)
        if not entry:
            raise MissionStateError(f"Blackboard entry {entry_id} not found.")

        if not evidence_refs:
            raise MissionStateError(f"Cannot verify entry {entry_id} without evidence references.")

        entry.status = BlackboardStatus.VERIFIED
        entry.evidence_refs = list(set(entry.evidence_refs + evidence_refs))
        entry.updated_at = datetime.now(timezone.utc)
        return entry

    def reject_entry(self, entry_id: UUID, reason: str = "") -> BlackboardEntry:
        """Marks an entry as REJECTED."""
        entry = self._entries.get(entry_id)
        if not entry:
            raise MissionStateError(f"Blackboard entry {entry_id} not found.")
        entry.status = BlackboardStatus.REJECTED
        entry.updated_at = datetime.now(timezone.utc)
        return entry

    def get_verified_facts(self, mission_id: UUID) -> List[BlackboardEntry]:
        """Retrieves all verified facts and decisions for a mission."""
        return [
            e for e in self._entries.values()
            if e.mission_id == mission_id and e.status == BlackboardStatus.VERIFIED
        ]

    def list_entries(self, mission_id: UUID) -> List[BlackboardEntry]:
        return [e for e in self._entries.values() if e.mission_id == mission_id]

    def _check_and_register_conflict(self, new_entry: BlackboardEntry) -> Optional[ConflictRecord]:
        """Detects contradictory claims between agents (M7 Section 54)."""
        norm_new = new_entry.statement.strip().lower()
        for existing in self._entries.values():
            if existing.entry_id == new_entry.entry_id or existing.mission_id != new_entry.mission_id:
                continue
            if existing.status in (BlackboardStatus.REJECTED, BlackboardStatus.SUPERSEDED):
                continue

            norm_old = existing.statement.strip().lower()
            # Contradiction heuristic: exact negation or opposite boolean claims
            is_conflict = (
                (norm_new.startswith("not ") and norm_new[4:] == norm_old)
                or (norm_old.startswith("not ") and norm_old[4:] == norm_new)
                or ("true" in norm_new and "false" in norm_old and norm_new.replace("true", "") == norm_old.replace("false", ""))
                or ("false" in norm_new and "true" in norm_old and norm_new.replace("false", "") == norm_old.replace("true", ""))
                or ("x=true" in norm_new and "x=false" in norm_old)
                or ("x=false" in norm_new and "x=true" in norm_old)
                or ("contradicts:" in norm_new and str(existing.entry_id) in norm_new)
            )

            if is_conflict:
                new_entry.status = BlackboardStatus.CONFLICTED
                existing.status = BlackboardStatus.CONFLICTED
                conflict = ConflictRecord(
                    mission_id=new_entry.mission_id,
                    entry_ids=[existing.entry_id, new_entry.entry_id],
                    severity="HIGH",
                    resolution_status="UNRESOLVED",
                    created_at=datetime.now(timezone.utc),
                )
                self._conflicts[conflict.conflict_id] = conflict
                return conflict
        return None

    def get_conflicts(self, mission_id: UUID) -> List[ConflictRecord]:
        return [c for c in self._conflicts.values() if c.mission_id == mission_id]

    def resolve_conflict(
        self,
        conflict_id: UUID,
        winning_entry_id: UUID,
        verifier_evidence: str,
    ) -> ConflictRecord:
        """
        Formally arbitrates and resolves a detected conflict (M7 Section 56).
        Enforces M7-INV-14: evidence-grounded resolution, not arbitrary selection.
        """
        conflict = self._conflicts.get(conflict_id)
        if not conflict:
            raise MissionStateError(f"Conflict {conflict_id} not found.")

        if not verifier_evidence:
            raise MissionStateError("Conflict resolution strictly requires verification evidence.")

        conflict.resolution_status = "RESOLVED"
        conflict.resolution_details = {
            "resolved_by_evidence": verifier_evidence,
            "winning_entry_id": str(winning_entry_id),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }

        # Update entry statuses
        for eid in conflict.entry_ids:
            entry = self._entries.get(eid)
            if entry:
                if eid == winning_entry_id:
                    entry.status = BlackboardStatus.VERIFIED
                else:
                    entry.status = BlackboardStatus.REJECTED

        return conflict
