import React, { useEffect, useMemo, useState } from "react";
import { Activity, BrainCircuit, Database, Gauge, Route as RouteIcon } from "lucide-react";
import { ApiClient } from "../services/api";
import { IntelligenceStatus } from "../types";

const formatTokens = (value: number) => {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
};

const healthClass = (health: string) => {
  if (health === "healthy") return "fabric-health healthy";
  if (health === "degraded") return "fabric-health degraded";
  return "fabric-health unavailable";
};

export const IntelligenceFabricView: React.FC = () => {
  const [status, setStatus] = useState<IntelligenceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const next = await ApiClient.getIntelligenceStatus();
        if (alive) {
          setStatus(next);
          setError(null);
        }
      } catch (err: any) {
        if (alive) setError(err?.message || "Unable to read Intelligence Fabric status");
      }
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const totalCost = useMemo(() => {
    if (!status) return 0;
    return status.routes.reduce(
      (sum, route) => sum + Number(route.telemetry?.total_cost_usd || 0),
      0,
    );
  }, [status]);

  if (error && !status) {
    return <div className="fabric-empty panel">{error}</div>;
  }
  if (!status) {
    return <div className="fabric-empty panel">Loading Intelligence Fabric telemetry…</div>;
  }
  if (!status.configured) {
    return (
      <div className="fabric-empty panel">
        <BrainCircuit size={34} />
        <strong>Intelligence Fabric is not attached to this runtime.</strong>
        <span>{status.note || "Attach an IntelligenceStack to the RuntimeContainer to expose live status."}</span>
      </div>
    );
  }

  return (
    <section className="fabric-view">
      <div className="fabric-heading">
        <div>
          <div className="fabric-eyebrow">MULTI-TRANSPORT COGNITIVE RUNTIME</div>
          <h1>Intelligence Fabric</h1>
          <p>Model identity, route health, privacy, quota and empirical quality. No prompt bodies are exposed here.</p>
        </div>
        <div className="fabric-live"><span className="status-dot pulse-emerald" /> OBSERVABILITY LIVE</div>
      </div>

      <div className="fabric-summary-grid">
        <div className="fabric-stat panel"><BrainCircuit size={18} /><span>Models</span><strong>{status.model_count}</strong></div>
        <div className="fabric-stat panel"><RouteIcon size={18} /><span>Routes</span><strong>{status.route_count}</strong></div>
        <div className="fabric-stat panel"><Activity size={18} /><span>Healthy</span><strong>{status.healthy_routes}</strong></div>
        <div className="fabric-stat panel"><Database size={18} /><span>Continuations</span><strong>{status.active_conversations}</strong></div>
        <div className="fabric-stat panel"><Gauge size={18} /><span>Recorded Cost</span><strong>${totalCost.toFixed(4)}</strong></div>
      </div>

      <div className="fabric-grid">
        <div className="fabric-card panel">
          <div className="fabric-card-header"><span>ACCESS ROUTES</span><small>{status.degraded_routes} degraded · {status.unavailable_routes} unavailable</small></div>
          <div className="fabric-table-wrap">
            <table className="fabric-table">
              <thead><tr><th>Route</th><th>Transport</th><th>Health</th><th>Privacy</th><th>Success</th><th>P95</th><th>Quota</th><th>Sessions</th><th>Recovery</th></tr></thead>
              <tbody>
                {status.routes.map((route) => (
                  <tr key={route.route_id}>
                    <td><strong>{route.route_id}</strong><small>{route.model_key}</small></td>
                    <td>{route.transport}</td>
                    <td><span className={healthClass(route.health)}>{route.health}</span></td>
                    <td><small>{route.retention_policy}</small><small>≤ {route.max_sensitivity}</small></td>
                    <td>{route.telemetry?.sample_count ? `${(Number(route.telemetry.success_rate) * 100).toFixed(0)}%` : "—"}</td>
                    <td>{route.telemetry?.sample_count ? `${Number(route.telemetry.p95_latency_ms).toFixed(0)} ms` : "—"}</td>
                    <td>{route.quota?.eligibility_reason ? <span className="fabric-warn">limited</span> : "ready"}</td>
                    <td>{route.active_conversations}</td>
                    <td>{route.recovery_candidates || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="fabric-card panel">
          <div className="fabric-card-header"><span>MODEL IDENTITIES</span><small>Quality is evaluation-derived, not vendor rank</small></div>
          <div className="fabric-model-list">
            {status.models.map((model) => (
              <div className="fabric-model-row" key={model.model_key}>
                <div><strong>{model.display_name}</strong><small>{model.model_key} · {model.family}</small></div>
                <div className="fabric-model-metric"><span>Context</span><strong>{formatTokens(model.context_window)}</strong></div>
                <div className="fabric-model-metric"><span>Routes</span><strong>{model.route_count}</strong></div>
                <div className="fabric-model-metric"><span>Empirical</span><strong>{(model.empirical_score * 100).toFixed(0)}%</strong></div>
                <div className="fabric-model-metric"><span>Samples</span><strong>{model.evaluation_samples}</strong></div>
                <div className="fabric-model-metric"><span>Cap obs</span><strong>{model.capability_evidence_samples || 0}</strong></div>
                {model.drift_alert && <span className="fabric-warn">DRIFT</span>}
              </div>
            ))}
          </div>
        </div>

        <div className="fabric-card panel fabric-invocations">
          <div className="fabric-card-header"><span>RECENT INVOCATIONS</span><small>Metadata only · content excluded</small></div>
          {status.recent_invocations.length === 0 ? (
            <div className="fabric-no-data">No invocations recorded yet.</div>
          ) : (
            <div className="fabric-invocation-list">
              {status.recent_invocations.slice(0, 12).map((item: any) => (
                <div className="fabric-invocation-row" key={item.invocation_id}>
                  <span className={healthClass(item.status === "success" ? "healthy" : "degraded")}>{item.status}</span>
                  <strong>{item.route_id}</strong>
                  <span>{Number(item.latency_ms || 0).toFixed(0)} ms</span>
                  <span>{item.usage?.input_tokens || 0} in / {item.usage?.output_tokens || 0} out</span>
                  <span>${Number(item.usage?.cost_usd || 0).toFixed(5)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
