"""
Universal Brain - Reversible Tool Gateway

Implements ADR-0002, ADR-0008, and Invariants ALN-004, ALN-007, ALN-008,
ALN-009, ALN-014, ALN-016, ALN-018.
The single point of execution for all external actions. Validates capability tokens,
contract bounds, preflight reversibility, and records tamper-evident audit events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from universal_brain.alignment.contract import (
    AlignmentContract,
    AmbiguityImpact,
    ContractStatus,
)
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.kernel.capability import CapabilityService, CapabilityToken
from universal_brain.kernel.errors import (
    ActionScopeViolationError,
    ActuatorProhibitedError,
    CapabilityDeniedError,
    RollbackPreflightError,
)
from universal_brain.kernel.event_store import EventStore
from universal_brain.kernel.events import (
    ActionClass,
    EventType,
    RelationType,
)
from universal_brain.memory.retention import StorageRetentionManager
from universal_brain.tools.base import BaseTool, ToolResult


_ACTION_CLASS_ORDER = {
    ActionClass.A0: 0,
    ActionClass.A1: 1,
    ActionClass.A2: 2,
    ActionClass.A3: 3,
}


class ToolGateway:
    """Central gateway enforcing security, capability, reversibility, and audit logging."""

    def __init__(
        self,
        event_store: EventStore,
        capability_service: CapabilityService,
        budget_gatekeeper: Optional[BudgetGatekeeper] = None,
        retention_manager: Optional[StorageRetentionManager] = None,
    ) -> None:
        self.store = event_store
        self.capability_service = capability_service
        self.budget = budget_gatekeeper or BudgetGatekeeper()
        self.retention = retention_manager or StorageRetentionManager()
        self._registry: Dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._registry[tool.name] = tool

    @staticmethod
    def _assert_contract_executable(contract: AlignmentContract) -> None:
        """Reassert alignment authority at the final execution boundary."""
        if contract.status != ContractStatus.ACTIVE:
            raise ActionScopeViolationError(
                f"Tool execution requires an ACTIVE Alignment Contract; got '{contract.status.value}'."
            )

        blocking = [
            ambiguity
            for ambiguity in contract.ambiguities
            if ambiguity.impact == AmbiguityImpact.HIGH
            and ambiguity.resolution_status not in {"answered"}
        ]
        if blocking:
            ids = ", ".join(item.ambiguity_id for item in blocking)
            raise ActionScopeViolationError(
                "ALN-004: HIGH-impact ambiguity blocks execution until explicitly answered: "
                f"{ids}"
            )

        expires_at = contract.permissions.expires_at
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise ActionScopeViolationError(
                f"Contract permissions expired at {expires_at.isoformat()}; execution is denied."
            )

    @staticmethod
    def _assert_token_action_class(
        capability_token: CapabilityToken,
        required_action_class: ActionClass,
    ) -> None:
        """Enforce the token's documented maximum action-class ceiling."""
        if _ACTION_CLASS_ORDER[required_action_class] > _ACTION_CLASS_ORDER[capability_token.action_class]:
            raise CapabilityDeniedError(
                f"Capability token action ceiling ({capability_token.action_class.value}) does not authorize "
                f"tool action class ({required_action_class.value})."
            )

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
        """Execute a registered tool only after all final-boundary checks pass."""
        tool = self._registry.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' is not registered in Tool Gateway.")

        self._assert_contract_executable(contract)

        if tool.action_class == ActionClass.A3:
            raise ActuatorProhibitedError(
                f"Tool '{tool_name}' is classified as A3 (Prohibited Actuator Control) and is denied."
            )

        self._assert_token_action_class(capability_token, tool.action_class)

        effective_target = "*"
        for key in ("target", "path", "file_path", "filename", "resource"):
            if key in args and isinstance(args[key], str):
                effective_target = args[key]
                break

        from universal_brain.kernel.capability import (
            compute_canonical_request_digest,
            is_resource_authorized,
        )

        if target_resource != "*" and effective_target != "*" and target_resource != effective_target:
            if not is_resource_authorized(target_resource, effective_target):
                raise CapabilityDeniedError(
                    f"Gateway target_resource '{target_resource}' conflicts with tool argument target '{effective_target}'."
                )

        computed_digest = None
        if capability_token.request_digest is not None:
            computed_digest = compute_canonical_request_digest(
                tool_name=tool_name,
                args=args,
                action_class=tool.action_class,
                contract_id=contract.contract_id,
                contract_version=contract.version,
                task_id=capability_token.task_id,
                idempotency_key=capability_token.idempotency_key,
            )

        self.capability_service.verify_token(
            token=capability_token,
            target_resource=effective_target if effective_target != "*" else target_resource,
            required_operation=tool_name,
            current_contract_id=contract.contract_id,
            current_contract_version=contract.version,
            expected_request_digest=computed_digest,
            required_action_class=tool.action_class,
        )

        if _ACTION_CLASS_ORDER[tool.action_class] > _ACTION_CLASS_ORDER[contract.permissions.action_ceiling]:
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
                "contract_id": str(contract.contract_id),
                "reversibility_class": getattr(tool, "reversibility_class", "UNKNOWN"),
            },
        )

        result = tool.execute(args)

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
                "contract_id": str(contract.contract_id),
                "reversibility_class": getattr(result, "reversibility_class", "UNKNOWN"),
                "pre_digest": getattr(result, "pre_digest", None),
                "post_digest": getattr(result, "post_digest", None),
            },
            caused_by_event_id=call_event.event_id,
        )
        self.store.add_edge(
            source_event_id=evidence_event.event_id,
            target_event_id=call_event.event_id,
            relation_type=RelationType.PROVES,
        )

        result.evidence = dict(result.evidence or {})
        result.evidence.setdefault("tool_call_event_id", str(call_event.event_id))
        result.evidence.setdefault("evidence_event_id", str(evidence_event.event_id))
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
        """Execute formal rollback only with current contract and cryptographic authority."""
        tool = self._registry.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' is not registered in Tool Gateway.")

        self._assert_contract_executable(contract)

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

        if isinstance(capability_token, RollbackGrant):
            self.capability_service.verify_rollback_grant(
                grant=capability_token,
                tool_name=tool_name,
                target_resource=effective_target,
            )
            project_id = capability_token.project_id
            task_id = capability_token.task_id
        else:
            self._assert_token_action_class(capability_token, tool.action_class)
            req_op = tool_name
            if capability_token.allowed_operations and "rollback" in capability_token.allowed_operations:
                req_op = "rollback"
            elif capability_token.allowed_operations and "*" in capability_token.allowed_operations:
                req_op = "*"
            self.capability_service.verify_token(
                token=capability_token,
                target_resource=effective_target,
                required_operation=req_op,
                current_contract_id=contract.contract_id,
                current_contract_version=contract.version,
                required_action_class=tool.action_class,
            )
            project_id = capability_token.project_id
            task_id = capability_token.task_id

        success = tool.rollback(rollback_data)

        if success:
            rb_event = self.store.append_event(
                event_type=EventType.ROLLBACK_EXECUTED,
                actor_id=actor_id,
                project_id=project_id,
                task_id=task_id,
                contract_version=contract.version,
                payload={
                    "tool_name": tool_name,
                    "status": "ROLLBACK_COMPLETED",
                    "contract_id": str(contract.contract_id),
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

        self.store.append_event(
            event_type=EventType.SYSTEM_FAILURE,
            actor_id=actor_id,
            project_id=project_id,
            task_id=task_id,
            contract_version=contract.version,
            payload={
                "tool_name": tool_name,
                "status": "ROLLBACK_FAILED",
                "contract_id": str(contract.contract_id),
                "error": "Tool rollback method returned False.",
            },
            caused_by_event_id=original_call_event_id,
        )
        return False
