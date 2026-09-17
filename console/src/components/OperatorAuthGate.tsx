import React, { FormEvent, useEffect, useState } from "react";
import { ApiClient } from "../services/api";
import { OperatorAuth } from "../services/operatorAuth";

export const OperatorAuthGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [authenticated, setAuthenticated] = useState(Boolean(OperatorAuth.getToken()));
  const [keyValue, setKeyValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => OperatorAuth.subscribe(() => {
    setAuthenticated(Boolean(OperatorAuth.getToken()));
  }), []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setChecking(true);
    setError(null);
    try {
      OperatorAuth.setToken(keyValue);
      await ApiClient.getHealth();
      setAuthenticated(true);
      setKeyValue("");
    } catch {
      OperatorAuth.clear();
      setAuthenticated(false);
      setError("Authentication failed. Check the configured operator API key.");
    } finally {
      setChecking(false);
    }
  };

  if (authenticated) return <>{children}</>;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "var(--bg-void, #070b12)",
        color: "var(--text-primary, #e5edf7)",
        padding: "24px",
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: "min(460px, 100%)",
          border: "1px solid var(--border-subtle, #263244)",
          borderRadius: "12px",
          padding: "28px",
          background: "var(--bg-panel, #0d1420)",
        }}
      >
        <h1 style={{ marginTop: 0, fontSize: "1.25rem" }}>Operator authentication</h1>
        <p style={{ color: "var(--text-muted, #92a0b3)", lineHeight: 1.5 }}>
          Enter the operator API key configured on this Universal Brain runtime. The key is kept only in this browser tab session.
        </p>
        <label style={{ display: "block", fontSize: "0.8rem", marginBottom: "8px" }}>
          Operator API key
        </label>
        <input
          type="password"
          autoComplete="off"
          value={keyValue}
          onChange={(event) => setKeyValue(event.target.value)}
          disabled={checking}
          style={{
            boxSizing: "border-box",
            width: "100%",
            padding: "11px 12px",
            borderRadius: "8px",
            border: "1px solid var(--border-subtle, #334155)",
            background: "var(--bg-void, #070b12)",
            color: "inherit",
          }}
        />
        {error && <p style={{ color: "#fca5a5", fontSize: "0.82rem" }}>{error}</p>}
        <button
          type="submit"
          disabled={checking || !keyValue.trim()}
          style={{
            width: "100%",
            marginTop: "16px",
            padding: "11px 14px",
            borderRadius: "8px",
            border: 0,
            cursor: checking ? "wait" : "pointer",
            fontWeight: 700,
          }}
        >
          {checking ? "Verifying…" : "Authenticate"}
        </button>
      </form>
    </div>
  );
};
