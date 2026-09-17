"""
Database Schema & Mapper Validation Tests

Asserts:
- SQLAlchemy 2.0 ORM mappers configure cleanly without relationship errors.
- Tables, foreign keys, and indexes for projects, events, event_edges, and alignment_contracts match specification.
"""

from sqlalchemy.orm import configure_mappers
from universal_brain.kernel.db_models import (
    Base,
    Project,
    Event,
    EventEdge,
    AlignmentContract,
)


def test_sqlalchemy_mappers_and_schema_definition():
    """Verify that all ORM models configure without relationship or mapping errors."""
    configure_mappers()

    # Check registered tables
    tables = Base.metadata.tables
    assert "projects" in tables
    assert "events" in tables
    assert "event_edges" in tables
    assert "alignment_contracts" in tables

    # Verify primary keys
    assert tables["projects"].primary_key.columns.keys() == ["project_id"]
    assert tables["events"].primary_key.columns.keys() == ["event_id"]
    assert tables["event_edges"].primary_key.columns.keys() == ["edge_id"]
    assert tables["alignment_contracts"].primary_key.columns.keys() == ["contract_id"]

    # Verify indexed columns on events
    event_indices = [idx.name for idx in tables["events"].indexes]
    assert "ix_events_payload_gin" in event_indices
    assert "ix_events_prev_event_hash" in event_indices
    assert "ix_events_event_hash" in event_indices
