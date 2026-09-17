"""
End-to-End Cellular Monolith Integration Test

Simulates an entire end-to-end execution loop across all interconnected cells:
1. Alignment Engine activates an Alignment Contract.
2. Capability Service issues a scoped A1 Capability Token.
3. Tool Gateway validates token, budget, storage, and preflight reversibility.
4. Tool executes, producing deterministic evidence.
5. Event Store records TOOL_CALLED and EVIDENCE_PRODUCED with tamper-evident hash chaining.
6. Memory Replicator drains the outbox into a chunked micro-batch journal file.
7. Verification asserts 100% cryptographic hash integrity across the full lifecycle.
"""

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
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType, RelationType
from universal_brain.memory.replicator import MemoryReplicator
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.kernel.errors import HealthGateError
from universal_brain.tools.base import BaseTool, ToolResult
from universal_brain.tools.gateway import ToolGateway


class MockPatchTool(BaseTool):
    """Simulates a reversible file patch tool (A1)."""

    name = "patch_file"
    action_class = ActionClass.A1
    description = "Applies a reversible file patch"

    def preflight_check(self, args: dict) -> bool:
        # Asserts preflight dry-run passes (ADR-0008)
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


def test_end_to_end_cellular_lifecycle():
    """Validates that all cellular modules operate in lockstep without friction."""
    with TemporaryDirectory() as tmp_dir:
        journal_dir = Path(tmp_dir) / "journal"

        # 1. Initialize System Services
        event_store = EventStore()
        capability_service = CapabilityService()
        replicator = MemoryReplicator(event_store=event_store, target_journal_dir=journal_dir)
        retention = StorageRetentionManager(critical_threshold_pct=99.9)
        gateway = ToolGateway(
            event_store=event_store,
            capability_service=capability_service,
            retention_manager=retention,
        )

        # Register tool
        tool = MockPatchTool()
        gateway.register_tool(tool)

        # 2. Alignment Subsystem: Create & Activate Contract
        project_id = uuid4()
        user_input = OriginalInput(exact_content_ref="User utterance: Build PID node")
        req = Requirement(
            requirement_id="REQ-01",
            statement="Write PID controller node",
            source_input_ids=[user_input.input_id],
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            verification_method="colcon test",
        )
        perm = PermissionsCeiling(action_ceiling=ActionClass.A1)
        crit = AcceptanceCriterion(
            criterion_id="AC-01",
            statement="Compiles cleanly with zero errors",
            evidence_type="build_log",
            verifier="deterministic",
        )

        draft = AlignmentContract.create_draft(
            objective="Humanoid PID Controller",
            requirements=[req],
            permissions=perm,
            acceptance_criteria=[crit],
            original_inputs=[user_input],
        )
        active_contract = draft.activate()
        assert active_contract.status == "active"

        # 3. Kernel Subsystem: Issue Capability Token for Task
        task_id = uuid4()
        token = capability_service.issue_token(
            project_id=project_id,
            task_id=task_id,
            contract_version=active_contract.version,
            action_class=ActionClass.A1,
            target_resource="./src/robot_controller.cpp",
            allowed_operations=["patch_file"],
        )

        # 4. Tools Subsystem: Execute Tool via Gateway
        result = gateway.execute_tool(
            tool_name="patch_file",
            args={"patch_content": "diff --git ..."},
            capability_token=token,
            contract=active_contract,
            target_resource="./src/robot_controller.cpp",
        )
        assert result.success is True
        assert "diff_sha256" in result.evidence

        # 5. Kernel Subsystem: Verify Event Chain Integrity (ALN-016)
        assert event_store.event_count == 2  # TOOL_CALLED and EVIDENCE_PRODUCED
        assert event_store.verify_chain_integrity() is True

        events = event_store.get_all_events()
        tool_call_event = events[0]
        evidence_event = events[1]

        assert tool_call_event.event_type == EventType.TOOL_CALLED
        assert evidence_event.event_type == EventType.EVIDENCE_PRODUCED
        assert evidence_event.prev_event_hash == tool_call_event.event_hash

        # 6. Memory Subsystem: Sync Outbox to Micro-batch Chunk File
        chunk_file = replicator.sync_outbox_batch()
        assert chunk_file is not None
        assert chunk_file.exists()

        # Read back chunked file lines and verify content
        with open(chunk_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        assert len(lines) == 2
        assert tool_call_event.event_hash in lines[0]
        assert evidence_event.event_hash in lines[1]


def test_disk_critical_halts_a1_write_aln014():
    """Verify that ALN-014 fail-closed gate blocks A1 writes when disk is critical."""
    event_store = EventStore()
    capability_service = CapabilityService()
    # Hermetic disk fixture: the test must not depend on host/container utilization.
    from collections import namedtuple
    DiskUsage = namedtuple("DiskUsage", "total used free")
    critical_retention = StorageRetentionManager(
        critical_threshold_pct=90.0,
        disk_usage_provider=lambda _path: DiskUsage(total=100, used=95, free=5),
    )
    gateway = ToolGateway(
        event_store=event_store,
        capability_service=capability_service,
        retention_manager=critical_retention,
    )

    tool = MockPatchTool()
    gateway.register_tool(tool)

    # Setup contract and token
    user_input = OriginalInput(exact_content_ref="Prompt")
    req = Requirement(
        requirement_id="REQ-01",
        statement="Node",
        source_input_ids=[user_input.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="test",
    )
    perm = PermissionsCeiling(action_ceiling=ActionClass.A1)
    crit = AcceptanceCriterion(criterion_id="AC-01", statement="Pass", evidence_type="log", verifier="det")
    active_contract = AlignmentContract.create_draft(
        objective="PID",
        requirements=[req],
        permissions=perm,
        acceptance_criteria=[crit],
        original_inputs=[user_input],
    ).activate()

    token = capability_service.issue_token(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_version=1,
        action_class=ActionClass.A1,
        target_resource="./src/robot_controller.cpp",
        allowed_operations=["patch_file"],
    )

    with pytest.raises(HealthGateError, match="Disk utilization is critical"):
        gateway.execute_tool(
            tool_name="patch_file",
            args={"patch_content": "diff"},
            capability_token=token,
            contract=active_contract,
            target_resource="./src/robot_controller.cpp",
        )

