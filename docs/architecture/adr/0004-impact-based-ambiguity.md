# ADR-0004: Impact-Based Ambiguity Handling & Deterministic Taxonomy

**Status:** Proposed (Pending Operator Review)  
**Date:** 2026-09-02  

## Context

The legacy JARVIS constitution mandated binary yes/no confirmation for every ambiguity. In complex software engineering, this causes severe operational paralysis on trivial decisions (e.g. naming helper functions), while failing to capture complex architectural trade-offs. Conversely, allowing an LLM to self-classify ambiguity invites sycophancy, where models falsely classify high-risk ambiguities as "low impact" to proceed unimpeded.

## Proposed Decision

We classify ambiguity into **Low**, **Medium**, and **High** impact using a **deterministic, hardcoded rule engine in the Kernel** (`ALN-004a`):

1. **High Impact (Always Block):** Actions modifying permissions, spending financial budget, touching production systems, altering files outside sandbox boundaries, or invoking A2 capabilities. Execution on the affected branch halts immediately until the operator responds.
2. **Medium Impact (Prefer Clarification):** Architectural forks, library/framework selections, or state schema designs. Requires clarification unless a verified safe default is documented with an explicit rollback path.
3. **Low Impact (Proceed with Assumption):** Internal sandbox naming, style, and benign formatting. Handled via recorded, inspectable assumptions.
4. **Default Rule:** Any unclassified ambiguity defaults strictly to Medium.

The Executive Model cannot unilaterally downgrade a High-impact ambiguity to Low.

## Consequences

- **Positive:** Protects developer ergonomics without sacrificing safety. Operator interruptions occur only when outcomes or risks are materially consequential.
- **Positive:** Completely eliminates model hallucination/sycophancy regarding safety gating.
- **Negative / Complexity:** Requires maintaining and testing the deterministic taxonomy pattern matcher within the Kernel.
