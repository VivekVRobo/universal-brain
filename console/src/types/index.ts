export type SystemMode = "LIVE" | "LOCAL" | "DEMO";
export type ConsoleSyncState = "LIVE" | "STALE" | "RECONCILING" | "DISCONNECTED" | "DEGRADED" | "DEMO";
export type ActiveView = "executive" | "intelligence" | "engineering" | "graph" | "governance";

export type ActionClass = "A0" | "A1" | "A2" | "A3";

export type EventType =
  | "USER_INPUT"
  | "INTENT_PARSED"
  | "CONTRACT_CREATED"
  | "CONTRACT_UPDATED"
  | "TASK_ASSIGNED"
  | "TOOL_CALLED"
  | "EVIDENCE_PRODUCED"
  | "OPERATOR_APPROVAL"
  | "OPERATOR_PAUSE"
  | "CHECKPOINT_SAVED"
  | "HEALTH_ALERT"
  | "BUDGET_EXHAUSTED"
  | "SYSTEM_SHUTDOWN";

export type RelationType =
  | "CAUSED_BY"
  | "PROVES"
  | "INVALIDATES"
  | "REQUIRES"
  | "SUPERSEDES";

export interface RuntimeHealth {
  node_id: string;
  status: "HEALTHY" | "DEGRADED" | "CRITICAL";
  disk_utilization_pct: number;
  is_disk_warning: boolean;
  is_disk_critical: boolean;
  budget_spend_usd: number;
  monthly_budget_usd: number;
  budget_tier: string;
  active_model_lease?: string | null;
  lease_expires_in_seconds?: number | null;
  active_actions_count: number;
  contract_version?: number | null;
  system_mode: SystemMode;
}

export interface ProjectSummary {
  project_id: string;
  title: string;
  status: string;
  current_contract_version?: number | null;
  created_at: string;
  active_tasks_count?: number | null;
  pending_actions_count: number;
}

export interface EventItem {
  event_id: string;
  timestamp: string;
  event_type: EventType;
  actor_id: string;
  project_id?: string;
  task_id?: string;
  contract_version?: number;
  payload: Record<string, any>;
  prev_event_hash: string;
  event_hash: string;
}

export interface CausalGraphNode {
  id: string;
  label: string;
  event_type: EventType;
  actor_id: string;
  timestamp: string;
  event_hash: string;
  payload_summary: string;
  has_evidence: boolean;
}

export interface CausalGraphEdge {
  source: string;
  target: string;
  relation_type: RelationType;
}

export interface CausalGraph {
  nodes: CausalGraphNode[];
  edges: CausalGraphEdge[];
  root_cause_event_ids: string[];
}

export interface ContractDiffItem {
  diff_type: "ADDED" | "REMOVED" | "MODIFIED";
  category: "REQUIREMENT" | "CONSTRAINT" | "CAPABILITY" | "AMBIGUITY";
  item_id: string;
  summary: string;
}

export interface ContractDetail {
  contract_id: string;
  version: number;
  status: string;
  objective: string;
  requirements_count: number;
  constraints_count: number;
  permissions_ceiling: ActionClass;
  created_at: string;
  semantic_diffs: ContractDiffItem[];
}

export interface InvariantItem {
  invariant_id: string;
  name: string;
  description: string;
  status: "PASS" | "WARN" | "FAIL" | "UNKNOWN";
  proofs_count: number;
  last_evaluated_at: string;
}

export interface InvariantLedger {
  invariants: InvariantItem[];
  pass_count: number;
  warn_count: number;
  fail_count: number;
  unknown_count: number;
}

export interface ActionProposal {
  action_id: string;
  proposal_version: number;
  project_id: string;
  task_id: string;
  action_type: string;
  target_resource: string;
  requested_effect: string;
  action_class: ActionClass;
  status: string;
  preflight_reversibility: "VERIFIED_REVERSIBLE" | "PARTIALLY_REVERSIBLE" | "IRREVERSIBLE" | "UNKNOWN";
  diff_preview: string;
  rollback_procedure: string;
  evidence_items_count: number;
  payload_hash: string;
  authorization_digest: string;
  created_at: string;
  expires_at: string;
  seconds_remaining: number;
}


export interface IntelligenceModelStatus {
  model_key: string;
  display_name: string;
  vendor: string;
  family: string;
  enabled: boolean;
  context_window: number;
  route_count: number;
  empirical_score: number;
  evaluation_samples: number;
  drift_alert: boolean;
  capability_evidence_samples: number;
  effective_capabilities: Record<string, number>;
}

export interface IntelligenceRouteStatus {
  route_id: string;
  model_key: string;
  transport: "api" | "browser" | "desktop_app" | "local" | string;
  enabled: boolean;
  health: string;
  retention_policy: string;
  max_sensitivity: string;
  cost_per_million_input: number;
  cost_per_million_output: number;
  quota: Record<string, any>;
  telemetry: Record<string, any>;
  active_conversations: number;
  recovery_candidates: number;
}

export interface IntelligenceStatus {
  configured: boolean;
  model_count: number;
  route_count: number;
  healthy_routes: number;
  degraded_routes: number;
  unavailable_routes: number;
  active_conversations: number;
  models: IntelligenceModelStatus[];
  routes: IntelligenceRouteStatus[];
  recent_invocations: Record<string, any>[];
  note?: string | null;
}


export interface EngineeringWorktreeStatus {
  requirement_ref: string;
  branch: string;
  path: string;
  node_count: number;
  verified_commit?: string | null;
  integrated_commit?: string | null;
}

export interface EngineeringLeaseStatus {
  task_id: string;
  worker_id: string;
  workspace_id: string;
  generation: number;
  expires_at: string;
}

export interface EngineeringServiceStatus {
  name: string;
  service_id: string;
  state: string;
  pid?: number | null;
  cwd: string;
}

export interface EngineeringStatus {
  configured: boolean;
  repository_root: string;
  symbol_count: number;
  reference_count: number;
  indexed_files: number;
  active_worktrees: EngineeringWorktreeStatus[];
  durable_worker_leases: EngineeringLeaseStatus[];
  repository_count: number;
  cross_repo_dependency_edges: number;
  services: EngineeringServiceStatus[];
  semantic_backends: string[];
  isolation_provider?: string | null;
  note?: string | null;
}
