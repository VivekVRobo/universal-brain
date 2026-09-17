"""S3 real-isolation and verified-rollback security regressions."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    ActionClass,
    AlignmentContract,
    ContractStatus,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.tools.base import BaseTool, ToolResult
from universal_brain.tools.gateway import ToolGateway
from universal_brain.tools.runner.tool import CommandRunnerTool
from universal_brain.tools.sandbox.file_tools import FileWriteTool
from universal_brain.tools.sandbox.manifests import hash_file
from universal_brain.tools.sandbox.workspace import WorkspaceTransactionManager
from universal_brain.tools.workers.queue import EphemeralJobQueue, FencedLeaseError
from universal_brain.tools.workers.schemas import JobStatus
from universal_brain.tools.workers.tool import CloudBatchDispatchTool


def _active_contract() -> AlignmentContract:
    original = OriginalInput(exact_content_ref="root4 security regression")
    requirement = Requirement(
        requirement_id="REQ-S3-R4",
        statement="Only verified reversible actions may report rollback completion",
        source_input_ids=[original.input_id],
        kind=RequirementKind.SAFETY,
        priority=RequirementPriority.MUST,
        verification_method="deterministic post-state verification",
    )
    return AlignmentContract.create_draft(
        objective="Root 4 isolation and rollback hardening",
        requirements=[requirement],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="AC-S3-R4",
                statement="Rollback claims require independently verified post-state",
                evidence_type="hash_or_state_probe",
                verifier="deterministic",
            )
        ],
        original_inputs=[original],
    ).activate()


class LyingRollbackTool(BaseTool):
    name = "lying_rollback"
    action_class = ActionClass.A1
    description = "Returns True from rollback without restoring state."

    def preflight_check(self, args: dict) -> bool:
        return True

    def execute(self, args: dict) -> ToolResult:
        return ToolResult(success=True, output="mutated")

    def rollback(self, rollback_data: dict) -> bool:
        return True


def test_gateway_never_records_rollback_executed_from_boolean_only():
    contract = _active_contract()
    capabilities = CapabilityService()
    store = EventStore()
    gateway = ToolGateway(store, capabilities)
    gateway.register_tool(LyingRollbackTool())

    token = capabilities.issue_token(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=contract.contract_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="*",
        allowed_operations=["rollback"],
    )

    assert gateway.rollback_tool(
        tool_name="lying_rollback",
        rollback_data={},
        capability_token=token,
        contract=contract,
    ) is False

    events = store.get_all_events()
    assert EventType.ROLLBACK_EXECUTED not in [event.event_type for event in events]
    failure = events[-1]
    assert failure.event_type == EventType.SYSTEM_FAILURE
    assert failure.payload["status"] == "ROLLBACK_UNVERIFIED"
    assert failure.payload["rollback_verified"] is False


def test_gateway_records_file_rollback_only_after_sha256_parity(tmp_path: Path):
    contract = _active_contract()
    project_id = uuid4()
    task_id = uuid4()
    target = tmp_path / "state.txt"
    target.write_text("pre-state", encoding="utf-8")
    pre_hash = hash_file(target)

    manager = WorkspaceTransactionManager(tmp_path, project_id, task_id)
    tool = FileWriteTool(manager)
    capabilities = CapabilityService()
    store = EventStore()
    gateway = ToolGateway(store, capabilities)
    gateway.register_tool(tool)

    token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="state.txt",
        allowed_operations=["write_file", "rollback"],
    )

    result = gateway.execute_tool(
        tool_name="write_file",
        args={"target": "state.txt", "content": "mutated"},
        capability_token=token,
        contract=contract,
        target_resource="state.txt",
    )
    assert result.success is True
    assert hash_file(target) != pre_hash

    assert gateway.rollback_tool(
        tool_name="write_file",
        rollback_data=result.rollback_data or {},
        capability_token=token,
        contract=contract,
        original_call_event_id=None,
    ) is True

    assert target.read_text(encoding="utf-8") == "pre-state"
    assert hash_file(target) == pre_hash
    rollback_events = [
        event for event in store.get_all_events()
        if event.event_type == EventType.ROLLBACK_EXECUTED
    ]
    assert len(rollback_events) == 1
    assert rollback_events[0].payload["rollback_verified"] is True


def test_signed_rollback_grant_recovers_after_forward_contract_closes(tmp_path: Path):
    contract = _active_contract()
    project_id = uuid4()
    task_id = uuid4()
    target = tmp_path / "recover.txt"
    target.write_text("before", encoding="utf-8")
    pre_hash = hash_file(target)

    manager = WorkspaceTransactionManager(tmp_path, project_id, task_id)
    tool = FileWriteTool(manager)
    capabilities = CapabilityService()
    store = EventStore()
    gateway = ToolGateway(store, capabilities)
    gateway.register_tool(tool)

    forward_token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="recover.txt",
        allowed_operations=["write_file"],
    )
    result = gateway.execute_tool(
        tool_name="write_file",
        args={"target": "recover.txt", "content": "after"},
        capability_token=forward_token,
        contract=contract,
        target_resource="recover.txt",
    )
    assert result.success is True

    grant = capabilities.issue_rollback_grant(
        project_id=project_id,
        task_id=task_id,
        action_id=uuid4(),
        tool_name="write_file",
        target_resource="recover.txt",
        pre_state_hash=pre_hash,
    )
    closed_contract = contract.model_copy(update={"status": ContractStatus.CLOSED})

    assert gateway.rollback_tool(
        tool_name="write_file",
        rollback_data=result.rollback_data or {},
        capability_token=grant,
        contract=closed_contract,
    ) is True
    assert hash_file(target) == pre_hash


def test_rollback_grant_pre_state_hash_must_match_checkpoint(tmp_path: Path):
    contract = _active_contract()
    project_id = uuid4()
    task_id = uuid4()
    target = tmp_path / "bound.txt"
    target.write_text("before", encoding="utf-8")

    manager = WorkspaceTransactionManager(tmp_path, project_id, task_id)
    tool = FileWriteTool(manager)
    capabilities = CapabilityService()
    gateway = ToolGateway(EventStore(), capabilities)
    gateway.register_tool(tool)

    forward_token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="bound.txt",
        allowed_operations=["write_file"],
    )
    result = gateway.execute_tool(
        tool_name="write_file",
        args={"target": "bound.txt", "content": "after"},
        capability_token=forward_token,
        contract=contract,
        target_resource="bound.txt",
    )
    forged_scope_grant = capabilities.issue_rollback_grant(
        project_id=project_id,
        task_id=task_id,
        action_id=uuid4(),
        tool_name="write_file",
        target_resource="bound.txt",
        pre_state_hash="0" * 64,
    )
    with pytest.raises(Exception, match="pre-state hash"):
        gateway.rollback_tool(
            tool_name="write_file",
            rollback_data=result.rollback_data or {},
            capability_token=forged_scope_grant,
            contract=contract,
        )


def test_command_runner_requires_real_compensation_and_separate_verification(tmp_path: Path):
    target = tmp_path / "command-state.txt"
    target.write_text("mutated", encoding="utf-8")
    tool = CommandRunnerTool(tmp_path)

    rollback_data = {
        "compensation_command": [
            "python",
            "-c",
            "from pathlib import Path; Path('command-state.txt').write_text('restored', encoding='utf-8')",
        ],
        "verification_command": [
            "python",
            "-c",
            "from pathlib import Path; raise SystemExit(0 if Path('command-state.txt').read_text(encoding='utf-8') == 'restored' else 7)",
        ],
        "cwd": str(tmp_path),
        "timeout_seconds": 10,
    }

    assert tool.rollback(rollback_data) is True
    assert target.read_text(encoding="utf-8") == "restored"
    assert tool.verify_rollback(rollback_data) is True
    assert tool.rollback({"checkpoint": "fake"}) is False


def test_cloud_job_rollback_cancels_and_fences_active_lease():
    queue = EphemeralJobQueue()
    tool = CloudBatchDispatchTool(queue)
    project_id = uuid4()
    task_id = uuid4()

    result = tool.execute(
        {
            "project_id": str(project_id),
            "task_id": str(task_id),
            "job_type": "simulation_run",
            "payload": {"steps": 10},
        }
    )
    job_id = result.evidence["job_id"]
    queue.register_worker("worker-a", "local_gpu")
    worker = queue._workers["worker-a"]
    leased = queue.poll_and_lease("worker-a", worker.worker_session_id)
    assert leased is not None
    job, lease = leased
    assert str(job.job_id) == job_id

    assert tool.rollback(result.rollback_data or {}) is True
    assert tool.verify_rollback(result.rollback_data or {}) is True
    assert job.status == JobStatus.CANCELLED
    assert job.current_lease is not None and job.current_lease.is_fenced

    with pytest.raises(FencedLeaseError):
        queue.complete_job(
            job.job_id,
            "worker-a",
            lease.lease_generation,
            {"forged_after_cancel": True},
        )
