# Universal Brain V5.2 — Engineering Runtime Hardening

**Status:** Cross-platform verified checkpoint candidate; target-machine evidence pending  
**Scope:** REQ-ENG-021 through REQ-ENG-033  
**Parent:** V5.1 Production Engineering Integration

## Objective

V5.2 hardens the engineering runtime around the remaining non-model bottlenecks: semantic code sensing, operating-system isolation, durable worker coordination, multi-repository impact, dependency rollback, verified integration, operator observability, and endurance.

The core authority rule remains unchanged:

> Models may reason and propose. Only deterministic, capability-gated runtime components may change external state.

## 1. Semantic Code Intelligence

V5.2 adds three replaceable semantic sensing/runtime paths:

1. **Tree-sitter syntax facts** through the optional `tree-sitter-language-pack` runtime. This produces real syntax-tree declarations without claiming cross-file type resolution.
2. **Standard LSP adapters** for `documentSymbol`, `workspace/symbol`, `references`, pull diagnostics, and rename `WorkspaceEdit` planning.
3. **Real stdio LSP runtime** via `StdioLspBackend`, which launches an operator-authorized language server without shell expansion, performs JSON-RPC/LSP framing, initializes a workspace, opens/changes documents, handles a conservative subset of server-to-client requests, and shuts the server down deterministically.

LSP/Tree-sitter state is derived and can be rebuilt. It never becomes canonical project truth.

### Incremental diagnostics

`IncrementalDiagnosticRegistry` binds diagnostics to document versions/content digests. Older reports are rejected and edits can invalidate stale diagnostic state immediately after file changes.

### Symbol-safe refactoring

`LspRenamePlanner` consumes the language server's rename `WorkspaceEdit`, validates every file URI against explicit workspace roots, rejects unhandled `documentChanges`/file operations, and returns a reviewable edit plan. It does not write files.

## 2. WSL2 / Hyper-V Isolation Plans

`WSL2IsolationProvider` and `HyperVIsolationProvider` are declarative isolation planners. Host execution is separated from plan construction. V5.2 now also includes `IsolationPlanExecutionTool` plus `ToolGatewayIsolationBackend`: a trusted runtime registers a validated plan under an opaque one-time ID, and the ToolGateway receives only that ID. This prevents model-authored arbitrary PowerShell/WSL command strings from bypassing the authority boundary.

An isolation request contains explicit ceilings for:

- memory;
- CPU quota;
- process/PID count;
- wall time;
- network mode (`deny`, `allowlist`, or `full`).

The provider must receive an attested capability set. If any requested control cannot be enforced, plan construction fails closed.

For WSL2, the plan uses a dedicated distro and `systemd-run` properties; network denial uses an isolated network namespace when the deployment attests support. Allowlist mode requires a preconfigured authority-gated egress guard.

For Hyper-V, the provider targets an already-managed VM and treats VM resource/network policy as deployment-attested state. VM creation and credentials remain outside the model layer.

## 3. Durable Distributed Worker Leases

`DurableWorkerLeaseStore` persists task leases with:

- worker ID;
- workspace ID;
- expiry/heartbeat;
- monotonically increasing generation number;
- fencing validation.

A stale worker holding generation `N` cannot submit as the active holder after the task is reassigned at generation `N+1`.

Lease files use atomic replacement and an inter-process lock file. Leases coordinate ownership only; they do not replace capability tokens.

## 4. Multi-Repository Dependency Graph

`MultiRepositoryGraphBuilder` discovers repository/package identities and local dependencies from:

- `package.json` / `file:` dependencies;
- `pyproject.toml` / Poetry path dependencies;
- `Cargo.toml` path/name dependencies;
- ROS2 `package.xml` dependencies;
- CMake `add_subdirectory` paths.

The graph can compute downstream repositories that should be re-indexed/reverified after a dependency changes.

## 5. Dependency Remediation With Rollback

V5.1 diagnosed dependency failures but deliberately stopped before installation. V5.2 adds `DependencyRemediationCoordinator` for an isolated, authorized remediation path.

The coordinator requires:

1. a clean isolated Git worktree;
2. explicit manifest-review approval when the plan requires it;
3. authority-gated dependency commands;
4. post-remediation executable verification.

It records the pre-remediation Git commit. If any command or verification step fails, the isolated worktree is reset to that commit through the authorized Git executor.

## 6. Verified Merge / Conflict Coordinator

`SerializedMergeCoordinator` closes a major integration gap.

The source branch must still point to the exact commit that was verified in its requirement worktree. Under a serialization lock the coordinator then:

1. confirms the base checkout is clean;
2. performs `merge --no-ff --no-commit`;
3. inspects unresolved conflicts;
4. aborts on any conflict;
5. runs executable verification against the **actual merged tree**;
6. aborts if verification fails;
7. creates the merge commit only after verification passes.

This prevents the earlier failure mode where a branch is verified independently but its integrated combination is never tested.

## 7. Authority-Gated Persistent Services

`ManagedServiceProcessTool` is a real `ToolGateway` tool for long-running engineering processes. It supports start/status/log/stop without `shell=True`, confines working directories to the engineering workspace, sanitizes environment variables, uses an executable allowlist, and gives the child its own process group/session.

The tool intentionally refuses to kill a PID that it does not own in the current runtime instance. After a restart, a persisted numeric PID alone is insufficient proof of process identity because PID reuse could terminate an unrelated process.

`ToolGatewayServiceBackend` connects the tool to `PersistentServiceSupervisor`.

## 8. Engineering Agency Operator Console

The control plane exposes `GET /api/v1/engineering/status`, containing only read-only engineering state:

- indexed files/symbols/references;
- active requirement worktrees;
- durable worker leases;
- multi-repository edge counts;
- managed service state;
- attached semantic backends;
- attached isolation provider.

The React Operator Console adds an **Engineering** view. It does not expose a shortcut around capability/approval gates.

## 9. Endurance Harness

`EngineeringEnduranceHarness` supports long-running real-repository scenarios with:

- requested run duration;
- bounded failure policy;
- atomic progress records after every cycle;
- evidence references per cycle;
- final pass/fail report.

CI uses short deterministic cycles. A genuine multi-hour endurance claim requires a target-machine run and an operator-produced endurance record; this checkpoint does not fabricate that evidence.


## 10. Target-Machine Evidence Bundle

V5.2 now includes a deployment-evidence layer rather than treating missing host proof as an informal note.

`V52TargetEvidenceCollector` emits a self-digested report with explicit `pass`, `fail`, and `skip` states for:

- real Tree-sitter parsing when the optional semantic dependency is installed;
- a real operator-supplied stdio language server;
- WSL2 distribution and `systemd-run` / `unshare` prerequisites on Windows;
- Hyper-V PowerShell capability and optional managed VM existence;
- durable generation-fenced lease reacquisition;
- a supplied multi-hour endurance record.

The report intentionally remains `partial` when a target-specific check cannot run. A Linux CI run cannot become evidence that WSL2 or Hyper-V works.

Operator helpers:

- `scripts/v52_target_evidence.py` — non-destructive target evidence collector;
- `scripts/v52_windows_evidence.ps1` — Windows wrapper;
- `scripts/v52_endurance.py` — shell-free, bounded command-cycle endurance runner with per-cycle hashes/logs.

A multi-hour endurance gate requires a passing run of at least two hours; shorter CI/smoke records are not upgraded into multi-hour evidence.

## 11. Known Boundaries

This checkpoint does **not** claim:

- that an external production language server (pyright/clangd/rust-analyzer/etc.) has been launched in this Linux sandbox; the stdio LSP runtime itself is integration-tested against a real subprocess-speaking LSP fixture;
- that Tree-sitter optional dependencies are installed here;
- that WSL2/Hyper-V execution was smoke-tested from this Linux sandbox;
- that dependency remediation was allowed to modify an external package registry/network;
- that a multi-hour real-repository endurance run has already completed;
- that every repository-wide persistence test can run without the missing optional DB packages.

Those are deployment/evidence gates, not hidden successes.
