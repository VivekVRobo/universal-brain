# ADR-0001: Local-first canonical state with selective cloud models

**Status:** Accepted by operator  
**Date:** 2026-09-02

## Decision

Store canonical goals, contracts, permissions, secrets, project state, audit records, and private context locally. Cloud models receive task-scoped, minimized, classified, and redacted awareness packages.

## Consequences

- Provider outages cannot own or erase project identity.
- Egress policy and redaction become critical security components.
- Local backup, encryption, and host security are required.
- Cloud quality remains available without making cloud sessions canonical.

