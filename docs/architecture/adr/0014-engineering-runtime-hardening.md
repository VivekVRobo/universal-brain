# ADR-0014 — Engineering Runtime Hardening

**Status:** Accepted for V5.2 checkpoint  
**Date:** 2026-09-08

## Context

V5/V5.1 established planning, bounded tool feedback, executable verification, requirement worktrees, incremental code graphs, recovery, local-model resource admission, dependency diagnosis, and service supervision. The remaining bottleneck is not additional frontier models; it is engineering agency under real operating-system, repository, and multi-worker conditions.

## Decision

Universal Brain V5.2 adopts the following rules:

1. **Semantic sensing is derived:** Tree-sitter and LSP facts/diagnostics may improve planning/context, but source files, contracts, Git history, and verified evidence remain authoritative.
2. **Refactors are plans before writes:** LSP WorkspaceEdits must be path-confined and still pass through ToolGateway for application.
3. **Isolation must be explicit:** WSL2/Hyper-V are modeled as attested isolation providers. Missing resource/network enforcement fails closed.
4. **Distributed work is generation-fenced:** Durable worker leases use monotonically increasing generations so stale workers cannot regain ownership implicitly.
5. **Cross-repository impact is first-class:** Local manifest dependencies form a derived graph used for replanning and verification scope.
6. **Dependency repair is transactional:** Repairs occur only in clean isolated worktrees and roll back to a captured commit on execution or verification failure.
7. **Integration is verified after merge:** A branch may only be committed into the base after the actual merged tree passes executable verification; conflicts abort automatically.
8. **Persistent process control is authority-gated:** Long-running services are managed by a ToolGateway tool; unknown persisted PIDs are never killed solely by number.
9. **Engineering state is observable, not directly mutable, from the Console:** the new status API/view is read-only.
10. **Endurance is evidence-based:** multi-hour autonomy is only claimed after an actual target-machine endurance record exists.
11. **LSP lifecycle is explicit:** production language servers are launched through a shell-free stdio JSON-RPC runtime with workspace confinement; semantic results remain derived and refactor edits remain plans until ToolGateway applies them.
12. **Isolation execution uses opaque one-time plans:** trusted runtime code registers validated WSL2/Hyper-V plans; ToolGateway authorizes execution by one-time plan ID rather than accepting model-authored host command strings.
13. **Deployment proof is a first-class artifact:** target-machine evidence uses self-digested reports with pass/fail/skip semantics. Unsupported host checks remain skipped, never promoted to success.

## Consequences

- Engineering workers gain stronger semantic and operating-system boundaries without granting models new authority.
- Parallel/distributed execution becomes safer under reassignment and crash recovery.
- Integration failures are detected before a merge commit rather than after main is mutated permanently.
- V5.2 introduces optional semantic dependencies and deployment-specific WSL2/Hyper-V capability probes.
- Some features can be unit/integration tested cross-platform, while real Windows isolation/LSP/endurance evidence remains target-machine gated.
