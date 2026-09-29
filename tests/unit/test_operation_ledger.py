from pathlib import Path
from uuid import uuid4

import pytest

from universal_brain.engineering.recovery_experiments import _research_contract
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.errors import OperationOutcomeUncertainError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass
from universal_brain.tools.base import BaseTool, ReversibilityClass, ToolResult
from universal_brain.tools.gateway import ToolGateway
from universal_brain.tools.operation_ledger import (
    DurableOperationLedger,
    OperationLedgerError,
    OperationState,
)


class _UnknownOutcomeTool(BaseTool):
    name = "unknown_outcome"
    action_class = ActionClass.A1
    description = "Research tool that cannot reconcile an interrupted execution"
    reversibility_class = ReversibilityClass.VERIFIED_REVERSIBLE

    def __init__(self, target: Path) -> None:
        self.target = target
        self.execute_calls = 0

    def preflight_check(self, args):
        return args.get("target") == str(self.target)

    def execute(self, args):
        self.execute_calls += 1
        raise RuntimeError("injected uncertain execution failure")

    def rollback(self, rollback_data):
        return True


def test_operation_ledger_rejects_idempotency_reuse_for_different_request(tmp_path):
    ledger = DurableOperationLedger(tmp_path / "operations.sqlite3")
    project_id = uuid4()
    task_id = uuid4()

    first = ledger.prepare(
        project_id=project_id,
        task_id=task_id,
        tool_name="write",
        target_resource="a.txt",
        idempotency_key="same-key",
        request_digest="digest-a",
    )
    assert first.state == OperationState.PREPARED

    with pytest.raises(OperationLedgerError, match="different canonical request"):
        ledger.prepare(
            project_id=project_id,
            task_id=task_id,
            tool_name="write",
            target_resource="a.txt",
            idempotency_key="same-key",
            request_digest="digest-b",
        )


def test_unknown_interrupted_outcome_fails_closed_without_replay(tmp_path):
    target = tmp_path / "effect.txt"
    ledger = DurableOperationLedger(tmp_path / "operations.sqlite3")
    capability = CapabilityService()
    tool = _UnknownOutcomeTool(target)
    gateway = ToolGateway(
        event_store=EventStore(),
        capability_service=capability,
        operation_ledger=ledger,
    )
    gateway.register_tool(tool)

    contract = _research_contract()
    project_id = uuid4()
    task_id = uuid4()
    operation_id = "unknown-recovery-case"
    token = capability.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource=str(target),
        allowed_operations=[tool.name],
        idempotency_key=operation_id,
    )
    args = {"target": str(target)}

    with pytest.raises(RuntimeError, match="injected uncertain execution failure"):
        gateway.execute_tool(
            tool_name=tool.name,
            args=args,
            capability_token=token,
            contract=contract,
            target_resource=str(target),
        )

    assert tool.execute_calls == 1

    with pytest.raises(OperationOutcomeUncertainError, match="cannot be safely replayed"):
        gateway.execute_tool(
            tool_name=tool.name,
            args=args,
            capability_token=token,
            contract=contract,
            target_resource=str(target),
        )

    assert tool.execute_calls == 1

    operation_key = ledger.operation_id(
        project_id=project_id,
        task_id=task_id,
        tool_name=tool.name,
        idempotency_key=operation_id,
    )
    record = ledger.get(operation_key)
    assert record is not None
    assert record.state == OperationState.IN_DOUBT
