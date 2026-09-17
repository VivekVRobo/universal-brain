# Decisions Required

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Implementation Plan & Governance

---

Planning Baseline 0 contains no unresolved decision that prevents reviewing the architectural specifications. The following decisions are tracked and gated by phase:

## Required before Phase 1 Implementation

### D-001 — Ratify or Revise Constitution Draft 0.1
- **Impact:** High  
- **Question:** Is the draft constitutional foundation ([UNIVERSAL_BRAIN_CONSTITUTION_DRAFT.md](constitution/UNIVERSAL_BRAIN_CONSTITUTION_DRAFT.md)) approved for implementation, subject to future versioned amendments?

### D-002 — Approve the Recommended Version 1 Stack
- **Impact:** Medium  
- **Recommendation:** Python 3.12+, FastAPI, Pydantic v2, PostgreSQL 16+ with `pgvector`, Docker Compose, pytest/Hypothesis, and OpenTelemetry in a modular monolith.

### D-007 — Approve Free-Tier Infrastructure & Geo-Redundancy Configuration
- **Impact:** Medium  
- **Recommendation:** Deploy the Sovereign Kernel on Oracle Cloud Always Free (4 ARM cores, 24GB RAM), using a private GitHub repository for 6-hour encrypted `pg_dump` backups and Google Drive for real-time `journal.jsonl` streaming per [ADR-0007](architecture/adr/0007-geo-redundant-free-tier-state.md).

---

## Required before Phase 4 (Multi-Model & Hybrid Access)

### D-003 — Initial Model Providers and Budget Ceilings
- **Impact:** Medium  
- **Scope:** Provider accounts, API keys, per-task spend limits, monthly hard ceilings, and data sensitivity classifications per model tier.

### D-004 — Local Model & Hardware Profile
- **Impact:** Low  
- **Scope:** Confirmation of local PC hardware baseline (RTX 3050, 16GB RAM, 4GB VRAM) as an Operator Command Center and lightweight CPU embedding engine.

### D-008 — Browser Agent Isolation Strategy
- **Impact:** Medium  
- **Recommendation:** Run the web scraping / consumer UI browser agent inside an isolated Docker container with strict network routing to prevent host compromise per [ADR-0006](architecture/adr/0006-hybrid-model-access-strategy.md).

---

## Required before Phase 5 (Tool Gateway & Actions)

### D-005 — Initial A1 Tool Scopes & Allowlist
- **Impact:** High  
- **Scope:** Specific allowed workspace roots, target git repositories, permitted CLI commands, network egress allowlists, and automated rollback scripts.

### D-006 — A2 Approval Authentication Mechanism
- **Impact:** High  
- **Scope:** Choose how consequential actions (production deployments, financial or external communication) are authenticated by the human operator (e.g., local CLI code, WebAuthn/FIDO2 hardware key, or signed cryptographic challenge).

---

## Deferred Beyond Version 1

- Multi-user access and trustee succession protocols.
- Physical robotics actuation and direct hardware control (targeted for Semester 3).
- Biometric sensing, voice-stress analysis, or duress inference.
- Autonomous financial or legal contracting.
- Public multi-tenant network exposure.
- Autonomous self-deployment to external production infrastructure.

Each deferred capability requires its own dedicated threat model, formal verification plan, ADR, and explicit operator ratification.
