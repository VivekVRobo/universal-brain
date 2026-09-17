"""
Universal Brain - Persistence Error Taxonomy

Implements M6 Section 64:
Normalizes database driver exceptions and concurrency failures into
canonical domain errors so domain layers never depend on driver-specific strings.
"""

from __future__ import annotations

from universal_brain.kernel.errors import UniversalBrainError


class PersistenceError(UniversalBrainError):
    """Base exception for all persistence layer failures."""
    pass


class DatabaseUnavailableError(PersistenceError):
    """Raised when the primary database engine cannot be reached or pool is exhausted."""
    pass


class PersistenceTimeoutError(PersistenceError):
    """Raised when a database query, lock acquisition, or transaction exceeds deadline."""
    pass


class ConstraintViolationError(PersistenceError):
    """Raised on relational integrity constraint failure (e.g. foreign key or unique constraint)."""
    pass


class OptimisticConcurrencyError(PersistenceError):
    """Raised when an update condition (version = N) fails because another writer modified the row."""
    pass


class StaleVersionError(OptimisticConcurrencyError):
    """Raised when an operation attempts to commit against a stale aggregate version."""
    pass


class DeadlockError(PersistenceError):
    """Raised when database engine detects a deadlock; candidate for bounded retry."""
    pass


class SchemaMismatchError(PersistenceError):
    """Raised when runtime expects a schema version incompatible with the database."""
    pass


class MigrationRequiredError(SchemaMismatchError):
    """Raised when database schema requires migration before writes are permitted."""
    pass


class IntegrityFailureError(PersistenceError):
    """Raised when cryptographic verification (hash-chain, digest, or causal link) fails."""
    pass


class StorageExhaustedError(PersistenceError):
    """Raised when disk capacity threshold is breached, halting state-changing writes."""
    pass


class FencedEpochError(PersistenceError):
    """Raised when an operation is attempted with an outdated kernel epoch or worker lease."""
    pass


class KernelSplitBrainError(PersistenceError):
    """Raised when another Kernel instance holds the active single-writer lease."""
    pass


class RecoveryRequiredError(PersistenceError):
    """Raised when startup recovery detects inconsistent or unfinalized state requiring recovery."""
    pass
