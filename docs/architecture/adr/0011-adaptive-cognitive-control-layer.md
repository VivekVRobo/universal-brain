# ADR-0011: Adaptive Cognitive Control Layer

**Status:** Implemented as a local/runtime slice; external-provider calibration remains operator-gated.  
**Date:** 2026-09-07  
**Supersedes:** No prior ADR. Extends ADR-0009.

## Context

ADR-0009 established model identity, access-route identity, and transport separation. That was necessary but insufficient for a mature Universal Brain: a router also needs local evidence about which model is good at which task, memory retrieval needs canonical provenance, model disagreements need structured handling, interactive provider sessions need recovery, and long-horizon TaskDAGs need a safe way to consume multi-model cognition.

Hard-coding vendor preferences would violate the provider-neutral design and age poorly. Treating model consensus as evidence would violate ALN-011. Treating browser/desktop provider threads as canonical memory would violate the Constitution's local-state and provider-independence requirements.

## Decision

Universal Brain will implement an **Adaptive Cognitive Control Layer** above the transport runtime and below the deterministic Executive/Kernel authority boundary.

The layer consists of:

1. local capability-evidence discovery blended with catalog priors;
2. deterministic evaluation harnesses feeding empirical routing data;
3. canonical/derived memory context adapters with provenance;
4. explicit Council disagreement graphs plus independent advisory adjudication;
5. recoverable, non-canonical provider session continuity;
6. authorized browser and Windows UI Automation drivers;
7. an adaptive cognitive TaskDAG runtime that never bypasses Verification Engine or ToolGateway authority.

## Authority Boundary

Adaptive control can decide **which cognitive worker to ask** and **what minimal context to provide**. It cannot:

- expand a task action class;
- mint capabilities;
- approve A2 actions;
- turn model agreement into evidence;
- execute model-proposed tools directly;
- treat provider memory as canonical state.

This preserves Constitution Articles III–VI and ALN-001, ALN-008, ALN-010, ALN-011, ALN-013, and ALN-021.

## Evaluation Decision

A model is never permitted to grade its own benchmark result for routing purposes. Evaluation verdicts must come from deterministic code/tests or an explicitly supplied operator/reviewer adapter with an evidence reference.

## Interactive Session Decision

Recovery is permitted only after the authorized route is usable again. The runtime may reopen a stored same-origin conversation URL or return to the configured provider start page. It may not enter credentials, bypass MFA/CAPTCHA, rotate identity to evade limits, or defeat anti-bot/security controls.

## Mission Decision

The adaptive mission runtime may execute cognitive work for TaskDAG nodes. A node cannot be marked `SUCCEEDED` merely because a model or Council says it is complete. Acceptance requires the supplied Verification Engine adapter. Tool proposals continue through Kernel/ToolGateway policy.

A2 cognitive tasks may require independent Council review. When this policy is active and independent routes are unavailable, the task fails closed rather than silently downgrading to a single model.

## Consequences

### Positive

- new frontier models can be calibrated locally rather than hard-coded by brand;
- routing can improve over time from benchmark evidence;
- context can include mission/event/semantic memory while preserving provenance;
- disagreements become inspectable rather than silently averaged away;
- provider UI continuity is more resilient;
- Windows desktop AI applications become valid operator-authorized routes;
- canonical mission DAGs can consume the Intelligence Fabric safely.

### Negative / Complexity

- capability and performance data require ongoing benchmark maintenance;
- browser/UIA selectors are provider/app-version sensitive;
- multi-model Council execution increases latency/cost;
- mission execution still requires separate ToolGateway and Verification Engine integrations for full autonomous completion.

## Rollback

The V4 layer is modular. Disable capability evidence, memory context sources, Council adjudication, interactive routes, or mission runtime independently and fall back to the V3 router/runtime without changing canonical Kernel state.
