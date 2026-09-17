"""
Adversarial Security & API Suite for Universal Brain Control Plane

Asserts authenticated CQRS access plus action lifecycle, TOCTOU, concurrency,
expiry, evidence redaction, and idempotency behavior.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from universal_brain.api.actions import ActionManager, ActionStatus
from universal_brain.api.app import app
from universal_brain.api.dependencies import RuntimeContainer, set_container
from universal_brain.config import settings
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType


def test_runtime_container_defers_default_persistence_construction(monkeypatch):
    import universal_brain.api.dependencies as dependencies

    calls = []

    class ExplodingDatabaseManager:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise RuntimeError("database backend materialized")

    monkeypatch.setattr(dependencies, "DatabaseManager", ExplodingDatabaseManager)
    container = dependencies.RuntimeContainer()
    assert container.persistence_initialized is False
    assert calls == []
    with pytest.raises(RuntimeError, match="database backend materialized"):
        _ = container.db_manager
    assert len(calls) == 1


@pytest.fixture
def test_setup():
    event_store = EventStore()
    capability_service = CapabilityService()
    action_manager = ActionManager(capability_service)
    container = RuntimeContainer(
        event_store=event_store,
        capability_service=capability_service,
        action_manager=action_manager,
    )
    set_container(container)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {settings.operator_api_key}"})
    return client, container


def test_cqrs_query_endpoints(test_setup):
    client, _ = test_setup

    res = client.get("/api/v1/runtime/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "disk_utilization_pct" in data
    assert "budget_spend_usd" in data

    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    res = client.get("/api/v1/invariants")
    assert res.status_code == 200
    invariants = res.json()
    assert invariants["pass_count"] >= 9
    assert invariants["fail_count"] == 0

    res = client.get("/api/v1/contracts/current")
    assert res.status_code == 200
    assert res.json()["version"] == 1


def test_adversarial_action_rejection_lifecycle(test_setup):
    client, container = test_setup
    proposal = container.action_manager.create_proposal(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        action_type="TEST_ACTION",
        target_resource="./test_file.cpp",
        action_class=ActionClass.A1,
        requested_effect="Modify test file",
        payload={"change": 1},
        required_capabilities=["write"],
        diff_preview="+ line",
        rollback_plan="reverse patch",
        preflight_passed=True,
    )

    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/reject",
        json={
            "operator_id": "untrusted-body-value",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "reason": "Requirements misunderstood",
        },
        headers={"Idempotency-Key": "reject-key-1"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"

    updated_prop = container.action_manager.get_proposal(proposal.action_id)
    assert updated_prop.status == ActionStatus.REJECTED
    assert updated_prop.operator_identity == settings.operator_id

    res_rollback = client.post(
        f"/api/v1/actions/{proposal.action_id}/rollback",
        json={
            "operator_id": "untrusted-body-value",
            "action_id": str(proposal.action_id),
            "reason": "Trying to rollback an unexecuted rejection",
        },
    )
    assert res_rollback.status_code == 409


def test_adversarial_toctou_and_digest_tampering(test_setup):
    client, container = test_setup
    now = datetime.now(timezone.utc)

    proposal = container.action_manager.create_proposal(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        action_type="DEPLOY_ACTUATOR",
        target_resource="/dev/can0",
        action_class=ActionClass.A2,
        requested_effect="Enable motors",
        payload={"power": True},
        required_capabilities=["can:write"],
        diff_preview="+ motor_enable()",
        rollback_plan="motor_disable()",
        preflight_passed=True,
    )

    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "attacker-selected-name",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "authorization_digest": "0" * 64,
            "nonce": proposal.nonce,
        },
    )
    assert res.status_code == 403
    assert "digest mismatch" in res.json()["detail"].lower()

    correct_digest = proposal.compute_authorization_digest(approved_at=now)
    res_bad_nonce = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "attacker-selected-name",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "authorization_digest": correct_digest,
            "nonce": "replayed-fake-nonce",
            "approved_at": now.isoformat(),
        },
    )
    assert res_bad_nonce.status_code == 403
    assert "nonce" in res_bad_nonce.json()["detail"].lower()


def test_adversarial_optimistic_concurrency_conflict(test_setup):
    client, container = test_setup
    now = datetime.now(timezone.utc)
    proposal = container.action_manager.create_proposal(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        action_type="DEPLOY",
        target_resource="/dev/can0",
        action_class=ActionClass.A2,
        requested_effect="Power",
        payload={"v": 1},
        required_capabilities=["write"],
        diff_preview="diff",
        rollback_plan="rollback",
        preflight_passed=True,
    )
    valid_digest = proposal.compute_authorization_digest(approved_at=now)
    proposal.proposal_version = 2

    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "untrusted-body-value",
            "action_id": str(proposal.action_id),
            "proposal_version": 1,
            "authorization_digest": valid_digest,
            "nonce": proposal.nonce,
            "approved_at": now.isoformat(),
        },
    )
    assert res.status_code == 409
    assert "APPROVAL_INVALIDATED" in res.json()["detail"]


def test_adversarial_dead_mans_expiry(test_setup):
    client, container = test_setup
    proposal = container.action_manager.create_proposal(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        action_type="DEPLOY",
        target_resource="/dev/can0",
        action_class=ActionClass.A2,
        requested_effect="Power",
        payload={"v": 1},
        required_capabilities=["write"],
        diff_preview="diff",
        rollback_plan="rollback",
        preflight_passed=True,
    )
    proposal.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "untrusted-body-value",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "authorization_digest": "any",
            "nonce": proposal.nonce,
        },
    )
    assert res.status_code == 403
    assert "expired" in res.json()["detail"].lower()


def test_adversarial_evidence_redaction(test_setup):
    client, container = test_setup
    event = container.event_store.append_event(
        event_type=EventType.EVIDENCE_PRODUCED,
        actor_id="tool_gateway",
        payload={
            "tool": "curl",
            "output": "HTTP 200 OK. Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDN secretly received sk-ant-api03-12345678901234567890",
            "token": "sensitive_access_token_123",
        },
    )

    res = client.get(f"/api/v1/evidence/{event.event_id}")
    assert res.status_code == 200
    evidence = res.json()["evidence"]
    assert "sk-ant-api03-12345678901234567890" not in str(evidence)
    assert "sensitive_access_token_123" not in str(evidence)
    assert "[REDACTED" in str(evidence)


def test_command_idempotency_caching(test_setup):
    client, container = test_setup
    proposal = container.action_manager.create_proposal(
        project_id=uuid4(),
        task_id=uuid4(),
        contract_id=uuid4(),
        contract_version=1,
        action_type="DEPLOY",
        target_resource="/dev/can0",
        action_class=ActionClass.A1,
        requested_effect="Power",
        payload={"v": 1},
        required_capabilities=["write"],
        diff_preview="diff",
        rollback_plan="rollback",
        preflight_passed=True,
    )
    idempotency_key = "test-idempotency-key-100"

    res1 = client.post(
        f"/api/v1/actions/{proposal.action_id}/reject",
        json={
            "operator_id": "untrusted-body-value",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "reason": "Test reason",
        },
        headers={"Idempotency-Key": idempotency_key},
    )
    assert res1.status_code == 200

    res2 = client.post(
        f"/api/v1/actions/{proposal.action_id}/reject",
        json={
            "operator_id": "another-untrusted-body-value",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "reason": "Test reason",
        },
        headers={"Idempotency-Key": idempotency_key},
    )
    assert res2.status_code == 200
    assert res1.json() == res2.json()
