# Engineering Agency V5.1 — Production Engineering Integration

V5.1 turns the V5 engineering primitives into a more durable production-oriented control loop. It remains subordinate to the deterministic Executive Kernel, Alignment Contract, capability authority, Verification Engine, and ToolGateway.

## Runtime Flow

```text
Project / Alignment Contract
          │
          ▼
Hierarchical Engineering Planner
          │
          ▼
Mutable TaskDAG
          │
          ├────────────── checkpoint + workspace fingerprints
          │
          ▼
Requirement Scheduler
          │
   ┌──────┴─────────┐
   │                │
REQ-A worktree    REQ-B worktree
   │                │
   ▼                ▼
Context / Code Graph / Model Cognition
   │                │
   ▼                ▼
Tool proposal → ToolGateway → evidence
   │                │
   ▼                ▼
Observation → diagnose / repair
   │                │
   ▼                ▼
Impact-aware executable verification
   │                │
   └──────┬─────────┘
          ▼
verified commit
          │
          ▼
serialized branch integration
          │
          ▼
incremental code-graph refresh
          │
          ▼
TaskDAG continues
```

## 1. Durable Mission Recovery

`EngineeringCheckpointStore` writes an atomic, self-verifying checkpoint. It stores the DAG, engineering-run metadata, requirement-worktree bindings, the base repository fingerprint, and retained-worktree fingerprints. Workspace fingerprints intentionally exclude generated/runtime trees such as `.git`, `.brain`, `node_modules`, `dist`, `build`, `target`, caches, and virtual environments.

Recovery fails closed on unexpected drift. In-flight states are downgraded to `REPLAN_REQUIRED`; recovery never manufactures successful completion.

## 2. Incremental Code Intelligence

`CodeGraphIndexer.refresh()` compares per-file digests and updates changed/deleted graph entries rather than rebuilding the entire derived index. Impact queries walk dependencies transitively so a changed leaf source can identify dependent source files and affected tests.

This remains a conservative graph foundation. Python uses deterministic AST extraction; additional languages use lexical symbol extraction. Full LSP/Tree-sitter semantics remain future work.

## 3. Impact-Aware Verification

`ImpactAwareExecutableVerificationAdapter` can resolve the actual requirement worktree for a node and scope compatible test commands to impacted tests. Changes to manifests/build configuration keep full verification instead of narrowing the gate unsafely.

Verification evidence remains the authority for success; model assertions are not accepted as proof.

## 4. Requirement-Scoped Worktrees

`RequirementWorktreeManager` keeps one managed worktree for each active requirement chain. Worktree capacity is bounded, so the scheduler can reuse an existing requirement slot while refusing to overcommit new isolated branches.

Finalization is retry-safe:

1. commit verified changes once;
2. merge the verified branch into the integration checkout;
3. if merge/integration fails, preserve the verified commit and retry integration without duplicating the commit;
4. remove the worktree only after successful integration.

## 5. Causal Cognition Audit

`EngineeringCausalAuditor` stores request/response SHA-256 digests plus task/model/route metadata. ToolGateway accepts the causal model-response event ID and emits auditable Tool/Evidence event IDs back to the caller. Follow-up cognition can therefore reference the exact observation that caused it.

Raw prompt/response bodies are deliberately excluded from the canonical ledger by this bridge.

## 6. Ollama Resource Scheduling

`OllamaRouteResourcePolicy` bridges the local resource manager into both routing and runtime execution. Selection can reject a route that cannot fit current resource conditions; execution additionally reserves/releases the local model profile around inference so a later scheduling race cannot silently oversubscribe RAM/VRAM/concurrency limits.

## 7. Dependency Diagnosis

`DependencyFailureDiagnoser` identifies common Python, npm-family, Cargo, CMake, and ROS2 dependency failures and maps them to the repository's existing manifests/lockfiles. It proposes conservative commands such as frozen/locked install or fetch operations. It does not run them itself.

## 8. Persistent Service Supervision

`PersistentServiceSupervisor` records long-running service state atomically and can reconcile persisted service records after restart. The concrete backend remains authority-gated and injectable. This supports future frontend/backend/database/ROS process lifecycles without making the persistence layer itself a process-execution bypass.

## 9. Safety / Authority Boundary

V5.1 does not change the system's authority model:

- models propose; ToolGateway executes only with valid authority;
- checkpoints do not grant permissions;
- code graphs are derived state, never canonical truth;
- parallelism is bounded by isolated source ownership;
- verification runs against the source tree being accepted;
- local compute admission is not action authorization;
- service persistence is not permission to spawn processes.

## 10. Next Production Gaps

The highest-value remaining engineering-agency work is:

1. full Tree-sitter/LSP semantic code indexing and incremental diagnostics;
2. WSL2/Hyper-V execution backend with CPU/RAM/network/process policy;
3. platform-specific authority-gated service/process backend;
4. multi-repository dependency and integration graph;
5. lockfile-aware dependency remediation with explicit approval/rollback;
6. durable scheduler queue/lease recovery across multiple concurrent engineering workers;
7. Operator Console Engineering Agency views for worktrees, causal traces, resource reservations, services, and recovery state;
8. real target-machine multi-hour mission trials against large repositories using the connected Ollama models.
