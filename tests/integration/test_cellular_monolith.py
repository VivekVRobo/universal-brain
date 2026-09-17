"""End-to-End Cellular Monolith Integration Test."""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    ActionClass,
    AlignmentContract,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.errors import HealthGateError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.memory.replicator import MemoryReplicator
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.tools.base import BaseTool, ToolResult
from universal_brain.tools.gateway import ToolGateway


class MockPatchTool(BaseTool):
    name = "patch_file"
    action_class = ActionClass.A1
    description = "Applies a reversible file patch"

    def preflight_check(self, args: dict) -> bool:
        return "patch_content" in args

    def execute(self, args: dict) -> ToolResult:
        return ToolResult(
            success=True,
            output="Applied patch cleanly to robot_controller.cpp",
            evidence={"diff_sha256": "3a7b9c1d2e...", "lines_changed": 12},
            rollback_data={"reverse_patch": "reverse diff content"},
        )

    def rollback(self, rollback_data: dict) -> bool:
        return True


def _active_contract() -> AlignmentContract:
    original = OriginalInput(exact_content_ref="User utterance: Build PID node")
    requirement = Requirement(
        requirement_id="REQ-01",
        statement="Write PID controller node",
        source_input_ids=[original.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="colcon test",
    )
    criterion = AcceptanceCriterion(
        criterion_id="AC-01",
        statement="Compiles cleanly with zero errors",
        evidence_type="build_log",
        verifier="deterministic",
    )
    return AlignmentContract.create_draft(
        objective="Humanoid PID Controller",
        requirements=[requirement],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[criterion],
        original_inputs=[original],
    ).activate()


def test_end_to_end_cellular_lifecycle():
    with TemporaryDirectory() as tmp_dir:
        journal_dir = Path(tmp_dir) / "journal"
        event_store = EventStore()
        capability_service = CapabilityService()
        replicator = MemoryReplicator(event_store=event_store, target_journal_dir=journal_dir)
        gateway = ToolGateway(
            event_store=event_store,
            capability_service=capability_service,
            retention_manager=StorageRetentionManager(critical_threshold_pct=99.9),
        )
        gateway.register_tool(MockPatchTool())

        contract = _active_contract()
        project_id = uuid4()
        task_id = uuid4()
        token = capability_service.issue_token(
            project_id=project_id,
            task_id=task_id,
            contract_id=contract.contract_id,
            contract_version=contract.version,
            action_class=ActionClass.A1,
            target_resource="./src/robot_controller.cpp",
            allowed_operations=["patch_file"],
        )
        result = gateway.execute_tool(
            tool_name="patch_file",
            args={"patch_content": "diff --git ..."},
            capability_token=token,
            contract=contract,
            target_resource="./src/robot_controller.cpp",
        )
        assert result.success is True
        assert "diff_sha256" in result.evidence
        assert event_store.event_count == 2
        assert event_store.verify_chain_integrity() is True

        events = event_store.get_all_events()
        assert events[0].event_type == EventType.TOOL_CALLED
        assert events[1].event_type == EventType.EVIDENCE_PRODUCED
        assert events[1].prev_event_hash == events[0].event_hash

        chunk_file = replicator.sync_outbox_batch()
        assert chunk_file is not None and chunk_file.exists()
        lines = [line.strip() for line in chunk_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 2
        assert events[0].event_hash in lines[0]
        assert events[1].event_hash in lines[1]


def test_disk_critical_halts_a1_write_aln014():
    from collections import namedtuple

    event_store = EventStore()
    capability_service = CapabilityService()
    DiskUsage = namedtuple("DiskUsage", "total used free")
    gateway = ToolGateway(
        event_store=event_store,
        capability_service=capability_service,
        retention_manager=StorageRetentionManager(
            critical_threshold_pct=90.0,
            disk_usage_provider=lambda _path: DiskUsage(total=100, used=95, free=5),
        ),
    )
    gateway.register_tool(MockPatchTool())
    contract = _active_contract()
    token = capability_service.issue_token(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=contract.contract_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="./src/robot_controller.cpp",
        allowed_operations=["patch_file"],
    )

    with pytest.raises(HealthGateError, match="Disk utilization is critical"):
        gateway.execute_tool(
            tool_name="patch_file",
            args={"patch_content": "diff"},
            capability_token=token,
            contract=contract,
            target_resource="./src/robot_controller.cpp",
        )
