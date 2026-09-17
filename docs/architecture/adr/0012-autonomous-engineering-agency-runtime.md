# ADR-0012: Autonomous Engineering Agency Runtime

**Status:** V5 implementation slice approved by explicit operator direction on 2026-09-08.  
**Date:** 2026-09-08  
**Extends:** ADR-0011 Adaptive Cognitive Control Layer

## Context

V4 can route cognition across multiple models safely, but large software projects require deeper engineering agency: scalable planning, codebase-wide awareness, a closed execution/observation loop, deterministic executable verification, isolated Git workspaces, and bounded parallelism.

Adding more models without these capabilities produces a smarter planner with immature hands. The operator explicitly directed V5 to prioritize engineering agency over additional model integrations.

## Decision

Universal Brain V5 introduces an **Autonomous Engineering Agency Runtime** above V4's Intelligence Fabric and below the existing deterministic authority boundary.

The V5 slice SHALL:

1. replace the fixed design/implementation/verification planner for engineering missions with requirement-oriented hierarchical branches (`REQ-ENG-001`);
2. allow explicit cycle-checked TaskDAG mutation and affected-descendant invalidation (`REQ-ENG-002`, `ALN-005`);
3. run a bounded cognition → ToolGateway → observation → cognition loop (`REQ-ENG-003`, `REQ-TOL-001`);
4. fail closed unless executable verification evidence satisfies acceptance (`REQ-ENG-004`, `ALN-010`, `ALN-020`);
5. maintain a local derived code-symbol/reference graph for context and test-impact analysis (`REQ-ENG-005`, `ALN-012`);
6. manage Git worktrees/commits through an authority-gated executor and confined paths (`REQ-ENG-006`, `ALN-007`, `ALN-016`);
7. permit bounded concurrency only for independent READY DAG branches (`REQ-ENG-007`).

## Authority Boundary

The Engineering Agency Runtime does **not**:

- bypass ToolGateway for external effects;
- mint or widen capability tokens;
- approve A2 actions;
- treat model output or Council agreement as verification evidence;
- treat the derived code graph as canonical source state;
- allow a worker's completion claim to become `SUCCEEDED` without deterministic verification.

## Isolation Decision

V5 introduces managed Git worktree semantics but does not claim complete WSL2/Hyper-V process isolation yet. A future ADR will define the host isolation runtime after operator approval of the concrete Windows strategy. Until then, worktree isolation and existing workspace confinement are the maximum implemented boundary.

## Code Intelligence Decision

V5 begins with deterministic Python AST extraction and conservative lexical extraction for selected additional languages. This is a **code-graph foundation, not a full LSP implementation**. Future work will add language-server-backed definition/reference/diagnostic queries and incremental invalidation.

## Consequences

### Positive

- large contracts produce parallelizable requirement branches rather than a fixed three-node DAG;
- tool failures become observations that models can diagnose and repair;
- completion depends on real executable checks;
- code retrieval can reason about symbols and impacted tests;
- parallel workers have a path toward isolated Git ownership.

### Remaining work

- full LSP/tree-sitter multi-language graph;
- automatic replanner that proposes and applies safe DAG mutations from observed failures;
- WSL2/Hyper-V sandbox provider;
- dependency/build-system resolver;
- integration of the implemented Ollama resource manager into live router admission/eviction telemetry;
- persistent project-level completion evidence storage and operator UI;
- deeper artifact-aware worker verification adapters for specific job types.
