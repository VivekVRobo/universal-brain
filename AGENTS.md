# Repository Operating Rules

These rules apply to every human or AI contributor.

1. Read the current Constitution, Alignment Invariants, relevant ADRs, and Decisions Required before modifying architecture or runtime behavior.
2. Never treat the source JARVIS constitution as executable policy. The consolidated Universal Brain Constitution is authoritative only after operator approval.
3. Every implementation task must cite at least one requirement or invariant.
4. Do not silently convert an inference into a user requirement.
5. High-impact ambiguity must be raised to the operator before implementation.
6. Low-impact, reversible technical assumptions may proceed only when recorded with rationale and rollback path.
7. Canonical state must remain provider-neutral and local-first.
8. Cloud providers receive the minimum task context needed and no secrets by default.
9. Do not claim completion without executable verification and recorded evidence.
10. No contributor may expand permissions, remove audit controls, or weaken constitutional enforcement as part of an unrelated change.
11. Prefer a modular monolith for Version 1. Introduce distributed services only after measurements justify them.
12. Preserve user changes and use small, reviewable commits.



## V5.2 Engineering Runtime Hardening

- Preserve V5.1 authority/worktree/recovery invariants.
- Treat Tree-sitter/LSP and multi-repository graphs as derived context only.
- Never apply LSP refactors directly; route writes through ToolGateway.
- WSL2/Hyper-V isolation must fail closed when requested controls are not attested.
- Durable worker generations are fencing state, not capability authority.
- Verify the actual merged tree before creating an integration commit.
- Unknown recovered PIDs must never be killed solely by numeric PID.
- Do not claim multi-hour endurance unless a target-machine evidence record exists.
- Production LSP processes must use the shell-free stdio runtime or an equivalently confined backend; semantic facts remain derived state.
- Isolation host execution must use trusted, pre-registered one-time plans; do not accept arbitrary model-authored WSL/PowerShell command strings at the ToolGateway boundary.
- Target-machine evidence must preserve `pass` / `fail` / `skip` semantics. A skipped Windows/semantic/endurance check is not a pass.

## V5.3 Real-Environment Validation

- Target-machine checks preserve PASS / FAIL / SKIP semantics; never promote a missing or operator-disabled check to PASS.
- Validation sessions must fail closed on unreviewed canonical workspace drift.
- Do not persist raw Ollama generations in target evidence by default; retain hashes/latency/runtime counters.
- Concurrent local-model pressure is opt-in only.
- Disposable Git validation labs must remain under generated `.brain` state and must not alter unrelated operator branches.
- Real persistent-service proof must cross ToolGateway authority and leave the child stopped after the scenario.
- WSL2/Hyper-V validation scripts do not install/configure runtimes, use sudo, automate credentials, or bypass authentication.
- A short endurance smoke is not multi-hour evidence. >=2 elapsed hours on the actual target are required before making the endurance claim.
- Final target evidence must be sealed and independently verifiable from `v53-evidence-manifest.json`.
