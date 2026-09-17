# Alignment Invariants

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Derived from Universal Brain Constitution and ADRs 0001–0007

Invariants are machine-testable rules that operationalize the Constitution.

| ID | Invariant | Enforcement target |
|---|---|---|
| ALN-001 | Every executable task cites an active requirement. | Database constraint + runtime gate |
| ALN-002 | Original user input is retained alongside every interpretation. | Append-only event + foreign key |
| ALN-003 | An inference cannot become an explicit requirement without an authority event. | Typed provenance + transition guard |
| ALN-004 | High-impact ambiguity blocks the affected execution branch. | Risk classifier + deterministic gate |
| ALN-005 | Operator corrections preserve history and invalidate affected descendants. | Dependency graph traversal |
| ALN-006 | Explicit constraints cannot be silently weakened by plans or tasks. | Contract-diff gate |
| ALN-007 | Every A1 action has bounded scope, rollback instructions, preconditions, and postconditions. | Action schema validation |
| ALN-008 | Every A2 action requires fresh, target-specific approval. | Capability token service |
| ALN-009 | A model or agent cannot expand its own permissions. | Separate authorization service |
| ALN-010 | Completion requires acceptance criteria and evidence. | Verification state machine |
| ALN-011 | Model agreement is not independent evidence. | Evidence source classification |
| ALN-012 | Canonical project state is independent of provider sessions. | Local event store |
| ALN-013 | Cloud requests exclude secrets and unrelated private context by default. | Egress policy + redaction tests |
| ALN-014 | Failed audit or verification services disable state-changing actions. | Health-dependent permission gate |
| ALN-015 | Resumed actions revalidate contract version, lease, permissions, and idempotency key. | Recovery gate |
| ALN-016 | Every state-changing action emits a tamper-evident audit event. | Transactional outbox + hash chain |
| ALN-017 | Human safety is not ranked by identity; operator preference breaks only credible ties. | Safety policy tests |
| ALN-018 | Version 1 cannot control physical actuators. | Tool registry deny rule |
| ALN-019 | Constitution and enforcement changes require semantic diff, tests, and explicit approval. | Protected change workflow |
| ALN-020 | The system never reports “verified” when required checks are missing, skipped, stale, or failed. | Verification aggregation rule |
| ALN-021 | The system must maintain an immutable, causal, and semantically queryable event graph of every user input, contract transition, task delegation, tool execution, verification result, and operator approval. No state-changing event may be lost or unlinked from its causal parent. | PostgreSQL recursive DAG + pgvector index |

---

## ALN-004a: Deterministic Ambiguity Classification Taxonomy

Ambiguities are **not** classified by the Executive Model or any LLM. The Kernel uses a hardcoded, deterministic rule engine to classify ambiguity impact:

| Impact Level | Deterministic Rule | Representative Examples | Enforcement Action |
|---|---|---|---|
| **HIGH** | Action affects filesystem outside declared sandbox, modifies permissions, spends financial budget, touches production systems, or requires A2 capability tokens. | `rm -rf /`, modifying `chmod 777`, `POST /api/billing`, `npm publish`, `ALTER TABLE` on production DB, external communications. | **Always Block Affected Branch.** Requires explicit operator confirmation. |
| **MEDIUM** | Action chooses between two semantically different libraries, frameworks, database architectures, or design patterns. | *"Should I use numpy or scipy?"*, *"Should I structure this as a class or functional pipeline?"*, choosing between Redis vs PostgreSQL for queue. | **Prefer Clarification.** Safe documented default allowed only if easily reversible. |
| **LOW** | Action affects only local variable names, code formatting, internal sandbox directory layout, or benign implementation details. | *"Should this function be named get_data() or fetch_records()?"*, *"Tabs vs spaces"*, choosing helper function breakdown. | **Proceed with Recorded Assumption.** Logged in contract assumption ledger. |

### Classification Rules & Monotonicity
1. **Default Rule:** If an ambiguity does not cleanly match any definition above, it defaults strictly to **MEDIUM** and seeks operator clarification.
2. **Reclassification Restriction:** The Executive Model may propose reclassifying an ambiguity, but this requires an explicit `UPDATE_CONTRACT` command with documented rationale and **requires operator approval if lowering the impact from HIGH to MEDIUM or LOW**.

---

## Required Invariant Test Classes

1. **Unit tests:** Deterministic validation for state transitions and taxonomy rules.
2. **Property tests:** Graph provenance, permission monotonicity, and ambiguity gating.
3. **Integration tests:** Action/audit atomicity, chunked replication, and outbox delivery.
4. **Failure-injection tests:** Provider outages, database failure, worker loss, and network partition.
5. **Adversarial scenario tests:** Goal drift, stale memory, prompt injection from web scrapers, and dishonest workers.
6. **Golden trace tests:** End-to-end mapping from raw user input to final response with evidence proofs.

No runtime milestone can pass while an applicable invariant lacks an executable test.
