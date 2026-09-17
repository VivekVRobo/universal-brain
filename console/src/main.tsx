import React from "react";
import ReactDOM from "react-dom/client";
import { ConsoleProvider } from "./context/ConsoleContext";
import { AppContent } from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConsoleProvider>
      <AppContent />
    </ConsoleProvider>
  </React.StrictMode>
);
