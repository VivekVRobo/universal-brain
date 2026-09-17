# Universal Brain V5 Engineering Agency Runtime — Verification Record

**Checkpoint date:** 2026-09-08  
**Scope:** First implementation checkpoint of ADR-0012 / REQ-ENG-001 through REQ-ENG-013.  
**Status:** Engineering-agency foundation implemented and regression-tested; not a claim of complete autonomous large-project capability.

## Implemented in this checkpoint

1. **Hierarchical requirement planner (`REQ-ENG-001`)**
   - replaces the fixed engineering-only 3-node shape with architecture + per-requirement analyze/implement/verify branches + project integration;
   - every generated task retains active requirement references (`ALN-001`) and acceptance criteria (`ALN-010`).

2. **Mutable TaskDAG (`REQ-ENG-002`)**
   - safe add/insert-before/insert-after operations;
   - cycle checks after mutation (`ALN-021`);
   - affected-descendant invalidation for replanning (`ALN-005`).

3. **Closed engineering cognition loop (`REQ-ENG-003`)**
   - model tool calls remain proposals;
   - tool names are checked against node `tool_scope`;
   - production execution adapter delegates to centralized ToolGateway (`REQ-TOL-001`);
   - tool observations are returned to cognition for bounded repair iterations;
   - iteration exhaustion becomes `REPLAN_REQUIRED`, not fabricated success.

4. **Executable verification (`REQ-ENG-004`)**
   - deterministic policy discovers pytest, TypeScript, Cargo and ROS2/colcon checks;
   - production executor invokes `run_command` through ToolGateway;
   - missing checks fail closed under `REQ-VER-003` / `ALN-020`.

5. **Code intelligence graph foundation (`REQ-ENG-005`)**
   - file SHA-256 digests;
   - Python AST class/function/method/call/import extraction;
   - conservative lexical symbol extraction for several additional source types;
   - symbol lookup, reference lookup and test-impact inference;
   - `CodeGraphContextSource` integrates symbol-aware snippets with Context Compiler V2.

6. **Git transaction/worktree foundation (`REQ-ENG-006`)**
   - managed worktree path confinement;
   - branch validation;
   - authority-gated worktree add, add, commit, rev-parse and remove command flows;
   - no direct subprocess execution inside the Git engine.

7. **Bounded concurrency safety (`REQ-ENG-007`)**
   - READY branches can execute concurrently in the engineering runtime;
   - concurrency >1 fails closed unless the caller explicitly asserts verified isolated workspace allocation;
   - automatic worktree allocation is still a remaining task, so the default is sequential.

8. **Local model resource admission (`REQ-ENG-009`)**
   - explicit estimated VRAM/RAM/concurrency/cold-start/speed profiles;
   - deterministic admission, scoring, reservation and release;
   - no autonomous model unloading/permission change.

9. **Project Definition-of-Done auditor (`REQ-ENG-010`)**
   - requires every active requirement to appear in the DAG;
   - requires every node to be `SUCCEEDED`;
   - requires passing executable verification evidence for every succeeded node.

10. **Independent worker completion gate (`REQ-ENG-011`)**
    - remote worker completion claims can be rejected before queue completion;
    - verified claims carry independent verification evidence refs.

11. **Deterministic adaptive replanning (`REQ-ENG-012`)**
    - classifies missing dependency, compile/symbol, test and merge-conflict failure classes;
    - injects requirement-preserving recovery tasks before the failed node;
    - unknown failure classes remain explicitly blocked for higher-level replanning.

12. **Read-only workspace ecosystem discovery (`REQ-ENG-013`)**
    - detects Python, npm/TypeScript, Rust/Cargo, CMake and ROS2/colcon project conventions;
    - does not install packages or mutate manifests.

## Additional hardening found during V5 regression work

Two pre-existing M5 portability/process-containment defects were exposed and fixed:

- Windows absolute paths such as `C:\\Windows\\...` are now rejected even when the test/runtime host is POSIX, preventing them from being misinterpreted as relative filenames.
- POSIX subprocesses now launch in a distinct process session before timeout tree-kill logic runs. This prevents `killpg()` from accidentally killing the supervising Universal Brain/pytest process.

## Executed verification

### V5 dedicated tests

```text
14 passed
0 failed
```

### Engineering + Intelligence Fabric + Executive + M5 + API/security selected gate

```text
97 passed
0 failed
```

This gate includes:

- V5 Engineering Agency tests;
- V2/V3/V4 Intelligence Fabric regression tests;
- Executive cognitive tests;
- M5 command-runner, workspace sandbox and ephemeral-worker tests;
- M3/M4 and M5 integration gates;
- cellular-monolith integration;
- API adversarial and S1 authority regression suites.

### Broader repository run excluding `test_db_models.py`

```text
143 passed
15 failed
8 errors
```

All 23 non-passing cases in that broader run were blocked by the execution environment lacking the already-declared optional development dependency `aiosqlite`. The unexcluded full suite stops earlier because `pgvector` is also unavailable in this sandbox. No attempt was made to hide these environment limitations.

### Python compilation

```text
python -m compileall -q src tests
PASS
```

## What V5 still does NOT claim

This checkpoint is **not yet** a complete 50k–100k-line autonomous software engineer. The most important remaining items are:

- full tree-sitter/LSP multi-language symbol/reference/diagnostics integration;
- incremental code-graph invalidation after each patch;
- automatic Git worktree allocation/ownership integrated into every parallel worker;
- WSL2/Hyper-V execution provider with CPU/RAM/network/process quotas;
- lockfile-aware dependency resolution and build-system repair;
- long-running process/service supervisor (frontend/backend/ROS/database lifecycles);
- multi-repository dependency graph and integration scheduler;
- local Ollama resource manager integration into the live Intelligence Router;
- model-request/response digest linkage into the canonical causal event graph;
- production artifact-specific worker verification adapters;
- persistent engineering-run/checkpoint recovery after process restart;
- operator-console Engineering Agency views.

## Verdict

V5 materially improves the **hands and senses** of Universal Brain: planning is more scalable, failures can generate recovery work, model actions can enter a real observe/repair loop, verification can be executable, code retrieval is symbol-aware, Git isolation has a governed transaction layer, and local multi-model resource pressure can be represented explicitly.

The remaining bottleneck has narrowed from generic "engineering agency" to **production integration of isolation, incremental code intelligence, dependency/build orchestration, durable mission recovery, and real large-repository end-to-end trials**.
