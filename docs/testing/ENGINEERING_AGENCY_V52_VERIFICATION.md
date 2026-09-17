# Universal Brain V5.2 — Engineering Runtime Hardening Verification Record

**Date:** 2026-09-08  
**Checkpoint label:** **Cross-Platform Verified Checkpoint / Target-Machine Evidence Pending**  
**Scope:** `REQ-ENG-021` through `REQ-ENG-033`  
**Parent:** V5.1 Production Engineering Integration

## 1. Verification conclusion

V5.2 is a clean cross-platform implementation checkpoint for semantic sensing, isolation planning/execution authority, distributed worker fencing, multi-repository impact, transactional dependency repair, verified branch integration, persistent services, engineering observability, endurance recording, and target-machine evidence collection.

It is **not** labeled production proven. The execution environment used for this record is Linux and does not contain the optional Tree-sitter package, a production language server, WSL2/Hyper-V, or a completed >=2 hour real-repository endurance record.

The checkpoint therefore uses explicit evidence states rather than treating unavailable deployment checks as success.

## 2. Additions verified in the final V5.2 hardening pass

### Real stdio LSP runtime

`StdioLspBackend` now provides a real shell-free JSON-RPC/LSP process lifecycle:

- launches an operator-specified language server with explicit argv;
- confines the server working directory/document access to the authorized workspace;
- performs `initialize` / `initialized`;
- opens and incrementally changes documents;
- frames and parses `Content-Length` JSON-RPC messages;
- answers a conservative set of server-to-client requests;
- supports `LspSemanticProvider` and `LspRenamePlanner` against a real subprocess transport;
- shuts the language server down deterministically.

The integration test launches a real Python subprocess that speaks LSP framing. This verifies the transport/lifecycle rather than merely mocking the Python protocol object. It does **not** claim that pyright/clangd/rust-analyzer is installed on this machine.

### Authority-gated isolation execution

V5.2 now closes the gap between declarative WSL2/Hyper-V plans and the ToolGateway boundary:

```text
trusted isolation provider
        ↓
validated IsolationCommandPlan
        ↓
IsolationPlanExecutionTool.register_plan()
        ↓
opaque one-time plan_id
        ↓
ToolGateway capability/contract checks
        ↓
host execution
```

The model-facing/tool invocation does not accept arbitrary PowerShell or WSL command strings. The execution tool:

- accepts only a previously registered one-time plan ID;
- confines host working directories to the engineering workspace;
- requires CPU/RAM/PID/wall-time controls;
- requires the correct network-control evidence for the selected policy;
- requires an explicitly authorized WSL distribution or Hyper-V VM;
- consumes the plan ID once to prevent replay;
- records exit/digest/isolation evidence.

### Target-machine evidence layer

`V52TargetEvidenceCollector` emits self-digested evidence reports with `pass`, `fail`, and `skip` states. The evidence bundle can validate:

- real Tree-sitter parsing when installed;
- a real operator-supplied stdio language server;
- WSL2 distribution + `systemd-run` / `unshare` prerequisites;
- Hyper-V PowerShell capability and optional VM existence;
- distributed lease fencing;
- a supplied >=2 hour endurance record.

Supporting commands:

- `scripts/v52_target_evidence.py`
- `scripts/v52_windows_evidence.ps1`
- `scripts/v52_endurance.py`

## 3. Executed verification gates

### Dedicated V5.2 gate

Command family:

```text
pytest -q
  tests/unit/test_engineering_agency_v52.py
  tests/unit/test_engineering_lsp_runtime.py
  tests/unit/test_engineering_isolation_tool.py
  tests/unit/test_engineering_target_evidence.py
```

Result:

```text
19 passed
0 failed
```

### V5 + V5.1 + V5.2 engineering gate

Result:

```text
46 passed
0 failed
```

### Engineering + Intelligence Fabric + Executive + M5 + security/integration gate

Result:

```text
121 passed
0 failed
```

This gate includes the V5/V5.1/V5.2 engineering suites, Intelligence Fabric suites, Executive cognitive tests, M5 command/worker/workspace security tests, S1 authority regression, and key cellular/M3-M5 integration gates.

### API/core/security regression gate

Result:

```text
32 passed
0 failed
```

### Python compilation

```text
python -m compileall -q src tests scripts
PASS
```

## 4. Broader repository suite

The environment does not contain `pgvector`, so the completely unfiltered suite cannot collect `tests/unit/test_db_models.py`.

After excluding only that DB-model collection test:

```text
175 passed
15 failed
8 errors
```

All 23 shown non-passing cases terminate while SQLAlchemy attempts to import the unavailable `aiosqlite` package. `aiosqlite>=0.20.0` is already declared under the project's `dev` dependencies. `pgvector` is already a declared runtime dependency.

The environment also lacks `asyncpg`, so PostgreSQL-backed deployment behavior is not claimed by this record.

These dependency absences are reported as environment blockers, not converted into passing tests.

## 5. Operator Console build status

The source tree contains the V5.2 Engineering Agency console view and API types. A dependency-backed frontend type/build gate could not be completed in this sandbox because the checkout initially contained no `node_modules`. An attempted `npm ci` did not complete within the available execution window.

Global `tsc` therefore reports missing `react`, `react-dom`, `lucide-react`, and their JSX type declarations. This record does **not** classify those missing-module diagnostics as source-level V5.2 UI regressions.

The target machine must run:

```text
cd console
npm ci
npm run build
```

before the frontend deployment gate is considered satisfied.

## 6. Current-environment deployment evidence

The evidence collector was executed in the current Linux environment. The sealed report is:

`docs/testing/evidence/V52_CURRENT_ENVIRONMENT_EVIDENCE.json`

Report digest:

```text
2bafe79d7325fdb9935d47bfef23a1a330e3535837c19f9e22c4e56bbe9b8a2f
```

Digest verification: **PASS**.

Observed states:

| Check | State | Meaning |
|---|---|---|
| Platform | PASS | Linux/Python runtime identified |
| Tree-sitter | SKIP | optional semantic dependency not installed |
| Real external LSP | SKIP | no production language-server command supplied |
| WSL2 | SKIP | current host is not Windows |
| Hyper-V | SKIP | current host is not Windows |
| Distributed lease fencing | PASS | generation-fenced reacquisition probe passed |
| >=2 hour endurance | SKIP | no operator-produced multi-hour record supplied |

Overall evidence status: **PARTIAL**.

This is the intended behavior: unsupported target-specific checks remain explicit skips.

## 7. Requirement traceability

| Requirement | Verification |
|---|---|
| `REQ-ENG-021` | Tree-sitter/LSP semantic provider tests + real stdio LSP subprocess transport |
| `REQ-ENG-022` | stale diagnostic version/digest invalidation tests |
| `REQ-ENG-023` | workspace-confined LSP rename planning tests |
| `REQ-ENG-024` | WSL2/Hyper-V isolation plan tests + one-time isolation execution tool |
| `REQ-ENG-025` | fail-closed resource/network-control tests |
| `REQ-ENG-026` | managed service lifecycle/process-identity test |
| `REQ-ENG-027` | multi-repository dependency fixture tests |
| `REQ-ENG-028` | dependency remediation rollback test |
| `REQ-ENG-029` | durable generation-fencing tests + evidence probe |
| `REQ-ENG-030` | conflict abort + actual merged-tree verification test |
| `REQ-ENG-031` | engineering observability snapshot/API/console implementation |
| `REQ-ENG-032` | atomic endurance harness + >=2h evidence-record validator |
| `REQ-ENG-033` | self-digested target evidence report + pass/fail/skip tests |

## 8. Remaining target-machine gates

V5.2 still requires deployment evidence for the actual Windows configuration before a production-proven label is justified:

1. install/load the real Tree-sitter optional runtime;
2. run a real production language server on a real repository;
3. execute a bounded WSL2 and/or Hyper-V plan through `ToolGatewayIsolationBackend`;
4. independently confirm CPU/RAM/PID/network enforcement on the chosen isolation environment;
5. exercise several real workers with fencing + isolated requirement worktrees;
6. exercise dependency remediation and merged-tree verification against real project failures;
7. exercise persistent services across runtime restart conditions;
8. complete and validate a >=2 hour real-repository endurance run;
9. install the declared persistence dependencies and make the complete applicable test suite green;
10. install frontend dependencies and pass `npm run build`.

Until those evidence gates exist, the correct V5.2 label is:

> **Universal Brain V5.2 — Engineering Runtime Hardening: Cross-Platform Verified Checkpoint / Target-Machine Evidence Pending**

## 9. Packaging gate

The clean V5.2 distribution excludes runtime/generated material including:

- `__pycache__` / bytecode;
- `.pytest_cache`;
- `.brain` / local runtime evidence state;
- `node_modules`;
- `dist`, `build`, and `target` outputs;
- local virtual environments and tool caches.

Packaging inventory at this checkpoint:

```text
327 source/documentation/test/config files
~6,100 Python lines in src/universal_brain/engineering/*.py
ZIP integrity test: PASS
```

The package intentionally includes the sealed **current-environment partial evidence** under `docs/testing/evidence/`, while machine-local `.brain` state is excluded. A separate `.sha256` file accompanies the ZIP.
