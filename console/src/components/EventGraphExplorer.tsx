import React, { useEffect, useState } from "react";
import { CausalGraph, CausalGraphNode } from "../types";
import { ApiClient } from "../services/api";
import {
  Copy,
  GitBranch,
  HelpCircle,
  Info,
  Network,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

export const EventGraphExplorer: React.FC = () => {
  const [graph, setGraph] = useState<CausalGraph | null>(null);
  const [selectedNode, setSelectedNode] = useState<CausalGraphNode | null>(null);
  const [causalPathNodeIds, setCausalPathNodeIds] = useState<Set<string>>(new Set());
  const [copiedHash, setCopiedHash] = useState(false);

  useEffect(() => {
    ApiClient.getCausalGraph()
      .then((g) => {
        setGraph(g);
        if (g.nodes.length > 0) {
          setSelectedNode(g.nodes[g.nodes.length - 1]);
        }
      })
      .catch((err) => console.error("Failed to load causal graph:", err));
  }, []);

  // Backward causal walk ("WHY?")
  const handleTraceWhy = () => {
    if (!selectedNode || !graph) return;
    const path = new Set<string>();
    path.add(selectedNode.id);

    let currentId = selectedNode.id;
    let foundParent = true;

    while (foundParent) {
      foundParent = false;
      const edge = graph.edges.find((e) => e.target === currentId && e.relation_type === "CAUSED_BY");
      if (edge && !path.has(edge.source)) {
        path.add(edge.source);
        currentId = edge.source;
        foundParent = true;
      }
    }
    setCausalPathNodeIds(path);
  };

  const handleCopyHash = () => {
    if (!selectedNode) return;
    navigator.clipboard.writeText(selectedNode.event_hash);
    setCopiedHash(true);
    setTimeout(() => setCopiedHash(false), 2000);
  };

  return (
    <div className="graph-view-container">
      {/* 1. Left Canvas: Interactive Visual Causal DAG */}
      <div className="panel graph-canvas-panel">
        <div className="graph-controls-bar">
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <Network size={18} color="var(--accent-violet)" />
            <span style={{ fontWeight: 700, fontSize: "0.9rem" }}>TOTAL AWARENESS CAUSAL GRAPH (ALN-021)</span>
          </div>

          <div style={{ display: "flex", gap: "8px" }}>
            <button
              className="btn-reject"
              style={{ padding: "6px 12px", fontSize: "0.78rem", display: "flex", alignItems: "center", gap: "6px" }}
              onClick={handleTraceWhy}
              disabled={!selectedNode}
            >
              <HelpCircle size={14} color="var(--accent-cyan)" />
              Trace Root Intent ("Why?")
            </button>
            <button
              className="btn-reject"
              style={{ padding: "6px 12px", fontSize: "0.78rem", display: "flex", alignItems: "center", gap: "6px" }}
              onClick={() => setCausalPathNodeIds(new Set())}
            >
              <RotateCcw size={14} />
              Reset Highlight
            </button>
          </div>
        </div>

        {/* DAG Nodes Display */}
        <div className="dag-canvas" style={{ padding: "24px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "20px" }}>
          {graph?.nodes.map((node, idx) => {
            const isSelected = selectedNode?.id === node.id;
            const isCausalPath = causalPathNodeIds.has(node.id);

            return (
              <div
                key={node.id}
                onClick={() => setSelectedNode(node)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "16px",
                  cursor: "pointer",
                  opacity: causalPathNodeIds.size > 0 && !isCausalPath ? 0.35 : 1,
                  transition: "all 0.2s ease",
                }}
              >
                {/* Node Box */}
                <div
                  style={{
                    background: isSelected ? "var(--bg-highlight)" : "var(--bg-elevated)",
                    border: `1.5px solid ${
                      isSelected
                        ? "var(--accent-cyan)"
                        : isCausalPath
                        ? "var(--accent-violet)"
                        : "var(--border-subtle)"
                    }`,
                    borderRadius: "var(--radius-md)",
                    padding: "12px 16px",
                    width: "420px",
                    boxShadow: isSelected ? "0 0 16px var(--accent-cyan-glow)" : "none",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.72rem",
                        color: "var(--accent-cyan)",
                        fontWeight: 700,
                      }}
                    >
                      {node.event_type}
                    </span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--text-muted)" }}>
                      {new Date(node.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.85rem", color: "var(--text-primary)", fontWeight: 600 }}>
                    {node.payload_summary}
                  </div>
                  <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "4px", fontFamily: "var(--font-mono)" }}>
                    Actor: {node.actor_id}
                  </div>
                </div>

                {/* Edge Connector indicator */}
                {idx < (graph?.nodes.length || 0) - 1 && (
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--accent-violet)", fontSize: "0.75rem", fontFamily: "var(--font-mono)" }}>
                    <GitBranch size={16} />
                    <span>CAUSED_BY</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. Right Panel: Node Inspector */}
      <div className="panel node-inspector-panel">
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700, fontSize: "0.9rem" }}>
          <Info size={16} color="var(--accent-cyan)" />
          SELECTED EVENT INSPECTOR
        </div>

        {selectedNode ? (
          <>
            <div className="inspector-section">
              <span className="inspector-label">Event Type</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", color: "var(--accent-cyan)", fontWeight: 700 }}>
                {selectedNode.event_type}
              </span>
            </div>

            <div className="inspector-section">
              <span className="inspector-label">Event ID</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                {selectedNode.id}
              </span>
            </div>

            <div className="inspector-section">
              <span className="inspector-label">Actor ID & Timestamp</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
                {selectedNode.actor_id} • {selectedNode.timestamp}
              </span>
            </div>

            <div className="inspector-section">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span className="inspector-label">SHA-256 Merkle Hash (ALN-016)</span>
                <button
                  onClick={handleCopyHash}
                  style={{ background: "transparent", border: "none", color: "var(--text-secondary)", cursor: "pointer" }}
                >
                  <Copy size={12} /> {copiedHash ? "Copied!" : ""}
                </button>
              </div>
              <div className="hash-box">{selectedNode.event_hash}</div>
            </div>

            <div className="inspector-section">
              <span className="inspector-label">Integrity Evidence</span>
              <div style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: "0.78rem" }}>
                Hash recorded in canonical event envelope. Full-chain verification is reported separately under Governance (ALN-016).
              </div>
            </div>

            <div className="inspector-section">
              <span className="inspector-label">Payload Summary</span>
              <div className="json-viewer">{JSON.stringify(selectedNode, null, 2)}</div>
            </div>
          </>
        ) : (
          <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: "20px" }}>
            Select an event node in the graph to inspect cryptographic lineage and payload.
          </div>
        )}
      </div>
    </div>
  );
};
