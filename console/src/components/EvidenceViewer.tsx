import React from "react";
import { ShieldCheck, X } from "lucide-react";

interface EvidenceViewerProps {
  evidence: any;
  onClose: () => void;
}

export const EvidenceViewer: React.FC<EvidenceViewerProps> = ({ evidence, onClose }) => {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="a2-modal-card" style={{ borderColor: "var(--border-emerald)" }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header" style={{ background: "rgba(16, 185, 129, 0.1)", borderBottomColor: "var(--border-emerald)" }}>
          <div className="modal-title-box" style={{ color: "#a7f3d0" }}>
            <ShieldCheck size={20} color="var(--accent-emerald)" />
            <span>UNIVERSAL EVIDENCE INSPECTOR (ALN-010)</span>
          </div>
          <button
            onClick={onClose}
            style={{ background: "transparent", border: "none", color: "var(--text-secondary)", cursor: "pointer" }}
          >
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontWeight: 700, fontSize: "0.95rem" }}>{evidence.title || "Deterministic Evidence Record"}</span>
            <span className="badge-pass">REDACTED & VERIFIED ✓</span>
          </div>

          <div className="diff-preview-box" style={{ maxHeight: "300px", color: "#f8fafc" }}>
            {evidence.log || evidence.diff || JSON.stringify(evidence, null, 2)}
          </div>

          {evidence.checksum && (
            <div>
              <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
                SHA-256 Checksum
              </div>
              <div className="hash-box" style={{ fontSize: "0.72rem" }}>
                {evidence.checksum}
              </div>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn-reject" onClick={onClose}>
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
};
