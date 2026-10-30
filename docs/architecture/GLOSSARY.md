# Universal Brain Architecture Glossary

This glossary explains recurring terms used in the repository's current architecture and verification documents. It is a navigation aid, not a new specification: when a definition matters to an implementation or release decision, follow the linked specification or ADR. A documented capability is not proof that every target environment has passed its evidence gates.

## Executive Kernel

The **Executive Kernel** is the deterministic, provider-neutral control plane. It owns canonical state, active permissions, contracts, mission lifecycle, budgets, checkpoints, audit history, and evidence indexes; models may propose transitions, but the Kernel validates them. See the [Executive Brain Spec](EXECUTIVE_BRAIN_SPEC.md) and [System Architecture](SYSTEM_ARCHITECTURE.md).

## Executive Model and model lease

The **Executive Model** is a replaceable reasoning model temporarily assigned to interpret intent, plan work, and propose typed action commands. Its **model lease** is the bounded, revocable reasoning assignment; the model cannot directly write canonical state, grant itself permissions, or bypass verification. See [Executive Brain Spec](EXECUTIVE_BRAIN_SPEC.md) and [ADR-0005](adr/0005-universal-executive-brain.md).

## Executive Awareness Package (EAP)

The **EAP** is the Kernel-compiled, structured, minimized context package supplied to the Executive Model for a turn. It provides task-relevant context under defined size and selection limits; receiving context is not receiving execution authority. See the [EAP protocol in the Executive Brain Spec](EXECUTIVE_BRAIN_SPEC.md).

## Alignment Contract

An **Alignment Contract** is the versioned bridge between the original natural-language request and executable work. It records requirements, constraints, assumptions, non-goals, ambiguity, acceptance criteria, and applicable evidence or rollback requirements; changing it creates a new version rather than silently overwriting history. See the [Alignment Contract Schema](../alignment/ALIGNMENT_CONTRACT_SCHEMA.md) and [alignment invariants](../alignment/INVARIANTS.md).

## Canonical state

**Canonical state** is the authoritative, model-neutral record of project goals, constraints, permissions, lifecycle state, decisions, and evidence references maintained by the control plane and its configured persistence. A model's prompt, conversation history, or provider-side memory is only a context projection and must not be treated as the source of truth. See the [Executive Brain Spec](EXECUTIVE_BRAIN_SPEC.md) and [ADR-0010](adr/0010-lazy-persistence-control-plane-boundary.md).

## Intelligence Fabric

The **Intelligence Fabric** is the provider and transport layer for routing work to frontier or local models, managing model access, and coordinating advisory reasoning. It keeps models replaceable and does not own canonical state, permissions, or action authority. See the [Intelligence Fabric Spec](INTELLIGENCE_FABRIC_SPEC.md).

## Tool Gateway

The **Tool Gateway** is the controlled execution boundary for consequential external effects. The architecture requires it to validate action class, target scope, preconditions, rollback path, idempotency, and audit health before an action is allowed. See [System Architecture](SYSTEM_ARCHITECTURE.md), the [action-authority ADR](adr/0002-version1-action-authority.md), and the [Constitution draft](../constitution/UNIVERSAL_BRAIN_CONSTITUTION_DRAFT.md).

## Authority level (action class)

The repository expresses action authority through action classes: **A0** is observation without state change; **A1** is bounded reversible digital work with tested rollback and audit; **A2** is consequential work requiring explicit, target-specific approval; and **A3** is prohibited autonomous action. An action class does not replace the separate checks for permissions, scope, preconditions, or verification. See the [Constitution draft](../constitution/UNIVERSAL_BRAIN_CONSTITUTION_DRAFT.md) and [alignment invariants](../alignment/INVARIANTS.md).

## Durable mission

A **durable mission** is a mission whose state and checkpoints are persisted so recovery can be attempted after interruption or process restart, rather than depending only on transient model context. Recovery claims must be backed by the applicable persistence and restart tests; the phrase alone does not establish target-machine endurance. See the README's [evidence board](../../README.md) and the [V5.3 verification record](../testing/ENGINEERING_AGENCY_V53_VERIFICATION.md).

## Worker lease and fencing

A **worker lease** is a time-bounded assignment of work to a worker. **Fencing** uses a monotonically increasing generation or token so a worker from an older assignment cannot commit results after its lease has expired or work has been reassigned. See [Platform Requirements](../requirements/PLATFORM_REQUIREMENTS.md) (REQ-ENG-029) and [ADR-0014](adr/0014-engineering-runtime-hardening.md).

## Evidence gate

An **evidence gate** is a required verification checkpoint that controls whether a state transition or completion claim may advance. Evidence must be relevant to the claim and independently inspectable; a missing or skipped applicable check is not a pass. The repository's target-validation rules distinguish **PASS**, **FAIL**, and **SKIP** explicitly. See [ADR-0015](adr/0015-real-environment-validation-and-endurance.md) and the [V5.3 verification record](../testing/ENGINEERING_AGENCY_V53_VERIFICATION.md).

## Remediation and rollback

**Remediation** is a bounded repair attempt performed within the authorized scope and followed by verification. **Rollback** restores the affected work to its defined pre-action state or last verified checkpoint using the specified recovery mechanism; it is not merely a promise that an operation can be undone. See [Platform Requirements](../requirements/PLATFORM_REQUIREMENTS.md), [ADR-0008](adr/0008-rollback-engine-specification.md), and [ADR-0014](adr/0014-engineering-runtime-hardening.md).

## Related reading

- [System Architecture](SYSTEM_ARCHITECTURE.md) — component boundaries and data flow.
- [Executive Brain Spec](EXECUTIVE_BRAIN_SPEC.md) — Kernel, model lease, EAP, and typed action commands.
- [Intelligence Fabric Spec](INTELLIGENCE_FABRIC_SPEC.md) — model routing and transport boundaries.
- [Alignment Contract Schema](../alignment/ALIGNMENT_CONTRACT_SCHEMA.md) — contract fields and lifecycle constraints.
- [Platform Requirements](../requirements/PLATFORM_REQUIREMENTS.md) — engineering requirements, including worker fencing and evidence.
- [V5.3 verification record](../testing/ENGINEERING_AGENCY_V53_VERIFICATION.md) — current verification claims and target-environment limitations.
