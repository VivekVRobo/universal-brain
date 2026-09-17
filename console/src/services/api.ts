import {
  ActionProposal,
  CausalGraph,
  ContractDetail,
  EventItem,
  InvariantLedger,
  IntelligenceStatus,
  EngineeringStatus,
  ProjectSummary,
  RuntimeHealth,
} from "../types";
import { OperatorAuth } from "./operatorAuth";

const API_BASE = "/api/v1";

function generateIdempotencyKey(): string {
  return "idemp-" + Math.random().toString(36).substring(2, 15) + "-" + Date.now();
}

async function authenticatedFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  for (const [key, value] of Object.entries(OperatorAuth.authorizationHeaders())) {
    headers.set(key, value);
  }
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) {
    OperatorAuth.clear();
  }
  return response;
}

export class ApiClient {
  static async getHealth(): Promise<RuntimeHealth> {
    const res = await authenticatedFetch(`${API_BASE}/runtime/health`);
    if (!res.ok) throw new Error(`Health fetch failed: ${res.status}`);
    return res.json();
  }

  static async getIntelligenceStatus(): Promise<IntelligenceStatus> {
    const res = await authenticatedFetch(`${API_BASE}/intelligence/status`);
    if (!res.ok) throw new Error(`Intelligence status fetch failed: ${res.status}`);
    return res.json();
  }

  static async getEngineeringStatus(): Promise<EngineeringStatus> {
    const res = await authenticatedFetch(`${API_BASE}/engineering/status`);
    if (!res.ok) throw new Error(`Engineering status fetch failed: ${res.status}`);
    return res.json();
  }

  static async getProjects(): Promise<ProjectSummary[]> {
    const res = await authenticatedFetch(`${API_BASE}/projects`);
    if (!res.ok) throw new Error(`Projects fetch failed: ${res.status}`);
    return res.json();
  }

  static async getEvents(page = 1, pageSize = 50): Promise<{ events: EventItem[]; total_count: number }> {
    const res = await authenticatedFetch(`${API_BASE}/events?page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error(`Events fetch failed: ${res.status}`);
    return res.json();
  }

  static async getCausalGraph(): Promise<CausalGraph> {
    const res = await authenticatedFetch(`${API_BASE}/graph?limit=100`);
    if (!res.ok) throw new Error(`Graph fetch failed: ${res.status}`);
    return res.json();
  }

  static async getCurrentContract(): Promise<ContractDetail> {
    const res = await authenticatedFetch(`${API_BASE}/contracts/current`);
    if (!res.ok) throw new Error(`Contract fetch failed: ${res.status}`);
    return res.json();
  }

  static async getInvariants(): Promise<InvariantLedger> {
    const res = await authenticatedFetch(`${API_BASE}/invariants`);
    if (!res.ok) throw new Error(`Invariants fetch failed: ${res.status}`);
    return res.json();
  }

  static async getPendingActions(): Promise<ActionProposal[]> {
    const res = await authenticatedFetch(`${API_BASE}/actions/pending`);
    if (!res.ok) throw new Error(`Pending actions fetch failed: ${res.status}`);
    return res.json();
  }

  static async getEvidence(eventId: string): Promise<any> {
    const res = await authenticatedFetch(`${API_BASE}/evidence/${eventId}`);
    if (!res.ok) throw new Error(`Evidence fetch failed: ${res.status}`);
    return res.json();
  }

  static async submitCommand(prompt: string, projectId?: string): Promise<any> {
    const res = await authenticatedFetch(`${API_BASE}/commands/submit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": generateIdempotencyKey(),
      },
      body: JSON.stringify({ prompt, project_id: projectId }),
    });
    if (!res.ok) throw new Error(`Command submit failed: ${res.status}`);
    return res.json();
  }

  static async approveAction(params: {
    action_id: string;
    proposal_version: number;
    operator_id: string;
    authorization_digest: string;
    nonce: string;
  }): Promise<any> {
    const res = await authenticatedFetch(`${API_BASE}/actions/${params.action_id}/approve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": generateIdempotencyKey(),
      },
      body: JSON.stringify(params),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Approval failed.");
    }
    return res.json();
  }

  static async rejectAction(params: {
    action_id: string;
    proposal_version: number;
    operator_id: string;
    reason: string;
  }): Promise<any> {
    const res = await authenticatedFetch(`${API_BASE}/actions/${params.action_id}/reject`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": generateIdempotencyKey(),
      },
      body: JSON.stringify(params),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Rejection failed.");
    }
    return res.json();
  }

  static async rollbackAction(params: {
    action_id: string;
    operator_id: string;
    reason: string;
  }): Promise<any> {
    const res = await authenticatedFetch(`${API_BASE}/actions/${params.action_id}/rollback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": generateIdempotencyKey(),
      },
      body: JSON.stringify(params),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Rollback failed.");
    }
    return res.json();
  }
}
