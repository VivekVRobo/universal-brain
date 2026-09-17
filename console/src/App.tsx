import React from "react";
import { Header } from "./components/Header";
import { ExecutiveStream } from "./components/ExecutiveStream";
import { EventGraphExplorer } from "./components/EventGraphExplorer";
import { GovernanceView } from "./components/GovernanceView";
import { IntelligenceFabricView } from "./components/IntelligenceFabricView";
import { EngineeringAgencyView } from "./components/EngineeringAgencyView";
import { A2ApprovalModal } from "./components/A2ApprovalModal";
import { EvidenceViewer } from "./components/EvidenceViewer";
import { useConsole } from "./context/ConsoleContext";

export const AppContent: React.FC = () => {
  const {
    activeView,
    activeModalAction,
    closeApprovalModal,
    activeEvidence,
    closeEvidenceModal,
  } = useConsole();

  return (
    <div className="console-app">
      <Header />
      <main className="console-main">
        {activeView === "executive" && <ExecutiveStream />}
        {activeView === "intelligence" && <IntelligenceFabricView />}
        {activeView === "engineering" && <EngineeringAgencyView />}
        {activeView === "graph" && <EventGraphExplorer />}
        {activeView === "governance" && <GovernanceView />}
      </main>

      {/* A2 Consequential Action Modal */}
      {activeModalAction && (
        <A2ApprovalModal
          action={activeModalAction}
          onClose={closeApprovalModal}
        />
      )}

      {/* Evidence Viewer Modal */}
      {activeEvidence && (
        <EvidenceViewer
          evidence={activeEvidence}
          onClose={closeEvidenceModal}
        />
      )}
    </div>
  );
};
