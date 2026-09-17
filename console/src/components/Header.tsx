import React from "react";
import { useConsole } from "../context/ConsoleContext";
import { AlertTriangle, BrainCircuit, Network, ShieldCheck, Terminal, Workflow } from "lucide-react";

export const Header: React.FC = () => {
  const {
    activeView,
    setActiveView,
    syncState,
    health,
    projects,
    activeProject,
    setActiveProject,
    pendingActions,
    openApprovalModal,
  } = useConsole();

  const getSyncDotClass = () => {
    switch (syncState) {
      case "LIVE":
        return "pulse-emerald";
      case "DEGRADED":
      case "RECONCILING":
        return "pulse-amber";
      default:
        return "pulse-crimson";
    }
  };

  return (
    <header className="global-header">
      <div className="header-left">
        <div className="brand-title">
          <Terminal size={20} color="var(--accent-cyan)" />
          UNIVERSAL BRAIN
          <span className="brand-tag">SOVEREIGN KERNEL</span>
        </div>

        <div className="status-pill">
          <span className={`status-dot ${getSyncDotClass()}`} />
          <span>{syncState}</span>
        </div>

        {projects.length > 0 ? (
          <select
            value={activeProject?.project_id || ""}
            onChange={(event) => {
              const project = projects.find((item) => item.project_id === event.target.value);
              if (project) setActiveProject(project);
            }}
            style={{
              background: "var(--bg-surface)",
              color: "var(--text-primary)",
              border: "1px solid var(--border-medium)",
              padding: "4px 8px",
              borderRadius: "var(--radius-sm)",
              fontSize: "0.8rem",
              fontFamily: "var(--font-mono)",
              outline: "none",
            }}
          >
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.title}
                {project.current_contract_version != null ? ` (v${project.current_contract_version})` : ""}
              </option>
            ))}
          </select>
        ) : (
          <span className="status-pill">NO PROJECT STATE</span>
        )}
      </div>

      <div className="header-center">
        <nav className="nav-tabs">
          <button className={`nav-tab ${activeView === "executive" ? "active" : ""}`} onClick={() => setActiveView("executive")}>
            <Terminal size={15} /> Executive Stream
          </button>
          <button className={`nav-tab ${activeView === "intelligence" ? "active" : ""}`} onClick={() => setActiveView("intelligence")}>
            <BrainCircuit size={15} /> Intelligence
          </button>
          <button className={`nav-tab ${activeView === "engineering" ? "active" : ""}`} onClick={() => setActiveView("engineering")}>
            <Workflow size={15} /> Engineering
          </button>
          <button className={`nav-tab ${activeView === "graph" ? "active" : ""}`} onClick={() => setActiveView("graph")}>
            <Network size={15} /> Causal Graph
          </button>
          <button className={`nav-tab ${activeView === "governance" ? "active" : ""}`} onClick={() => setActiveView("governance")}>
            <ShieldCheck size={15} /> Governance
          </button>
        </nav>
      </div>

      <div className="header-right">
        <div className="metric-group">
          <span className="metric-label">Health</span>
          <span
            className="metric-value"
            style={{
              color:
                health?.status === "HEALTHY"
                  ? "var(--accent-emerald)"
                  : health
                    ? "var(--accent-amber)"
                    : "var(--text-muted)",
            }}
          >
            {health?.status ?? "UNKNOWN"}
          </span>
        </div>

        <div className="metric-group">
          <span className="metric-label">API Spend</span>
          <span className="metric-value">
            {health ? `$${health.budget_spend_usd.toFixed(2)} / $${health.monthly_budget_usd.toFixed(0)}` : "—"}
          </span>
        </div>

        <div className="metric-group">
          <span className="metric-label">Storage</span>
          <span
            className="metric-value"
            style={{ color: health?.is_disk_warning ? "var(--accent-amber)" : "var(--text-primary)" }}
          >
            {health ? `${health.disk_utilization_pct}%` : "—"}
          </span>
        </div>

        {pendingActions.length > 0 && (
          <button
            className="btn-action-alert"
            onClick={() => openApprovalModal(pendingActions[0])}
            title="Consequential Action Pending Authorization"
          >
            <AlertTriangle size={16} />
            <span>PENDING ACTIONS ({pendingActions.length})</span>
          </button>
        )}
      </div>
    </header>
  );
};
