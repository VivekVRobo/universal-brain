# ADR-0010: Lazy Persistence Initialization at the Control-Plane Boundary

**Status:** Implemented in the V3 stabilization slice.  
**Date:** 2026-09-07

## Traceability

This decision supports **REQ-STA-001** and preserves the fail-closed intent of **ALN-014**: unrelated read-only control-plane surfaces may remain available, but a persistence/audit failure must never be converted into permission for state-changing work.

## Context

The API dependency container previously constructed `DatabaseManager` at module import time. The configured default PostgreSQL URL caused SQLAlchemy to import the `asyncpg` driver immediately. As a result, a missing or intentionally omitted persistence driver prevented unrelated FastAPI query/security endpoints from even being collected or started.

That coupling violated the desired control-plane boundary: read-only runtime health, authorization tests, worker authentication checks, and Intelligence Fabric observability do not inherently require a live persistence backend.

## Decision

`RuntimeContainer` now keeps the database manager, recovery manager, and artifact store behind lazy properties. A supplied `DatabaseManager` is still treated as the authoritative singleton; otherwise the default manager is constructed only when a persistence-backed route or subsystem first requests it.

The persistence boundary remains fail-closed. Laziness does **not** emulate a database, hide persistence failure, or permit durable operations to continue without their configured backend.

## Consequences

- Positive: importing the API no longer requires `asyncpg` merely because PostgreSQL is the configured production backend.
- Positive: CQRS read-only/security endpoints can be tested in minimal environments without creating alternate authoritative state.
- Positive: persistence-backed routes continue to share one manager/recovery instance once materialized.
- Positive: optional SQLite test environments can use `aiosqlite` without affecting PostgreSQL production configuration.
- Negative: persistence errors occur on first persistence use rather than at module import, so startup policy must explicitly decide whether a deployment should eagerly probe persistence for readiness.
- Constraint: production boot/recovery flows should still initialize and health-check persistence deliberately before declaring the durable runtime READY.
