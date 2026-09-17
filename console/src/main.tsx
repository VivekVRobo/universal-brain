import React from "react";
import ReactDOM from "react-dom/client";
import { ConsoleProvider } from "./context/ConsoleContext";
import { AppContent } from "./App";
import { OperatorAuthGate } from "./components/OperatorAuthGate";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <OperatorAuthGate>
      <ConsoleProvider>
        <AppContent />
      </ConsoleProvider>
    </OperatorAuthGate>
  </React.StrictMode>
);
