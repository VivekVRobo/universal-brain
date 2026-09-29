"""
Universal Brain - Reversible Tool Gateway

Implements ADR-0002, ADR-0008, and Invariants ALN-007, ALN-008, ALN-014, ALN-016, ALN-018.
The single point of execution for all external actions. Validates capability tokens,
contract bounds, preflight reversibility, and records tamper-evident audit events.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from universal_brain.alignment.contract import AlignmentContract
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.kernel.capability import (
    CapabilityService,
    CapabilityToken,
    compute_canonical_request_digest,
    is_resource_authorized,
)
from universal_brain.kernel.errors import (
    ActionScopeViolationError,
    ActuatorProhibitedError,
    CapabilityDeniedError,
    OperationOutcomeUncertainError,
    RollbackPreflightError,
)
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import (
    ActionClass,
    EventType,
    RelationType,
)
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.tools.base import BaseTool, ReconciliationStatus, ToolResult
from universal_brain.tools.operation_ledger import DurableOperationLedger, OperationState


class ToolGateway:
    """Central gateway enforcing security, capability, reversibility, and audit logging."""

    def __init__(
        self,
        event_store: EventStore,
        capability_service: CapabilityService,
        budget_gatekeeper: Optional[BudgetGatekeeper] = None,
        retention_manager: Optional[StorageRetentionManager] = None,
        operation_ledger: Optional[DurableOperationLedger] = None,
    ) -> None:
        self.store = event_store
        self.capability_service = capability_service
        self.budget = budget_gatekeeper or BudgetGatekeeper()
        self.retention = retention_manager or StorageRetentionManager()
        self.operation_ledger = operation_ledger
        self._registry: Dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._registry[tool.name] = tool

    def _record_execution_evidence(
        self,
        *,
        tool_name: str,
        result: ToolResult,
        capability_token: CapabilityToken,
        contract: AlignmentContract,
        call_event_id: Optional[UUID],
        operation_id: Optional[str] = None,
        reconciled: bool = False,
    ) -> ToolResult:
        """Persist deterministic evidence without repeating the external effect."""

        cause = None
        if call_event_id is not None and self.store.get_event(call_event_id) is not None:
            cause = call_event_id

        evidence_event = self.store.append_event(
            event_type=EventType.EVIDENCE_PRODUCED,
            actor_id="tool_gateway",
            project_id=capability_token.project_id,
            task_id=capability_token.task_id,
            contract_version=contract.version,
            payload={
                "tool_name": tool_name,
                "success": result.success,
                "evidence": result.evidence,
                "reversibility_class": getattr(result, "reversibility_class", "UNKNOWN"),
                "pre_digest": getattr(result, "pre_digest", None),
                "post_digest": getattr(result, "post_digest", None),
                "operation_id": operation_id,
                "reconciled": reconciled,
            },
            caused_by_event_id=cause,
        )
        if cause is not None:
            self.store.add_edge(
                source_event_id=evidence_event.event_id,
                target_event_id=cause,
                relation_type=RelationType.PROVES,
            )

        result.evidence = dict(result.evidence or {})
        if cause is not None:
            result.evidence.setdefault("tool_call_event_id", str(cause))
        result.evidence.setdefault("evidence_event_id", str(evidence_event.event_id))
        if operation_id is not None:
            result.evidence.setdefault("operation_id", operation_id)
        if reconciled:
            result.evidence.setdefault("reconciled_after_interruption", True)
        return result

    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        capability_token: CapabilityToken,
        contract: AlignmentContract,
        actor_id: str = "agent",
        target_resource: str = "*",
        caused_by_event_id: Optional[UUID] = None,
    ) -> ToolResult:
        """
        Execute a registered tool inside authority, reversibility, audit, and
        optional durable operation recovery boundaries.

        When a durable operation ledger and idempotency key are available, an
        interrupted state changing action is reconciled before any retry.
        """
        tool = self._registry.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' is not registered in Tool Gateway.")

        if tool.action_class == ActionClass.A3:
            raise ActuatorProhibitedError(
                f"Tool '{tool_name}' is classified as A3 (Prohibited Actuator Control) and is denied."
            )

        effective_target = "*"
        for key in ("target", "path", "file_path", "filename", "resource"):
            if key in args and isinstance(args[key], str):
                effective_target = args[key]
                break

        if target_resource != "*" and effective_target != "*" and target_resource != effective_target:
            if not is_resource_authorized(target_resource, effective_target):
                raise CapabilityDeniedError(
                    f"Gateway target_resource '{target_resource}' conflicts with tool argument target '{effective_target}'."
                )

        canonical_digest = compute_canonical_request_digest(
            tool_name=tool_name,
            args=args,
            action_class=tool.action_class,
            contract_version=contract.version,
            task_id=capability_token.task_id,
            idempotency_key=capability_token.idempotency_key,
        )

        self.capability_service.verify_token(
            token=capability_token,
            target_resource=effective_target if effective_target != "*" else target_resource,
            required_operation=tool_name,
            current_contract_version=contract.version,
            expected_request_digest=(
                canonical_digest if capability_token.request_digest is not None else None
            ),
        )

        class_order = {"A0": 0, "A1": 1, "A2": 2, "A3": 3}
        if class_order[tool.action_class.value] > class_order[contract.permissions.action_ceiling.value]:
            raise ActionScopeViolationError(
                f"Tool '{tool_name}' action class ({tool.action_class.value}) exceeds "
                f"contract permissions ceiling ({contract.permissions.action_ceiling.value})."
            )

        self.budget.check_authorization(tool.action_class.value)
        self.retention.assert_write_permitted(tool.action_class.value)

        if not tool.preflight_check(args):
            raise RollbackPreflightError(
                f"Preflight reversibility check failed for tool '{tool_name}' with args {args}."
            )

        operation = None
        durable_target = effective_target if effective_target != "*" else target_resource
        if self.operation_ledger is not None and capability_token.idempotency_key:
            operation = self.operation_ledger.prepare(
                project_id=capability_token.project_id,
                task_id=capability_token.task_id,
                tool_name=tool_name,
                target_resource=durable_target,
                idempotency_key=capability_token.idempotency_key,
                request_digest=canonical_digest,
            )

            if operation.state == OperationState.EVIDENCE_COMMITTED:
                if operation.result is None:
                    raise OperationOutcomeUncertainError(
                        f"Operation {operation.operation_id} is marked complete without a stored result."
                    )
                cached = operation.result.model_copy(deep=True)
                cached.evidence = dict(cached.evidence or {})
                cached.evidence.setdefault("operation_id", operation.operation_id)
                cached.evidence.setdefault("reused_durable_result", True)
                return cached

            if operation.state == OperationState.EFFECT_CONFIRMED:
                if operation.result is None:
                    raise OperationOutcomeUncertainError(
                        f"Operation {operation.operation_id} has confirmed effect without a stored result."
                    )
                recovered = operation.result.model_copy(deep=True)
                recovered = self._record_execution_evidence(
                    tool_name=tool_name,
                    result=recovered,
                    capability_token=capability_token,
                    contract=contract,
                    call_event_id=operation.call_event_id,
                    operation_id=operation.operation_id,
                    reconciled=True,
                )
                self.operation_ledger.mark_evidence_committed(
                    operation.operation_id,
                    evidence_event_id=UUID(recovered.evidence["evidence_event_id"]),
                )
                return recovered

            if operation.state in {OperationState.EXECUTING, OperationState.IN_DOUBT}:
                reconciliation = tool.reconcile(args, operation.operation_id)
                if reconciliation.status == ReconciliationStatus.CONFIRMED:
                    if reconciliation.result is None:
                        self.operation_ledger.mark_in_doubt(
                            operation.operation_id,
                            error="tool reconciliation confirmed an effect without a result",
                        )
                        raise OperationOutcomeUncertainError(
                            f"Operation {operation.operation_id} was observed but its result cannot be reconstructed."
                        )
                    operation = self.operation_ledger.mark_effect_confirmed(
                        operation.operation_id,
                        result=reconciliation.result,
                    )
                    recovered = reconciliation.result.model_copy(deep=True)
                    recovered = self._record_execution_evidence(
                        tool_name=tool_name,
                        result=recovered,
                        capability_token=capability_token,
                        contract=contract,
                        call_event_id=operation.call_event_id,
                        operation_id=operation.operation_id,
                        reconciled=True,
                    )
                    self.operation_ledger.mark_evidence_committed(
                        operation.operation_id,
                        evidence_event_id=UUID(recovered.evidence["evidence_event_id"]),
                    )
                    return recovered

                if reconciliation.status == ReconciliationStatus.UNKNOWN:
                    detail = reconciliation.detail or "tool could not determine prior execution outcome"
                    self.operation_ledger.mark_in_doubt(
                        operation.operation_id,
                        error=detail,
                    )
                    raise OperationOutcomeUncertainError(
                        f"Operation {operation.operation_id} cannot be safely replayed: {detail}"
                    )

                # ABSENT means the tool proved the prior external effect did not occur.
                # A fresh execution may proceed under the same durable operation identity.

        call_event = self.store.append_event(
            event_type=EventType.TOOL_CALLED,
            actor_id=actor_id,
            project_id=capability_token.project_id,
            task_id=capability_token.task_id,
            contract_version=contract.version,
            caused_by_event_id=caused_by_event_id,
            payload={
                "tool_name": tool_name,
                "action_class": tool.action_class.value,
                "target_resource": target_resource,
                "token_id": str(capability_token.token_id),
                "reversibility_class": getattr(tool, "reversibility_class", "UNKNOWN"),
                "operation_id": operation.operation_id if operation is not None else None,
            },
        )

        if operation is not None:
            operation = self.operation_ledger.mark_executing(
                operation.operation_id,
                call_event_id=call_event.event_id,
            )

        try:
            result = tool.execute(args)
        except BaseException as exc:
            if operation is not None:
                self.operation_ledger.mark_in_doubt(
                    operation.operation_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise

        if operation is not None:
            operation = self.operation_ledger.mark_effect_confirmed(
                operation.operation_id,
                result=result,
            )

        result = self._record_execution_evidence(
            tool_name=tool_name,
            result=result,
            capability_token=capability_token,
            contract=contract,
            call_event_id=call_event.event_id,
            operation_id=operation.operation_id if operation is not None else None,
            reconciled=False,
        )

        if operation is not None:
            self.operation_ledger.mark_evidence_committed(
                operation.operation_id,
                evidence_event_id=UUID(result.evidence["evidence_event_id"]),
            )

        return result

    def rollback_tool(
        self,
        tool_name: str,
        rollback_data: Dict[str, Any],
        capability_token: Any,
        contract: AlignmentContract,
        actor_id: str = "operator",
        original_call_event_id: Optional[UUID] = None,
    ) -> bool:
        """
        Executes formal rollback of an A1 action and records tamper-evident audit trail.
        (M5 Section 70, 71, Invariants ALN-007, ALN-016, M5-INV-04).
        Enforces cryptographic verification of capability token or rollback grant.
        """
        tool = self._registry.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' is not registered in Tool Gateway.")

        # Determine effective target from rollback data
        effective_target = "*"
        if "checkpoint" in rollback_data and isinstance(rollback_data["checkpoint"], dict):
            cp = rollback_data["checkpoint"]
            if "targets" in cp and cp["targets"]:
                effective_target = cp["targets"][0]
            else:
                effective_target = cp.get("target_path") or cp.get("target_resource") or cp.get("target") or "*"
        elif "target" in rollback_data:
            effective_target = str(rollback_data["target"])
        elif "target_resource" in rollback_data:
            effective_target = str(rollback_data["target_resource"])

        if effective_target == "*" and hasattr(capability_token, "target_resource"):
            effective_target = capability_token.target_resource

        from universal_brain.kernel.capability import RollbackGrant

        # Cryptographic authority verification (Gate S1)
        if isinstance(capability_token, RollbackGrant):
            self.capability_service.verify_rollback_grant(
                grant=capability_token,
                tool_name=tool_name,
                target_resource=effective_target,
            )
            project_id = capability_token.project_id
            task_id = capability_token.task_id
        else:
            req_op = tool_name
            if capability_token.allowed_operations and "rollback" in capability_token.allowed_operations:
                req_op = "rollback"
            elif capability_token.allowed_operations and "*" in capability_token.allowed_operations:
                req_op = "*"
            self.capability_service.verify_token(
                token=capability_token,
                target_resource=effective_target,
                required_operation=req_op,
                current_contract_version=contract.version,
            )
            project_id = capability_token.project_id
            task_id = capability_token.task_id

        success = tool.rollback(rollback_data)

        if success:
            rb_event = self.store.append_event(
                event_type=EventType.ROLLBACK_EXECUTED,
                actor_id=actor_id,
                project_id=capability_token.project_id,
                task_id=capability_token.task_id,
                contract_version=contract.version,
                payload={
                    "tool_name": tool_name,
                    "status": "ROLLBACK_COMPLETED",
                    "rollback_data_keys": list(rollback_data.keys()),
                },
                caused_by_event_id=original_call_event_id,
            )
            if original_call_event_id:
                self.store.add_edge(
                    source_event_id=rb_event.event_id,
                    target_event_id=original_call_event_id,
                    relation_type=RelationType.INVALIDATES,
                )
            return True
        else:
            self.store.append_event(
                event_type=EventType.SYSTEM_FAILURE,
                actor_id=actor_id,
                project_id=capability_token.project_id,
                task_id=capability_token.task_id,
                contract_version=contract.version,
                payload={
                    "tool_name": tool_name,
                    "status": "ROLLBACK_FAILED",
                    "error": "Tool rollback method returned False.",
                },
                caused_by_event_id=original_call_event_id,
            )
            return False
