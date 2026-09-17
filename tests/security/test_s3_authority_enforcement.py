"""S3 authority-enforcement regression tests.

These tests exercise the final ToolGateway boundary rather than trusting upstream
callers to have performed alignment and capability checks correctly.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    AlignmentContract,
    Ambiguity,
    AmbiguityImpact,
    OriginalInput,
    PermissionsCeiling,
    Requirement,
    RequirementKind,
    RequirementPriority,
)
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.errors import ActionScopeViolationError, CapabilityDeniedError
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass
from universal_brain.tools.gateway import ToolGateway
from universal_brain.tools.sandbox.file_tools import FileWriteTool
from universal_brain.tools.sandbox.workspace import WorkspaceTransactionManager


def _contract(
    *,
    active: bool = True,
    high_blocked: bool = False,
    expires_at: datetime | None = None,
) -> AlignmentContract:
    original = OriginalInput(exact_content_ref="s3-authority-test")
    requirement = Requirement(
        requirement_id="REQ-S3-001",
        statement="Authority boundaries must fail closed.",
        source_input_ids=[original.input_id],
        kind=RequirementKind.SAFETY,
        priority=RequirementPriority.MUST,
        verification_method="security regression test",
    )
    criterion = AcceptanceCriterion(
        criterion_id="AC-S3-001",
        statement="Unauthorized execution is rejected before tool invocation.",
        evidence_type="test_output",
        verifier="deterministic",
    )
    ambiguities = []
    if high_blocked:
        ambiguities.append(
            Ambiguity(
                ambiguity_id="AMB-S3-001",
                question="Should a consequential interpretation be assumed?",
                impact=AmbiguityImpact.HIGH,
                resolution_status="blocked",
            )
        )

    draft = AlignmentContract.create_draft(
        objective="Exercise final authority boundary",
        requirements=[requirement],
        permissions=PermissionsCeiling(
            action_ceiling=ActionClass.A1,
            expires_at=expires_at,
        ),
        acceptance_criteria=[criterion],
        original_inputs=[original],
        ambiguities=ambiguities,
    )
    return draft.activate() if active else draft


def _gateway(tmp_path: Path):
    project_id = uuid4()
    task_id = uuid4()
    tx = WorkspaceTransactionManager(
        workspace_root=tmp_path,
        project_id=project_id,
        task_id=task_id,
    )
    tool = FileWriteTool(tx)
    capabilities = CapabilityService()
    gateway = ToolGateway(EventStore(), capabilities)
    gateway.register_tool(tool)
    return gateway, capabilities, project_id, task_id


def test_a0_token_cannot_execute_a1_tool(tmp_path: Path):
    gateway, capabilities, project_id, task_id = _gateway(tmp_path)
    contract = _contract()
    token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=contract.version,
        action_class=ActionClass.A0,
        target_resource="protected.txt",
        allowed_operations=["write_file"],
    )

    with pytest.raises(CapabilityDeniedError, match="action ceiling \(A0\).+\(A1\)"):
        gateway.execute_tool(
            tool_name="write_file",
            args={"target": "protected.txt", "content": "must not be written"},
            capability_token=token,
            contract=contract,
        )

    assert not (tmp_path / "protected.txt").exists()


def test_draft_contract_cannot_execute_tool(tmp_path: Path):
    gateway, capabilities, project_id, task_id = _gateway(tmp_path)
    contract = _contract(active=False)
    token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="draft.txt",
        allowed_operations=["write_file"],
    )

    with pytest.raises(ActionScopeViolationError, match="requires an ACTIVE Alignment Contract"):
        gateway.execute_tool(
            tool_name="write_file",
            args={"target": "draft.txt", "content": "must not be written"},
            capability_token=token,
            contract=contract,
        )

    assert not (tmp_path / "draft.txt").exists()


def test_high_impact_blocked_ambiguity_is_rechecked_at_gateway(tmp_path: Path):
    gateway, capabilities, project_id, task_id = _gateway(tmp_path)
    contract = _contract(high_blocked=True)
    token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="ambiguous.txt",
        allowed_operations=["write_file"],
    )

    with pytest.raises(ActionScopeViolationError, match="HIGH-impact ambiguity blocks execution"):
        gateway.execute_tool(
            tool_name="write_file",
            args={"target": "ambiguous.txt", "content": "must not be written"},
            capability_token=token,
            contract=contract,
        )

    assert not (tmp_path / "ambiguous.txt").exists()


def test_expired_contract_permissions_fail_closed(tmp_path: Path):
    gateway, capabilities, project_id, task_id = _gateway(tmp_path)
    contract = _contract(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=contract.version,
        action_class=ActionClass.A1,
        target_resource="expired.txt",
        allowed_operations=["write_file"],
    )

    with pytest.raises(ActionScopeViolationError, match="Contract permissions expired"):
        gateway.execute_tool(
            tool_name="write_file",
            args={"target": "expired.txt", "content": "must not be written"},
            capability_token=token,
            contract=contract,
        )

    assert not (tmp_path / "expired.txt").exists()
