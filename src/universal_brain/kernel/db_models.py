"""
Universal Brain - Database Models

SQLAlchemy 2.0 ORM models for the Universal Brain's canonical state.

Includes:
- Projects
- Tamper-evident event graph (hash chain + pgvector embeddings)
- Event causality edges
- Alignment contracts (versioned JSONB)

Supports ALN-016 (hash chain), ALN-021 (Total Awareness).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID as PyUUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    current_contract_version: Mapped[int] = mapped_column(
        nullable=False, default=0
    )

    # Relationships
    events: Mapped[List["Event"]] = relationship(back_populates="project")
    contracts: Mapped[List["AlignmentContract"]] = relationship(back_populates="project")


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    contract_version: Mapped[Optional[int]] = mapped_column(nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    prev_event_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    embedding: Mapped[Optional[List[float]]] = mapped_column(
        Vector(384), nullable=True
    )

    # Relationships
    project: Mapped[Optional["Project"]] = relationship(back_populates="events")
    outgoing_edges: Mapped[List["EventEdge"]] = relationship(
        "EventEdge",
        foreign_keys="EventEdge.source_event_id",
        back_populates="source_event",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[List["EventEdge"]] = relationship(
        "EventEdge",
        foreign_keys="EventEdge.target_event_id",
        back_populates="target_event",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_events_payload_gin", payload, postgresql_using="gin"),
        Index("ix_events_prev_event_hash", prev_event_hash),
        Index("ix_events_event_hash", event_hash),
    )


class EventEdge(Base):
    __tablename__ = "event_edges"

    edge_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_event_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    target_event_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    source_event: Mapped["Event"] = relationship(
        "Event", foreign_keys=[source_event_id], back_populates="outgoing_edges"
    )
    target_event: Mapped["Event"] = relationship(
        "Event", foreign_keys=[target_event_id], back_populates="incoming_edges"
    )

    __table_args__ = (
        Index("ix_event_edges_source", source_event_id),
        Index("ix_event_edges_target", target_event_id),
        UniqueConstraint("source_event_id", "target_event_id", name="uq_event_edges_no_self_loop"),
    )


class AlignmentContract(Base):
    __tablename__ = "alignment_contracts"

    contract_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    contract_data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="contracts")

    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_contract_project_version"),
        Index("ix_alignment_contracts_status", status),
        Index("ix_alignment_contracts_created_at", created_at),
    )
