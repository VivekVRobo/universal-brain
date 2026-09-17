# System Architecture

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Derived from Constitution Articles I, III, V, VI and ADRs 0001, 0002, 0005, 0006, 0007

---

## 1. Architectural Style

Version 1 is a **local-first, event-driven modular monolith** with strict internal boundaries, running in a **geo-redundant distributed topology**. This eliminates premature microservice network latency while ensuring continuous 24/7 sovereignty, zero-loss durability, and an eventual path to service extraction.

---

## 2. The Universal Executive Brain Construct

The system repudiates the idea that any single LLM sits permanently at the apex. Instead, it defines the **Universal Executive Brain (UEB)** as two decoupled layers:

```mermaid
flowchart TD
    subgraph UEB ["Universal Executive Brain (UEB)"]
        subgraph SovereignCore ["Executive Kernel (Permanent / Deterministic Core)"]
            K_State["Canonical State & Ledger (PostgreSQL)"]
            K_Perm["Capability & Permission Engine"]
            K_Audit["Tamper-Evident Audit Chain"]
            K_Health["Health & Budget Gatekeeper"]
        end
        subgraph IntelLayer ["Executive Model (Ephemeral / Reasoning Leaseholder)"]
            M_Reason["Frontier LLM (GPT / Claude / Gemini)"]
            M_Plan["Semantic Planner & Decomposer"]
        end
    end

    subgraph Peripherals ["Execution & Reality Layer"]
        Spine["Alignment Spine (Contracts & Invariants)"]
        GW["Tool Gateway (Deny-by-Default A0/A1/A2)"]
        Verify["Reality & Verification Engine"]
        Mem["4-Tier Geo-Redundant Memory"]
    end

    Operator["Operator Interface"] <--> Spine
    Spine <--> SovereignCore
    SovereignCore -->|Executive Awareness Package (EAP)| IntelLayer
    IntelLayer -->|Typed Action Commands| SovereignCore
    SovereignCore <--> GW
    GW <--> Verify
    SovereignCore <--> Mem
    Verify --> SovereignCore
```

- **Executive Kernel (Sovereign Core):** Permanent, deterministic software (PostgreSQL, state machines, capability controllers). Owns canonical truth, contracts, permissions, health, budgets, and audit records.
- **Executive Model (Intelligence Layer):** Ephemeral reasoning leaseholder. Receives the scoped **Executive Awareness Package (EAP)** and emits typed action commands. It cannot write directly to canonical state. Detailed specifications are defined in [EXECUTIVE_BRAIN_SPEC.md](EXECUTIVE_BRAIN_SPEC.md).

---

## 3. Core Subsystems

### 1. Alignment Spine
Owns original input retention, alignment contracts, requirements ledgers, constraint boundaries, non-goals, assumption tracking, ambiguity classification (low/medium/high), and transition gates.

### 2. Executive Kernel
Owns the model-neutral world state: projects, milestones, tasks, agents, models, capability leases, budgets, health, checkpoints, and evidence indexes.

### 3. Universal Executive
Constructs the EAP, proposes plans, delegates bounded work to specialized agents, monitors execution, requests operator clarification for high-impact ambiguities, and synthesizes coherent progress reports.

### 4. Goal and Task Engine
Maintains the directed acyclic graph (DAG) of work items, ensuring 100% provenance from user inputs to requirements, tasks, actions, and verification results.

### 5. Model Registry & Cognitive Router
Tracks provider capabilities, health, cost, latency, token limits, and task evaluation history. Routes high-leverage executive tasks to frontier APIs and data-harvesting tasks to sandboxed browser agents per [ADR-0006](adr/0006-hybrid-model-access-strategy.md).

### 6. Agent Runtime
Maintains persistent agent roles independently of the underlying models. Enforces task-scoped awareness packages, capability tokens, budget ceilings, and checkpoint protocols.

### 7. Tool Gateway
The sole execution gateway for external effects. Validates action class (A0, A1, A2, A3), target scopes, preconditions, rollback procedures, idempotency keys, and audit health.

### 8. Reality & Verification Engine
Executes compilers, linters, unit tests, physics simulations (Gazebo/Isaac Sim), and independent critic workflows. Generates tamper-evident evidence records rather than relying on model assertions.

### 9. 4-Tier Geo-Redundant Memory & Retention Lifecycle
Resolves cloud instance volatility and eliminates Single Points of Failure:
- **Tier 0 (RAM):** Volatile scratchpad context.
- **Tier 1 (PostgreSQL):** Relational truth; replicated via chunked 60-second micro-batches to Google Drive/R2 and 6-hour encrypted dumps to a private GitHub repo.
- **Tier 2 (Vector Store):** Embeddings stored directly inside PostgreSQL (`pgvector`/`JSONB`), backed up atomically with Tier 1.
- **Tier 3 (Raw Knowledge & Cold Sink):** Mounted via `rclone` from Google Drive, with >90-day cold archives offloaded to a private Telegram channel.
- **Retention Lifecycle:** 30-day hot local tier, 90-day cold cloud tier, automatic compaction, and 80% disk warning gates. Detailed specifications are in [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md).

### 10. Audit & Observability
Maintains hash-linked append-only audit events (ALN-016), OpenTelemetry distributed traces, token/budget expenditures, out-of-band Telegram alert pushes, and operator-readable decision explanations.

---

## 4. Recommended Version 1 Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| **Primary Language** | Python 3.12+ | Rich AI/ML ecosystem, strict typing, rapid testing tooling. |
| **Local API** | FastAPI + Uvicorn | High-performance async endpoints with automatic OpenAPI docs. |
| **Domain Schemas** | Pydantic v2 | High-performance Rust-based serialization and strict JSON Schema validation. |
| **Canonical Database** | PostgreSQL 16+ | ACID transactions, robust row-level locking, JSONB, and `pgvector` support. |
| **Vector Storage** | `pgvector` / JSONB | Co-located with relational data; eliminates separate fragile vector DB backups. |
| **Event Bus & Outbox** | PostgreSQL Transactional Outbox | Atomic state-and-audit event delivery; avoids premature message broker overhead. |
| **Host Infrastructure** | Oracle Cloud Always Free (4 ARM / 24GB) | Free 24/7 cloud node for Kernel, PostgreSQL, and Tool Gateway. |
| **Ephemeral Compute** | Google Colab / Kaggle | Free GPU workers for heavy batch, simulation, and scraping tasks (pull-based). |
| **Off-Site Redundancy** | Google Drive + GitHub Private Repo | Real-time chunked micro-batch streaming and 6-hour encrypted database dumps. |
| **Out-of-Band Alerts & Cold Sink** | Telegram Bot API & Private Channel | High-priority mobile push alerts (A2, health, disk) and free unlimited 2GB file cold archive. |
| **Secrets Management** | OS Keychain / Environment Vault | Zero plaintext secrets committed to repositories or passed to models. |
| **Observability** | OpenTelemetry | Standardized, vendor-neutral traces, metrics, and span propagation. |
| **Verification Suite** | pytest, Hypothesis, Testcontainers | Deterministic unit, property-based, and containerized integration tests. |

---

## 5. Directory Layout

```
apps/
  api/                      # FastAPI local service and webhook endpoints
  operator_console/         # CLI & web interface for human operator
src/universal_brain/
  alignment/                # Contracts, invariants, ambiguity classifiers
  constitution/             # Constitutional hash verification & amendment gates
  executive/                # Executive Kernel, EAP builder, command parser
  kernel/                   # State machines, lease controllers, project ledgers
  agents/                   # Persistent agent roles, task runners
  models/                   # Model registry, API adapters, router, cognitive handoff
  tools/                    # Tool Gateway, capability token verifier, sandboxes
  verification/             # Reality checks, test runners, evidence indexer
  memory/                   # Memory Replicator daemon, PostgreSQL & vector store
  audit/                    # Hash-chain audit ledger, event outbox
  infrastructure/           # Colab/Kaggle worker dispatchers, rclone mounts
tests/
  unit/                     # Deterministic component tests
  property/                 # Hypothesis property tests (invariants, tokens)
  integration/              # Multi-component & database integration tests
  adversarial/              # Prompt injection, drift, and fault-injection suites
  golden_traces/            # End-to-end intent-to-evidence verified traces
docs/                       # System documentation and architecture records
```
