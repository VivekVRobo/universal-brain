"""S3 truthful LIVE-state regressions.

The operator console must only report state that the runtime actually holds.
Starting the API may not seed demo projects, evidence, contracts, approvals, or
invariant PASS claims.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from universal_brain.api.actions import ActionManager
from universal_brain.api.app import app
from universal_brain.api.dependencies import RuntimeContainer, get_container, set_container
from universal_brain.config import settings
from universal_brain.kernel.capability import CapabilityService
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import EventType


@pytest.fixture
def truthful_client():
    previous = get_container()
    event_store = EventStore()
    capability_service = CapabilityService()
    container = RuntimeContainer(
        event_store=event_store,
        capability_service=capability_service,
        action_manager=ActionManager(capability_service),
    )
    set_container(container)
    try:
        with TestClient(app) as client:
            yield client, container
    finally:
        set_container(previous)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.operator_api_key}"}


def test_fresh_runtime_starts_without_synthetic_domain_state(truthful_client):
    client, container = truthful_client

    assert container.event_store.event_count == 0
    assert container.action_manager.list_proposals() == []

    projects = client.get("/api/v1/projects", headers=_auth_headers())
    assert projects.status_code == 200
    assert projects.json() == []

    contract = client.get("/api/v1/contracts/current", headers=_auth_headers())
    assert contract.status_code == 404
    assert "No active Alignment Contract" in contract.json()["detail"]

    invariants = client.get("/api/v1/invariants", headers=_auth_headers())
    assert invariants.status_code == 200
    ledger = invariants.json()
    assert ledger["pass_count"] == 0
    assert ledger["warn_count"] == 0
    assert ledger["fail_count"] == 0
    assert ledger["unknown_count"] == 9
    assert all(item["status"] == "UNKNOWN" for item in ledger["invariants"])

    health = client.get("/api/v1/runtime/health", headers=_auth_headers())
    assert health.status_code == 200
    snapshot = health.json()
    assert snapshot["active_model_lease"] is None
    assert snapshot["lease_expires_in_seconds"] is None
    assert snapshot["contract_version"] is None
    assert snapshot["system_mode"] == "LOCAL"


def test_real_operator_command_creates_the_state_read_models_report(truthful_client):
    client, container = truthful_client
    prompt = "Build a verified parser\n- Must pass deterministic tests"

    submitted = client.post(
        "/api/v1/commands/submit",
        headers=_auth_headers(),
        json={"prompt": prompt},
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    assert result["contract_version"] == 1

    events = container.event_store.get_all_events()
    assert [event.event_type for event in events] == [
        EventType.USER_INPUT,
        EventType.INTENT_PARSED,
        EventType.CONTRACT_CREATED,
    ]
    assert events[0].actor_id == settings.operator_id
    assert events[1].prev_event_hash == events[0].event_hash
    assert events[2].prev_event_hash == events[1].event_hash
    assert container.event_store.verify_chain_integrity() is True

    projects = client.get("/api/v1/projects", headers=_auth_headers())
    assert projects.status_code == 200
    project_rows = projects.json()
    assert len(project_rows) == 1
    assert project_rows[0]["project_id"] == result["project_id"]
    assert project_rows[0]["title"] == "Build a verified parser"
    assert project_rows[0]["current_contract_version"] == 1
    assert project_rows[0]["active_tasks_count"] is None
    assert project_rows[0]["pending_actions_count"] == 0

    contract = client.get("/api/v1/contracts/current", headers=_auth_headers())
    assert contract.status_code == 200, contract.text
    current = contract.json()
    assert current["contract_id"] == result["contract_id"]
    assert current["version"] == 1
    assert current["status"] == "active"
    assert current["objective"] == "Build a verified parser"
    assert current["requirements_count"] == 1
    assert current["semantic_diffs"] == []

    health = client.get("/api/v1/runtime/health", headers=_auth_headers()).json()
    assert health["contract_version"] == 1
    assert health["active_model_lease"] is None

    ledger = client.get("/api/v1/invariants", headers=_auth_headers()).json()
    assert ledger["pass_count"] == 1
    assert ledger["unknown_count"] == 8
    chain = next(item for item in ledger["invariants"] if item["invariant_id"] == "ALN-016")
    assert chain["status"] == "PASS"
    assert chain["proofs_count"] == 3


def test_production_control_plane_contains_no_demo_truth_claims():
    root = Path(__file__).resolve().parents[2]
    production_surfaces = [
        root / "src/universal_brain/api/app.py",
        root / "src/universal_brain/api/router.py",
        root / "console/src/components/ExecutiveStream.tsx",
        root / "console/src/components/GovernanceView.tsx",
        root / "console/src/components/Header.tsx",
        root / "console/src/components/EventGraphExplorer.tsx",
        root / "console/src/components/A2ApprovalModal.tsx",
    ]
    forbidden = [
        "Humanoid Robot Controller",
        "14/14",
        "Claude 3.5 Sonnet",
        "ALL PASSING",
        "200,000",
        "00000000-0000-0000-0000-000000000001",
        "CRYPTOGRAPHICALLY VERIFIED",
        "ADR-0008 PASS",
        "\"nonce-\" + action.action_id",
    ]

    for path in production_surfaces:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text, f"{phrase!r} reintroduced in {path.relative_to(root)}"
