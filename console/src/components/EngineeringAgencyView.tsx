import React, { useEffect, useMemo, useState } from "react";
import {
  Boxes,
  GitBranch,
  Network,
  ServerCog,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { ApiClient } from "../services/api";
import { EngineeringStatus } from "../types";

export const EngineeringAgencyView: React.FC = () => {
  const [status, setStatus] = useState<EngineeringStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const next = await ApiClient.getEngineeringStatus();
        if (alive) {
          setStatus(next);
          setError(null);
        }
      } catch (err: any) {
        if (alive) setError(err?.message || "Unable to read Engineering Agency status");
      }
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const semanticSummary = useMemo(() => {
    if (!status || status.semantic_backends.length === 0) return "not reported";
    return status.semantic_backends.join(" + ");
  }, [status]);

  if (error && !status) return <div className="engineering-empty panel">{error}</div>;
  if (!status) return <div className="engineering-empty panel">Loading Engineering Agency telemetry…</div>;
  if (!status.configured) {
    return (
      <div className="engineering-empty panel">
        <Workflow size={34} />
        <strong>Engineering Agency is not attached to this runtime.</strong>
        <span>{status.note || "Attach EngineeringAgencyStack to RuntimeContainer for live status."}</span>
      </div>
    );
  }

  return (
    <section className="engineering-view">
      <div className="engineering-heading">
        <div>
          <div className="engineering-eyebrow">AUTONOMOUS ENGINEERING AGENCY · V5.2</div>
          <h1>Engineering Runtime</h1>
          <p>
            Semantic code sensing, isolated worktrees, durable worker leases, verified integration,
            services and repository-level execution state.
          </p>
        </div>
        <div className="engineering-live"><span className="status-dot pulse-emerald" /> OBSERVABILITY ATTACHED</div>
      </div>

      <div className="engineering-summary-grid">
        <div className="engineering-stat panel"><Boxes size={18} /><span>Indexed files</span><strong>{status.indexed_files}</strong></div>
        <div className="engineering-stat panel"><Network size={18} /><span>Symbols</span><strong>{status.symbol_count}</strong></div>
        <div className="engineering-stat panel"><GitBranch size={18} /><span>Worktrees</span><strong>{status.active_worktrees.length}</strong></div>
        <div className="engineering-stat panel"><Workflow size={18} /><span>Worker leases</span><strong>{status.durable_worker_leases.length}</strong></div>
        <div className="engineering-stat panel"><ServerCog size={18} /><span>Services</span><strong>{status.services.length}</strong></div>
        <div className="engineering-stat panel"><ShieldCheck size={18} /><span>Repos</span><strong>{status.repository_count}</strong></div>
      </div>

      <div className="engineering-grid">
        <div className="engineering-card panel">
          <div className="engineering-card-header">
            <span>REQUIREMENT WORKTREES</span>
            <small>one requirement chain · one isolated branch</small>
          </div>
          {status.active_worktrees.length === 0 ? (
            <div className="engineering-no-data">No active requirement worktrees.</div>
          ) : (
            <div className="engineering-table-wrap">
              <table className="engineering-table">
                <thead><tr><th>Requirement</th><th>Branch</th><th>Nodes</th><th>Verified</th><th>Integrated</th></tr></thead>
                <tbody>
                  {status.active_worktrees.map((item) => (
                    <tr key={item.requirement_ref}>
                      <td><strong>{item.requirement_ref}</strong><small>{item.path}</small></td>
                      <td>{item.branch}</td>
                      <td>{item.node_count}</td>
                      <td>{item.verified_commit?.slice(0, 10) || "—"}</td>
                      <td>{item.integrated_commit?.slice(0, 10) || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="engineering-card panel">
          <div className="engineering-card-header"><span>RUNTIME HARDENING</span><small>read-only deployment capabilities</small></div>
          <div className="engineering-facts">
            <div><span>Repository</span><strong>{status.repository_root}</strong></div>
            <div><span>Semantic sensing</span><strong>{semanticSummary}</strong></div>
            <div><span>Isolation provider</span><strong>{status.isolation_provider || "not attached"}</strong></div>
            <div><span>Cross-repo edges</span><strong>{status.cross_repo_dependency_edges}</strong></div>
          </div>
        </div>

        <div className="engineering-card panel">
          <div className="engineering-card-header"><span>DURABLE WORKER LEASES</span><small>generation-fenced coordination</small></div>
          {status.durable_worker_leases.length === 0 ? (
            <div className="engineering-no-data">No active durable worker leases.</div>
          ) : (
            <div className="engineering-list">
              {status.durable_worker_leases.map((lease) => (
                <div className="engineering-list-row" key={`${lease.task_id}-${lease.generation}`}>
                  <strong>{lease.task_id}</strong>
                  <span>{lease.worker_id}</span>
                  <span>gen {lease.generation}</span>
                  <span>{new Date(lease.expires_at).toLocaleTimeString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="engineering-card panel">
          <div className="engineering-card-header"><span>MANAGED SERVICES</span><small>ToolGateway-controlled persistent processes</small></div>
          {status.services.length === 0 ? (
            <div className="engineering-no-data">No managed engineering services.</div>
          ) : (
            <div className="engineering-list">
              {status.services.map((service) => (
                <div className="engineering-list-row" key={service.service_id}>
                  <strong>{service.name}</strong>
                  <span>{service.state}</span>
                  <span>pid {service.pid ?? "—"}</span>
                  <span>{service.cwd}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
