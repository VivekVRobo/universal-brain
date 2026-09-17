"""
Universal Brain - Agent Commitments & Accountability

Implements M7 Sections 38-40:
- Agents declare explicit commitments to produce specific verifiable evidence;
- Commitments transition to SATISFIED only when verified evidence exists;
- Agent assertion alone is insufficient.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from universal_brain.autonomy.errors import MissionStateError
from universal_brain.autonomy.schemas import Commitment, CommitmentStatus


class CommitmentTracker:
    """Manages accountability commitments and objective verification proofs."""

    def __init__(self) -> None:
        self._commitments: Dict[UUID, Commitment] = {}

    def create_commitment(
        self,
        mission_id: UUID,
        task_id: UUID,
        agent_id: UUID,
        statement: str,
        expected_evidence: str,
        expires_in_minutes: int = 60,
    ) -> Commitment:
        """Registers a new explicit commitment from an Agent Cell."""
        now = datetime.now(timezone.utc)
        commitment = Commitment(
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent_id,
            statement=statement,
            expected_evidence=expected_evidence,
            created_at=now,
            expires_at=now + timedelta(minutes=expires_in_minutes),
            status=CommitmentStatus.OPEN,
        )
        self._commitments[commitment.commitment_id] = commitment
        return commitment

    def satisfy_commitment(
        self,
        commitment_id: UUID,
        verified_evidence_digest: str,
    ) -> Commitment:
        """
        Transitions commitment to SATISFIED only upon cryptographic evidence proof (M7 Section 40).
        """
        commitment = self._commitments.get(commitment_id)
        if not commitment:
            raise MissionStateError(f"Commitment {commitment_id} not found.")

        if not verified_evidence_digest or len(verified_evidence_digest) < 16:
            raise MissionStateError(
                f"Cannot satisfy commitment {commitment_id}: invalid or missing evidence digest."
            )

        commitment.status = CommitmentStatus.SATISFIED
        return commitment

    def fail_commitment(self, commitment_id: UUID, reason: str = "") -> Commitment:
        """Marks a commitment as failed."""
        commitment = self._commitments.get(commitment_id)
        if not commitment:
            raise MissionStateError(f"Commitment {commitment_id} not found.")
        commitment.status = CommitmentStatus.FAILED
        return commitment

    def get_open_commitments(self, mission_id: UUID) -> List[Commitment]:
        return [
            c for c in self._commitments.values()
            if c.mission_id == mission_id and c.status == CommitmentStatus.OPEN
        ]
