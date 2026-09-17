# Universal Brain

Universal Brain is a sovereign, local-first, multi-model executive system designed to preserve human intent from request through execution and verification.

This repository preserves **Planning Baseline 0** as its constitutional/design baseline while also containing an exploratory stabilization runtime. Real external-provider execution remains operator-gated; deterministic Kernel, security, persistence, autonomy, world-model, and Intelligence Fabric slices are implemented and tested incrementally.

---

## Governing Objective

> **Make silent misalignment structurally difficult, observable, and recoverable.**

The system does not claim guaranteed access to unexpressed human intent. It instead establishes enforceable, machine-testable guarantees for explicit instructions:

- Complete requirement and action traceability (`REQ-ALN-001` to `REQ-ALN-006`);
- Versioned constraints, assumptions, corrections, and commitments;
- Fail-closed handling of high-impact ambiguity;
- Centralized permission checks via a deny-by-default Tool Gateway before any consequential action;
- Evidence-backed completion (primary measurements and tests over model assertions);
- Model-independent state, memory, and continuity.

---

## Approved Foundation Decisions

1. **Reversible Digital Actions:** Version 1 may perform approved, reversible digital actions (A1) within declared scopes.
2. **Local-First Canonical Sovereignty:** Canonical state, private data, and ledgers remain local-first; cloud models receive only scoped, minimized context.
3. **Neutral Human Safety:** Human safety is not ranked by identity or relationship. Operator preference breaks ties only when credible human risks are materially equivalent.
4. **Universal Executive Brain (UEB):** No LLM permanently sits at the top. The deterministic Executive Kernel owns canonical truth, while ephemeral Executive Models are leased for reasoning.
5. **Local Windows + WSL2/Hyper-V Execution (No Docker):** Untrusted and model-generated execution boundaries use Windows-native isolation via dedicated WSL2 distributions or Hyper-V VMs without raw Docker dependencies. *(Cloud geo-redundancy via Oracle Always Free is pending operator ratification under Decision D-007).*

---

## Milestone Implementation & Verification Status

| Milestone | Capability Area | Implementation Status | Verification Baseline |
| :--- | :--- | :--- | :--- |
| **M1** | Sovereign Kernel & Events | Implemented (Exploratory) | Unit & Master Gate passed (SQLite) |
| **M2** | Alignment Contracts & Ambiguity | Implemented (Exploratory) | Hardened in S1: Ambiguity defaults to `MEDIUM` |
| **M3–M4** | Executive Leases, Handoffs & EAP | Mechanics implemented; Providers stubbed | Mock verified; Real Ollama provider scheduled in S4 |
| **M5** | Reversible Sandboxing & Workers | Implemented (Exploratory) | Hardened in S1: Request-bound capability & two-token worker auth |
| **M6** | Durable Persistence & Repositories | Implemented (Exploratory) | SQLite verified; PostgreSQL consolidation scheduled in S2 |
| **M7** | Autonomous Missions & Coordination | Implemented (Exploratory) | Unit & Master Gate passed (SQLite) |
| **M8** | World Model & Situational Awareness | Implemented (Exploratory) | Unit & Master Gate passed; A2 actions locked in S1 |
| **S0** | Working Copy Baseline & Manifest | **Completed & Verified** | 109/109 tests passed; Hash manifest generated |
| **S0.5** | Governance Reconciliation | **Active** | `SAR-S0-S2` authorized; Draft status affirmed |
| **S1** | Authority, Worker Auth & A2 Lockdown | Stabilized in current working slice | Security regression suite passing in V3 checkpoint |
| **IF-V4** | Adaptive Cognitive Control / Multi-Transport Runtime | **Packaged & Verified Checkpoint** | 10 V4 tests; 45-test cognitive/integration gate; 18-test API/security gate passing |
| **EA-V5** | Autonomous Engineering Agency Runtime | **Packaged Foundation Checkpoint** | 14 dedicated V5 tests; historical 97-test engineering/intelligence/security gate |
| **EA-V5.1** | Production Engineering Integration | **Packaged & Verified Checkpoint** | 13 dedicated V5.1 tests; 102-test engineering/intelligence/security gate; 23-test API/core/security gate passing |
| **EA-V5.2** | Engineering Runtime Hardening | **Packaged & Cross-Platform Verified Checkpoint — target-machine evidence pending** | 19 dedicated V5.2 tests; 121-test engineering/intelligence/security gate; 32-test API/core/security gate passing |
| **EA-V5.3** | Real-Environment Validation & Endurance | **Validation harness implemented — target-machine execution pending** | Resumable target sessions, Ollama/pressure probes, authority-gated service workload, cross-process recovery, WSL2 execution probe, sealed evidence manifest |

---

## Master Documentation Index

### 1. Constitutional & Alignment Foundations
- [Stabilization Authorization Record](docs/governance/STABILIZATION_AUTHORIZATION_RECORD_S0_S2.md) — Bounded authorization for S0–S2 stabilization changes (`SAR-S0-S2`).
- [Draft Constitution](docs/constitution/UNIVERSAL_BRAIN_CONSTITUTION_DRAFT.md) — 10 Articles governing authority, safety, permissions, truth, and resilience (Draft 0.1, unratified).
- [Alignment Invariants](docs/alignment/INVARIANTS.md) — 21 machine-testable rules (`ALN-001` to `ALN-021`), deterministic ambiguity taxonomy, and mandatory test classes.
- [Alignment Contract Schema](docs/alignment/ALIGNMENT_CONTRACT_SCHEMA.md) — The canonical schema bridging human intent and executable tasks.
- [Total Awareness Architecture](docs/alignment/TOTAL_AWARENESS.md) — Unified Causal Event Graph, 18-event taxonomy, PostgreSQL recursive CTEs, and semantic vector memory.
- [JARVIS Migration Notes](docs/constitution/JARVIS_MIGRATION_NOTES.md) — Reconciliation matrix from legacy JARVIS concepts to Universal Brain.
- [Source JARVIS Constitution](docs/constitution/source/JARVIS_CONSTITUTION_V1_V2_SOURCE.md) — Historical reference evidence.

### 2. Architecture & Subsystem Specifications
- [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md) — Core modular monolith design, subsystem boundaries, and tech stack.
- [Executive Brain Specification](docs/architecture/EXECUTIVE_BRAIN_SPEC.md) — Executive Awareness Package (EAP), Action Commands, and Cognitive Handoff protocols.
- [Memory Architecture](docs/architecture/MEMORY_ARCHITECTURE.md) — Local-first storage and backup architecture.
- [Cost Control Policy](docs/architecture/COST_CONTROL_POLICY.md) — Hierarchical budgets, 3-tier exhaustion algorithm, and hard circuit breakers.
- [Operator Console Specification](docs/architecture/OPERATOR_CONSOLE_SPEC.md) — React SPA layout and telemetry isolation.
- [Intelligence Fabric Specification](docs/architecture/INTELLIGENCE_FABRIC_SPEC.md) — Model/route/transport separation, context compilation, routing, escalation, Council execution, interactive transports, telemetry, and safety invariants.
- [Engineering Agency V5.1](docs/architecture/ENGINEERING_AGENCY_V51.md) — Durable engineering recovery, requirement-scoped worktrees, impact-aware verification, causal cognition audit, local-resource admission, dependency diagnosis, and persistent service supervision.
- [Engineering Agency V5.2](docs/architecture/ENGINEERING_AGENCY_V52.md) — Tree-sitter/LSP semantic sensing, real stdio LSP runtime, opaque one-time ToolGateway isolation execution plans, durable worker fencing, multi-repository impact, transactional dependency remediation, verified merged-tree integration, authority-gated services, Operator Console telemetry, endurance harness, and target-evidence tooling.
- [Engineering Agency V5.3](docs/architecture/ENGINEERING_AGENCY_V53.md) — Resumable real-environment validation, three-model Ollama probes, optional concurrent pressure, disposable Git conflict proof, authority-gated service workload, cross-process recovery, real WSL2 execution probe, and offline-verifiable evidence bundles.
- [Platform Requirements](docs/requirements/PLATFORM_REQUIREMENTS.md) — Traceable functional and non-functional requirements.
- [Threat Model & Security](docs/security/THREAT_MODEL.md) — 16 threat vectors, trust boundaries, and mitigations.

### 3. Architecture Decision Records (ADRs)
- [ADR-0001: Local-First Canonical State](docs/architecture/adr/0001-local-first-selective-cloud.md)
- [ADR-0002: Version 1 Action Authority](docs/architecture/adr/0002-version1-action-authority.md)
- [ADR-0003: Neutral Human Safety](docs/architecture/adr/0003-human-safety-tie-break.md)
- [ADR-0004: Impact-Based Ambiguity Handling](docs/architecture/adr/0004-impact-based-ambiguity.md)
- [ADR-0005: Universal Executive Brain (Kernel vs. Model)](docs/architecture/adr/0005-universal-executive-brain.md)
- [ADR-0006: Hybrid Model Access Strategy (API + Browser Agent)](docs/architecture/adr/0006-hybrid-model-access-strategy.md)
- [ADR-0007: Geo-Redundant State & Zero-Cost Infrastructure](docs/architecture/adr/0007-geo-redundant-free-tier-state.md)
- [ADR-0008: Rollback Engine Specification (A1 Reversibility Mechanics)](docs/architecture/adr/0008-rollback-engine-specification.md)
- [ADR-0009: Intelligence Fabric / Multi-Transport Model Runtime](docs/architecture/adr/0009-intelligence-fabric-multi-transport-runtime.md)
- [ADR-0010: Lazy Persistence Initialization at the Control-Plane Boundary](docs/architecture/adr/0010-lazy-persistence-control-plane-boundary.md)
- [ADR-0011: Adaptive Cognitive Control Layer](docs/architecture/adr/0011-adaptive-cognitive-control-layer.md)
- [ADR-0012: Autonomous Engineering Agency Runtime](docs/architecture/adr/0012-autonomous-engineering-agency-runtime.md)
- [ADR-0013: Production Engineering Integration](docs/architecture/adr/0013-production-engineering-integration.md)
- [ADR-0014: Engineering Runtime Hardening](docs/architecture/adr/0014-engineering-runtime-hardening.md)
- [ADR-0015: Real-Environment Validation and Endurance](docs/architecture/adr/0015-real-environment-validation-and-endurance.md)

### 4. Testing & Verification
- [Engineering Agency V5.3 Verification Record](docs/testing/ENGINEERING_AGENCY_V53_VERIFICATION.md) — Real-environment validation harness, Ollama/pressure probes, ToolGateway service workload, process-restart proof, evidence sealing, and explicit target-machine gaps.
- [V5.3 Real-Environment Validation Runbook](docs/infrastructure/V53_REAL_ENV_VALIDATION_RUNBOOK.md) — Exact Windows/Ollama/LSP/WSL2/endurance procedure and evidence-label rules.
- [Engineering Agency V5.2 Verification Record](docs/testing/ENGINEERING_AGENCY_V52_VERIFICATION.md) — Runtime hardening, stdio LSP, authority-gated isolation plan execution, target-evidence tooling, and current environment limitations.
- [V5.2 Target-Machine Evidence Runbook](docs/infrastructure/V52_TARGET_MACHINE_EVIDENCE_RUNBOOK.md) — Windows/semantic/isolation/endurance proof procedure and evidence-label rules.
- [Engineering Agency V5.1 Verification Record](docs/testing/ENGINEERING_AGENCY_V51_VERIFICATION.md) — Durable recovery, incremental code intelligence, isolated requirement branches, causal audit, resource admission, dependency diagnosis, and service-supervision verification.
- [Intelligence Fabric V4 Verification Record](docs/testing/INTELLIGENCE_FABRIC_V4_VERIFICATION.md) — Adaptive cognitive control, memory, Council adjudication, session recovery, and mission-runtime verification.
- [Intelligence Fabric V3 Verification Record](docs/testing/INTELLIGENCE_FABRIC_V3_VERIFICATION.md) — Previous multi-transport runtime checkpoint.
- [Security Review](file:///C:/Users/vivek/Documents/Codex/2026-09-02/about-openai-astra-chatgpt-conversation-6a97c18c/outputs/CURRENT_UNIVERSAL_BRAIN_CODE_REVIEW.md) — Comprehensive code and authority audit.
- [Chaos Engineering Plan](docs/testing/CHAOS_ENGINEERING_PLAN.md) — 5 disaster scenarios (VM destruction, network split, DB corruption).

---

## Current Status

The repository remains constitutionally governed by the existing stabilization authorization record, while the current working slice has advanced the provider layer into a real **Intelligence Fabric / Multi-Transport Runtime**. External live routes remain disabled until explicitly configured and authorized.

The V4 packaged checkpoint adds evidence-backed capability discovery, deterministic evaluation-driven routing, canonical/derived memory context adapters, Council disagreement adjudication, provider-session recovery, authorized Windows UIA support, and TaskDAG cognitive mission execution. The dedicated adaptive Fabric tests, Executive cognitive tests, M3/M4 master gate, cellular-monolith integration tests, and API/security regression gates pass in the recorded V4 verification run. Live external-provider/browser/desktop smoke testing remains explicitly operator- and environment-gated and is not claimed by this checkpoint. Persistence is now lazy at the FastAPI dependency boundary so importing/querying the control plane does not require a concrete database driver until durable persistence is actually used.

V5 adds an **Autonomous Engineering Agency Runtime** above the Intelligence Fabric: requirement-oriented hierarchical planning, cycle-checked DAG mutation, deterministic failure-classification/recovery insertion, a bounded cognition→ToolGateway→observation→repair loop, executable verification adapters, a local code-symbol/reference graph with test-impact retrieval, authority-gated Git worktree transactions, local Ollama resource profiles, independent worker completion gates, and a project Definition-of-Done auditor.

V5.1 advances that foundation into **Production Engineering Integration**: atomic self-verifying mission checkpoints with repository/worktree drift detection; incremental code-graph refresh and transitive impact analysis; impact-aware verification in the exact requirement worktree; requirement-scoped branch affinity and retry-safe verified integration; model-request/response digest events causally linked to ToolGateway evidence; router/runtime Ollama RAM/VRAM/concurrency admission; manifest/lockfile-aware dependency failure diagnosis; and durable long-running service state behind an authority-gated process backend. The V5.1 checkpoint records 13/13 dedicated tests, a 102/102 engineering/intelligence/security regression gate, a 23/23 API/core/security gate, and successful Python compilation. The unfiltered repository suite remains environment-blocked by unavailable `pgvector`; after excluding only that DB-model collection test, remaining non-passing cases are due unavailable `aiosqlite` in this sandbox.

V5.2 advances the runtime hardening layer with optional real Tree-sitter parsing, standard-LSP semantic/diagnostic/refactor adapters, a shell-free **real stdio LSP process runtime**, stale-diagnostic invalidation, explicit WSL2/Hyper-V isolation plans with fail-closed resource/network capability checks, and an **opaque one-time isolation plan execution tool behind ToolGateway** so model-authored host command strings are not accepted directly. It also includes durable generation-fenced worker leases, derived multi-repository dependency impact, dependency remediation with Git rollback, merged-tree verification before integration commit, a real ToolGateway-compatible persistent service process tool, read-only Engineering Agency API/Console telemetry, an atomic endurance harness, and a self-digested target-machine evidence collector. The recorded cross-platform gate is 19/19 dedicated V5.2 tests, 121/121 engineering/intelligence/security tests, 32/32 API/core/security tests, and successful Python compilation. The broader suite excluding the unavailable `pgvector` DB-model test reached 175 passed with 15 failures and 8 errors, all shown from unavailable `aiosqlite` in this sandbox.

V5.3 adds a dedicated **real-environment validation harness** rather than another architecture rewrite. It persists self-digested validation sessions with workspace-drift checks, probes the operator-selected Ollama models without retaining raw generations, optionally performs one bounded concurrent local-model pressure cycle, exercises disposable Git worktrees/conflict abort, runs a real bounded service through ToolGateway, proves checkpoint recovery across two Python processes, can execute one real WSL2 one-time isolation plan when the operator supplies the distro/path mapping, and seals target artifacts into an offline-verifiable SHA-256 manifest. The code/harness is cross-platform tested, but the Windows/Ollama/WSL2/multi-hour deployment evidence still must be produced on the operator machine.

V5.2 still does **not** claim demonstrated autonomous completion of a 50k–100k-line production system or production-proven Windows isolation. Real external language-server/Tree-sitter installation, WSL2/Hyper-V ToolGateway execution evidence, a >=2-hour real-repository endurance run, and dependency-complete full-suite verification remain target-machine proof gates.

---

## License

All rights reserved. Dedicated to the operator until explicitly decided otherwise.
## Intelligence Fabric / Multi-Transport Runtime

The provider-neutral `universal_brain.intelligence` layer separates **model identity**, **access route**, and **runtime transport**. V4 adds evidence-backed capability discovery, deterministic evaluation-driven routing, mission/event/semantic memory retrieval with provenance, independent Council disagreement adjudication, recoverable provider-session continuity, bounded browser attachments, a real optional Windows UIA chat driver, and adaptive TaskDAG cognitive execution that stops at Verification Engine / ToolGateway boundaries. New frontier models remain catalog/configuration data rather than Kernel architecture changes. See [INTELLIGENCE_FABRIC_SPEC.md](docs/architecture/INTELLIGENCE_FABRIC_SPEC.md) and [ADR-0009](docs/architecture/adr/0009-intelligence-fabric-multi-transport-runtime.md).

