# Master Implementation Plan

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Derived from Constitution Articles I, IV, VII and Milestones M0–M8

---

## 1. Delivery Philosophy

**Vertical Slice First:** Build one verified end-to-end slice early, then deepen each subsystem behind stable contracts. Do not build a loose collection of impressive but disconnected agents.

The roadmap is structured into a **2-Year Master Horizon** across **Four 6-Month Semesters**, mapping directly to technical development phases.

```mermaid
gantt
    title Universal Brain 2-Year Master Implementation Horizon
    dateFormat  YYYY-MM-DD
    section Semester 1: Core Kernel
    Phase 0: Planning Baseline           :done,    p0, 2026-09-01, 2026-09-15
    Phase 1: Executable Foundation       :active,  p1, 2026-09-16, 2026-10-15
    Phase 2: Alignment Vertical Slice    :         p2, 2026-10-16, 2026-11-30
    Phase 3: Executive Kernel & Memory   :         p3, 2026-12-01, 2027-02-28
    section Semester 2: Swarms
    Phase 4: Multi-Model & Hybrid Access :         p4, 2027-03-01, 2027-04-30
    Phase 5: Reversible Tooling & Sandbox:         p5, 2027-05-01, 2027-06-30
    Phase 6: Long-Horizon Swarm DAGs     :         p6, 2027-07-01, 2027-08-31
    section Semester 3: Reality Bridge
    Phase 7: Verification & Sim Bridging :         p7, 2027-09-01, 2028-02-28
    section Semester 4: Meta-Learning
    Phase 8: Hardening & Meta-Learning   :         p8, 2028-03-01, 2028-08-31
```

---

## 2. Semester 1 (Months 1–6): The Sovereign Kernel & Vertical Slice

**Governing Goal:** Prove the constitutional architecture end-to-end on local/free-tier infrastructure. Deliver a fully verified intent-to-execution pipeline.

### Phase 0 — Planning & Constitutional Baseline (Current)
- **Deliverables:** Consolidated Constitution, Alignment Invariants, Threat Model, Executive Brain Spec, Memory Architecture, Infrastructure Map, and initial ADRs (0001–0007).
- **Exit Gate:** Operator ratifies Constitution Draft 0.1 and approves decisions D-001 and D-002.

### Phase 1 — Executable Foundation & Infrastructure Setup
- **Deliverables:**
  - Python 3.12+ project repository, dependency locking (`uv` or `poetry`), Ruff, Mypy, pytest.
  - PostgreSQL schema migrations (`alembic`) for contracts, projects, events, and audit logs.
  - Oracle Cloud Always Free VM provisioning with Docker Compose setup.
  - Off-site Google Drive `journal.jsonl` integration and encrypted GitHub backup script.
- **Exit Gate:** Clean deployment from scratch on local machine and Oracle VM with zero manual DB configuration.

### Phase 2 — Alignment Vertical Slice
- **Deliverables:**
  - Original-input and authority-event stores.
  - Alignment Contract versioning and transition state machine.
  - Deterministic ambiguity and constraint-diff transition guards.
  - Mock model provider and single sandboxed A1 filesystem tool.
- **Exit Gate:** ALN-001 through ALN-010 verified by automated tests. High-impact ambiguity strictly blocks execution.

### Phase 3 — Executive Kernel & Memory Replicator
- **Deliverables:**
  - Implementation of the **Executive Awareness Package (EAP)** builder and Action Command parser per [EXECUTIVE_BRAIN_SPEC.md](EXECUTIVE_BRAIN_SPEC.md).
  - Background `memory_replicator` daemon running continuous off-site sync per [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md).
  - Crash/restart recovery worker with lease revalidation (ALN-015).
- **Semester 1 Exit Gate:** A 100-step autonomous engineering task completes successfully, surviving 3 forced model swaps and 2 tool failures with zero human intervention.

---

## 3. Semester 2 (Months 7–12): Long-Horizon Autonomy & Swarm Orchestration

**Governing Goal:** Transition from single-task execution to concurrent, multi-agent project execution across extended horizons.

### Phase 4 — Multi-Model Runtime & Hybrid Access
- **Deliverables:**
  - Provider-neutral model adapters (OpenAI, Anthropic, Google, DeepSeek, Local).
  - Hybrid routing: API-based executive reasoning and VM-sandboxed Browser Agent for web scraping and consumer model digestion ([ADR-0006](adr/0006-hybrid-model-access-strategy.md)).
  - Cognitive state checkpointing and dynamic failover routing.

### Phase 5 — Tool Gateway & Sandboxing
- **Deliverables:**
  - Capability token minting and cryptographic verification.
  - Sandboxed execution environments (Docker/Bubblewrap) for compilation and scripts.
  - Mandatory rollback test execution for all A1 actions prior to commit.
  - Approval queue for A2 consequential actions (external notifications, production writes).

### Phase 6 — Long-Horizon Swarms & Failure Ledger
- **Deliverables:**
  - Project Director delegation hierarchy (Executive spawns domain directors: Architect, Coder, Verifier).
  - Task Graph DAG engine with inter-task dependency tracking.
  - Persistent **Failure Ledger**: records exact conditions, error traces, and negative test results to prevent workers from repeating known dead ends.
- **Semester 2 Exit Gate:** Universal Brain executes an autonomous project continuously for 7 days without human intervention, encountering and successfully recovering from at least 15 runtime errors.

---

## 4. Semester 3 (Months 13–18): Reality Bridging & Advanced Verification

**Governing Goal:** Bridge the system to real-world physical and simulation environments with expert-grade verification.

### Phase 7 — Robotics Simulation & The Evidence Ladder
- **Deliverables:**
  - Integration with robotics middleware: ROS 2 Humble/Iron, Gazebo headless, and Nvidia Isaac Sim running on ephemeral GPU workers (Colab/local RTX 3050).
  - **The Evidence Ladder:** Multi-tier verification pipeline:
    $$\text{Compiles} \longrightarrow \text{Unit Tests} \longrightarrow \text{Integration Tests} \longrightarrow \text{Simulation Verification} \longrightarrow \text{Hardware-in-the-Loop}$$
  - Adversarial Critic Agents: Red-team models trained to identify edge-case logic faults.
  - Formal verification pilots (e.g., TLA+ specifications for mission-critical state transitions).
- **Semester 3 Exit Gate:** The Brain generates a 10,000-line C++ robotic motion controller and catches at least 3 latent concurrency/race condition faults via formal verification and physics simulation prior to deployment.

---

## 5. Semester 4 (Months 19–24): Cognitive Continuity & Meta-Learning

**Governing Goal:** Enable the system to optimize its own operational performance without violating constitutional invariants.

### Phase 8 — Meta-Optimization & Sovereign Resilience
- **Deliverables:**
  - Bayesian/RL Router: Dynamic scoring of model providers based on historical empirical accuracy, latency, and cost per task category.
  - **The Guardian Process:** Autonomous background observer analyzing task logs to propose efficiency optimizations and constitutional amendments.
  - Global Rollback Engine: Time-travel capability to roll back the entire project DAG to a known checkpoint and replay with corrected assumptions.
  - Full system DR drills: Intentional simulated destruction of the host VM with automated cold-boot restoration in <15 minutes.
- **Final Master Exit Gate:** Complete a hardware-in-the-loop autonomous robotics project continuously over 2 weeks, surviving at least 4 upstream API outages, returning a 100% auditable, tamper-evident trace.

---

## 6. Work Ownership Matrix

| Area | Primary Responsible Party | Verification Authority |
|---|---|---|
| Repository Architecture & Code | AI Engineering Assistant | Deterministic Test Suite / CI |
| Constitutional Ratification & Amendments | Human Operator | Operator Cryptographic Signature |
| Upstream Credentials & Cloud Accounts | Human Operator | Secret Scanning & Egress Filters |
| A2 Consequential Action Approvals | Human Operator | Capability Token Service |
| Evidence Satisfaction & Task Completion | Verification Engine | Reality & Verification Engine |
