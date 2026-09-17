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
      {/* Left: Brand, Node & Project Selector */}
      <div className="header-left">
        <div className="brand-title">
          <Terminal size={20} color="var(--accent-cyan)" />
          UNIVERSAL BRAIN
          <span className="brand-tag">SOVEREIGN KERNEL</span>
        </div>

        {/* Sync Status */}
        <div className="status-pill">
          <span className={`status-dot ${getSyncDotClass()}`} />
          <span>{syncState}</span>
        </div>

        {/* Project Selector */}
        {projects.length > 0 && (
          <select
            value={activeProject?.project_id || ""}
            onChange={(e) => {
              const p = projects.find((x) => x.project_id === e.target.value);
              if (p) setActiveProject(p);
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
            {projects.map((p) => (
              <option key={p.project_id} value={p.project_id}>
                {p.title} (v{p.current_contract_version})
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Center: View Navigation Tabs */}
      <div className="header-center">
        <nav className="nav-tabs">
          <button
            className={`nav-tab ${activeView === "executive" ? "active" : ""}`}
            onClick={() => setActiveView("executive")}
          >
            <Terminal size={15} />
            Executive Stream
          </button>
          <button
            className={`nav-tab ${activeView === "intelligence" ? "active" : ""}`}
            onClick={() => setActiveView("intelligence")}
          >
            <BrainCircuit size={15} />
            Intelligence
          </button>
          <button
            className={`nav-tab ${activeView === "engineering" ? "active" : ""}`}
            onClick={() => setActiveView("engineering")}
          >
            <Workflow size={15} />
            Engineering
          </button>
          <button
            className={`nav-tab ${activeView === "graph" ? "active" : ""}`}
            onClick={() => setActiveView("graph")}
          >
            <Network size={15} />
            Causal Graph
          </button>
          <button
            className={`nav-tab ${activeView === "governance" ? "active" : ""}`}
            onClick={() => setActiveView("governance")}
          >
            <ShieldCheck size={15} />
            Governance
          </button>
        </nav>
      </div>

      {/* Right: Real-time Telemetry & A2 Alert Button */}
      <div className="header-right">
        {/* Health */}
        <div className="metric-group">
          <span className="metric-label">Health</span>
          <span
            className="metric-value"
            style={{
              color: health?.status === "HEALTHY" ? "var(--accent-emerald)" : "var(--accent-amber)",
            }}
          >
            {health?.status || "ONLINE"}
          </span>
        </div>

        {/* Spend */}
        <div className="metric-group">
          <span className="metric-label">API Spend</span>
          <span className="metric-value">
            ${health?.budget_spend_usd.toFixed(2) || "0.00"} / ${health?.monthly_budget_usd.toFixed(0) || "20"}
          </span>
        </div>

        {/* Disk */}
        <div className="metric-group">
          <span className="metric-label">Storage</span>
          <span
            className="metric-value"
            style={{
              color: health?.is_disk_warning ? "var(--accent-amber)" : "var(--text-primary)",
            }}
          >
            {health?.disk_utilization_pct || 0}%
          </span>
        </div>

        {/* Consequential Action Alert Button */}
        {pendingActions.length > 0 && (
          <button
            className="btn-action-alert"
            onClick={() => openApprovalModal(pendingActions[0])}
            title="Consequential Action Pending Authorization"
          >
            <AlertTriangle size={16} />
            <span>A2 APPROVAL ({pendingActions.length})</span>
          </button>
        )}
      </div>
    </header>
  );
};
