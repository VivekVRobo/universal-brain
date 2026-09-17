# Intelligence Fabric / Multi-Transport Model Runtime

## Purpose

The Intelligence Fabric makes frontier and local models **replaceable cognitive workers** rather than architectural authorities. The deterministic Universal Brain Kernel continues to own canonical goals, permissions, contracts, evidence, budgets, and action authority.

### Requirement and Invariant Traceability

This runtime slice directly advances **REQ-MOD-001**, **REQ-MOD-003**, **REQ-MOD-005**, **REQ-MOD-006**, **REQ-VER-001**, **REQ-STA-001**, and **REQ-STA-006**, while preserving **ALN-009**, **ALN-011**, **ALN-012**, **ALN-013**, **ALN-014**, and **ALN-020**.

The Fabric deliberately separates three identities that older provider abstractions often collapse together:

1. **Model identity** — the cognitive model/family being requested.
2. **Access route** — the account/provider/endpoint/session through which that model is reachable.
3. **Transport runtime** — API, browser UI, desktop application, or local inference mechanism used to execute the request.

A route failure therefore does not automatically mean a model is unavailable, and a model upgrade does not require redesigning the Kernel.

```text
Canonical task
    |
    v
DeterministicTaskProfiler
    |
    +--> ContextCompiler V2 ---------> minimized, ranked, redacted context
    |
    v
Hard eligibility guards
(capability / sensitivity / context / transport / quota / budget)
    |
    v
IntelligenceRouter
    |
    +--> empirical quality ledger
    +--> route health
    +--> durable route telemetry
    +--> route cost / quota
    |
    v
Escalation Policy Graph / Model Council
    |
    v
Model + Access Route + Transport
    |
    +-------- API
    +-------- authorized browser UI
    +-------- authorized desktop UI
    +-------- local runtime
    |
    v
NormalizedModelResult + normalized tool calls + metadata
    |
    v
Kernel validation / verification / ToolGateway
```

## V3 Runtime Capabilities

The current implementation slice includes:

- model identity vs. access-route vs. transport separation;
- capability, privacy, context, cost, budget, quota, health, and empirical-performance routing;
- deterministic task profiling;
- Context Compiler V2 with ranked repository/file context sources, bounded packing, and secret redaction;
- route-local circuit breaking and rate-limit cooldowns;
- sliding-window operator quota admission;
- durable content-free route telemetry (success/failure, latency, token/cost metadata, recent invocations);
- empirical model-performance ledger with drift detection;
- transport-neutral normalized results;
- provider-neutral streaming boundary with no silent mid-answer model switching after substantive output;
- normalized tool-call extraction for OpenAI-compatible, Anthropic-style, and Gemini-style response shapes;
- deterministic route failover;
- durable non-canonical conversation-reference registry with atomic JSON persistence;
- deterministic result-quality escalation through a policy graph;
- parallel Model Council execution with explicit critic/role independence constraints;
- disagreement graph and synthesis metadata that never count as verification evidence;
- authorized browser-driver boundary plus configurable Playwright chat UI driver;
- desktop-app transport boundary and session supervision;
- authentication-loss detection that fails closed and requests operator intervention;
- read-only Intelligence Fabric observability snapshot for the Operator Console;
- safe live-smoke harness that defaults to dry-run and requires explicit authorization for external calls;
- inline-secret rejection in catalog configuration.

## Context Compiler V2

The Context Compiler is responsible for deciding **what a model needs to see**, not for granting authority. It supports multiple context sources, ranks candidate material against the task, enforces a bounded packing budget, applies redaction, and marks retrieved text as untrusted data.

Key properties:

- Canonical state remains in Universal Brain; provider context is a projection.
- Secrets are filtered before provider dispatch.
- Retrieval content cannot grant new permissions or alter action ceilings.
- Context loss at a provider does not erase Universal Brain state.

## Routing and Escalation

Routing is data-driven. The router does not contain vendor-name branches such as “use Claude for architecture” or “use Astra for coding.” It scores eligible model/route pairs using current capability metadata and local operational evidence.

The escalation layer can attempt economical/local routes first and move through a deterministic policy graph when:

- no eligible route exists at the current stage;
- a transport fails;
- a deterministic result-quality gate rejects the result.

Escalation never bypasses provider quotas, authentication, or Kernel permissions.

## Model Council

The Council assigns **roles**, not permanently bound model names. Example roles include Architect, Researcher, Implementer, Critic, Security Reviewer, and Synthesizer.

Council agreement is advisory only:

> Multi-model consensus is not evidence and cannot satisfy acceptance criteria by itself.

A consequential action still requires the normal Universal Brain evidence, capability, approval, and ToolGateway path.

## Interactive Browser/Desktop Access

Interactive transports are user-authorized access routes. The intended priority is:

```text
Official/compatible machine interface
    -> DOM/accessibility-based browser automation
    -> Windows UI Automation
    -> visual interaction only when necessary
```

The runtime must not implement CAPTCHA bypass, MFA bypass, anti-bot evasion, stealth fingerprinting, credential theft, or rate-limit circumvention. Authentication loss changes the route state and requires operator intervention.

Provider conversation IDs, URLs, or session references are stored only as **non-canonical continuity hints**. Losing them may reduce convenience but cannot lose goals, permissions, commitments, evidence, or audit history.

## Streaming Invariant

Before substantive output is emitted, a failed route may be replaced by another eligible route. After substantive output begins, the runtime must not silently splice output from a different model/route into the same answer. Any restart must be explicit and traceable.

## Tool-Call Boundary

Provider-specific tool-call shapes are normalized into a common representation before the Kernel sees them. A model-generated tool call is only a proposal. It does not execute directly and does not grant itself capabilities.

```text
Model output
  -> normalized tool proposal
  -> Kernel validation
  -> capability / contract / action-class checks
  -> ToolGateway
  -> evidence
```

## Observability and Privacy

Operational telemetry is intentionally content-free. The control plane may retain route IDs, model IDs, latency, success/failure, token/cost estimates, quota state, and invocation timestamps, but it must not store raw prompts/responses merely for routing telemetry.

## Persistence Boundary

The FastAPI dependency container now materializes the database and recovery manager **lazily**. Importing or using read-only/security control-plane endpoints must not require a PostgreSQL/SQLite driver until a persistence-backed operation is actually invoked. This preserves the Runtime Singleton Invariant while preventing an optional backend driver from crashing unrelated API surfaces at import time.

Persistence-backed endpoints still fail closed when their configured backend is unavailable.

## Extension Contract

Adding a new frontier model should normally be a catalog/configuration change plus, only when necessary, a reusable transport protocol implementation. Adding a model must not require changes to the Executive Kernel, ToolGateway, capability model, or canonical event system.

The intended lifecycle is:

```text
new model release
    -> catalog descriptor
    -> one or more access routes
    -> existing transport or new protocol adapter
    -> benchmark/evaluation samples
    -> router learns local performance
```

This keeps Universal Brain model-agnostic even as the frontier changes.

---

# V4 Adaptive Cognitive Control Layer

**Status:** Implemented runtime slice; live external provider smoke tests remain operator/environment gated.

V4 moves the Intelligence Fabric beyond transport plumbing into adaptive cognitive control while preserving the constitutional rule that models are replaceable workers, not authorities.

## V4 Traceable Requirements

| Requirement | Statement | Primary invariant / article |
|---|---|---|
| REQ-IF-V4-001 | Capability routing must be able to incorporate fresh, local, inspectable capability evidence without allowing a model to grant itself authority. | Constitution 3.4; ALN-008 |
| REQ-IF-V4-002 | Model-quality evaluations must be supplied by deterministic harnesses or explicit operator evidence; a tested model must not self-grade. | Constitution IV; ALN-010/011 |
| REQ-IF-V4-003 | Context compilation must retrieve canonical/derived memory with provenance and preserve the distinction between verified state, proposed claims, conflicts, and derived semantic candidates. | Constitution V; ALN-013/021 |
| REQ-IF-V4-004 | Council disagreements must be preserved and may be independently adjudicated, but adjudication/consensus remains advisory rather than verification evidence. | Constitution 4.4; ALN-011 |
| REQ-IF-V4-005 | Browser/desktop conversation continuity may be recovered after operator authorization is healthy without turning provider state into canonical state. | Constitution 5.1/5.3 |
| REQ-IF-V4-006 | Browser attachments require explicit local upload roots. Interactive drivers must not automate credentials, CAPTCHA/MFA bypass, stealth, or rate-limit circumvention. | Constitution 3.1/5.2; ALN-013 |
| REQ-IF-V4-007 | A real Windows UI Automation adapter may drive already-authorized desktop AI applications through the accessibility tree. | ADR-0009; least authority |
| REQ-IF-V4-008 | Canonical TaskDAG nodes may be executed through the Intelligence Fabric, but model tool calls remain proposals and task acceptance requires an external Verification Engine adapter. | ALN-001/010/011 |
| REQ-IF-V4-009 | A2 cognitive work must not silently degrade from required independent multi-model review when the configured policy requires Council execution. | Constitution 3.3/3.4; ALN-008 |

## Capability Discovery Registry

The static catalog capability profile is now a conservative prior. V4 adds a local `CapabilityDiscoveryRegistry` that can ingest evidence from:

- deterministic capability probes;
- benchmark suites;
- explicit operator observations;
- deterministic evaluation runs.

Model self-reports are intentionally not accepted as a capability-evidence source.

Evidence may be global to a model or scoped to a particular access route. Scores are freshness-decayed and blended with the declared prior. The registry exposes effective score, confidence, sample count, freshness state, and evidence references.

This changes **routing knowledge only**. It cannot change action class, permissions, tool grants, contract ceilings, or Kernel authority.

## Adaptive Evaluation Harness

`AdaptiveEvaluationHarness` executes operator/test-defined evaluation cases through the same Intelligence Fabric used in normal work. A deterministic external evaluator returns:

- quality score;
- success/failure;
- evidence reference;
- optional capability observations.

The harness writes quality into the `PerformanceLedger` and optional capability observations into `CapabilityDiscoveryRegistry`. Prompt/response bodies are not persisted by those ledgers.

The tested model never grades itself.

## Memory-Aware Context Retrieval

V4 adds adapters for three existing Universal Brain memory surfaces:

1. `SemanticMemoryContextSource` — derived semantic candidates from `SemanticMemoryIndex`, with source event/version/digest provenance and an explicit `non_authoritative` marker.
2. `EventStoreContextSource` — canonical event retrieval with event hashes, task/project identity, contract version, and timestamps.
3. `MissionBlackboardContextSource` — mission-scoped structured assertions that preserve `VERIFIED`, `PROPOSED`, `CONFLICTED`, and `REJECTED` state plus evidence references.

These sources can be combined with `CompositeContextSource` and packed by Context Compiler V2. Retrieved context remains untrusted input and cannot grant permissions.

## Disagreement Resolution

V4 extends Model Council with optional independent adjudication for explicit disagreement edges.

```text
Member A ─┐
          ├─> disagreement graph ─> independent resolver ─┐
Member B ─┘                                               │
                                                          v
                                                   synthesis model
```

The resolver is selected with model/route independence from the two conflicting members where eligible alternatives exist. Its output must identify evidence gaps and remains marked:

```text
advisory_only = true
consensus_is_evidence = false
```

The synthesizer receives the original member outputs, disagreement graph, and advisory adjudications. It must preserve unresolved uncertainty.

## Provider Session Recovery

`ConversationRegistry` now records recovery count and failure/recovery timestamps for non-canonical provider conversations. `InteractionSessionSupervisor` can:

- detect auth/application loss;
- invalidate affected continuity bindings;
- wait for the operator to restore authentication;
- ask the authorized driver to reopen an existing provider conversation when possible;
- reactivate the same logical binding or bind a replacement provider thread.

Recovery never enters passwords or bypasses MFA/CAPTCHA. Losing every provider conversation still cannot lose canonical mission/project state.

## Authorized Browser Adapter Improvements

The Playwright chat driver now supports:

- multiple DOM/accessibility selector candidates rather than one brittle selector;
- persistent operator-owned browser profiles;
- same-origin validation for stored conversation URLs;
- explicit login/auth-required detection;
- bounded local file attachments through `allowed_upload_roots`;
- session evidence screenshots and response digests;
- continuity recovery hooks.

Provider-specific selectors remain external configuration and require live operator-environment smoke testing before production use.

## Windows Desktop UI Automation

V4 adds `WindowsUIAChatDriver`, an optional `pywinauto`-backed adapter for already-running, already-authorized Windows AI applications.

The driver locates the application through window title/process configuration and uses UI Automation selectors (`auto_id`, title, control type) for prompt, response, and submit controls. It captures a response digest and, when supported by the target UI, a screenshot artifact.

The adapter does not automate sign-in or attempt to conceal automation.

## Adaptive Cognitive Mission Runtime

`AdaptiveCognitiveMissionRuntime` maps canonical `TaskNode` objects into task-scoped Intelligence Fabric profiles and requests.

Key rules:

- `requirement_refs` are mandatory (`ALN-001`);
- acceptance criteria are mandatory (`ALN-010`);
- TaskNode action class and tool scope are copied downward but never expanded;
- model tool calls remain proposals;
- complex/frontier tasks may use Model Council;
- A2 cognition can be configured to require independent Council review;
- without an approved Verification Engine adapter, nodes stop at `VERIFYING` or `TOOL_PROPOSED`;
- only a supplied verification adapter may advance a node to `SUCCEEDED`;
- downstream DAG nodes are released only after verified dependency success.

Therefore V4 can run an end-to-end **cognitive** task DAG while preserving the existing ToolGateway and Verification Engine authority boundaries.

## V4 Operational Observability

The read-only Intelligence status surface additionally exposes:

- number of local capability observations per model;
- effective capability scores derived from local evidence;
- inactive interactive conversation bindings eligible for recovery.

No prompt or response bodies are added to control-plane telemetry.

## Remaining Production Gates

V4 is not a claim that every external UI is production-tested. The following remain environment/operator gated:

- real provider account/model selection and budget ceilings (D-003);
- browser isolation strategy (D-008);
- live ChatGPT/Claude/Gemini/Grok selector smoke tests under authorized user sessions;
- live Windows desktop application UIA selector capture/testing;
- actual ToolGateway execution integration for mission tool proposals;
- a production Verification Engine implementation behind `MissionVerificationAdapter`;
- full external-provider benchmark suites used to populate empirical capability evidence.
