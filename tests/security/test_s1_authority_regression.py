"""Universal Brain - Gate S1 Security Regression Test Suite."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from universal_brain.alignment.contract import (
    AcceptanceCriterion,
    AlignmentContract,
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
from universal_brain.config import Settings, settings
from universal_brain.kernel.capability import (
    CapabilityService,
    CapabilityToken,
    compute_canonical_request_digest,
    is_resource_authorized,
)
from universal_brain.kernel.errors import CapabilityDeniedError
from universal_brain.kernel.events import ActionClass
from universal_brain.kernel.event_store import EventStore
from universal_brain.tools.gateway import ToolGateway
from universal_brain.tools.runner.tool import CommandRunnerTool
from universal_brain.tools.sandbox.file_tools import FileWriteTool
from universal_brain.tools.sandbox.workspace import WorkspaceTransactionManager
from universal_brain.tools.workers.auth import WorkerAuthService


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def mock_contract() -> AlignmentContract:
    original = OriginalInput(exact_content_ref="ref_hash")
    requirement = Requirement(
        requirement_id="REQ-01",
        statement="Security test requirement",
        source_input_ids=[original.input_id],
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        verification_method="unit tests",
    )
    criterion = AcceptanceCriterion(
        criterion_id="AC-01",
        statement="Security test criterion",
        evidence_type="test_output",
        verifier="deterministic",
    )
    return AlignmentContract.create_draft(
        objective="Security Testing",
        requirements=[requirement],
        permissions=PermissionsCeiling(action_ceiling=ActionClass.A1),
        acceptance_criteria=[criterion],
        original_inputs=[original],
    ).activate()


def _write_gateway(tmp_path: Path, project_id: UUID, task_id: UUID):
    manager = WorkspaceTransactionManager(
        workspace_root=tmp_path,
        project_id=project_id,
        task_id=task_id,
    )
    tool = FileWriteTool(manager)
    capabilities = CapabilityService()
    gateway = ToolGateway(event_store=EventStore(), capability_service=capabilities)
    gateway.register_tool(tool)
    return gateway, capabilities


def _operator_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.operator_api_key}"}


def test_argument_target_tampering_rejected_by_request_bound_token(
    tmp_path: Path,
    mock_contract: AlignmentContract,
    project_id: UUID,
):
    task_id = uuid4()
    gateway, capabilities = _write_gateway(tmp_path, project_id, task_id)
    token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_id=mock_contract.contract_id,
        contract_version=mock_contract.version,
        action_class=ActionClass.A1,
        target_resource="authorized.txt",
        allowed_operations=["write_file"],
    )

    unauthorized_file = tmp_path / "unauthorized.txt"
    with pytest.raises(CapabilityDeniedError):
        gateway.execute_tool(
            tool_name="write_file",
            args={"target": "unauthorized.txt", "content": "malicious injection"},
            capability_token=token,
            contract=mock_contract,
            target_resource="authorized.txt",
        )
    assert not unauthorized_file.exists()


def test_request_digest_tampering_rejected(
    tmp_path: Path,
    mock_contract: AlignmentContract,
    project_id: UUID,
):
    task_id = uuid4()
    gateway, capabilities = _write_gateway(tmp_path, project_id, task_id)
    canonical_args = {"target": "safe.txt", "content": "original content"}
    request_digest = compute_canonical_request_digest(
        tool_name="write_file",
        args=canonical_args,
        action_class=ActionClass.A1,
        contract_id=mock_contract.contract_id,
        contract_version=mock_contract.version,
        task_id=task_id,
    )
    token = capabilities.issue_token(
        project_id=project_id,
        task_id=task_id,
        contract_id=mock_contract.contract_id,
        contract_version=mock_contract.version,
        action_class=ActionClass.A1,
        target_resource="safe.txt",
        allowed_operations=["write_file"],
        request_digest=request_digest,
    )

    with pytest.raises(CapabilityDeniedError, match="request digest mismatch"):
        gateway.execute_tool(
            tool_name="write_file",
            args={"target": "safe.txt", "content": "TAMPERED payload"},
            capability_token=token,
            contract=mock_contract,
        )


def test_resource_matching_rejects_prefix_collision_safeevil():
    assert not is_resource_authorized("safe*", "safeevil")
    assert not is_resource_authorized("safe/*", "safeevil")
    assert is_resource_authorized("safe/*", "safe/file.txt")
    assert is_resource_authorized("safe", "safe")
    assert is_resource_authorized("*", "anything")

    capabilities = CapabilityService()
    token = capabilities.issue_token(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_version=1,
        action_class=ActionClass.A1,
        target_resource="safe*",
        allowed_operations=["read"],
    )
    with pytest.raises(CapabilityDeniedError, match="outside authorized scope"):
        capabilities.verify_token(
            token=token,
            target_resource="safeevil",
            required_operation="read",
            current_contract_version=1,
        )


def test_unauthenticated_worker_progress_and_completion_rejected():
    client = TestClient(app)
    job_id = str(uuid4())
    progress = client.post(
        "/api/v1/workers/progress",
        json={
            "job_id": job_id,
            "worker_id": "attacker_worker",
            "lease_generation": 1,
            "sequence": 1,
            "progress_pct": 50.0,
        },
    )
    assert progress.status_code == 401
    assert "Missing or invalid Authorization Bearer header" in progress.json()["detail"]

    complete = client.post(
        "/api/v1/workers/complete",
        json={
            "job_id": job_id,
            "worker_id": "attacker_worker",
            "lease_generation": 1,
            "evidence": {"status": "forged"},
        },
    )
    assert complete.status_code == 401
    assert "Missing or invalid Authorization Bearer header" in complete.json()["detail"]


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


def test_forged_expired_wrong_scope_rollback_token_rejected(
    tmp_path: Path,
    mock_contract: AlignmentContract,
    project_id: UUID,
):
    task_id = uuid4()
    gateway, _ = _write_gateway(tmp_path, project_id, task_id)
    test_file = tmp_path / "important.txt"
    test_file.write_text("pre-mutation state", encoding="utf-8")

    forged_token = CapabilityToken(
        token_id=uuid4(),
        project_id=project_id,
        task_id=task_id,
        contract_id=mock_contract.contract_id,
        contract_version=mock_contract.version,
        action_class=ActionClass.A1,
        target_resource=str(test_file),
        allowed_operations=["write_file", "rollback"],
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        signature="0" * 64,
    )

    with pytest.raises(CapabilityDeniedError, match="signature is invalid"):
        gateway.rollback_tool(
            tool_name="write_file",
            rollback_data={"target": str(test_file)},
            capability_token=forged_token,
            contract=mock_contract,
        )
    assert test_file.read_text(encoding="utf-8") == "pre-mutation state"


def test_a2_endpoints_return_forbidden_under_stabilization_lockdown():
    client = TestClient(app)
    container = get_container()
    now = datetime.now(timezone.utc)
    proposal = container.action_manager.create_proposal(
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
    digest = proposal.compute_authorization_digest(approved_at=now)
    approve = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "operator_id": "untrusted-request-body-value",
            "authorization_digest": digest,
            "nonce": proposal.nonce,
            "approved_at": now.isoformat(),
        },
        headers=_operator_headers(),
    )
    assert approve.status_code == 403
    assert "A2_LOCKED_PENDING_CHALLENGE_POLICY" in approve.json()["detail"]

    proposal.status = ActionStatus.SUCCEEDED
    rollback = client.post(
        f"/api/v1/actions/{proposal.action_id}/rollback",
        json={
            "action_id": str(proposal.action_id),
            "operator_id": "untrusted-request-body-value",
            "reason": "testing A2 rollback lockdown",
        },
        headers=_operator_headers(),
    )
    assert rollback.status_code == 403
    assert "A2_LOCKED_PENDING_CHALLENGE_POLICY" in rollback.json()["detail"]


def test_unrecognized_ambiguity_strictly_defaults_to_medium():
    assert AmbiguityClassifier.classify("What color theme should we use?") == AmbiguityImpact.MEDIUM
    assert AmbiguityClassifier.classify("Should we add extra logging?") == AmbiguityImpact.MEDIUM
    assert AmbiguityClassifier.classify("delete production database") == AmbiguityImpact.HIGH
    assert AmbiguityClassifier.classify("fix variable_name typo") == AmbiguityImpact.LOW
    assert AmbiguityClassifier.classify("clean up whitespace and comment") == AmbiguityImpact.LOW


def test_production_environment_rejects_development_secrets():
    secure_operator_key = "secure-operator-key-for-production-tests-123456789"
    with pytest.raises(ValueError, match="hmac_secret_key must be an externally configured secret"):
        Settings(
            app_env="production",
            hmac_secret_key="dev-secret-key-change-in-production-min-32-chars-long",
            operator_api_key=secure_operator_key,
            database_url="postgresql+asyncpg://admin:secure_pass@localhost:5432/brain",
        )
    with pytest.raises(ValueError, match="database_url must not contain default development credentials"):
        Settings(
            app_env="staging",
            hmac_secret_key="a_very_secure_production_secret_key_1234567890",
            operator_api_key=secure_operator_key,
            database_url="postgresql+asyncpg://admin:brain_dev_password@localhost:5432/brain",
        )
    with pytest.raises(ValueError, match="operator_api_key must be an externally configured secret"):
        Settings(
            app_env="production",
            hmac_secret_key="a_very_secure_production_secret_key_1234567890",
            operator_api_key="dev-operator-key-change-in-production-min-32-chars",
            database_url="postgresql+asyncpg://admin:secure_prod_password@localhost:5432/brain",
        )
    prod = Settings(
        app_env="production",
        hmac_secret_key="a_very_secure_production_secret_key_1234567890",
        operator_api_key=secure_operator_key,
        database_url="postgresql+asyncpg://admin:secure_prod_password@localhost:5432/brain",
    )
    assert prod.app_env == "production"


def test_command_runner_rollback_fails_closed_without_compensation(tmp_path: Path):
    tool = CommandRunnerTool(workspace_root=tmp_path)
    assert tool.rollback({}) is False
    assert tool.rollback({"compensation_command": []}) is False
    assert tool.rollback({"checkpoint": "cp_01"}) is True
