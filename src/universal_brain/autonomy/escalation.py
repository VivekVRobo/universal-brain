"""
Universal Brain - Mission Escalation Engine

Implements M7 Sections 76-79:
- Formally registers blocking situations requiring human operator action;
- Deduplicates equivalent unresolved escalation fingerprints (M7 Section 79);
- Manages escalation lifecycles without spamming the operator.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.schemas import EscalationRecord, EscalationStatus


class EscalationEngine:
    """Manages formal operator escalations with deduplication."""

    def __init__(self) -> None:
        self._escalations: Dict[UUID, EscalationRecord] = {}
        self._fingerprints: Dict[str, UUID] = {}

    def escalate(
        self,
        mission_id: UUID,
        reason: str,
        required_operator_action: str,
        severity: str = "HIGH",
        evidence_refs: Optional[List[str]] = None,
    ) -> EscalationRecord:
        """
        Creates an operator escalation envelope. Deduplicates if an identical open escalation exists.
        """
        fp = hashlib.sha256(f"{mission_id}:{reason.strip().lower()}".encode("utf-8")).hexdigest()
        existing_id = self._fingerprints.get(fp)
        if existing_id:
            existing = self._escalations.get(existing_id)
            if existing and existing.status == EscalationStatus.OPEN:
                return existing

        esc = EscalationRecord(
            mission_id=mission_id,
            severity=severity,
            reason=reason,
            required_operator_action=required_operator_action,
            evidence_refs=evidence_refs or [],
            created_at=datetime.now(timezone.utc),
            status=EscalationStatus.OPEN,
        )
        self._escalations[esc.escalation_id] = esc
        self._fingerprints[fp] = esc.escalation_id
        return esc

    def resolve(self, escalation_id: UUID, resolution_notes: str = "") -> EscalationRecord:
        """Marks an escalation as RESOLVED by the operator."""
        esc = self._escalations.get(escalation_id)
        if not esc:
            raise KeyError(f"Escalation {escalation_id} not found.")

        esc.status = EscalationStatus.RESOLVED
        esc.resolved_at = datetime.now(timezone.utc)
        return esc

    def list_open_escalations(self, mission_id: UUID) -> List[EscalationRecord]:
        return [
            e for e in self._escalations.values()
            if e.mission_id == mission_id and e.status == EscalationStatus.OPEN
        ]
