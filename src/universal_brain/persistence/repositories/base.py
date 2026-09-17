"""
Universal Brain - Base Repository Pattern

Implements M6 Section 7 & 8:
Encapsulates database access behind explicit repository abstractions,
insulating domain layers from raw query objects and translating exceptions.
"""

from __future__ import annotations

from typing import Generic, TypeVar
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from universal_brain.persistence.errors import (
    ConstraintViolationError,
    PersistenceError,
)

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Generic repository holding an active AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _translate_exception(self, exc: Exception) -> PersistenceError:
        """Translates SQLAlchemy exceptions to canonical persistence taxonomy."""
        if isinstance(exc, IntegrityError):
            return ConstraintViolationError(f"Database constraint violation: {exc}")
        if isinstance(exc, SQLAlchemyError):
            return PersistenceError(f"Database driver error: {exc}")
        if isinstance(exc, PersistenceError):
            return exc
        return PersistenceError(f"Unexpected persistence error: {exc}")
