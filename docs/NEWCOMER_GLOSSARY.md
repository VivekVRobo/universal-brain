# Universal Brain Newcomer Glossary

This glossary defines the recurring architecture terms used throughout Universal Brain. Definitions are intentionally scoped to the current repository specifications; they do not introduce new architecture or implementation claims.

## Executive Kernel

The **Executive Kernel** is the deterministic control-plane core. It owns canonical state, permissions, mission lifecycle, health, budgets, checkpoints, audit history, and evidence indexes.

The Kernel is the authority boundary: models can propose actions, but they do not directly own canonical state or permissions.

**Authoritative references:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md), [Threat Model](../security/THREAT_MODEL.md)

## Executive Model

The **Executive Model** is the ephemeral intelligence layer used for reasoning, planning, task decomposition, and communication.

A model operates under an explicit reasoning lease. It cannot directly write canonical state, grant permissions, or bypass verification gates.

**Authoritative reference:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md)

## Model Lease

A **model lease** is the bounded authorization/context under which an Executive Model performs a task or turn.

The lease is ephemeral and can be revoked by the Kernel. It is not permanent authority and does not transfer ownership of canonical state to the model.

**Authoritative reference:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md)

## Executive Awareness Package (EAP)

The **Executive Awareness Package (EAP)** is the structured, bounded context package that the Kernel supplies to the Executive Model.

It contains selected session context, constitutional boundaries, health, budgets, active projects/agents, pending decisions, and recent critical events. The model can request deeper system inspection through the typed `INSPECT_SYSTEM` command instead of receiving unrestricted raw database access.

**Authoritative reference:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md)

## Alignment Contract

The **Alignment Contract** is the structured record that preserves the user's original intent, requirements, constraints, assumptions, non-goals, and ambiguity decisions across execution.

Contract versions are preserved rather than silently overwritten. Changes require an explicit semantic difference and rationale.

**Authoritative references:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md), [Alignment Invariants](alignment/INVARIANTS.md)

## Tool Gateway

The **Tool Gateway** is the execution boundary for consequential external actions.

Model-authored intent is not equivalent to permission. Actions crossing this boundary require the applicable authority checks and capability controls before execution.

**Authoritative references:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md), [Threat Model](security/THREAT_MODEL.md)

## Authority Level

An **authority level** describes the allowed consequence boundary for an action. The current architecture distinguishes action ceilings such as A0, A1, and A2.

Higher-impact actions require stronger controls. The system is designed to fail closed rather than infer operator consent.

**Authoritative references:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md), [Threat Model](security/THREAT_MODEL.md)

## Canonical State

**Canonical state** is the authoritative persistent system state maintained by the deterministic control plane.

Models, transient context, cached summaries, and external observations are not automatically canonical. Evidence and validated state transitions are used to update the canonical record.

**Authoritative references:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md), [Threat Model](security/THREAT_MODEL.md)

## Durable Mission

A **durable mission** is execution state that is persisted so work can survive process boundaries, interruption, and restart.

The V5.3 validation architecture uses checkpoints, session fingerprints, and sealed evidence to verify recovery rather than relying on an in-memory model context.

**Authoritative reference:** [Engineering Agency V5.3](architecture/ENGINEERING_AGENCY_V53.md)

## Worker Lease / Fencing

A **worker lease** bounds a worker's authority and lifetime. **Fencing** prevents an expired or superseded worker from continuing to act as though it still owns the task.

This is part of the Engineering Agency runtime's durability and recovery controls.

**Authoritative reference:** [Engineering Agency V5.3](architecture/ENGINEERING_AGENCY_V53.md)

## Evidence Gate

An **evidence gate** is a completion boundary that requires verifiable artifacts or test results before a capability or milestone can be marked proven.

A passing software test is not automatically proof of target-machine execution, hardware behavior, endurance, or production readiness.

**Authoritative references:** [Engineering Agency V5.3](architecture/ENGINEERING_AGENCY_V53.md), [Release Readiness](RELEASE_READINESS.md)

## Remediation / Rollback

**Remediation** is the controlled response to a detected failure or invalid state. **Rollback** restores an affected execution branch to a previously verified checkpoint when the applicable rollback path exists.

These mechanisms are part of the recovery model and are not equivalent to silently ignoring a failed verification step.

**Authoritative references:** [Executive Brain Specification](architecture/EXECUTIVE_BRAIN_SPEC.md), [Engineering Agency V5.3](architecture/ENGINEERING_AGENCY_V53.md)

## Intelligence Fabric

The **Intelligence Fabric** is the model/provider routing layer.

It separates model identity, provider access, routing, council behavior, and transport from canonical state and execution authority. Models are replaceable reasoning services rather than sources of truth.

**Authoritative reference:** [Intelligence Fabric](architecture/INTELLIGENCE_FABRIC_SPEC.md)

## Evidence Sealing

**Evidence sealing** is the process of recording cryptographic hashes and metadata for validation artifacts so their integrity can be checked later.

V5.3 uses SHA-256 manifests and offline verification to detect missing, altered, or unexpected evidence artifacts.

**Authoritative reference:** [Engineering Agency V5.3](architecture/ENGINEERING_AGENCY_V53.md)

## Quick mental model

When reading the repository, keep this separation in mind:

```text
Models reason
   ↓
Executive Model proposes typed actions
   ↓
Executive Kernel validates authority + state
   ↓
Tool Gateway controls consequential effects
   ↓
Verification produces evidence
   ↓
Canonical state records the verified result
```

The central rule is:

> **Reasoning is replaceable; authority, canonical state, verification, and recovery remain deterministic and explicitly controlled.**
