import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { ApiClient } from "../services/api";
import { EventItem } from "../types";
import { FileSearch, Send } from "lucide-react";

function summarizeEvent(event: EventItem): string {
  const payload = event.payload || {};
  const candidate =
    payload.utterance ??
    payload.primary_goal ??
    payload.goal ??
    payload.tool ??
    payload.status ??
    payload.objective;

  if (typeof candidate === "string" && candidate.trim()) {
    return candidate.trim();
  }

  const serialized = JSON.stringify(payload);
  return serialized === "{}" ? "No payload details recorded." : serialized.slice(0, 220);
}

export const ExecutiveStream: React.FC = () => {
  const { health, activeProject, openApprovalModal, openEvidenceModal, pendingActions, refreshState } = useConsole();
  const [prompt, setPrompt] = useState("");
  const [events, setEvents] = useState<EventItem[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionStatus, setSubmissionStatus] = useState<string | null>(null);
  const [eventError, setEventError] = useState<string | null>(null);

  const loadEvents = useCallback(async () => {
    try {
      let page = await ApiClient.getEvents(1, 200);
      if (page.total_count > 200) {
        const lastPage = Math.ceil(page.total_count / 200);
        page = await ApiClient.getEvents(lastPage, 200);
      }
      setEvents(page.events);
      setEventError(null);
    } catch (error: any) {
      setEventError(error?.message || "Unable to load canonical events.");
    }
  }, []);

  useEffect(() => {
    loadEvents();
    const interval = window.setInterval(loadEvents, 5000);
    return () => window.clearInterval(interval);
  }, [loadEvents]);

  const visibleEvents = useMemo(() => {
    const filtered = activeProject
      ? events.filter((event) => !event.project_id || event.project_id === activeProject.project_id)
      : events;
    return [...filtered].reverse();
  }, [events, activeProject]);

  const operatorInputs = visibleEvents.filter((event) => event.event_type === "USER_INPUT");

  const handleSend = async () => {
    if (!prompt.trim() || isSubmitting) return;
    const userPrompt = prompt.trim();
    setIsSubmitting(true);
    setSubmissionStatus(null);

    try {
      const result = await ApiClient.submitCommand(userPrompt, activeProject?.project_id);
      setPrompt("");
      setSubmissionStatus(
        `Accepted into canonical state as project ${result.project_id}; contract v${result.contract_version} recorded.`,
      );
      await Promise.all([loadEvents(), refreshState()]);
    } catch (error: any) {
      setSubmissionStatus(`Command failed: ${error?.message || "unknown error"}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const openCanonicalEvidence = async (event: EventItem) => {
    try {
      const evidence = await ApiClient.getEvidence(event.event_id);
      openEvidenceModal({
        title: `Canonical Evidence • ${event.event_type}`,
        ...evidence,
      });
    } catch (error: any) {
      openEvidenceModal({
        title: "Evidence unavailable",
        error: error?.message || "Unable to load evidence.",
      });
    }
  };

  return (
    <div className="executive-grid">
      <div className="panel chat-column">
        <div className="chat-header">
          <span>OPERATOR COMMANDS</span>
          <span className="status-pill">{operatorInputs.length} RECORDED</span>
        </div>

        <div className="messages-list">
          {operatorInputs.length === 0 && (
            <div className="chat-message executive">
              <div className="msg-bubble">
                No operator commands are present in canonical runtime state.
              </div>
            </div>
          )}
          {operatorInputs.map((event) => (
            <div key={event.event_id} className="chat-message operator">
              <div className="msg-meta">
                <span>{event.actor_id.toUpperCase()}</span>
                <span>•</span>
                <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
              </div>
              <div className="msg-bubble">{summarizeEvent(event)}</div>
            </div>
          ))}
        </div>

        <div className="composer-box">
          <input
            type="text"
            className="composer-input"
            placeholder="Submit an operator command..."
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSend();
              }
            }}
          />
          <button className="btn-send" onClick={handleSend} disabled={isSubmitting}>
            <Send size={16} />
          </button>
        </div>
        {submissionStatus && (
          <div style={{ padding: "8px 12px", color: "var(--text-muted)", fontSize: "0.78rem" }}>
            {submissionStatus}
          </div>
        )}
      </div>

      <div className="panel timeline-column">
        <div className="timeline-header">
          <span>CANONICAL EVENT TIMELINE</span>
          <span className="status-pill">{visibleEvents.length} OBSERVED</span>
        </div>

        <div className="timeline-list">
          {eventError && <div className="timeline-card">{eventError}</div>}
          {!eventError && visibleEvents.length === 0 && (
            <div className="timeline-card">
              No canonical events are present. The runtime is intentionally not seeded with demo evidence.
            </div>
          )}

          {visibleEvents.map((event) => (
            <div className="timeline-item" key={event.event_id}>
              <span className="timeline-dot" style={{ background: "var(--accent-cyan)" }} />
              <div className="timeline-card">
                <div className="card-title-row">
                  <span className="card-title">{event.event_type}</span>
                  <span className="card-time">{new Date(event.timestamp).toLocaleTimeString()}</span>
                </div>
                <div className="card-detail">{summarizeEvent(event)}</div>
                <div style={{ marginTop: "6px", fontSize: "0.7rem", color: "var(--text-muted)" }}>
                  Actor: {event.actor_id} • Event: {event.event_id.slice(0, 8)}
                  {event.contract_version != null ? ` • Contract v${event.contract_version}` : ""}
                </div>
                {event.event_type === "EVIDENCE_PRODUCED" && (
                  <button
                    className="evidence-badge"
                    onClick={() => openCanonicalEvidence(event)}
                    style={{ border: 0, cursor: "pointer" }}
                  >
                    <FileSearch size={12} /> Inspect recorded evidence
                  </button>
                )}
              </div>
            </div>
          ))}

          {pendingActions.map((action) => (
            <div className="timeline-item" key={action.action_id}>
              <span className="timeline-dot" style={{ background: "var(--accent-crimson)" }} />
              <div
                className="timeline-card"
                style={{
                  borderColor: "var(--border-crimson)",
                  background: "rgba(239, 68, 68, 0.08)",
                  cursor: "pointer",
                }}
                onClick={() => openApprovalModal(action)}
              >
                <div className="card-title-row">
                  <span className="card-title" style={{ color: "#fca5a5" }}>
                    {action.action_class} • {action.action_type}
                  </span>
                  <span className="status-pill">{action.status}</span>
                </div>
                <div className="card-detail">
                  {action.requested_effect} • Target: {action.target_resource}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="telemetry-column">
        <div className="panel telemetry-card">
          <div className="stat-row">
            <span className="stat-label">Runtime Mode</span>
            <span className="stat-val">{health?.system_mode ?? "Unknown"}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Observed Model</span>
            <span className="stat-val" style={{ color: "var(--accent-cyan)" }}>
              {health?.active_model_lease ?? "Not observed"}
            </span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Lease Expiry</span>
            <span className="stat-val">
              {health?.lease_expires_in_seconds != null
                ? `${health.lease_expires_in_seconds}s`
                : "Not reported"}
            </span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Contract Version</span>
            <span className="stat-val">{health?.contract_version ?? "Not observed"}</span>
          </div>
        </div>

        <div className="panel telemetry-card">
          <div className="stat-row">
            <span className="stat-label">Monthly Budget</span>
            <span className="stat-val">
              {health
                ? `$${health.budget_spend_usd.toFixed(2)} / $${health.monthly_budget_usd.toFixed(2)}`
                : "Unknown"}
            </span>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: health && health.monthly_budget_usd > 0
                  ? `${Math.min(100, (health.budget_spend_usd / health.monthly_budget_usd) * 100)}%`
                  : "0%",
              }}
            />
          </div>
          <div className="stat-row">
            <span className="stat-label">Budget Tier</span>
            <span className="stat-val">{health?.budget_tier ?? "Unknown"}</span>
          </div>
        </div>

        <div className="panel telemetry-card">
          <div className="stat-row">
            <span className="stat-label">Storage Capacity</span>
            <span className="stat-val">
              {health ? `${health.disk_utilization_pct}%` : "Unknown"}
            </span>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: health ? `${health.disk_utilization_pct}%` : "0%",
                background: health?.is_disk_warning ? "var(--accent-amber)" : "var(--accent-cyan)",
              }}
            />
          </div>
          <div className="stat-row">
            <span className="stat-label">Node Health</span>
            <span className="stat-val">{health?.status ?? "Unknown"}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Pending Actions</span>
            <span className="stat-val">{health?.active_actions_count ?? "Unknown"}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
