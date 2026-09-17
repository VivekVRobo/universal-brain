import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
import {
  ActionProposal,
  ActiveView,
  ConsoleSyncState,
  ProjectSummary,
  RuntimeHealth,
} from "../types";
import { ApiClient } from "../services/api";
import { OperatorAuth } from "../services/operatorAuth";

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
  const websocketConnected = useRef(false);

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
      setSyncState(websocketConnected.current ? "LIVE" : "RECONCILING");
    } catch (err) {
      console.warn("API state reconciliation error:", err);
      setSyncState(websocketConnected.current ? "DEGRADED" : "DISCONNECTED");
    }
  }, [activeProject]);

  useEffect(() => {
    refreshState();
    const interval = setInterval(refreshState, 5000);
    return () => clearInterval(interval);
  }, [refreshState]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const connectWs = () => {
      if (disposed || !OperatorAuth.getToken()) {
        setSyncState("DISCONNECTED");
        return;
      }

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const baseUrl = `${protocol}//${window.location.host}/ws/stream`;
      ws = new WebSocket(OperatorAuth.websocketUrl(baseUrl));

      ws.onopen = () => {
        websocketConnected.current = true;
        setSyncState("LIVE");
        ws?.send(JSON.stringify({ action: "subscribe", last_confirmed_sequence: 0 }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "SNAPSHOT_REQUIRED") {
            refreshState();
          } else {
            refreshState();
          }
        } catch {
          // Ignore malformed/non-JSON messages; authoritative state is re-fetched.
        }
      };

      ws.onclose = (event) => {
        websocketConnected.current = false;
        setSyncState("DISCONNECTED");
        if (event.code === 4401) {
          OperatorAuth.clear();
          return;
        }
        if (!disposed && OperatorAuth.getToken()) {
          reconnectTimeout = setTimeout(connectWs, 3000);
        }
      };

      ws.onerror = () => {
        ws?.close();
      };
    };

    connectWs();
    const unsubscribe = OperatorAuth.subscribe(() => {
      if (!OperatorAuth.getToken()) {
        ws?.close(4401, "operator authentication cleared");
      }
    });

    return () => {
      disposed = true;
      websocketConnected.current = false;
      unsubscribe();
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
