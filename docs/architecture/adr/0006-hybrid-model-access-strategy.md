# ADR-0006: Hybrid Model Access Strategy (APIs vs. Browser Agents)

**Status:** Proposed; access-routing details generalized by ADR-0009 (isolation decision D-008 remains pending)  
**Date:** 2026-09-02  

## Context

Pure API access provides tight alignment, low latency, structured JSON output, and deterministic auditing, but becomes prohibitively expensive when performing massive web harvesting, broad exploration, or long-context document ingestion. Conversely, driving consumer web UIs directly via browser automation saves token costs but introduces latency, brittle DOM selectors, and anti-bot obstacles.

## Decision

We adopt a **Hybrid Model Access Strategy**:
1. **Direct API Access (Option 2):** Reserved exclusively for the **Executive Model** and high-consequence reasoning tasks (planning, code generation, architectural decisions, and verification). All API payloads and responses are logged deterministically.
2. **Sandboxed Browser Agent (Option 1):** A dedicated, sandboxed sub-agent running inside an isolated VM/container. It is deployed for mass data harvesting, web search, literature scraping, and interacting with consumer web interfaces (e.g., ChatGPT Plus, Claude Pro) for non-critical high-volume text digestion.

**Enforcement Rule:** The Executive Model never directly manipulates or views raw browser sessions. The Browser Agent extracts, filters, and sanitizes data into clean JSON schemas before delivering it to the Kernel. The Browser Agent's visual sessions are recorded as inspectable evidence artifacts (satisfying ALN-016).

## Consequences

- **Positive:** Reduces operational API expenses by 70–90% while keeping executive planning rigorous and secure.
- **Positive:** Mitigates prompt injection: raw web HTML is quarantined in the browser sandbox and sanitized before executive consumption.
- **Negative / Complexity:** Requires maintaining browser automation infrastructure (Playwright/Puppeteer), session keepalive, and VM container isolation.


## Relationship to ADR-0009

ADR-0009 generalizes this two-lane API/browser decision into model identity + access route + transport. Browser access is no longer architecturally limited to harvesting: an operator-authorized UI session can be an eligible cognitive route when policy allows it. This does **not** ratify D-008 or authorize any CAPTCHA/MFA/rate-limit bypass. The final browser isolation mechanism remains operator-gated.
