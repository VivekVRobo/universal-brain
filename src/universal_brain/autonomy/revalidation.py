"""
Universal Brain - Mission Revalidation & Contract Change Guard

Implements M7 Sections 73-75 and Invariant M7-INV-11:
- Detects material contract amendments;
- Enforces MISSION_REVALIDATION_REQUIRED barrier;
- Blocks consequential execution until revalidation succeeds.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.autonomy.errors import MissionContractChangedError
from universal_brain.autonomy.schemas import Mission, MissionStatus


class MissionRevalidationEngine:
    """Guards missions against running under obsolete or amended constitutional contracts."""

    @staticmethod
    def check_contract_alignment(
        mission: Mission,
        active_contract: AlignmentContract,
    ) -> bool:
        """
        Verifies that the mission's bound contract matches the authoritative active contract.
        Raises MissionContractChangedError if a divergence occurs (M7-INV-11).
        """
        if mission.contract_id != active_contract.contract_id:
            mission.status = MissionStatus.BLOCKED
            raise MissionContractChangedError(
                f"Contract divergence: mission {mission.mission_id} bound to contract {mission.contract_id}, but active is {active_contract.contract_id}."
            )

        if mission.contract_version != active_contract.version:
            # Material version change detected!
            mission.status = MissionStatus.BLOCKED
            raise MissionContractChangedError(
                f"MISSION_REVALIDATION_REQUIRED: mission {mission.mission_id} bound to contract v{mission.contract_version}, but active contract is v{active_contract.version}."
            )

        return True

    @staticmethod
    def revalidate_and_upgrade(
        mission: Mission,
        new_contract: AlignmentContract,
    ) -> Mission:
        """Revalidates mission against the new contract version and restores active status."""
        if mission.contract_id != new_contract.contract_id:
            raise MissionContractChangedError("Cannot revalidate against an unrelated contract ID.")

        mission.contract_version = new_contract.version
        mission.mission_version += 1
        if mission.status == MissionStatus.BLOCKED:
            mission.status = MissionStatus.ACTIVE
        return mission
