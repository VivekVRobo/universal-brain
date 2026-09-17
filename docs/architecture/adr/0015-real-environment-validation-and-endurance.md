# ADR-0015 — Real-Environment Validation and Endurance

**Status:** Accepted for V5.3 validation-harness checkpoint  
**Date:** 2026-09-08

## Context

V5.2 completed most of the remaining engineering-runtime hardening in code, but deliberately left WSL2/Hyper-V, production LSP, local-model pressure, real service workloads, restart recovery, and multi-hour repository endurance as target-machine proof gates. Cross-platform tests cannot honestly establish those deployment facts.

## Decision

Universal Brain V5.3 introduces a dedicated real-environment validation layer rather than another architecture rewrite.

1. **Target validation is resumable and self-verifying.** Validation state is atomically persisted with a workspace fingerprint and SHA-256 digest. Unreviewed repository drift fails closed.
2. **PASS / FAIL / SKIP semantics remain authoritative.** Missing Windows features, omitted model names, absent endurance records, or operator-disabled pressure tests are SKIP, never PASS.
3. **Local-model validation uses the real Ollama runtime.** Operator-selected model names are enumerated and probed. Raw generations are not retained by default; hashes, byte counts, latency, and runtime counters are sufficient evidence.
4. **Pressure is explicitly opt-in.** A concurrent Ollama probe can intentionally load multiple selected models, but is never enabled by default because it may materially consume RAM/VRAM.
5. **Git conflict testing uses a disposable lab.** The validation harness may create temporary repositories/worktrees under `.brain`, intentionally create a conflict, verify detection/abort, and remove the successful lab. It may not use this as proof of production branch integration by itself.
6. **Persistent-service proof crosses ToolGateway.** A bounded validation service starts/status/logs/stops through capability-gated `manage_service`, and the causal event chain must remain valid.
7. **Restart proof crosses a real process boundary.** One Python process creates a sealed checkpoint and exits; a second process must recover the same session without workspace drift.
8. **Real WSL2 execution remains operator-configured.** When a distro and mapped Linux workspace are supplied, V5.3 may execute one tiny one-time isolation plan through ToolGateway. Failure remains failure; the harness does not install/configure WSL or elevate privileges.
9. **Evidence is sealed for offline verification.** All target-validation artifacts under the evidence root are hashed into a manifest. Tampering or missing artifacts makes offline verification fail.
10. **Endurance requires elapsed reality.** A short smoke proves only the harness. The deployment label can advance only after a >=2-hour passing target-machine engineering mission record and applicable required target checks are present.

## Consequences

- V5.3 can be developed/tested cross-platform while refusing to fabricate Windows evidence.
- The user's Windows machine becomes the authoritative environment for WSL2/Hyper-V/Ollama/endurance proof.
- Target validation can resume after interruption without silently accepting repository changes.
- The project obtains auditable deployment artifacts instead of screenshots or informal claims.
- Hyper-V production proof remains pending until a credential/session-safe deployment path is configured and exercised by the operator; V5.3 does not automate passwords, MFA, or credentials.
