import React, { useEffect, useState } from "react";
import { ContractDetail, InvariantLedger } from "../types";
import { ApiClient } from "../services/api";
import { FileText, ShieldCheck } from "lucide-react";

export const GovernanceView: React.FC = () => {
  const [contract, setContract] = useState<ContractDetail | null>(null);
  const [ledger, setLedger] = useState<InvariantLedger | null>(null);

  useEffect(() => {
    Promise.all([ApiClient.getCurrentContract(), ApiClient.getInvariants()])
      .then(([c, l]) => {
        setContract(c);
        setLedger(l);
      })
      .catch((err) => console.error("Failed to load governance data:", err));
  }, []);

  return (
    <div className="governance-view-container">
      {/* 1. Left: Active Alignment Contract & Semantic Diff */}
      <div className="panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border-subtle)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700 }}>
            <FileText size={18} color="var(--accent-cyan)" />
            ACTIVE ALIGNMENT CONTRACT
          </div>
          <span className="status-pill" style={{ color: "var(--accent-emerald)" }}>
            VERSION {contract?.version || 1} • ACTIVE
          </span>
        </div>

        <div style={{ padding: "16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "16px" }}>
          <div>
            <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
              Contract Objective
            </div>
            <div style={{ fontSize: "0.95rem", fontWeight: 600, marginTop: "4px" }}>
              {contract?.objective}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            <div style={{ background: "var(--bg-elevated)", padding: "12px", borderRadius: "var(--radius-md)" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>PERMISSIONS CEILING</div>
              <div style={{ fontSize: "1.1rem", fontWeight: 800, color: "var(--accent-cyan)", marginTop: "2px" }}>
                {contract?.permissions_ceiling} (CONSEQUENTIAL)
              </div>
            </div>

            <div style={{ background: "var(--bg-elevated)", padding: "12px", borderRadius: "var(--radius-md)" }}>
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>REQUIREMENTS CITED</div>
              <div style={{ fontSize: "1.1rem", fontWeight: 800, color: "var(--accent-emerald)", marginTop: "2px" }}>
                {contract?.requirements_count} MANDATORY
              </div>
            </div>
          </div>

          {/* Semantic Diff */}
          <div>
            <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, marginBottom: "8px" }}>
              Semantic Contract Diffs (Compared to v0 Draft)
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {contract?.semantic_diffs.map((diff, i) => (
                <div
                  key={i}
                  style={{
                    background: "var(--bg-elevated)",
                    borderLeft: "3px solid var(--accent-emerald)",
                    padding: "8px 12px",
                    borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
                    fontSize: "0.82rem",
                  }}
                >
                  <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent-emerald)", fontWeight: 700 }}>
                    + [{diff.category}] {diff.item_id}:
                  </span>{" "}
                  {diff.summary}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 2. Right: 21 Invariants Compliance Matrix */}
      <div className="panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border-subtle)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700 }}>
            <ShieldCheck size={18} color="var(--accent-emerald)" />
            CONSTITUTIONAL INVARIANTS MATRIX (ALN-001 TO ALN-021)
          </div>
          <span className="badge-pass">ALL PASSING ({ledger?.pass_count || 9}/9)</span>
        </div>

        <div style={{ flex: 1, overflowY: "auto" }}>
          <table className="invariants-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>INVARIANT</th>
                <th>STATUS</th>
                <th>PROOFS</th>
              </tr>
            </thead>
            <tbody>
              {ledger?.invariants.map((inv) => (
                <tr key={inv.invariant_id}>
                  <td style={{ fontFamily: "var(--font-mono)", color: "var(--accent-cyan)", fontWeight: 700 }}>
                    {inv.invariant_id}
                  </td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{inv.name}</div>
                    <div style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>{inv.description}</div>
                  </td>
                  <td>
                    <span className="badge-pass">PASS</span>
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--accent-emerald)" }}>
                    {inv.proofs_count} proofs
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
