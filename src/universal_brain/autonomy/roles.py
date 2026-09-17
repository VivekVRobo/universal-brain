"""
Universal Brain - Agent Role Registry & Profiles

Implements M7 Sections 22-24 and Invariant M7-INV-03:
- Functional role taxonomy (ARCHITECT, RESEARCHER, BUILDER, VERIFIER, etc.);
- Functional profiles describing cognitive operations, preferred models, and tool scopes;
- Strict invariant: ROLE DOES NOT GRANT CAPABILITY. Authority is capability-token based.
"""

from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel, Field

from universal_brain.autonomy.schemas import AgentRole
from universal_brain.kernel.events import ActionClass


class RoleProfile(BaseModel):
    """Specification of responsibilities and scope for an Agent Role (M7 Section 23)."""

    model_config = {"frozen": True}

    role: AgentRole
    cognitive_responsibilities: List[str]
    preferred_model_capabilities: List[str]
    allowed_tool_categories: List[str]
    default_evidence_expectations: List[str]
    maximum_recommended_action_class: ActionClass = ActionClass.A1


class AgentRoleRegistry:
    """Canonical registry mapping functional agent roles to execution profiles."""

    DEFAULT_PROFILES: Dict[AgentRole, RoleProfile] = {
        AgentRole.ARCHITECT: RoleProfile(
            role=AgentRole.ARCHITECT,
            cognitive_responsibilities=["System decomposition", "Interface specification", "Invariant formulation"],
            preferred_model_capabilities=["deep_reasoning", "structured_json"],
            allowed_tool_categories=["read", "search"],
            default_evidence_expectations=["architecture_decision_record", "interface_schema"],
            maximum_recommended_action_class=ActionClass.A0,
        ),
        AgentRole.RESEARCHER: RoleProfile(
            role=AgentRole.RESEARCHER,
            cognitive_responsibilities=["Information retrieval", "External documentation", "Empirical measurement"],
            preferred_model_capabilities=["web_search", "document_extraction"],
            allowed_tool_categories=["search", "read", "http"],
            default_evidence_expectations=["source_url_digest", "retrieved_artifact_digest"],
            maximum_recommended_action_class=ActionClass.A0,
        ),
        AgentRole.PLANNER: RoleProfile(
            role=AgentRole.PLANNER,
            cognitive_responsibilities=["DAG generation", "Dependency scheduling", "Milestone definition"],
            preferred_model_capabilities=["planning", "constraint_satisfaction"],
            allowed_tool_categories=["read"],
            default_evidence_expectations=["task_dag_digest"],
            maximum_recommended_action_class=ActionClass.A0,
        ),
        AgentRole.BUILDER: RoleProfile(
            role=AgentRole.BUILDER,
            cognitive_responsibilities=["Code synthesis", "File mutation", "Test generation"],
            preferred_model_capabilities=["code_generation", "patch_diffing"],
            allowed_tool_categories=["workspace_sandbox", "command_runner", "read"],
            default_evidence_expectations=["patch_digest", "workspace_checkpoint_ref"],
            maximum_recommended_action_class=ActionClass.A1,
        ),
        AgentRole.VERIFIER: RoleProfile(
            role=AgentRole.VERIFIER,
            cognitive_responsibilities=["Independent evidence validation", "Criterion evaluation", "Integrity assertion"],
            preferred_model_capabilities=["rigorous_critique", "test_evaluation"],
            allowed_tool_categories=["read", "test_runner"],
            default_evidence_expectations=["verification_report_digest", "test_output_hash"],
            maximum_recommended_action_class=ActionClass.A0,
        ),
        AgentRole.TESTER: RoleProfile(
            role=AgentRole.TESTER,
            cognitive_responsibilities=["Test execution", "Edge case generation", "Fuzzing"],
            preferred_model_capabilities=["test_automation", "failure_analysis"],
            allowed_tool_categories=["command_runner", "read"],
            default_evidence_expectations=["pytest_log_digest"],
            maximum_recommended_action_class=ActionClass.A1,
        ),
        AgentRole.REVIEWER: RoleProfile(
            role=AgentRole.REVIEWER,
            cognitive_responsibilities=["Code review", "Style compliance", "Security audit"],
            preferred_model_capabilities=["code_review", "security_scanning"],
            allowed_tool_categories=["read"],
            default_evidence_expectations=["review_comments_digest"],
            maximum_recommended_action_class=ActionClass.A0,
        ),
        AgentRole.OBSERVER: RoleProfile(
            role=AgentRole.OBSERVER,
            cognitive_responsibilities=["Health monitoring", "External service telemetry", "Progress logging"],
            preferred_model_capabilities=["summarization"],
            allowed_tool_categories=["telemetry", "read"],
            default_evidence_expectations=["observation_digest"],
            maximum_recommended_action_class=ActionClass.A0,
        ),
        AgentRole.COORDINATOR: RoleProfile(
            role=AgentRole.COORDINATOR,
            cognitive_responsibilities=["Multi-agent handoff", "Blackboard curation", "Conflict escalation"],
            preferred_model_capabilities=["synthesis", "arbitration"],
            allowed_tool_categories=["read"],
            default_evidence_expectations=["coordination_handoff_digest"],
            maximum_recommended_action_class=ActionClass.A0,
        ),
    }

    @classmethod
    def get_profile(cls, role: AgentRole) -> RoleProfile:
        """Retrieves profile for a specified role."""
        if role not in cls.DEFAULT_PROFILES:
            raise KeyError(f"Role {role} not registered in AgentRoleRegistry.")
        return cls.DEFAULT_PROFILES[role]
