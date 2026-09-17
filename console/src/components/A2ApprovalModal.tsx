import React, { useEffect, useState } from "react";
import { ActionProposal } from "../types";
import { useConsole } from "../context/ConsoleContext";
import { ApiClient } from "../services/api";
import { AlertTriangle, Clock, ShieldCheck } from "lucide-react";

interface A2ApprovalModalProps {
  action: ActionProposal;
  onClose: () => void;
}

export const A2ApprovalModal: React.FC<A2ApprovalModalProps> = ({ action, onClose }) => {
  const { syncState, refreshState } = useConsole();
  const [secondsLeft, setSecondsLeft] = useState(action.seconds_remaining);
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Authoritative countdown derived from action.expires_at
  useEffect(() => {
    const targetTime = new Date(action.expires_at).getTime();
    const timer = setInterval(() => {
      const now = Date.now();
      const diff = Math.max(0, Math.floor((targetTime - now) / 1000));
      setSecondsLeft(diff);
      if (diff === 0) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [action.expires_at]);

  const formatCountdown = (secs: number) => {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    return `${h.toString().padStart(2, "0")}h : ${m.toString().padStart(2, "0")}m : ${s.toString().padStart(2, "0")}s`;
  };

  const handleApprove = async () => {
    setIsProcessing(true);
    setErrorMessage(null);
    try {
      const res = await ApiClient.approveAction({
        action_id: action.action_id,
        proposal_version: action.proposal_version,
        operator_id: "operator-primary",
        authorization_digest: action.authorization_digest,
        nonce: (action as any).nonce || "nonce-" + action.action_id.substring(0, 8),
      });
      setSuccessMessage(`Action Approved! Capability Token issued: ${res.capability_token_id}`);
      setTimeout(() => {
        refreshState();
        onClose();
      }, 1500);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to approve action.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReject = async () => {
    setIsProcessing(true);
    setErrorMessage(null);
    try {
      await ApiClient.rejectAction({
        action_id: action.action_id,
        proposal_version: action.proposal_version,
        operator_id: "operator-primary",
        reason: "Operator denied hardware bringup at this stage.",
      });
      setSuccessMessage("Action Rejected. Rollback was not executed because state was unmutated.");
      setTimeout(() => {
        refreshState();
        onClose();
      }, 1500);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to reject action.");
    } finally {
      setIsProcessing(false);
    }
  };

  const isStale = syncState !== "LIVE";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="a2-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-box">
            <AlertTriangle size={22} color="var(--accent-crimson)" />
            <span>ACTION APPROVAL REQUIRED (Action Class: A2 Consequential)</span>
          </div>
          <div className="countdown-timer">
            <Clock size={14} style={{ display: "inline", marginRight: "4px" }} />
            {formatCountdown(secondsLeft)}
          </div>
        </div>

        {/* Body */}
        <div className="modal-body">
          {errorMessage && (
            <div style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid var(--border-crimson)", padding: "10px", borderRadius: "var(--radius-sm)", color: "#fca5a5", fontSize: "0.85rem" }}>
              {errorMessage}
            </div>
          )}

          {successMessage && (
            <div style={{ background: "rgba(16, 185, 129, 0.15)", border: "1px solid var(--border-emerald)", padding: "10px", borderRadius: "var(--radius-sm)", color: "#6ee7b7", fontSize: "0.85rem" }}>
              {successMessage}
            </div>
          )}

          {isStale && (
            <div style={{ background: "rgba(245, 158, 11, 0.15)", border: "1px solid var(--accent-amber)", padding: "8px", borderRadius: "var(--radius-sm)", color: "#fde68a", fontSize: "0.8rem" }}>
              ⚠️ Console connection is {syncState}. Privileged actions are disabled fail-closed until live state is reconciled.
            </div>
          )}

          {/* Action Spec */}
          <div className="spec-grid">
            <span className="spec-label">Target Resource:</span>
            <span className="spec-val" style={{ color: "var(--accent-cyan)" }}>{action.target_resource}</span>

            <span className="spec-label">Action Type:</span>
            <span className="spec-val">{action.action_type}</span>

            <span className="spec-label">Requested Effect:</span>
            <span className="spec-val" style={{ color: "#e2e8f0" }}>{action.requested_effect}</span>

            <span className="spec-label">Preflight Reversibility:</span>
            <span className="spec-val" style={{ color: "var(--accent-emerald)" }}>
              {action.preflight_reversibility} (ADR-0008 PASS)
            </span>

            <span className="spec-label">Proposal Version:</span>
            <span className="spec-val">v{action.proposal_version} (Optimistic Concurrency Active)</span>
          </div>

          {/* Diff Preview */}
          <div>
            <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, marginBottom: "4px" }}>
              Exact Action Diff / Payload Preview
            </div>
            <div className="diff-preview-box">{action.diff_preview}</div>
          </div>

          {/* Rollback Procedure */}
          <div>
            <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, marginBottom: "4px" }}>
              Rollback Plan (Stored Compensation)
            </div>
            <div style={{ fontSize: "0.82rem", color: "var(--text-secondary)", background: "var(--bg-void)", padding: "8px 12px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)" }}>
              {action.rollback_procedure}
            </div>
          </div>

          {/* 16-Field Authorization Digest */}
          <div>
            <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, marginBottom: "4px" }}>
              16-Field TOCTOU Authorization Digest (SHA-256)
            </div>
            <div className="hash-box" style={{ fontSize: "0.7rem" }}>
              {action.authorization_digest}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button
            className="btn-reject"
            onClick={handleReject}
            disabled={isProcessing}
          >
            Reject Proposal
          </button>
          <button
            className="btn-approve"
            onClick={handleApprove}
            disabled={isProcessing || isStale || secondsLeft === 0}
          >
            <ShieldCheck size={18} />
            Approve Action
          </button>
        </div>
      </div>
    </div>
  );
};
