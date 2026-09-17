import React, { useEffect, useState } from "react";
import { ContractDetail, InvariantLedger } from "../types";
import { ApiClient } from "../services/api";
import { FileText, ShieldCheck } from "lucide-react";

export const GovernanceView: React.FC = () => {
  const [contract, setContract] = useState<ContractDetail | null>(null);
  const [ledger, setLedger] = useState<InvariantLedger | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([ApiClient.getCurrentContract(), ApiClient.getInvariants()])
      .then(([currentContract, currentLedger]) => {
        setContract(currentContract);
        setLedger(currentLedger);
        setError(null);
      })
      .catch((err) => {
        setError(err?.message || "Failed to load governance state.");
      });
  }, []);

  const summary = ledger
    ? ledger.fail_count > 0
      ? `${ledger.fail_count} FAIL • ${ledger.unknown_count} UNKNOWN`
      : ledger.unknown_count > 0
        ? `${ledger.pass_count} PASS • ${ledger.unknown_count} UNKNOWN`
        : `ALL VERIFIED (${ledger.pass_count})`
    : "LOADING";

  const statusColor = (status: string) => {
    if (status === "PASS") return "var(--accent-emerald)";
    if (status === "FAIL") return "var(--accent-crimson)";
    if (status === "WARN") return "var(--accent-amber)";
    return "var(--text-muted)";
  };

  return (
    <div className="governance-view-container">
      <div className="panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border-subtle)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700 }}>
            <FileText size={18} color="var(--accent-cyan)" />
            ALIGNMENT CONTRACT
          </div>
          <span className="status-pill" style={{ color: contract ? "var(--accent-emerald)" : "var(--text-muted)" }}>
            {contract ? `VERSION ${contract.version} • ${contract.status.toUpperCase()}` : "NOT OBSERVED"}
          </span>
        </div>

        <div style={{ padding: "16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "16px" }}>
          {error && <div style={{ color: "var(--accent-crimson)" }}>{error}</div>}

          {!error && !contract && (
            <div style={{ color: "var(--text-muted)", lineHeight: 1.5 }}>
              No fully materialized active Alignment Contract is present in canonical runtime state.
              The console will not substitute demo contract data.
            </div>
          )}

          {contract && (
            <>
              <div>
                <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
                  Contract Objective
                </div>
                <div style={{ fontSize: "0.95rem", fontWeight: 600, marginTop: "4px" }}>
                  {contract.objective}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                <div style={{ background: "var(--bg-elevated)", padding: "12px", borderRadius: "var(--radius-md)" }}>
                  <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>PERMISSIONS CEILING</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 800, color: "var(--accent-cyan)", marginTop: "2px" }}>
                    {contract.permissions_ceiling}
                  </div>
                </div>

                <div style={{ background: "var(--bg-elevated)", padding: "12px", borderRadius: "var(--radius-md)" }}>
                  <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>REQUIREMENTS RECORDED</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 800, color: "var(--accent-emerald)", marginTop: "2px" }}>
                    {contract.requirements_count}
                  </div>
                </div>
              </div>

              <div>
                <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700, marginBottom: "8px" }}>
                  Persisted Semantic Diffs
                </div>
                {contract.semantic_diffs.length === 0 ? (
                  <div style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
                    No semantic-diff artifact is attached to the current canonical contract event.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {contract.semantic_diffs.map((diff, index) => (
                      <div
                        key={index}
                        style={{
                          background: "var(--bg-elevated)",
                          borderLeft: "3px solid var(--accent-emerald)",
                          padding: "8px 12px",
                          borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
                          fontSize: "0.82rem",
                        }}
                      >
                        <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent-emerald)", fontWeight: 700 }}>
                          [{diff.diff_type}] [{diff.category}] {diff.item_id}:
                        </span>{" "}
                        {diff.summary}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="panel" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border-subtle)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700 }}>
            <ShieldCheck size={18} color="var(--accent-cyan)" />
            RUNTIME INVARIANT EVIDENCE
          </div>
          <span className="status-pill">{summary}</span>
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
                    <span className="status-pill" style={{ color: statusColor(inv.status) }}>
                      {inv.status}
                    </span>
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                    {inv.proofs_count > 0 ? `${inv.proofs_count} observed` : "—"}
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
