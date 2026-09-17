import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import {
  ActionProposal,
  ActiveView,
  ConsoleSyncState,
  ProjectSummary,
  RuntimeHealth,
} from "../types";
import { ApiClient } from "../services/api";

interface ConsoleContextType {
  activeView: ActiveView;
  setActiveView: (view: ActiveView) => void;
  syncState: ConsoleSyncState;
  health: RuntimeHealth | null;
  projects: ProjectSummary[];
  activeProject: ProjectSummary | null;
  setActiveProject: (p: ProjectSummary) => void;
  pendingActions: ActionProposal[];
  activeModalAction: ActionProposal | null;
  openApprovalModal: (action: ActionProposal) => void;
  closeApprovalModal: () => void;
  activeEvidence: any | null;
  openEvidenceModal: (ev: any) => void;
  closeEvidenceModal: () => void;
  refreshState: () => Promise<void>;
}

const ConsoleContext = createContext<ConsoleContextType | undefined>(undefined);

export const ConsoleProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeView, setActiveView] = useState<ActiveView>("executive");
  const [syncState, setSyncState] = useState<ConsoleSyncState>("RECONCILING");
  const [health, setHealth] = useState<RuntimeHealth | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectSummary | null>(null);
  const [pendingActions, setPendingActions] = useState<ActionProposal[]>([]);
  const [activeModalAction, setActiveModalAction] = useState<ActionProposal | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<any | null>(null);

  const refreshState = useCallback(async () => {
    try {
      const [h, projList, actions] = await Promise.all([
        ApiClient.getHealth(),
        ApiClient.getProjects(),
        ApiClient.getPendingActions(),
      ]);
      setHealth(h);
      setProjects(projList);
      if (projList.length > 0 && !activeProject) {
        setActiveProject(projList[0]);
      }
      setPendingActions(actions);
      setSyncState("LIVE");
    } catch (err) {
      console.warn("API state reconciliation error:", err);
      setSyncState("DISCONNECTED");
    }
  }, [activeProject]);

  useEffect(() => {
    refreshState();
    const interval = setInterval(refreshState, 5000);
    return () => clearInterval(interval);
  }, [refreshState]);

  // WebSocket connection with auto-reconnect
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimeout: any = null;

    const connectWs = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/stream`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setSyncState("LIVE");
        ws?.send(JSON.stringify({ action: "subscribe", last_confirmed_sequence: 0 }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "SNAPSHOT_REQUIRED") {
            refreshState();
          } else {
            // New event arrived, trigger fresh pull
            refreshState();
          }
        } catch {
          // ignore
        }
      };

      ws.onclose = () => {
        setSyncState("DISCONNECTED");
        reconnectTimeout = setTimeout(connectWs, 3000);
      };

      ws.onerror = () => {
        ws?.close();
      };
    };

    connectWs();
    return () => {
      if (ws) ws.close();
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
    };
  }, [refreshState]);

  return (
    <ConsoleContext.Provider
      value={{
        activeView,
        setActiveView,
        syncState,
        health,
        projects,
        activeProject,
        setActiveProject,
        pendingActions,
        activeModalAction,
        openApprovalModal: (a) => setActiveModalAction(a),
        closeApprovalModal: () => setActiveModalAction(null),
        activeEvidence,
        openEvidenceModal: (ev) => setActiveEvidence(ev),
        closeEvidenceModal: () => setActiveEvidence(null),
        refreshState,
      }}
    >
      {children}
    </ConsoleContext.Provider>
  );
};

export const useConsole = (): ConsoleContextType => {
  const context = useContext(ConsoleContext);
  if (!context) {
    throw new Error("useConsole must be used within a ConsoleProvider");
  }
  return context;
};
