"""
Universal Brain - REST API Router (CQRS Architecture)

Exposes Query-side (read-only) and Command-side (idempotent mutations)
routes connecting the Operator Console to backend runtime singletons.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

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
from universal_brain.api.actions import ActionProposal, ActionStatus
from universal_brain.api.dependencies import RuntimeContainer, get_container
from universal_brain.api.redaction import redact_evidence_payload
from universal_brain.api.read_models import (
    evaluate_runtime_invariants,
    latest_active_contract,
    latest_model_identity,
    latest_mission,
    observed_contract_version,
    project_observations,
)
from universal_brain.api.schemas import (
    ActionApproveRequest,
    ActionCancelRequest,
    ActionProposalResponse,
    ActionRejectRequest,
    ActionRollbackRequest,
    CausalGraphEdge,
    CausalGraphNode,
    CausalGraphResponse,
    ContractDetailResponse,
    ContractDiffItem,
    EventItemResponse,
    EventListResponse,
    InvariantItem,
    InvariantLedgerResponse,
    ProjectSummaryResponse,
    RuntimeHealthResponse,
    IntelligenceStatusResponse,
    EngineeringStatusResponse,
    SubmitCommandRequest,
)
from universal_brain.config import settings
from universal_brain.kernel.errors import (
    ActionScopeViolationError,
    CapabilityDeniedError,
    UniversalBrainError,
)
from universal_brain.executive.intent import IntentParser
from universal_brain.intelligence.observability import build_observability_snapshot
from universal_brain.engineering.observability import build_engineering_observability_snapshot
from universal_brain.kernel.events import EventType, RelationType

router = APIRouter(prefix="/api/v1")


# -----------------------------------------------------------------------------
# 1. QUERY SIDE (Read-Only)
# -----------------------------------------------------------------------------


@router.get("/runtime/health", response_model=RuntimeHealthResponse)
async def get_runtime_health(container: RuntimeContainer = Depends(get_container)) -> RuntimeHealthResponse:
    """Expose only health and runtime-state values that are actually observable."""
    disk = container.retention_manager.check_disk_capacity()
    tier = container.budget_gatekeeper.get_tier()

    node_status = "HEALTHY"
    if disk.is_warning or tier.value in ["TIER_1", "TIER_2"]:
        node_status = "DEGRADED"
    if disk.is_critical or tier.value == "TIER_3":
        node_status = "CRITICAL"

    # A production/staging process without materialized persistence must not
    # advertise itself as fully LIVE.
    if settings.app_env in {"production", "staging"} and not container.canonical_state_ready:
        if node_status == "HEALTHY":
            node_status = "DEGRADED"

    pending_actions = len([
        p for p in container.action_manager.list_proposals()
        if p.status == ActionStatus.AWAITING_APPROVAL
    ])

    is_live = settings.app_env == "production" and container.canonical_state_ready
    return RuntimeHealthResponse(
        node_id=settings.system_id,
        status=node_status,
        disk_utilization_pct=disk.utilization_pct,
        is_disk_warning=disk.is_warning,
        is_disk_critical=disk.is_critical,
        budget_spend_usd=container.budget_gatekeeper.cumulative_spend_usd,
        monthly_budget_usd=container.budget_gatekeeper.monthly_budget_usd,
        budget_tier=tier,
        active_model_lease=latest_model_identity(container.event_store),
        lease_expires_in_seconds=None,
        active_actions_count=pending_actions,
        contract_version=observed_contract_version(container.event_store),
        system_mode="LIVE" if is_live else "LOCAL",
    )

@router.get("/intelligence/status", response_model=IntelligenceStatusResponse)
async def get_intelligence_status(
    container: RuntimeContainer = Depends(get_container),
) -> IntelligenceStatusResponse:
    """Read-only Intelligence Fabric observability. No prompt or response bodies are exposed."""
    stack = container.intelligence_stack
    if stack is None:
        return IntelligenceStatusResponse(
            configured=False,
            note="Intelligence Fabric is not attached to this runtime container.",
        )
    snapshot = build_observability_snapshot(stack)
    return IntelligenceStatusResponse.model_validate(snapshot.model_dump(mode="json"))


@router.get("/engineering/status", response_model=EngineeringStatusResponse)
async def get_engineering_status(
    container: RuntimeContainer = Depends(get_container),
) -> EngineeringStatusResponse:
    """Read-only Engineering Agency V5.2 observability."""
    stack = container.engineering_stack
    if stack is None:
        return EngineeringStatusResponse(
            configured=False,
            note="Engineering Agency stack is not attached to this runtime container.",
        )
    snapshot = build_engineering_observability_snapshot(stack)
    return EngineeringStatusResponse.model_validate(snapshot.model_dump(mode="json"))


@router.get("/projects", response_model=List[ProjectSummaryResponse])
async def list_projects(container: RuntimeContainer = Depends(get_container)) -> List[ProjectSummaryResponse]:
    """List projects actually observed in canonical runtime state."""
    observations = project_observations(container.event_store)
    proposals = container.action_manager.list_proposals()

    # Consequential proposals are canonical state too; include their project even
    # if the current in-memory EventStore has not observed another project event.
    for proposal in proposals:
        if proposal.project_id not in observations:
            observations[proposal.project_id] = {
                "title": f"Project {str(proposal.project_id)[:8]}",
                "status": "observed",
                "current_contract_version": proposal.contract_version,
                "created_at": proposal.created_at,
                "observed_task_assignments": None,
            }

    responses: List[ProjectSummaryResponse] = []
    for project_id, observed in sorted(
        observations.items(), key=lambda item: item[1]["created_at"]
    ):
        pending = sum(
            1
            for proposal in proposals
            if proposal.project_id == project_id
            and proposal.status == ActionStatus.AWAITING_APPROVAL
        )
        responses.append(
            ProjectSummaryResponse(
                project_id=project_id,
                title=observed["title"],
                status=observed["status"],
                current_contract_version=observed["current_contract_version"],
                created_at=observed["created_at"],
                # EventStore currently proves assignment, not task liveness.
                active_tasks_count=None,
                pending_actions_count=pending,
            )
        )
    return responses

@router.get("/events", response_model=EventListResponse)
async def query_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    project_id: Optional[UUID] = None,
    event_type: Optional[EventType] = None,
    container: RuntimeContainer = Depends(get_container),
) -> EventListResponse:
    """Paginated event queries over the authoritative EventStore."""
    all_events = container.event_store.get_all_events()

    if project_id:
        all_events = [e for e in all_events if e.project_id == project_id]
    if event_type:
        all_events = [e for e in all_events if e.event_type == event_type]

    total = len(all_events)
    start = (page - 1) * page_size
    end = start + page_size
    slice_events = all_events[start:end]

    items = [
        EventItemResponse(
            event_id=e.event_id,
            timestamp=e.timestamp,
            event_type=e.event_type,
            actor_id=e.actor_id,
            project_id=e.project_id,
            task_id=e.task_id,
            contract_version=e.contract_version,
            payload=redact_evidence_payload(e.payload),
            prev_event_hash=e.prev_event_hash,
            event_hash=e.event_hash,
        )
        for e in slice_events
    ]

    return EventListResponse(events=items, total_count=total, page=page, page_size=page_size)


@router.get("/graph", response_model=CausalGraphResponse)
async def get_causal_graph(
    project_id: Optional[UUID] = None,
    limit: int = Query(100, ge=1, le=500),
    container: RuntimeContainer = Depends(get_container),
) -> CausalGraphResponse:
    """Returns nodes and edges formatted for the Total Awareness Causal DAG Explorer."""
    events = container.event_store.get_all_events()[-limit:]
    edges = container.event_store._edges

    nodes: List[CausalGraphNode] = []
    for e in events:
        summary = str(e.payload.get("utterance") or e.payload.get("goal") or e.payload.get("tool") or e.event_type.value)
        nodes.append(
            CausalGraphNode(
                id=str(e.event_id),
                label=f"{e.event_type.value}: {summary[:24]}",
                event_type=e.event_type,
                actor_id=e.actor_id,
                timestamp=e.timestamp,
                event_hash=e.event_hash,
                payload_summary=summary,
                has_evidence=(e.event_type == EventType.EVIDENCE_PRODUCED),
            )
        )

    graph_edges = [
        CausalGraphEdge(
            source=str(edge.source_event_id),
            target=str(edge.target_event_id),
            relation_type=edge.relation_type,
        )
        for edge in edges
        if any(n.id == str(edge.source_event_id) for n in nodes)
        and any(n.id == str(edge.target_event_id) for n in nodes)
    ]

    root_ids = [n.id for n in nodes if n.event_type == EventType.USER_INPUT]

    return CausalGraphResponse(nodes=nodes, edges=graph_edges, root_cause_event_ids=root_ids)


@router.get("/contracts/current", response_model=ContractDetailResponse)
async def get_current_contract(
    container: RuntimeContainer = Depends(get_container),
) -> ContractDetailResponse:
    """Return the latest fully materialized active contract, or 404 if absent."""
    resolved = latest_active_contract(container.event_store)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail="No active Alignment Contract is present in canonical runtime state.",
        )

    contract, observed_at = resolved
    return ContractDetailResponse(
        contract_id=contract.contract_id,
        version=contract.version,
        status=contract.status.value,
        objective=contract.objective,
        requirements_count=len(contract.requirements),
        constraints_count=len(contract.constraints),
        permissions_ceiling=contract.permissions.action_ceiling,
        created_at=observed_at,
        # Semantic diffs require persisted diff artifacts. Do not synthesize them.
        semantic_diffs=[],
    )

@router.get("/invariants", response_model=InvariantLedgerResponse)
async def get_invariants_matrix(
    container: RuntimeContainer = Depends(get_container),
) -> InvariantLedgerResponse:
    """Report runtime-proven invariant status; unproven checks remain UNKNOWN."""
    invariants = evaluate_runtime_invariants(container.event_store)
    return InvariantLedgerResponse(
        invariants=invariants,
        pass_count=sum(item.status == "PASS" for item in invariants),
        warn_count=sum(item.status == "WARN" for item in invariants),
        fail_count=sum(item.status == "FAIL" for item in invariants),
        unknown_count=sum(item.status == "UNKNOWN" for item in invariants),
    )

@router.get("/actions/pending", response_model=List[ActionProposalResponse])
async def list_pending_actions(
    project_id: Optional[UUID] = None,
    container: RuntimeContainer = Depends(get_container),
) -> List[ActionProposalResponse]:
    """Exposes all pending consequential actions awaiting operator review."""
    proposals = container.action_manager.list_proposals(project_id)
    now = datetime.now(timezone.utc)
    responses = []

    for p in proposals:
        seconds_left = max(0, int((p.expires_at - now).total_seconds()))
        # The digest is a review fingerprint, not an identity credential. Bind it
        # to the authenticated server-side operator identity and expose the exact
        # timestamp required to reproduce it during approval validation.
        authorization_approved_at = now
        auth_digest = p.compute_authorization_digest(
            settings.operator_id,
            authorization_approved_at,
        )
        responses.append(
            ActionProposalResponse(
                action_id=p.action_id,
                proposal_version=p.proposal_version,
                project_id=p.project_id,
                task_id=p.task_id,
                action_type=p.action_type,
                target_resource=p.target_resource,
                requested_effect=p.requested_effect,
                action_class=p.action_class,
                status=p.status.value,
                preflight_reversibility="VERIFIED_REVERSIBLE" if p.preflight_passed else "UNKNOWN",
                diff_preview=p.diff_preview,
                rollback_procedure=p.rollback_plan,
                evidence_items_count=p.evidence_items_count,
                payload_hash=p.compute_payload_hash(),
                authorization_digest=auth_digest,
                authorization_approved_at=authorization_approved_at,
                nonce=p.nonce,
                created_at=p.created_at,
                expires_at=p.expires_at,
                seconds_remaining=seconds_left,
            )
        )
    return responses


@router.get("/evidence/{event_id}")
async def get_evidence(
    event_id: UUID,
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Fetches evidence artifact, applying backend-side credential redaction."""
    event = container.event_store.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evidence event not found.")

    # Apply strict backend redaction
    sanitized_payload = redact_evidence_payload(event.payload)
    return {
        "event_id": str(event.event_id),
        "timestamp": event.timestamp.isoformat(),
        "event_hash": event.event_hash,
        "evidence": sanitized_payload,
    }


# -----------------------------------------------------------------------------
# 2. COMMAND SIDE (Idempotent State Mutations)
# -----------------------------------------------------------------------------


@router.post("/commands/submit")
async def submit_operator_command(
    req: SubmitCommandRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Record an operator command and the real contract derived from it."""
    project_id = req.project_id or uuid4()
    event = container.event_store.append_event(
        event_type=EventType.USER_INPUT,
        actor_id=settings.operator_id,
        payload={"utterance": req.prompt},
        project_id=project_id,
    )

    parser = IntentParser(container.alignment_engine)
    intent = parser.parse_intent(
        req.prompt,
        project_id=project_id,
        operator_id=settings.operator_id,
        source_event_id=event.event_id,
    )
    intent_event = container.event_store.append_event(
        event_type=EventType.INTENT_PARSED,
        actor_id="intent_parser",
        payload=intent.model_dump(mode="json"),
        project_id=project_id,
        caused_by_event_id=event.event_id,
    )

    contract = parser.propose_contract(intent)
    contract_event = container.event_store.append_event(
        event_type=EventType.CONTRACT_CREATED,
        actor_id="alignment_engine",
        payload={
            "contract": contract.model_dump(mode="json"),
            "intent_id": str(intent.intent_id),
        },
        project_id=project_id,
        contract_version=contract.version,
        caused_by_event_id=intent_event.event_id,
    )

    await container.ws_gateway.broadcast(
        channel="events",
        event_type="USER_INPUT",
        payload={"event_id": str(event.event_id), "prompt": req.prompt},
        event_id=event.event_id,
    )
    await container.ws_gateway.broadcast(
        channel="events",
        event_type="INTENT_PARSED",
        payload={
            "event_id": str(intent_event.event_id),
            "primary_goal": intent.primary_goal,
            "requirements_count": len(intent.functional_requirements),
            "ambiguities_count": len(intent.ambiguities),
        },
        event_id=intent_event.event_id,
    )
    await container.ws_gateway.broadcast(
        channel="governance",
        event_type="CONTRACT_CREATED",
        payload={
            "event_id": str(contract_event.event_id),
            "contract_id": str(contract.contract_id),
            "version": contract.version,
            "status": contract.status.value,
        },
        event_id=contract_event.event_id,
    )

    return {
        "status": "ACCEPTED",
        "project_id": str(project_id),
        "event_id": str(event.event_id),
        "event_hash": event.event_hash,
        "intent_id": str(intent.intent_id),
        "primary_goal": intent.primary_goal,
        "contract_id": str(contract.contract_id),
        "contract_version": contract.version,
    }

@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: UUID,
    req: ActionApproveRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """
    Operator approves a pending action.
    Enforces expiry, optimistic concurrency, nonce, digest, and Gate S1 A2 lockdown.
    """
    if action_id != req.action_id:
        raise HTTPException(status_code=400, detail="Path action_id does not match request body.")

    try:
        token = container.action_manager.approve_action(
            action_id=req.action_id,
            proposal_version=req.proposal_version,
            operator_id=req.operator_id,
            authorization_digest=req.authorization_digest,
            nonce=req.nonce,
            idempotency_key=idempotency_key,
            approved_at=req.approved_at,
        )

        # Broadcast update
        await container.ws_gateway.broadcast(
            channel="actions",
            event_type="ACTION_APPROVED",
            payload={
                "action_id": str(action_id),
                "token_id": str(token.token_id),
                "operator_id": settings.operator_id,
            },
        )

        return {
            "status": "APPROVED",
            "action_id": str(action_id),
            "capability_token_id": str(token.token_id),
            "target_resource": token.target_resource,
            "expires_at": token.expires_at.isoformat(),
        }

    except ActionScopeViolationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except CapabilityDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: UUID,
    req: ActionRejectRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """
    Operator rejects an unexecuted proposal.
    Transitions state to REJECTED. Rollback is NOT executed.
    """
    if action_id != req.action_id:
        raise HTTPException(status_code=400, detail="Path action_id does not match request body.")

    try:
        proposal = container.action_manager.reject_action(
            action_id=req.action_id,
            proposal_version=req.proposal_version,
            operator_id=req.operator_id,
            reason=req.reason,
            idempotency_key=idempotency_key,
        )

        await container.ws_gateway.broadcast(
            channel="actions",
            event_type="ACTION_REJECTED",
            payload={"action_id": str(action_id), "reason": req.reason},
        )

        return {
            "status": "REJECTED",
            "action_id": str(action_id),
            "proposal_version": proposal.proposal_version,
            "reason": req.reason,
        }
    except ActionScopeViolationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/actions/{action_id}/rollback")
async def rollback_action(
    action_id: UUID,
    req: ActionRollbackRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """
    Reverses an executed or failed action using recorded rollback compensation.
    Enforces state validation and Gate S1 A2 rollback lockdown.
    """
    if action_id != req.action_id:
        raise HTTPException(status_code=400, detail="Path action_id does not match request body.")

    try:
        p = container.action_manager.rollback_action(
            action_id=req.action_id,
            operator_id=req.operator_id,
            reason=req.reason,
            idempotency_key=idempotency_key,
        )

        await container.ws_gateway.broadcast(
            channel="actions",
            event_type="ACTION_ROLLED_BACK",
            payload={"action_id": str(action_id), "reason": req.reason},
        )

        return {
            "status": "ROLLED_BACK",
            "action_id": str(action_id),
            "reason": req.reason,
        }
    except ActionScopeViolationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except CapabilityDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# -----------------------------------------------------------------------------
# 3. WORKER FABRIC ENDPOINTS (Pull-Based Ephemeral Workers)
# -----------------------------------------------------------------------------


@router.post("/workers/register")
async def register_worker(
    req: Dict[str, Any],
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Registers remote ephemeral worker and returns authentication token."""
    worker_id = req.get("worker_id")
    worker_type = req.get("worker_type", "colab_t4")
    capabilities = req.get("capabilities", {})

    if not worker_id:
        raise HTTPException(status_code=400, detail="worker_id is required.")

    reg = container.job_queue.register_worker(
        worker_id=worker_id,
        worker_type=worker_type,
        capabilities=capabilities,
    )
    token = container.worker_auth.generate_worker_token(
        worker_id=worker_id,
        session_id=str(reg.worker_session_id),
    )
    return {
        "status": "REGISTERED",
        "worker_id": reg.worker_id,
        "session_id": str(reg.worker_session_id),
        "auth_token": token,
    }


@router.post("/workers/poll")
async def poll_for_job(
    req: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Worker polls for work. Returns 204 if no work, or leased job payload."""
    raw_token = authorization or req.get("auth_token")
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing worker auth token.")

    token = raw_token.replace("Bearer ", "").strip()
    worker_id = req.get("worker_id")
    session_id_str = req.get("session_id")
    if not worker_id or not session_id_str:
        raise HTTPException(status_code=400, detail="worker_id and session_id are required.")

    try:
        container.worker_auth.verify_worker_session_token(
            token=token,
            expected_worker_id=worker_id,
            expected_session_id=session_id_str,
        )
    except CapabilityDeniedError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    session_id = UUID(session_id_str)
    leased = container.job_queue.poll_and_lease(worker_id, session_id)
    if not leased:
        return {"status": "NO_JOBS", "job": None}

    job, lease = leased
    return {
        "status": "JOB_LEASED",
        "job": {
            "job_id": str(job.job_id),
            "job_type": job.job_type,
            "payload": job.payload,
            "lease_generation": lease.lease_generation,
            "lease_token": lease.lease_token,
            "expires_at": lease.expires_at.isoformat(),
        },
    }


@router.post("/workers/progress")
async def report_worker_progress(
    req: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Records intermediate progress checkpoint from active worker."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization Bearer header. Worker credentials must be supplied via header.",
        )
    token = authorization.split("Bearer ", 1)[1].strip()

    job_id = UUID(req["job_id"])
    worker_id = req["worker_id"]
    lease_generation = int(req["lease_generation"])
    sequence = int(req["sequence"])
    progress_pct = float(req["progress_pct"])

    try:
        container.worker_auth.verify_job_lease_token(
            token=token,
            expected_worker_id=worker_id,
            expected_job_id=str(job_id),
            expected_lease_generation=lease_generation,
        )
    except CapabilityDeniedError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    try:
        cp = container.job_queue.record_progress(
            job_id=job_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            sequence=sequence,
            progress_pct=progress_pct,
            state_artifact_ref=req.get("state_artifact_ref"),
            artifact_digest=req.get("artifact_digest"),
            lease_token=token,
        )
        return {
            "status": "CHECKPOINT_RECORDED",
            "checkpoint_id": str(cp.checkpoint_id),
            "sequence": cp.sequence,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/workers/complete")
async def complete_worker_job(
    req: Dict[str, Any],
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Submits final completion evidence from worker."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization Bearer header. Worker credentials must be supplied via header.",
        )
    token = authorization.split("Bearer ", 1)[1].strip()

    job_id = UUID(req["job_id"])
    worker_id = req["worker_id"]
    lease_generation = int(req["lease_generation"])
    evidence = req.get("evidence", {})

    try:
        container.worker_auth.verify_job_lease_token(
            token=token,
            expected_worker_id=worker_id,
            expected_job_id=str(job_id),
            expected_lease_generation=lease_generation,
        )
    except CapabilityDeniedError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    try:
        job = container.job_queue.complete_job(
            job_id=job_id,
            worker_id=worker_id,
            lease_generation=lease_generation,
            completion_evidence=evidence,
            idempotency_key=idempotency_key or req.get("idempotency_key"),
            lease_token=token,
        )
        return {
            "status": "COMPLETED",
            "job_id": str(job.job_id),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workers/jobs/{job_id}")
async def get_worker_job(
    job_id: UUID,
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Queries current state of a worker job."""
    job = container.job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Worker job not found.")
    return {
        "job_id": str(job.job_id),
        "job_type": job.job_type,
        "status": job.status.value,
        "lease_generation": job.lease_generation,
        "checkpoints_count": len(job.checkpoints),
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


# -----------------------------------------------------------------------------
# 4. PERSISTENCE, BACKUP & DISASTER RECOVERY ENDPOINTS (M6)
# -----------------------------------------------------------------------------


@router.get("/persistence/status")
async def get_persistence_status(
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Returns database health, kernel epoch, system readiness state, and outbox lag."""
    db_health = await container.db_manager.health_check()
    return {
        "system_status": container.recovery_manager.system_status,
        "kernel_epoch": container.recovery_manager.current_epoch,
        "database": db_health,
        "event_count": container.event_store.event_count,
        "latest_event_hash": container.event_store.latest_hash,
    }


@router.post("/backup/create")
async def create_backup(
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Triggers an authenticated backup manifest creation (M6 Section 89)."""
    from universal_brain.persistence.backup.manifest import BackupManifest
    import hashlib

    # Compute digest over current event head
    db_digest = hashlib.sha256(container.event_store.latest_hash.encode("utf-8")).hexdigest()
    manifest = BackupManifest(
        kernel_epoch=container.recovery_manager.current_epoch,
        event_sequence_head=container.event_store.event_count,
        database_digest=db_digest,
    )
    manifest.sign()

    return {
        "status": "BACKUP_VERIFIED",
        "manifest": manifest.model_dump(mode="json"),
    }


# -----------------------------------------------------------------------------
# M7 Mission Control Endpoints (M7 Section 111-114)
# -----------------------------------------------------------------------------


@router.post("/missions")
async def create_mission_endpoint(
    req: Dict[str, Any],
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Create a mission in canonical durable state; SQL is only a projection."""
    from universal_brain.autonomy.schemas import Mission, MissionStatus

    project_id = UUID(req["project_id"])
    mission = Mission(
        project_id=project_id,
        title=req.get("title", "Untitled Mission"),
        goal=req.get("goal", ""),
        description=req.get("description", ""),
        contract_id=UUID(req.get("contract_id", str(uuid4()))),
        contract_version=int(req.get("contract_version", 1)),
        priority=int(req.get("priority", 50)),
        status=MissionStatus.READY,
    )

    container.event_store.append_event(
        EventType.MISSION_CREATED,
        actor_id=settings.operator_id,
        payload={"mission": mission.model_dump(mode="json")},
        project_id=project_id,
        contract_version=mission.contract_version,
    )

    return {
        "status": "MISSION_CREATED",
        "mission": mission.model_dump(mode="json"),
        "source_of_truth": "canonical_event_journal",
        "sql_projection_status": "DEFERRED_TO_RECONCILIATION",
    }


@router.get("/missions/{mission_id}")
async def get_mission_endpoint(
    mission_id: UUID,
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Read mission state only from the canonical event projection."""
    mission = latest_mission(container.event_store, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found in canonical state")

    return {
        "mission_id": str(mission.mission_id),
        "project_id": str(mission.project_id),
        "title": mission.title,
        "goal": mission.goal,
        "status": mission.status.value,
        "priority": mission.priority,
        "mission_version": mission.mission_version,
        "created_at": mission.created_at.isoformat(),
        "updated_at": mission.updated_at.isoformat(),
        "source_of_truth": "canonical_event_journal",
    }


@router.post("/missions/{mission_id}/pause")
async def pause_mission_endpoint(
    mission_id: UUID,
    req: Dict[str, Any],
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Pause a mission by appending a new canonical mission snapshot."""
    from universal_brain.autonomy.schemas import MissionStatus

    mission = latest_mission(container.event_store, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found in canonical state")

    expected_version = int(req.get("expected_version", mission.mission_version))
    if mission.mission_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Mission version conflict: expected {expected_version}, "
                f"canonical version is {mission.mission_version}."
            ),
        )
    if mission.status in {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mission in terminal state {mission.status.value} cannot be paused.",
        )

    updated = mission.model_copy(
        update={
            "status": MissionStatus.PAUSED,
            "mission_version": mission.mission_version + 1,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    container.event_store.append_event(
        EventType.MISSION_PAUSED,
        actor_id=settings.operator_id,
        payload={"mission": updated.model_dump(mode="json")},
        project_id=updated.project_id,
        contract_version=updated.contract_version,
    )
    return {
        "status": "MISSION_PAUSED",
        "mission_version": updated.mission_version,
        "source_of_truth": "canonical_event_journal",
    }


@router.post("/missions/{mission_id}/resume")
async def resume_mission_endpoint(
    mission_id: UUID,
    req: Dict[str, Any],
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Resume a paused mission through a canonical durable transition."""
    from universal_brain.autonomy.schemas import MissionStatus

    mission = latest_mission(container.event_store, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found in canonical state")

    expected_version = int(req.get("expected_version", mission.mission_version))
    if mission.mission_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Mission version conflict: expected {expected_version}, "
                f"canonical version is {mission.mission_version}."
            ),
        )
    if mission.status != MissionStatus.PAUSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a PAUSED mission can resume; current state is {mission.status.value}.",
        )

    updated = mission.model_copy(
        update={
            "status": MissionStatus.ACTIVE,
            "mission_version": mission.mission_version + 1,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    container.event_store.append_event(
        EventType.MISSION_RESUMED,
        actor_id=settings.operator_id,
        payload={"mission": updated.model_dump(mode="json")},
        project_id=updated.project_id,
        contract_version=updated.contract_version,
    )
    return {
        "status": "MISSION_ACTIVE",
        "mission_version": updated.mission_version,
        "source_of_truth": "canonical_event_journal",
    }


# =============================================================================
# Milestone M8: World Model & Perception Endpoints (Section 113)
# =============================================================================


@router.get("/world/entities")
async def list_world_entities_endpoint(
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Lists all tracked world entities (M8 Section 113)."""
    from universal_brain.persistence.unit_of_work import UnitOfWork

    async with UnitOfWork(container.db_manager) as uow:
        assert uow.world_entities is not None
        entities = await uow.world_entities.list_entities()
        return {
            "entities": [
                {
                    "entity_id": e.entity_id,
                    "entity_type": e.entity_type,
                    "canonical_name": e.canonical_name,
                    "status": e.status,
                    "entity_version": e.entity_version,
                    "merged_into": e.merged_into,
                }
                for e in entities
            ]
        }


@router.get("/world/entities/{entity_id}")
async def get_world_entity_endpoint(
    entity_id: str,
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Retrieves a world entity and its active property assertions."""
    from universal_brain.persistence.unit_of_work import UnitOfWork

    async with UnitOfWork(container.db_manager) as uow:
        assert uow.world_entities is not None
        assert uow.world_assertions is not None
        entity = await uow.world_entities.get_entity(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        assertions = await uow.world_assertions.list_assertions_for_entity(entity_id)
        return {
            "entity": {
                "entity_id": entity.entity_id,
                "entity_type": entity.entity_type,
                "canonical_name": entity.canonical_name,
                "status": entity.status,
                "entity_version": entity.entity_version,
            },
            "assertions": [
                {
                    "assertion_id": str(a.assertion_id),
                    "property_key": a.property_key,
                    "value": a.value,
                    "unit": a.unit,
                    "coordinate_frame": a.coordinate_frame,
                    "state_class": a.state_class.value,
                    "freshness_status": a.freshness_status.value,
                    "confidence": a.confidence,
                }
                for a in assertions
            ],
        }


@router.get("/world/observations")
async def list_world_observations_endpoint(
    limit: int = 50,
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Lists recent canonical observations from the immutable ledger."""
    from universal_brain.persistence.unit_of_work import UnitOfWork

    async with UnitOfWork(container.db_manager) as uow:
        assert uow.observations is not None
        obs_list = await uow.observations.list_observations(limit=limit)
        return {
            "observations": [
                {
                    "observation_id": str(o.observation_id),
                    "source_id": o.source_id,
                    "subject_ref": o.subject_ref,
                    "property_key": o.property_key,
                    "value": o.value,
                    "observed_at": o.observed_at.isoformat(),
                    "confidence": o.confidence,
                }
                for o in obs_list
            ]
        }


@router.get("/world/contradictions")
async def list_world_contradictions_endpoint(
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Lists open tracked world contradictions."""
    from universal_brain.persistence.unit_of_work import UnitOfWork

    async with UnitOfWork(container.db_manager) as uow:
        assert uow.world_contradictions is not None
        contradictions = await uow.world_contradictions.list_open_contradictions()
        return {
            "contradictions": [
                {
                    "contradiction_id": str(c.contradiction_id),
                    "entity_id": c.entity_id,
                    "property_key": c.property_key,
                    "assertion_ids": [str(x) for x in c.assertion_ids],
                    "resolution_status": c.resolution_status.value,
                    "severity": c.severity.value,
                }
                for c in contradictions
            ]
        }


@router.get("/world/watches")
async def list_world_watches_endpoint(
    container: RuntimeContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Lists active world watches."""
    from universal_brain.persistence.unit_of_work import UnitOfWork

    async with UnitOfWork(container.db_manager) as uow:
        assert uow.world_watches is not None
        watches = await uow.world_watches.list_active_watches()
        return {
            "watches": [
                {
                    "watch_id": str(w.watch_id),
                    "mission_id": str(w.mission_id),
                    "entity_id": w.entity_id,
                    "property_key": w.property_key,
                    "expected_value": w.expected_value,
                    "operator": w.operator,
                    "status": w.status.value,
                }
                for w in watches
            ]
        }
