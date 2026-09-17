"""
Adversarial Security & API Suite for Universal Brain Control Plane

Asserts:
- CQRS Query side endpoints (Health, Projects, Graph, Contracts, Invariants)
- Strict separation of Reject (no rollback) vs. Rollback (reversibility execution)
- 16-field TOCTOU Authorization Digest verification
- Optimistic concurrency conflict (proposal_version mismatch -> 409 Conflict)
- Nonce verification and replay prevention
- 6-Hour Dead-Man's Expiry rejection
- Backend evidence secret & API key redaction
- Mutation idempotency caching via Idempotency-Key header
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from universal_brain.api.actions import ActionManager, ActionProposal, ActionStatus
from universal_brain.api.app import app
from universal_brain.api.dependencies import RuntimeContainer, set_container
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import ActionClass, EventType


def test_runtime_container_defers_default_persistence_construction(monkeypatch):
    """REQ-STA-001/ALN-014: optional persistence must be lazy but fail on first use."""
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
    """Provides isolated runtime container and TestClient."""
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
    return client, container


def test_cqrs_query_endpoints(test_setup):
    """Verify read-only endpoints return structured, unmutated state."""
    client, _ = test_setup

    # 1. Health
    res = client.get("/api/v1/runtime/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "disk_utilization_pct" in data
    assert "budget_spend_usd" in data

    # 2. Projects
    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    # 3. Invariants Matrix
    res = client.get("/api/v1/invariants")
    assert res.status_code == 200
    invariants = res.json()
    assert invariants["pass_count"] >= 9
    assert invariants["fail_count"] == 0

    # 4. Current Contract
    res = client.get("/api/v1/contracts/current")
    assert res.status_code == 200
    assert res.json()["version"] == 1


def test_adversarial_action_rejection_lifecycle(test_setup):
    """Verify that rejecting an action transitions to REJECTED and does NOT trigger rollback."""
    client, container = test_setup

    # Create proposal
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

    # 1. Reject action
    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/reject",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "reason": "Requirements misunderstood",
        },
        headers={"Idempotency-Key": "reject-key-1"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"

    # Verify state in manager
    updated_prop = container.action_manager.get_proposal(proposal.action_id)
    assert updated_prop.status == ActionStatus.REJECTED

    # 2. Attempting rollback on REJECTED action must fail (Rollback is only for executed/failed actions!)
    res_rollback = client.post(
        f"/api/v1/actions/{proposal.action_id}/rollback",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "reason": "Trying to rollback an unexecuted rejection",
        },
    )
    assert res_rollback.status_code == 409  # Conflict: cannot rollback unexecuted action


def test_adversarial_toctou_and_digest_tampering(test_setup):
    """Verify 16-field Authorization Digest prevents tampered approvals."""
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

    # 1. Tampered Digest rejected
    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "authorization_digest": "0000000000000000000000000000000000000000000000000000000000000000",
            "nonce": proposal.nonce,
        },
    )
    assert res.status_code == 403
    assert "digest mismatch" in res.json()["detail"].lower()

    # 2. Replayed Nonce rejected
    correct_digest = proposal.compute_authorization_digest("operator-vivek", now)
    res_bad_nonce = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "authorization_digest": correct_digest,
            "nonce": "replayed-fake-nonce",
        },
    )
    assert res_bad_nonce.status_code == 403
    assert "nonce" in res_bad_nonce.json()["detail"].lower()


def test_adversarial_optimistic_concurrency_conflict(test_setup):
    """Verify mutating proposal version invalidates pending approval (APPROVAL_INVALIDATED)."""
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

    # Operator reviewed version 1
    valid_digest = proposal.compute_authorization_digest("operator-vivek", now)

    # Background process mutates proposal to version 2
    proposal.proposal_version = 2

    # Operator attempts to submit approval with version 1
    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "proposal_version": 1,  # Stale version!
            "authorization_digest": valid_digest,
            "nonce": proposal.nonce,
        },
    )
    assert res.status_code == 409
    assert "APPROVAL_INVALIDATED" in res.json()["detail"]


def test_adversarial_dead_mans_expiry(test_setup):
    """Verify approval attempted after 6-hour deadline fails closed."""
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

    # Expire proposal
    proposal.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    res = client.post(
        f"/api/v1/actions/{proposal.action_id}/approve",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "authorization_digest": "any",
            "nonce": proposal.nonce,
        },
    )
    assert res.status_code == 403
    assert "expired" in res.json()["detail"].lower()


def test_adversarial_evidence_redaction(test_setup):
    """Verify backend redaction removes API keys and tokens before sending to client."""
    client, container = test_setup

    # Append event with raw secrets in evidence
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

    # Raw secrets must NOT be present
    assert "sk-ant-api03-12345678901234567890" not in str(evidence)
    assert "sensitive_access_token_123" not in str(evidence)
    assert "[REDACTED" in str(evidence)


def test_command_idempotency_caching(test_setup):
    """Verify repeated requests with identical Idempotency-Key return cached response."""
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

    # Reject call 1
    res1 = client.post(
        f"/api/v1/actions/{proposal.action_id}/reject",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "reason": "Test reason",
        },
        headers={"Idempotency-Key": idempotency_key},
    )
    assert res1.status_code == 200

    # Reject call 2 with SAME idempotency key
    res2 = client.post(
        f"/api/v1/actions/{proposal.action_id}/reject",
        json={
            "operator_id": "operator-vivek",
            "action_id": str(proposal.action_id),
            "proposal_version": proposal.proposal_version,
            "reason": "Test reason",
        },
        headers={"Idempotency-Key": idempotency_key},
    )
    assert res2.status_code == 200
    assert res1.json() == res2.json()
