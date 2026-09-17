# Platform Requirements

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Derived from Constitution, ADRs 0001–0008, and System Architecture

---

## 1. Alignment Subsystem

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-ALN-001** | Preserve exact original operator input alongside every structured interpretation. | Golden trace and database foreign key tests |
| **REQ-ALN-002** | Represent objectives, requirements, constraints, non-goals, assumptions, ambiguities, permissions, commitments, and criteria in an Alignment Contract. | JSON schema and state transition tests |
| **REQ-ALN-003** | Trace every executable task, action, and artifact to its active requirement ID and contract version. | Provenance DAG integrity tests |
| **REQ-ALN-004** | Block execution on affected branches when high-impact ambiguity is unresolved (`ALN-004a` deterministic taxonomy). | Adversarial ambiguity classification tests |
| **REQ-ALN-005** | Apply operator corrections by versioning history and invalidating affected descendant nodes only. | Correction propagation property tests |
| **REQ-ALN-006** | Detect and reject silent weakening of explicit operator constraints. | Semantic and deterministic contract-diff tests |

---

## 2. Executive & Project Engine

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-EXE-001** | Present one persistent Executive identity independent of the underlying model provider. | Executive failover scenario tests |
| **REQ-EXE-002** | Maintain a model-neutral System World Model (projects, tasks, agents, models, tools, budgets, checkpoints, evidence). | Registry integration tests |
| **REQ-EXE-003** | Construct a scoped, classified Executive Awareness Package (EAP) capped at 5,000 tokens with hard pagination limits. | EAP schema validation and tokenizer ceiling tests |
| **REQ-EXE-004** | Expose current objective, progress, blockers, pending decisions, and completion evidence to the operator. | CLI / UI acceptance tests |
| **REQ-EXE-005** | Enforce typed Executive Action Commands via JSON-RPC 2.0 / tool calling with 3-attempt retry loop. | Command parser test fixtures |
| **REQ-EXE-006** | Execute zero-data-loss cognitive state handoff between model families during context exhaustion or swap. | Handoff sequence and state continuity tests |
| **REQ-EXE-007** | Execute automatic Safe Rollback on A2 approval timeout (6-hour dead-man's switch) without simulating operator consent. | Timeout and fallback state machine tests |

---

## 3. Models, Agents & Hybrid Access

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-MOD-001** | Separate persistent agent roles from replaceable model providers. | Cross-provider role handoff tests |
| **REQ-MOD-002** | Route requests by capability profile, latency, cost, evaluated benchmark accuracy, and privacy policy. | Deterministic routing test fixtures |
| **REQ-MOD-003** | Persist goals, state, decisions, and checkpoints outside provider conversations. | Provider simulated outage tests |
| **REQ-MOD-004** | Require an independent critic model or deterministic test for consequential outputs. | Critic independence policy tests |
| **REQ-MOD-005** | Implement hybrid access: direct APIs for executive reasoning and sandboxed browser agents for web harvesting. | Egress and sandbox isolation tests |
| **REQ-MOD-006** | Track dynamic model performance decay (time-weighted rolling average, 10% inactivity decay, and <70% drift alerts). | Router decay fixtures & adversarial regression tests |

---

## 4. Tools & Permissions

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-TOL-001** | Route every external effect through one centralized, deny-by-default Tool Gateway. | Architecture boundary & bypass tests |
| **REQ-TOL-002** | Bind action authority to actor, task, target path, operation, contract version, budget, and expiry. | Capability-token cryptographic tests |
| **REQ-TOL-003** | Require preconditions, preflight dry-run rollback (`patch -R --dry-run`), postconditions, and idempotency for A1 actions. | ADR-0008 Rollback engine test suites |
| **REQ-TOL-004** | Require fresh, target-specific operator approval for A2 consequential actions dispatched via UI and Telegram bot. | Approval replay and out-of-band delivery tests |
| **REQ-TOL-005** | Strictly prohibit Version 1 physical robotics actuation, weaponized actions, or autonomous self-escalation. | Tool registry deny tests |

---

## 5. Truth & Reality Verification

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-VER-001** | Use reproducible evidence (compiles, test runs, measurements) rather than model confidence for verified completion. | Completion state-machine tests |
| **REQ-VER-002** | Scale verification rigor to consequence, uncertainty, and evidence quality. | Risk profile fixtures |
| **REQ-VER-003** | Prevent missing, stale, skipped, or failed checks from producing a verified state. | Negative aggregation tests |
| **REQ-VER-004** | Retain tamper-evident evidence bundles mapped directly to contract acceptance criteria. | Evidence integrity tests |

---

## 6. State, Geo-Redundant Memory & Resilience

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-STA-001** | Keep canonical state, relational ledgers, and private data local-first by default. | Storage inspection tests |
| **REQ-STA-002** | Minimize, classify, and redact cloud-bound context; exclude secrets by default. | Egress scanning adversarial tests |
| **REQ-STA-003** | Record state-changing events in an append-only, hash-linked audit chain. | Hash-chain mutation tests |
| **REQ-STA-004** | Revalidate contract version, leases, permissions, and idempotency before resuming paused/crashed work. | Crash & recovery simulation tests |
| **REQ-STA-005** | Disable state-changing execution immediately if audit or verification service health fails. | Fault injection tests |
| **REQ-STA-006** | Enforce explicit per-task, per-provider, and monthly cost and compute budgets. | Budget exhaustion tests |
| **REQ-STA-007** | Implement 4-Tier Geo-Redundant Memory: 6-hour encrypted GitHub dumps, chunked micro-batches, and Telegram cold storage. | Cold-boot disaster recovery drill (<15m RTO) |
| **REQ-STA-008** | Manage ephemeral burst compute workers (Colab/Kaggle) with pull-based queue, 60s heartbeats, and safe sleep. | Worker disconnect and re-queue tests |
| **REQ-STA-009** | Enforce storage lifecycle retention policy (30-day hot, 90-day cold, deep archive, 80% warning, 90% pause). | Disk quota simulation tests |

---

## 7. Operator Control

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-OPS-001** | Allow operator to pause, resume, correct, cancel, and revoke capability leases at any time via UI or Telegram bot. | End-to-end control tests |
| **REQ-OPS-002** | Provide an inspectable trace answering "what is happening, why, with what authority, and what proves it?". | Trace explorer acceptance tests |
| **REQ-OPS-003** | Protect constitutional amendments through semantic diff, invariant analysis, cooling period, and signature. | Amendment workflow tests |

---

## 8. Autonomous Engineering Agency Runtime (V5)

These requirements are directly authorized by the operator's V5 engineering-agency plan and remain bounded by the existing Constitution and ToolGateway authority model.

| ID | Requirement | Verification Method |
|---|---|---|
| **REQ-ENG-001** | Decompose large engineering goals into requirement-traceable, hierarchical TaskDAG branches with explicit integration gates. | Planner scale/traceability tests |
| **REQ-ENG-002** | Support deterministic DAG mutation and descendant invalidation when new dependencies or failures are discovered, without losing provenance or introducing cycles. | Mutation/cycle/invalidation tests |
| **REQ-ENG-003** | Implement a bounded cognition → authority-gated tool execution → observation → cognition repair loop. Models may propose actions but may never mint their own authority. | Closed-loop tool proposal tests |
| **REQ-ENG-004** | Mark engineering tasks successful only after real executable verification adapters produce required evidence; missing checks fail closed. | Compiler/test adapter tests |
| **REQ-ENG-005** | Maintain a derived code intelligence graph containing file digests, symbols, imports/calls/references, and test-impact relationships. | Symbol/reference/impact fixtures |
| **REQ-ENG-006** | Execute repository changes through reviewable Git transactions and isolated managed worktrees rather than uncontrolled shared checkouts. | Git worktree/branch/path-confinement tests |
| **REQ-ENG-007** | Permit independent READY engineering branches to execute concurrently only under bounded concurrency and isolated workspace ownership. | Parallel scheduler/worktree isolation tests |
| **REQ-ENG-008** | Preserve engineering observations, verification evidence, and project-level completion state in model-neutral form so long-running work can resume safely. | Crash/recovery and completion-audit tests |
| **REQ-ENG-009** | Admit local/Ollama model work using explicit RAM/VRAM/concurrency profiles and resource reservations rather than loading models blindly. | Resource admission/reservation tests |
| **REQ-ENG-010** | Declare whole-project completion only when every active requirement is covered, all DAG nodes succeeded, and every succeeded node has passing executable verification evidence. | Definition-of-Done audit tests |
| **REQ-ENG-011** | Independently verify remote worker completion claims before the authoritative worker queue accepts them as completed. | Worker result rejection/acceptance tests |
| **REQ-ENG-012** | Classify common engineering failures deterministically and insert requirement-preserving recovery tasks into the mutable DAG when a safe recovery class is known. | Failure-classification/replan insertion tests |
| **REQ-ENG-013** | Discover repository language/build/test ecosystems read-only so planning and verification can use existing project conventions instead of inventing new ones. | Workspace discovery fixtures |
| **REQ-ENG-014** | Persist self-verifying engineering mission checkpoints with repository/worktree fingerprints and fail closed on unreviewed workspace drift during recovery. | Checkpoint integrity/drift/recovery tests |
| **REQ-ENG-015** | Refresh the derived code graph incrementally after source changes and compute transitive source/test impact for verification selection. | Incremental graph and transitive-impact tests |
| **REQ-ENG-016** | Link model request/response digests, ToolGateway calls, and produced evidence through the canonical causal event graph without requiring raw prompt/response retention. | Causal-audit lineage and hash tests |
| **REQ-ENG-017** | Preserve one isolated Git branch/worktree across a requirement's analyze → implement → verify chain and integrate only after executable verification succeeds. | Requirement-affinity, retry-safe integration, and capacity tests |
| **REQ-ENG-018** | Apply local-model RAM/VRAM/concurrency admission both at route selection and at execution-time reservation to prevent oversubscription races. | Router/runtime resource-policy tests |
| **REQ-ENG-019** | Diagnose common dependency failures against existing manifests/lockfiles and propose ecosystem-preserving repair commands without installing or mutating dependencies autonomously. | Manifest/lockfile diagnosis tests |
| **REQ-ENG-020** | Persist and recover long-running engineering service state while delegating process start/stop/status/log actions to an authority-gated backend. | Service-supervisor persistence/recovery tests |
| **REQ-ENG-021** | Augment lexical/AST code intelligence with optional real Tree-sitter syntax facts and standard-LSP document/workspace symbol/reference/diagnostic adapters, while treating all semantic indexes as derived state. | Semantic-provider and LSP fixture tests |
| **REQ-ENG-022** | Maintain version/digest-aware incremental diagnostics and invalidate stale diagnostic state after autonomous code changes. | Diagnostic version/invalidation tests |
| **REQ-ENG-023** | Generate symbol-safe refactoring plans from LSP WorkspaceEdits, confine every edit to authorized workspace roots, and never apply refactors outside ToolGateway authority. | Rename-plan confinement tests |
| **REQ-ENG-024** | Represent WSL2 and Hyper-V engineering isolation as explicit, authority-gated execution plans rather than assuming a workspace directory alone is a security boundary. | Isolation-plan tests |
| **REQ-ENG-025** | Fail closed when requested memory, CPU, PID, wall-time, or network controls cannot be attested/enforced by the selected isolation runtime. | Quota/network fail-closed tests |
| **REQ-ENG-026** | Provide a real ToolGateway-gated persistent service process tool with process-group containment and safe runtime-identity semantics; recovered unknown PIDs must never be killed blindly. | Managed-service lifecycle tests |
| **REQ-ENG-027** | Maintain a derived multi-repository dependency graph from Python/npm/Cargo/ROS2/CMake manifests and compute downstream repository impact. | Multi-repository manifest fixtures |
| **REQ-ENG-028** | Execute dependency remediation only in clean isolated worktrees through authority-gated commands and deterministically roll back to a captured Git commit if repair or post-repair verification fails. | Remediation rollback tests |
| **REQ-ENG-029** | Coordinate distributed engineering workers with durable expiring leases and monotonically increasing fencing generations so stale workers cannot commit results after reassignment. | Durable lease fencing tests |
| **REQ-ENG-030** | Serialize verified branch integration, bind verification to an immutable source commit, detect merge conflicts, verify the actual merged tree, and abort rather than commit on conflict or verification failure. | Merge coordinator tests |
| **REQ-ENG-031** | Expose read-only Engineering Agency observability (code graph, worktrees, worker leases, repositories, services, semantic/isolation status) through the control plane and Operator Console. | API/schema/UI type checks |
| **REQ-ENG-032** | Provide a resumable endurance harness capable of exercising real repositories for multi-hour runs with atomic progress records and bounded failure policy; short deterministic cycles are used in CI. | Endurance harness tests + operator-run endurance record |
| **REQ-ENG-033** | Produce self-verifying target-machine evidence records that distinguish pass/fail/skip for real Tree-sitter, stdio LSP, WSL2/Hyper-V prerequisites, distributed lease fencing, and multi-hour endurance; evidence collection must not fabricate unsupported deployment claims. | Target evidence collector/report digest tests + operator-run Windows evidence record |
| **REQ-ENG-034** | Persist resumable V5.3 target-validation sessions with self-digested checkpoints and fail closed on unreviewed workspace drift between validation stages. | Validation checkpoint digest/drift/restart tests |
| **REQ-ENG-035** | Validate operator-selected local Ollama models against the real target runtime, recording only response hashes/usage/latency rather than raw generations by default. | Ollama probe tests + target model evidence |
| **REQ-ENG-036** | Exercise real engineering runtime behaviors on the target machine, including disposable worktrees/conflicts, authority-gated service lifecycle, and optional WSL2 one-time ToolGateway isolation execution, without mutating unrelated operator state. | Target scenario tests + Windows evidence bundle |
| **REQ-ENG-037** | Support an explicit opt-in bounded concurrent local-model pressure probe; potentially expensive pressure checks must never run implicitly. | Pressure opt-in/unit tests + target resource evidence |
| **REQ-ENG-038** | Prove checkpoint survival across a real process restart boundary and preserve the same session identity/fingerprint before resuming validation. | Cross-process restart recovery tests |
| **REQ-ENG-039** | Seal every V5.3 target-validation artifact into an offline-verifiable SHA-256 manifest and detect missing, altered, or escaped evidence artifacts. | Evidence manifest tamper tests |
| **REQ-ENG-040** | Require an actual >=2-hour passing target-machine engineering mission/endurance record plus all applicable required target checks before upgrading the deployment label beyond target-evidence-pending. | V5.3 endurance runner + final target evidence review |
