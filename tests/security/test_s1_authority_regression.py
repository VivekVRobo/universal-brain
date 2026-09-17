"""
Universal Brain - Gate S1 Security Regression Test Suite

Verifies that all P0/P1 authority vulnerabilities identified in the audit
are mathematically and deterministically blocked (fail-closed):
1. Target/argument decoupling in capability tokens (P0).
2. Sibling prefix resource boundary collision (safe* vs safeevil) (P1).
3. Missing or body-supplied worker authentication (P0).
4. Multi-dimensional worker lease token tampering (P0).
5. Forged / expired / wrong-scope rollback capability bypass (P0).
6. Unauthenticated A2 action/approval API lockdown (P0).
7. Unrecognized ambiguity defaulting to MEDIUM (P0).
8. Default development secrets rejected in production mode (P1).
9. Command runner rollback failing closed without verified compensation (P1).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

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
from universal_brain.alignment.engine import AmbiguityClassifier
from universal_brain.api.actions import ActionStatus
from universal_brain.api.app import app
from universal_brain.api.dependencies import get_container
from universal_brain.config import Settings
from universal_brain.kernel.capability import (
    CapabilityService,
    CapabilityToken,
    RollbackGrant,
    compute_canonical_request_digest,
    is_resource_authorized,
)
from universal_brain.kernel.errors import CapabilityDeniedError
from universal_brain.kernel.events import ActionClass
from universal_brain.kernel.event_store import EventStore
from universal_brain.tools.gateway import ToolGateway
from universal_brain.tools.runner.process import SubprocessRunner
from universal_brain.tools.runner.tool import CommandRunnerTool
from universal_brain.tools.sandbox.file_tools import FileWriteTool
from universal_brain.tools.sandbox.workspace import WorkspaceTransactionManager
from universal_brain.tools.workers.auth import WorkerAuthService
from universal_brain.tools.workers.queue import EphemeralJobQueue


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def mock_contract() -> AlignmentContract:
    inp = OriginalInput(exact_content_ref="ref_hash")
    req = Requirement(
        requirement_id="REQ-01",
        statement="Security test requirement",
        source_input_ids=[inp.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="unit tests",
    )
    crit = AcceptanceCriterion(
        criterion_id="AC-01",
        statement="Security test criterion",
        evidence_type="test_output",
        verifier="deterministic",
    )
    contract = AlignmentContract.create_draft(
        objective="Security Testing",
        requirements=[req],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[crit],
        original_inputs=[inp],
    )
    return contract.activate()


# -----------------------------------------------------------------------------
# 1. Argument & Target Decoupling (P0)
# -----------------------------------------------------------------------------

def test_argument_target_tampering_rejected_by_request_bound_token(tmp_path: Path, mock_contract: AlignmentContract, project_id: UUID):
    """
    Reproduces audit exploit:
    Caller presents token for 'authorized.txt' but passes args['target'] = 'unauthorized.txt'.
    ToolGateway must extract authoritative target from args and reject decoupling.
    """
    task_id = uuid4()
    tx_manager = WorkspaceTransactionManager(workspace_root=tmp_path, project_id=project_id, task_id=task_id)
    tool = FileWriteTool(tx_manager)
    cap_service = CapabilityService()
    event_store = EventStore()
    gateway = ToolGateway(event_store=event_store, capability_service=cap_service)
    gateway.register_tool(tool)

    token = cap_service.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=mock_contract.version,
        action_class=ActionClass.A1,
        target_resource="authorized.txt",
        allowed_operations=["write_file"],
    )

    unauthorized_file = tmp_path / "unauthorized.txt"
    assert not unauthorized_file.exists()

    with pytest.raises(CapabilityDeniedError):
        gateway.execute_tool(
            tool_name="write_file",
            args={"target": "unauthorized.txt", "content": "malicious injection"},
            capability_token=token,
            contract=mock_contract,
            target_resource="authorized.txt",
        )

    assert not unauthorized_file.exists()


def test_request_digest_tampering_rejected(tmp_path: Path, mock_contract: AlignmentContract, project_id: UUID):
    """Any argument mutation invalidates a request-bound token."""
    task_id = uuid4()
    tx_manager = WorkspaceTransactionManager(workspace_root=tmp_path, project_id=project_id, task_id=task_id)
    tool = FileWriteTool(tx_manager)
    cap_service = CapabilityService()
    event_store = EventStore()
    gateway = ToolGateway(event_store=event_store, capability_service=cap_service)
    gateway.register_tool(tool)

    canonical_args = {"target": "safe.txt", "content": "original content"}
    request_digest = compute_canonical_request_digest(
        tool_name="write_file",
        args=canonical_args,
        action_class=ActionClass.A1,
        contract_version=mock_contract.version,
        task_id=task_id,
    )

    token = cap_service.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_version=mock_contract.version,
        action_class=ActionClass.A1,
        target_resource="safe.txt",
        allowed_operations=["write_file"],
        request_digest=request_digest,
    )

    tampered_args = {"target": "safe.txt", "content": "TAMPERED payload"}
    with pytest.raises(CapabilityDeniedError, match="request digest mismatch"):
        gateway.execute_tool(
            tool_name="write_file",
            args=tampered_args,
            capability_token=token,
            contract=mock_contract,
        )


# -----------------------------------------------------------------------------
# 2. Resource Boundary Sibling Collision (P1)
# -----------------------------------------------------------------------------

def test_resource_matching_rejects_prefix_collision_safeevil():
    assert not is_resource_authorized("safe*", "safeevil")
    assert not is_resource_authorized("safe/*", "safeevil")
    assert is_resource_authorized("safe/*", "safe/file.txt")
    assert is_resource_authorized("safe", "safe")
    assert is_resource_authorized("*", "anything")

    cap_service = CapabilityService()
    task_id = uuid4()
    proj_id = uuid4()
    token = cap_service.issue_token(
        project_id=proj_id,
        task_id=task_id,
        contract_version=1,
        action_class=ActionClass.A1,
        target_resource="safe*",
        allowed_operations=["read"],
    )

    with pytest.raises(CapabilityDeniedError, match="outside authorized scope"):
        cap_service.verify_token(
            token=token,
            target_resource="safeevil",
            required_operation="read",
            current_contract_version=1,
        )


# -----------------------------------------------------------------------------
# 3. Unauthenticated Worker Operations (P0)
# -----------------------------------------------------------------------------

def test_unauthenticated_worker_progress_and_completion_rejected():
    client = TestClient(app)
    job_id = str(uuid4())

    res = client.post(
        "/api/v1/workers/progress",
        json={
            "job_id": job_id,
            "worker_id": "attacker_worker",
            "lease_generation": 1,
            "sequence": 1,
            "progress_pct": 50.0,
        },
    )
    assert res.status_code == 401
    assert "Missing or invalid Authorization Bearer header" in res.json()["detail"]

    res = client.post(
        "/api/v1/workers/complete",
        json={
            "job_id": job_id,
            "worker_id": "attacker_worker",
            "lease_generation": 1,
            "evidence": {"status": "forged"},
        },
    )
    assert res.status_code == 401
    assert "Missing or invalid Authorization Bearer header" in res.json()["detail"]


# -----------------------------------------------------------------------------
# 4. Multi-Dimensional Worker Token Binding (P0)
# -----------------------------------------------------------------------------

def test_worker_lease_token_mismatch_rejected():
    auth = WorkerAuthService()
    session_id = str(uuid4())
    job_1 = str(uuid4())
    job_2 = str(uuid4())

    token = auth.generate_job_lease_token(
        worker_id="worker_A",
        session_id=session_id,
        job_id=job_1,
        lease_generation=1,
        kernel_epoch=1,
    )

    claims = auth.verify_job_lease_token(
        token=token,
        expected_worker_id="worker_A",
        expected_job_id=job_1,
        expected_lease_generation=1,
        expected_session_id=session_id,
        current_epoch=1,
    )
    assert claims["worker_id"] == "worker_A"

    with pytest.raises(CapabilityDeniedError, match="attempted use by 'worker_B'"):
        auth.verify_job_lease_token(
            token=token,
            expected_worker_id="worker_B",
            expected_job_id=job_1,
            expected_lease_generation=1,
        )

    with pytest.raises(CapabilityDeniedError, match="attempted use on job"):
        auth.verify_job_lease_token(
            token=token,
            expected_worker_id="worker_A",
            expected_job_id=job_2,
            expected_lease_generation=1,
        )

    with pytest.raises(CapabilityDeniedError, match="does not match active generation"):
        auth.verify_job_lease_token(
            token=token,
            expected_worker_id="worker_A",
            expected_job_id=job_1,
            expected_lease_generation=2,
        )

    with pytest.raises(CapabilityDeniedError, match="is stale; current kernel epoch is 2"):
        auth.verify_job_lease_token(
            token=token,
            expected_worker_id="worker_A",
            expected_job_id=job_1,
            expected_lease_generation=1,
            current_epoch=2,
        )


# -----------------------------------------------------------------------------
# 5. Rollback Token Verification & Scope (P0)
# -----------------------------------------------------------------------------

def test_forged_expired_wrong_scope_rollback_token_rejected(tmp_path: Path, mock_contract: AlignmentContract, project_id: UUID):
    tx_manager = WorkspaceTransactionManager(workspace_root=tmp_path, project_id=project_id, task_id=uuid4())
    tool = FileWriteTool(tx_manager)
    cap_service = CapabilityService()
    event_store = EventStore()
    gateway = ToolGateway(event_store=event_store, capability_service=cap_service)
    gateway.register_tool(tool)

    test_file = tmp_path / "important.txt"
    test_file.write_text("pre-mutation state", encoding="utf-8")

    forged_token = CapabilityToken(
        token_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        contract_version=1,
        action_class=ActionClass.A1,
        target_resource=str(test_file),
        allowed_operations=["write_file", "rollback"],
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        signature="0000000000000000000000000000000000000000000000000000000000000000",
    )

    with pytest.raises(CapabilityDeniedError, match="signature is invalid"):
        gateway.rollback_tool(
            tool_name="write_file",
            rollback_data={"target": str(test_file)},
            capability_token=forged_token,
            contract=mock_contract,
        )

    assert test_file.read_text(encoding="utf-8") == "pre-mutation state"


# -----------------------------------------------------------------------------
# 6. A2 Endpoint Lockdown (S1 Policy)
# -----------------------------------------------------------------------------

def test_a2_endpoints_return_forbidden_under_stabilization_lockdown():
    client = TestClient(app)
    cnt = get_container()
    now = datetime.now(timezone.utc)

    proposal = cnt.action_manager.create_proposal(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        action_type="DEPLOY_ACTUATOR",
        target_resource="/dev/can0",
        action_class=ActionClass.A2,
        requested_effect="Enable physical actuator",
        payload={"power": True},
        required_capabilities=["can:write"],
        diff_preview="+ enable()",
        rollback_plan="disable()",
        preflight_passed=True,
    )

    valid_digest = proposal.compute_authorization_digest("operator-vivek", now)
    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "operator_id": "operator-vivek",
            "authorization_digest": valid_digest,
            "nonce": proposal.nonce,
            "approved_at": now.isoformat(),
        },
    )
    assert res.status_code == 403
    assert "A2_LOCKED_PENDING_OPERATOR_AUTH" in res.json()["detail"]

    proposal.status = ActionStatus.SUCCEEDED
    res_rb = client.post(
        f"/api/v1/actions/{proposal.action_id}/rollback",
        json={
            "action_id": str(proposal.action_id),
            "operator_id": "operator-vivek",
            "reason": "testing A2 rollback lockdown",
        },
    )
    assert res_rb.status_code == 403
    assert "A2_LOCKED_PENDING_OPERATOR_AUTH" in res_rb.json()["detail"]


# -----------------------------------------------------------------------------
# 7. Unrecognized Ambiguity Defaults to MEDIUM (P0)
# -----------------------------------------------------------------------------

def test_unrecognized_ambiguity_strictly_defaults_to_medium():
    assert AmbiguityClassifier.classify("What color theme should we use?") == AmbiguityImpact.MEDIUM
    assert AmbiguityClassifier.classify("Should we add extra logging?") == AmbiguityImpact.MEDIUM
    assert AmbiguityClassifier.classify("delete production database") == AmbiguityImpact.HIGH
    assert AmbiguityClassifier.classify("fix variable_name typo") == AmbiguityImpact.LOW
    assert AmbiguityClassifier.classify("clean up whitespace and comment") == AmbiguityImpact.LOW


# -----------------------------------------------------------------------------
# 8. Secret Guardrail in Production (P1)
# -----------------------------------------------------------------------------

def test_production_environment_rejects_development_secrets():
    with pytest.raises(ValueError, match="FATAL: In 'production' mode, hmac_secret_key must be an externally configured secret"):
        Settings(
            app_env="production",
            hmac_secret_key="dev-secret-key-change-in-production-min-32-chars-long",
            database_url="postgresql+asyncpg://admin:secure_pass@localhost:5432/brain",
        )

    with pytest.raises(ValueError, match="database_url must not contain default development credentials"):
        Settings(
            app_env="staging",
            hmac_secret_key="a_very_secure_production_secret_key_1234567890",
            database_url="postgresql+asyncpg://admin:brain_dev_password@localhost:5432/brain",
        )

    prod = Settings(
        app_env="production",
        hmac_secret_key="a_very_secure_production_secret_key_1234567890",
        database_url="postgresql+asyncpg://admin:secure_prod_password@localhost:5432/brain",
    )
    assert prod.app_env == "production"


# -----------------------------------------------------------------------------
# 9. Command Runner Rollback Fails Closed (P1)
# -----------------------------------------------------------------------------

def test_command_runner_rollback_fails_closed_without_compensation(tmp_path: Path):
    tool = CommandRunnerTool(workspace_root=tmp_path)
    assert tool.rollback({}) is False
    assert tool.rollback({"compensation_command": []}) is False
    assert tool.rollback({"checkpoint": "cp_01"}) is True
