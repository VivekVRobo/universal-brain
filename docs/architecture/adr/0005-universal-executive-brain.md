# ADR-0005: Universal Executive Brain (Kernel vs. Model Separation)

**Status:** Proposed (Pending Operator Review)  
**Date:** 2026-09-02  

## Context

A fundamental flaw in existing autonomous AI architectures is tightly coupling system ownership, memory, and permissions to a specific LLM session or provider. When that model encounters context saturation, changes prompt formats, hallucinates, or suffers an outage, the system's identity and operational state collapse.

## Decision

We separate the executive function into two distinct layers:
1. **The Executive Kernel:** A permanent, deterministic, provider-neutral core (PostgreSQL, state machines, capability controllers) that owns all canonical truth, contracts, permissions, health, and audit logs.
2. **The Executive Model:** A dynamically leased, replaceable frontier reasoning model (GPT, Claude, Gemini) that receives an Executive Awareness Package (EAP) and emits typed action commands.

The model is treated as an ephemeral reasoning application running on top of the deterministic operating system (the Kernel).

## Consequences

- **Positive:** An Executive Model can crash, hallucinate, or be swapped mid-project with zero loss of canonical state.
- **Positive:** Strong defense against model takeover: the model cannot directly execute code or grant itself permissions; every transition passes through deterministic Kernel guards.
- **Negative / Complexity:** Requires maintaining the Executive Awareness Package (EAP) schema, command parser, and cognitive handoff checkpointing logic.
