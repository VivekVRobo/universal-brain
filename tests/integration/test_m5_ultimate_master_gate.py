"""Universal Brain - Milestone M5 Ultimate Master Gate Verification."""

from datetime import datetime, timedelta, timezone
import shutil
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from universal_brain.alignment.contract import ActionClass
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.tools.base import ReversibilityClass
from universal_brain.tools.gateway import ToolGateway
from universal_brain.tools.runner.tool import CommandRunnerTool
from universal_brain.tools.sandbox.file_tools import FilePatchTool, FileWriteTool
from universal_brain.tools.sandbox.manifests import hash_file
from universal_brain.tools.sandbox.workspace import WorkspaceTransactionManager
from universal_brain.tools.workers.queue import EphemeralJobQueue, FencedLeaseError
from universal_brain.tools.workers.tool import CloudBatchDispatchTool


def test_ultimate_m5_master_gate():
    temp_dir = tempfile.mkdtemp(prefix="brain_m5_gate_")
    workspace = Path(temp_dir).resolve()
    try:
        project_id = uuid4()
        task_id = uuid4()
        event_store = EventStore()
        capability_service = CapabilityService()
        from universal_brain.executive.budget import BudgetGatekeeper

        gateway = ToolGateway(
            event_store=event_store,
            capability_service=capability_service,
            budget_gatekeeper=BudgetGatekeeper(monthly_budget_usd=50.0),
            retention_manager=StorageRetentionManager(critical_threshold_pct=99.9),
        )
        transaction_manager = WorkspaceTransactionManager(workspace, project_id, task_id)
        job_queue = EphemeralJobQueue()
        patch_tool = FilePatchTool(transaction_manager)
        gateway.register_tool(FileWriteTool(transaction_manager))
        gateway.register_tool(patch_tool)
        gateway.register_tool(CommandRunnerTool(workspace))
        gateway.register_tool(CloudBatchDispatchTool(job_queue))

        target = workspace / "controller.cpp"
        target_rel = "controller.cpp"
        initial_content = "// ROS 2 Humble Controller Baseline\nvoid update() {\n    double kp = 1.0;\n}\n"
        target.write_text(initial_content, encoding="utf-8")
        baseline_sha = hash_file(target)

        from universal_brain.executive.intent import IntentParser

        parser = IntentParser()
        contract = parser.propose_contract(
            parser.parse_intent("Deploy High-Precision PID Controller\n1. Must pass 100% tests")
        )

        mutation_token = capability_service.issue_token(
            project_id=project_id,
            task_id=task_id,
            contract_id=contract.contract_id,
            contract_version=contract.version,
            action_class=ActionClass.A1,
            target_resource=target_rel,
            allowed_operations=["write_file", "patch_file", "run_command", "cloud_batch_dispatch"],
        )

        new_content = "// ROS 2 Humble Controller Baseline\nvoid update() {\n    double kp = 4.2;\n    double kd = 0.5;\n}\n"
        assert patch_tool.preflight_check({"target": target_rel, "new_content": new_content}) is True
        patch_result = gateway.execute_tool(
            tool_name="patch_file",
            args={"target": target_rel, "new_content": new_content},
            capability_token=mutation_token,
            contract=contract,
            target_resource=target_rel,
        )
        assert patch_result.success is True
        assert patch_result.reversibility_class == ReversibilityClass.VERIFIED_REVERSIBLE
        assert hash_file(target) != baseline_sha

        command_token = capability_service.issue_token(
            project_id=project_id,
            task_id=task_id,
            contract_id=contract.contract_id,
            contract_version=contract.version,
            action_class=ActionClass.A1,
            target_resource="*",
            allowed_operations=["run_command"],
        )
        command_result = gateway.execute_tool(
            tool_name="run_command",
            args={"executable": "python", "arguments": ["-c", "print('PID test preflight: pass')"]},
            capability_token=command_token,
            contract=contract,
            target_resource="*",
        )
        assert command_result.success is True
        assert "PID test preflight: pass" in command_result.output

        batch_token = capability_service.issue_token(
            project_id=project_id,
            task_id=task_id,
            contract_id=contract.contract_id,
            contract_version=contract.version,
            action_class=ActionClass.A1,
            target_resource="simulation/gazebo",
            allowed_operations=["cloud_batch_dispatch"],
        )
        batch_result = gateway.execute_tool(
            tool_name="cloud_batch_dispatch",
            args={
                "project_id": str(project_id),
                "task_id": str(task_id),
                "job_type": "gazebo_sim",
                "payload": {"sim_steps": 5000},
            },
            capability_token=batch_token,
            contract=contract,
            target_resource="simulation/gazebo",
        )
        assert batch_result.success is True
        job_id = UUID(batch_result.evidence["job_id"])

        worker_a = "colab-worker-gpu-a"
        worker_b = "kaggle-worker-gpu-b"
        session_a = uuid4()
        session_b = uuid4()
        job_queue.register_worker(worker_a, "colab_t4", session_id=session_a)
        job_queue.register_worker(worker_b, "kaggle_p100", session_id=session_b)
        leased_a = job_queue.poll_and_lease(worker_a, session_a, lease_duration_seconds=5)
        assert leased_a is not None
        _, lease_a = leased_a
        job_queue.record_progress(job_id, worker_a, lease_a.lease_generation, sequence=1, progress_pct=50.0)
        job_queue.reap_stale_leases(current_time=datetime.now(timezone.utc) + timedelta(seconds=15))
        leased_b = job_queue.poll_and_lease(worker_b, session_b)
        assert leased_b is not None
        _, lease_b = leased_b
        assert lease_b.lease_generation == 2

        with pytest.raises(FencedLeaseError):
            job_queue.complete_job(job_id, worker_a, lease_a.lease_generation, {"frames": 5000})
        completed = job_queue.complete_job(
            job_id,
            worker_b,
            lease_b.lease_generation,
            {"sim_passed": False, "collision": True},
        )
        assert completed.status == "COMPLETED"

        assert gateway.rollback_tool(
            tool_name="patch_file",
            rollback_data=patch_result.rollback_data,
            capability_token=mutation_token,
            contract=contract,
        ) is True
        assert hash_file(target) == baseline_sha
        assert target.read_text(encoding="utf-8") == initial_content

        event_types = [event.event_type for event in event_store.get_all_events()]
        assert EventType.TOOL_CALLED in event_types
        assert EventType.EVIDENCE_PRODUCED in event_types
        assert EventType.ROLLBACK_EXECUTED in event_types
        assert event_store.verify_chain_integrity() is True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
