# Threat Model & Security Posture

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Derived from Constitution Articles II, III, V, VIII and ADRs 0001–0007

---

## 1. Protected Assets

- **Operator Intent & Private Context:** Raw instructions, personal data, constraints, and uncommitted goals.
- **Constitutional Integrity & Policies:** Active constitution hash, invariant rules, and permission state.
- **Credentials & API Secrets:** Frontier model API keys, SSH keys, GitHub tokens, and cloud account credentials.
- **Canonical State & Audit Trail:** PostgreSQL database, event outbox, and the hash-linked audit log.
- **Off-Site Backups & Sync Journal:** Google Drive `journal.jsonl` and private GitHub backup snapshots.
- **Tool Targets & Rollback Snapshots:** Local filesystem, code repositories, and intermediate build artifacts.
- **Executive Checkpoints:** Cognitive state snapshots and active capability leases.

---

## 2. Trust Boundaries

1. **Operator Interface $\leftrightarrow$ Local API / Kernel:** Untrusted input from chat or terminal must be parsed into structured Alignment Contracts.
2. **Executive Model $\leftrightarrow$ Kernel Command Parser:** LLM outputs are treated as untrusted proposals; only valid typed commands are executed.
3. **Kernel $\leftrightarrow$ Cloud Model Egress:** Outgoing requests are strictly minimized, classified, and redacted. Secrets are never passed.
4. **Agent Runtime $\leftrightarrow$ Tool Gateway:** Deny-by-default execution boundary requiring valid, unexpired capability tokens.
5. **Tool Gateway $\leftrightarrow$ Browser Scraping Sandbox:** Raw web content and consumer AI interfaces are isolated in a quarantined container.
6. **Kernel $\leftrightarrow$ Ephemeral Cloud Workers (Colab/Kaggle):** Ephemeral compute nodes are untrusted workers returning data for verification.
7. **Local Host $\leftrightarrow$ Off-Site Cloud Storage (Google Drive / GitHub):** Backups are encrypted client-side prior to transit.

---

## 3. Primary Threat Vectors and Required Mitigations

| Threat ID | Threat Scenario | Required Security Control | Invariant / Ref |
|---|---|---|---|
| **THR-001** | **Goal Drift via Context Summaries** | Original user input is permanently preserved; semantic diffs computed across contract versions. | ALN-002, ALN-006 |
| **THR-002** | **Indirect Prompt Injection from Web/Tools** | The Executive never views raw HTML. The Browser Agent extracts text into structured schemas; outputs are quarantined. | ADR-0006, REQ-TOL-001 |
| **THR-003** | **Model Hallucinates Completion / State** | Canonical state is owned solely by PostgreSQL. Only the Verification Engine can mark acceptance criteria satisfied. | ALN-010, ALN-020 |
| **THR-004** | **Excessive Context or Secret Egress** | Automated regex/entropy secret scanning and context minimizers scrub all model prompts. | ALN-013, REQ-STA-002 |
| **THR-005** | **Agent Self-Escalates Privileges** | Separate authorization service mints short-lived capability tokens; agents have no self-grant endpoint. | ALN-009, REQ-TOL-002 |
| **THR-006** | **Confused Deputy Action on Local Files** | Capability tokens are strictly bound to target paths, specific operations, and contract versions. | REQ-TOL-002 |
| **THR-007** | **Replay or Duplicate Action Attacks** | Idempotency keys, lease nonces, and transactional outbox deduplication prevent duplicate execution. | ALN-015, REQ-STA-004 |
| **THR-008** | **Irreversible Action Masquerading as A1** | Mandatory pre-flight rollback verification; actions lacking tested rollback are classified A2. | ALN-007, ADR-0002 |
| **THR-009** | **Audit Log Tampering or Erasure** | Cryptographic hash-chain linking (SHA-256) per event; append-only database permissions; off-site replication. | ALN-016, REQ-STA-003 |
| **THR-010** | **Ephemeral Worker Disconnection / Corruption** | Ephemeral nodes (Colab) save checkpoints every 10–15m; Kernel verifies output schemas and hashes before ingestion. | FREE_CLOUD_ORCHESTRATION |
| **THR-011** | **Host Instance Destruction (SPOF)** | 4-Tier Geo-Redundant Memory: 6-hour encrypted GitHub dumps + real-time Google Drive `journal.jsonl`. | ADR-0007, MEMORY_ARCHITECTURE |
| **THR-012** | **Cognitive State Hijacking during Handoff** | Checkpoints are cryptographically signed and re-validated against the active contract version prior to resuming. | ALN-015, EXECUTIVE_BRAIN_SPEC |
| **THR-013** | **Critic Model Collusion** | Verification uses deterministic compilers/tests first; model critics are selected from independent provider families. | ALN-011, REQ-MOD-004 |
| **THR-014** | **Uncontrolled API Spend / Cost Runaway** | Per-task, per-provider, and monthly hard budget ceilings; automatic circuit breakers trigger pause on threshold breach. | ALN-014, REQ-STA-006 |
| **THR-015** | **Supply Chain Compromise (Packages/Weights)** | Dependency pinning (`uv.lock`), SHA-256 checksum verification, and clean-room containerized builds. | REQ-STA-001 |
| **THR-016** | **Malicious Constitutional Mutation** | Constitution hash verified at startup; mutations require explicit operator approval, semantic diff, and cooling period. | ALN-019, REQ-OPS-003 |

---

## 4. Version 1 Security Baseline Posture

- **Single Authenticated Operator:** No multi-tenant access or unauthenticated public endpoints.
- **Local Sovereignty:** Relational database and canonical logs reside under operator control.
- **Zero Inbound Internet Exposure:** The Sovereign Kernel on Oracle Cloud communicates via Tailscale VPN or authenticated private SSH reverse proxy. No open web ports.
- **Zero Autonomous Lethal / Physical Actuation:** Physical actuators, robotics control, and weapons systems are entirely excluded from Version 1 capability registries (Article IX).
- **Client-Side Backup Encryption:** All database dumps pushed to GitHub are encrypted with GPG/Age before leaving the host instance.
