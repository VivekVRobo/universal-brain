# ADR-0013: Production Engineering Integration

**Status:** V5.1 implementation checkpoint approved by explicit operator direction on 2026-09-08.  
**Date:** 2026-09-08  
**Extends:** ADR-0012 Autonomous Engineering Agency Runtime

## Context

V5 established the engineering-agency primitives required to plan, modify, observe, and verify software work. The next bottleneck is not model intelligence; it is production integration across long-running mission state, code-index freshness, isolated workspaces, verification scope, causal auditability, local compute admission, dependency diagnosis, and service lifecycles.

A large project can run for hours. During that time Universal Brain may restart, the repository may change externally, independent requirement branches may execute concurrently, local models may compete for finite VRAM, and development services may need to remain available across multiple task nodes. Treating these as incidental implementation details would make the system non-recoverable or allow verification to occur against the wrong source tree.

## Decision

Universal Brain V5.1 introduces a **Production Engineering Integration** layer with the following requirements:

1. persist self-verifying mission checkpoints and fail closed when the base repository or retained worktree state has drifted unexpectedly (`REQ-ENG-014`);
2. incrementally refresh the derived code graph and use transitive impact relationships to choose verification scope (`REQ-ENG-015`);
3. hash model requests/responses and causally link them to ToolGateway calls/evidence without forcing raw prompt retention (`REQ-ENG-016`);
4. assign a requirement chain to one isolated Git worktree/branch across analyze → implement → verify, then integrate only after executable verification succeeds (`REQ-ENG-017`);
5. enforce local-model RAM/VRAM/concurrency policy both when selecting a route and when reserving execution capacity (`REQ-ENG-018`);
6. diagnose dependency failures against existing manifests and lockfiles without automatically mutating package state (`REQ-ENG-019`);
7. persist long-running service metadata while delegating process control to an authority-gated backend (`REQ-ENG-020`).

## Recovery Invariant

Provider conversation state and engineering checkpoints are convenience/derived state, not authority. Recovery SHALL NOT:

- turn an in-flight task into `SUCCEEDED` merely because it was running before a crash;
- widen a capability scope;
- accept repository drift silently;
- reuse a worktree whose recorded content fingerprint does not match the recovered content.

Transient task states are recovered conservatively as `REPLAN_REQUIRED` unless independently re-established.

## Requirement-Scoped Worktree Invariant

The unit of isolated source ownership is a requirement chain, not an individual DAG node.

```text
REQ-17
  └─ brain/req-REQ-17
       └─ managed worktree
            ├─ analyze
            ├─ implement
            └─ verify
```

Verification MUST execute against the same worktree that contains the implementation under review. A verified requirement may be committed and serialized into the integration branch. If integration fails, the worktree/commit remains recoverable for replanning rather than being silently discarded.

## Causal Audit Decision

Raw prompts and model responses are not required to be retained in the canonical ledger. Instead the ledger stores deterministic digests and routing/task metadata:

```text
MODEL_REQUESTED(request_sha256)
        ↓ caused-by
MODEL_RESPONSE(response_sha256)
        ↓ caused-by
TOOL_CALLED
        ↓ caused-by
EVIDENCE_PRODUCED
```

This allows an operator to prove which cognition led to which external action while keeping prompt/response content outside the immutable audit store when privacy policy requires that.

## Local Resource Decision

Local inference is treated as a finite engineering resource. A model route can be eligible only if current RAM/VRAM/concurrency constraints admit it, and execution must reserve the resource again atomically enough to catch scheduling races. Resource admission never grants tool authority.

## Service Supervision Decision

The persistent service supervisor stores service identity, command metadata, state, PID, and log references. It does not directly bypass ToolGateway to launch privileged processes. Actual process control is delegated to an injected authority-gated backend.

## Consequences

### Positive

- long missions can resume conservatively after process restart;
- code intelligence and verification stay closer to the repository's current state;
- parallel requirement work cannot accidentally verify another worker's checkout;
- model/tool causality is auditable without storing raw private prompts;
- local Ollama models cannot be scheduled as if RAM/VRAM were unlimited;
- dependency recovery respects the project's existing package-management conventions;
- frontend/backend/ROS/dev-service lifecycles can be represented durably.

### Remaining work

V5.1 still does not provide:

- full Tree-sitter/LSP semantic indexing;
- production WSL2/Hyper-V isolation with quotas;
- a platform-specific authority-gated long-running process backend;
- automatic package installation or general dependency solving;
- multi-repository integration graphs;
- a fully green repository-wide test run in the current sandbox, because `pgvector` and `aiosqlite` are not installed there;
- a target-machine, multi-hour autonomous mission trial with real Ollama/Git/build/service workloads.
