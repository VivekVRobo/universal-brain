import React, { useState } from "react";
import { useConsole } from "../context/ConsoleContext";
import { ApiClient } from "../services/api";
import { CheckCircle2, FileCode, Send } from "lucide-react";

export const ExecutiveStream: React.FC = () => {
  const { health, activeProject, openApprovalModal, openEvidenceModal, pendingActions } = useConsole();
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<Array<{ id: string; sender: "operator" | "executive"; text: string; time: string; intent?: string }>>([
    {
      id: "1",
      sender: "operator",
      text: "Design, verify, and deploy a ROS 2 Humble PID controller for humanoid balance.",
      time: "14:10:02",
    },
    {
      id: "2",
      sender: "executive",
      text: "Alignment Contract v1 bound to REQ-001 & REQ-002. Delegated task to RoboticsCoder (Claude 3.5 Sonnet). Permissions Ceiling: A2.",
      time: "14:10:04",
      intent: "ROS2_HUMANOID_PID_BRINGUP",
    },
    {
      id: "3",
      sender: "executive",
      text: "Preflight reversibility passed cleanly (ADR-0008). Physical testbed deployment to /dev/ttyUSB0 CAN bus requested. Awaiting operator authorization.",
      time: "14:10:15",
      intent: "A2_CONSEQUENTIAL_GATE",
    },
  ]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSend = async () => {
    if (!prompt.trim() || isSubmitting) return;
    const userPrompt = prompt.trim();
    setPrompt("");
    setIsSubmitting(true);

    const now = new Date().toLocaleTimeString();
    setMessages((prev) => [
      ...prev,
      { id: Date.now().toString(), sender: "operator", text: userPrompt, time: now },
    ]);

    try {
      await ApiClient.submitCommand(userPrompt, activeProject?.project_id);
      setTimeout(() => {
        setMessages((prev) => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            sender: "executive",
            text: `Command ingested into EventStore. Causal lineage recorded under ALN-021.`,
            time: new Date().toLocaleTimeString(),
            intent: "EXECUTION_DISPATCH",
          },
        ]);
      }, 600);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          sender: "executive",
          text: `Command Error: ${err.message}`,
          time: new Date().toLocaleTimeString(),
        },
      ]);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="executive-grid">
      {/* 1. LEFT: Conversation Stream */}
      <div className="panel chat-column">
        <div className="chat-header">
          <span>OPERATOR ↔ EXECUTIVE CONVERSATION</span>
          <span className="status-pill">ALN-001 BOUND</span>
        </div>

        <div className="messages-list">
          {messages.map((m) => (
            <div key={m.id} className={`chat-message ${m.sender}`}>
              <div className="msg-meta">
                <span>{m.sender.toUpperCase()}</span>
                <span>•</span>
                <span>{m.time}</span>
                {m.intent && <span className="intent-pill">{m.intent}</span>}
              </div>
              <div className="msg-bubble">{m.text}</div>
            </div>
          ))}
        </div>

        <div className="composer-box">
          <input
            type="text"
            className="composer-input"
            placeholder="Instruct Executive or authorize action..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <button className="btn-send" onClick={handleSend} disabled={isSubmitting}>
            <Send size={16} />
          </button>
        </div>
      </div>

      {/* 2. CENTER: Real-time Task DAG & Build Timeline */}
      <div className="panel timeline-column">
        <div className="timeline-header">
          <span>ACTIVE TASK DAG & EXECUTION TIMELINE</span>
          <span className="status-pill">PHASE 2: VERIFICATION</span>
        </div>

        <div className="timeline-list">
          {/* Step 1 */}
          <div className="timeline-item">
            <span className="timeline-dot" style={{ background: "var(--accent-emerald)" }} />
            <div className="timeline-card">
              <div className="card-title-row">
                <span className="card-title">1. Parse Intent & Align Contract v1</span>
                <span className="card-time">14:10:02</span>
              </div>
              <div className="card-detail">Bound requirements: REQ-001 (PID balance), REQ-002 (CAN bus safety).</div>
              <div
                className="evidence-badge"
                onClick={() =>
                  openEvidenceModal({
                    title: "Intent Parsing & Contract Proof",
                    contract_version: 1,
                    checksum: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    details: "Requirements cited: REQ-001, REQ-002. Deterministic ambiguity score: 0.0 (CLEAR).",
                  })
                }
              >
                <CheckCircle2 size={12} /> Proof #ev-intent-8902
              </div>
            </div>
          </div>

          {/* Step 2 */}
          <div className="timeline-item">
            <span className="timeline-dot" style={{ background: "var(--accent-emerald)" }} />
            <div className="timeline-card">
              <div className="card-title-row">
                <span className="card-title">2. Generate ROS 2 Node (robot_controller.cpp)</span>
                <span className="card-time">14:10:07</span>
              </div>
              <div className="card-detail">Agent: RoboticsCoder (Claude 3.5 Sonnet). 184 lines generated.</div>
              <div
                className="evidence-badge"
                onClick={() =>
                  openEvidenceModal({
                    title: "Source Code Diff",
                    target: "./src/pid_controller.cpp",
                    lines_changed: 48,
                    diff: "+ void pid_calculate(double setpoint, double current) {\n+   double error = setpoint - current;\n+   // Invariant ALN-018: Actuator torque limits strictly enforced\n+ }",
                  })
                }
              >
                <FileCode size={12} /> Diff #ev-patch-0041
              </div>
            </div>
          </div>

          {/* Step 3 */}
          <div className="timeline-item">
            <span className="timeline-dot" style={{ background: "var(--accent-emerald)" }} />
            <div className="timeline-card">
              <div className="card-title-row">
                <span className="card-title">3. Preflight Reversibility Verification (ADR-0008)</span>
                <span className="card-time">14:10:11</span>
              </div>
              <div className="card-detail">patch -R --dry-run: PASS. Compensation snapshot saved to journal.</div>
            </div>
          </div>

          {/* Step 4 */}
          <div className="timeline-item">
            <span className="timeline-dot" style={{ background: "var(--accent-emerald)" }} />
            <div className="timeline-card">
              <div className="card-title-row">
                <span className="card-title">4. Colcon Build & Simulation Verification</span>
                <span className="card-time">14:10:14</span>
              </div>
              <div className="card-detail">colcon test: 14/14 passed. Gazebo headless physics: 0 collisions.</div>
              <div
                className="evidence-badge"
                onClick={() =>
                  openEvidenceModal({
                    title: "Colcon Build & Gazebo Physics Proof",
                    exit_code: 0,
                    tests_passed: "14/14",
                    collisions: 0,
                    log: "Finished <<< humanoid_controller [4.21s]\nSummary: 1 package finished, 0 packages failed",
                  })
                }
              >
                <CheckCircle2 size={12} /> Test Proof #ev-colcon-3104
              </div>
            </div>
          </div>

          {/* Step 5: A2 Action Pending */}
          {pendingActions.length > 0 && (
            <div className="timeline-item">
              <span className="timeline-dot" style={{ background: "var(--accent-crimson)" }} />
              <div
                className="timeline-card"
                style={{
                  borderColor: "var(--border-crimson)",
                  background: "rgba(239, 68, 68, 0.08)",
                  cursor: "pointer",
                }}
                onClick={() => openApprovalModal(pendingActions[0])}
              >
                <div className="card-title-row">
                  <span className="card-title" style={{ color: "#fca5a5" }}>
                    5. A2 Consequential Deployment: Physical Hardware CAN Bus
                  </span>
                  <span className="status-pill" style={{ color: "var(--accent-crimson)" }}>
                    AWAITING OPERATOR SIGN-OFF
                  </span>
                </div>
                <div className="card-detail">Target: /dev/ttyUSB0. Action class: A2. Requires elevated authorization.</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 3. RIGHT: System Telemetry & EAP Inspector */}
      <div className="telemetry-column">
        {/* Model Lease */}
        <div className="panel telemetry-card">
          <div className="stat-row">
            <span className="stat-label">Executive Model</span>
            <span className="stat-val" style={{ color: "var(--accent-cyan)" }}>
              {health?.active_model_lease || "Claude 3.5 Sonnet"}
            </span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Lease Status</span>
            <span className="stat-val" style={{ color: "var(--accent-emerald)" }}>
              Active (28m left)
            </span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Active Agents</span>
            <span className="stat-val">3 (1 running)</span>
          </div>
        </div>

        {/* Budget Spending */}
        <div className="panel telemetry-card">
          <div className="stat-row">
            <span className="stat-label">Monthly Budget</span>
            <span className="stat-val">
              ${health?.budget_spend_usd.toFixed(2)} / ${health?.monthly_budget_usd.toFixed(2)}
            </span>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${Math.min(100, ((health?.budget_spend_usd || 0) / (health?.monthly_budget_usd || 20)) * 100)}%`,
              }}
            />
          </div>
          <div className="stat-row">
            <span className="stat-label">Budget Tier</span>
            <span className="stat-val" style={{ color: "var(--accent-emerald)" }}>
              {health?.budget_tier || "TIER_0_NORMAL"}
            </span>
          </div>
        </div>

        {/* Storage Retention */}
        <div className="panel telemetry-card">
          <div className="stat-row">
            <span className="stat-label">Storage Capacity</span>
            <span className="stat-val">{health?.disk_utilization_pct || 0}%</span>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${health?.disk_utilization_pct || 0}%`,
                background: health?.is_disk_warning ? "var(--accent-amber)" : "var(--accent-cyan)",
              }}
            />
          </div>
          <div className="stat-row">
            <span className="stat-label">Safety Gate (ALN-014)</span>
            <span className="stat-val" style={{ color: "var(--accent-emerald)" }}>
              ARMED (90% pause)
            </span>
          </div>
        </div>

        {/* EAP Context Token Inspector */}
        <div className="panel telemetry-card">
          <div className="stat-row">
            <span className="stat-label">EAP Context Tokens</span>
            <span className="stat-val">1,840 / 200,000</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Memory Micro-Batches</span>
            <span className="stat-val">Synced to Drive</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Tamper-Proof Merkle</span>
            <span className="stat-val" style={{ color: "var(--accent-emerald)" }}>
              ALN-016 VALID
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
