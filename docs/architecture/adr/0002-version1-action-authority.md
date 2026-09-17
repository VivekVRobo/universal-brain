# ADR-0002: Version 1 Permits Approved Reversible Digital Actions

**Status:** Accepted by operator  
**Date:** 2026-09-02  

## Decision

Version 1 may execute A1 reversible digital actions within approved tasks. Each action requires bounded scope, preconditions, verified rollback, postconditions, idempotency, capability token authorization, and tamper-evident audit evidence.

A2 actions require immediate explicit approval and remain disabled until their approval workflow is implemented and tested. Physical actuation is excluded.

The exact mechanics of reversibility and preflight rollback verification are governed by [ADR-0008: Rollback Engine Specification](0008-rollback-engine-specification.md).

## Consequences

- The first vertical slice can create real but recoverable repository changes.
- “Reversible” is a verified property tested via preflight dry-run (`patch -R --dry-run`), not a label chosen by an LLM.
- External messages, account deletion, financial activity, and production deployment are not A1.
