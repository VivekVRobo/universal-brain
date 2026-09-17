# Milestones and Master Acceptance Gates

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Derived from Constitution Articles I, IV, VII and Implementation Plan

---

## 1. Master Semester Milestones

| Milestone | Semester | Primary Objective | Master Exit Gate |
|---|---|---|---|
| **M-S1** | Semester 1 (M1–6) | **Sovereign Kernel & Vertical Slice** | 100-step autonomous task completes, surviving 3 forced model swaps and 2 tool failures with zero human intervention. |
| **M-S2** | Semester 2 (M7–12) | **Long-Horizon Swarm Orchestration** | Brain executes an autonomous multi-agent project continuously for 7 days, recovering from 15 runtime errors without human input. |
| **M-S3** | Semester 3 (M13–18) | **Reality Bridging & Advanced Verification** | 10,000-line C++ robotic controller generated and 3 latent concurrency bugs caught via formal verification and physics simulation. |
| **M-S4** | Semester 4 (M19–24) | **Cognitive Continuity & Meta-Learning** | Complete a 2-week hardware-in-the-loop robotics project surviving 4 API outages, returning a 100% auditable trace. |

---

## 2. Technical Phase Gates (M0 through M8)

| Phase Milestone | Target Outcome | Required Validation Gate |
|---|---|---|
| **M0 Planning Baseline** | Approved constitution and architecture | Operator ratifies Constitution Draft 0.1; decisions D-001 & D-002 approved. |
| **M1 Foundation & Infra** | Clean local & Oracle VM environment | Format, type, unit, migration, secret scans pass; Google Drive journal syncing. |
| **M2 Alignment Slice** | End-to-end traced request in sandbox | ALN-001–010 pass; high-impact ambiguity blocks execution; correction diffs pass. |
| **M3 Executive & Memory** | Durable Kernel & Memory Replicator | EAP generation, cognitive handoff, zero-data-loss recovery drill (<15m RTO). |
| **M4 Hybrid Multi-Model** | Replaceable models & Browser Agent | API routing, browser agent sandboxing, and strict egress privacy tests pass. |
| **M5 Reversible Tooling** | Verified safe A1 effects | Capability token verification, target allowlists, mandatory rollback tests pass. |
| **M6 Swarm & Verification** | Multi-agent DAG & Evidence Engine | Missing/failed evidence cannot mark task verified; Failure Ledger active. |
| **M7 Operator Console** | Full observability & control | Trace explorer, live pause/resume/revoke, and explanation interfaces verified. |
| **M8 Hardened Platform** | Long-running resilient deployment | Full invariant suite (ALN-001–020), soak testing, and cold-boot disaster recovery drill. |

---

## 3. Definition of Done for Any Milestone

No milestone can be marked complete unless:
1. Every executable task cites an active requirement (`REQ-...`) and invariant (`ALN-...`).
2. Automated acceptance tests pass cleanly from a fresh, clean-room checkout.
3. Test evidence artifacts are cryptographically hashed and indexed in the verification ledger.
4. Known limitations and residual risks are explicitly documented.
5. All security checks pass with zero unaddressed high/critical vulnerabilities.
6. Documentation reflects real, implemented behavior rather than hypothetical intent.

---

## 4. Universal Stop Conditions

Execution on any affected branch halts immediately when:
- A high-impact ambiguity is detected and remains unresolved (blocks the branch, ALN-004).
- A required capability token is missing, expired, or tampered with.
- Audit service or verification service health drops to an unhealthy state (ALN-014).
- The active Alignment Contract or Constitution is amended mid-execution without revalidation.
- Empirical verification contradicts the plan or model assertions.
- An action produces an irreversible side effect that was misclassified as A1.
- API or compute costs exceed the pre-approved budget ceiling.
