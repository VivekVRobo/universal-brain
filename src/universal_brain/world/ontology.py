"""
Universal Brain - Versioned World Ontology
Implements Sections 24-26 of Milestone M8 Specification (M8-INV-18).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from universal_brain.world.errors import OntologyMismatchError


class PropertySchema(BaseModel):
    property_key: str
    value_type: str  # "float", "int", "str", "bool", "dict", "list", "pose"
    allowed_units: List[str] = Field(default_factory=list)
    requires_coordinate_frame: bool = False
    default_privacy: str = "INTERNAL"
    description: str = ""


class EntityClassSchema(BaseModel):
    class_name: str  # e.g., "ROBOT", "WORKBENCH", "SERVICE", "REPOSITORY", "FILE", "HUMAN"
    allowed_properties: Set[str] = Field(default_factory=set)
    description: str = ""


class RelationTypeSchema(BaseModel):
    relation_type: str  # e.g., "LOCATED_IN", "OBSERVES", "DEPENDS_ON", "MONITORS", "HOLDS"
    source_class: str
    target_class: str
    description: str = ""


class WorldOntology(BaseModel):
    """
    Versioned World Ontology defining the structural semantics of the external world.
    """

    ontology_version: int = 1
    entity_classes: Dict[str, EntityClassSchema] = Field(default_factory=dict)
    property_schemas: Dict[str, PropertySchema] = Field(default_factory=dict)
    relation_schemas: Dict[str, RelationTypeSchema] = Field(default_factory=dict)

    @classmethod
    def get_canonical_ontology(cls, version: int = 1) -> WorldOntology:
        """Factory for the canonical universal brain world ontology v1."""
        if version != 1:
            raise OntologyMismatchError(
                f"Unsupported ontology version: {version}. Canonical active ontology is version 1.",
                {"requested_version": version, "supported_versions": [1]},
            )

        properties = {
            "pose": PropertySchema(
                property_key="pose",
                value_type="dict",
                allowed_units=["m", "meters", "cm", "mm", "rad", "deg"],
                requires_coordinate_frame=True,
                description="3D position and orientation coordinates",
            ),
            "joint_angles": PropertySchema(
                property_key="joint_angles",
                value_type="dict",
                allowed_units=["rad", "deg"],
                requires_coordinate_frame=False,
                description="Robot actuator joint angles",
            ),
            "status": PropertySchema(
                property_key="status",
                value_type="str",
                allowed_units=[],
                description="Categorical health or operating status (e.g. HEALTHY, FAILED)",
            ),
            "battery_level": PropertySchema(
                property_key="battery_level",
                value_type="float",
                allowed_units=["percent", "pct", "fraction"],
                description="Remaining power percentage",
            ),
            "head_commit": PropertySchema(
                property_key="head_commit",
                value_type="str",
                allowed_units=[],
                description="Git repository HEAD SHA commit digest",
            ),
            "file_digest": PropertySchema(
                property_key="file_digest",
                value_type="str",
                allowed_units=[],
                description="Cryptographic SHA-256 digest of file content",
            ),
            "cpu_utilization_pct": PropertySchema(
                property_key="cpu_utilization_pct",
                value_type="float",
                allowed_units=["percent", "pct"],
                description="Host CPU load percentage",
            ),
            "memory_free_bytes": PropertySchema(
                property_key="memory_free_bytes",
                value_type="int",
                allowed_units=["bytes"],
                description="Available system memory in bytes",
            ),
            "is_occupied": PropertySchema(
                property_key="is_occupied",
                value_type="bool",
                allowed_units=[],
                description="Occupancy status of physical workbench or region",
            ),
        }

        classes = {
            "ROBOT": EntityClassSchema(
                class_name="ROBOT",
                allowed_properties={"pose", "joint_angles", "status", "battery_level"},
                description="Physical or simulated robotic manipulator or agent",
            ),
            "WORKBENCH": EntityClassSchema(
                class_name="WORKBENCH",
                allowed_properties={"pose", "is_occupied", "status"},
                description="Physical workstation or table",
            ),
            "SERVICE": EntityClassSchema(
                class_name="SERVICE",
                allowed_properties={"status", "cpu_utilization_pct", "memory_free_bytes"},
                description="Software process or daemon",
            ),
            "REPOSITORY": EntityClassSchema(
                class_name="REPOSITORY",
                allowed_properties={"head_commit", "status"},
                description="Source code or data repository",
            ),
            "FILE": EntityClassSchema(
                class_name="FILE",
                allowed_properties={"file_digest", "status"},
                description="Filesystem artifact",
            ),
            "DEVICE": EntityClassSchema(
                class_name="DEVICE",
                allowed_properties={"status", "battery_level"},
                description="Hardware peripheral or sensor",
            ),
        }

        relations = {
            "LOCATED_IN": RelationTypeSchema(
                relation_type="LOCATED_IN",
                source_class="ROBOT",
                target_class="WORKBENCH",
                description="Entity is physically situated within target area",
            ),
            "DEPENDS_ON": RelationTypeSchema(
                relation_type="DEPENDS_ON",
                source_class="SERVICE",
                target_class="SERVICE",
                description="Service dependency link",
            ),
            "MONITORS": RelationTypeSchema(
                relation_type="MONITORS",
                source_class="DEVICE",
                target_class="ROBOT",
                description="Perception hardware monitoring target entity",
            ),
        }

        return cls(
            ontology_version=1,
            entity_classes=classes,
            property_schemas=properties,
            relation_schemas=relations,
        )

    def validate_property_assignment(
        self,
        entity_class: str,
        property_key: str,
        value: Any,
        unit: Optional[str] = None,
        coordinate_frame: Optional[str] = None,
        version: Optional[int] = None,
    ) -> None:
        """Validates property assignment against ontology rules."""
        if version is not None and version != self.ontology_version:
            raise OntologyMismatchError(
                f"Ontology version mismatch: requested {version}, active {self.ontology_version}.",
                {"requested_version": version, "active_version": self.ontology_version},
            )
        if entity_class not in self.entity_classes:
            # Custom or generic classes allowed, but if class is registered, check property
            pass
        elif property_key not in self.entity_classes[entity_class].allowed_properties:
            # Warn or enforce
            pass

        if property_key in self.property_schemas:
            schema = self.property_schemas[property_key]
            if schema.requires_coordinate_frame and not coordinate_frame:
                raise OntologyMismatchError(
                    f"Property '{property_key}' requires coordinate_frame to be explicitly specified.",
                    {"property_key": property_key},
                )
            if unit and schema.allowed_units and unit.lower() not in [u.lower() for u in schema.allowed_units]:
                raise OntologyMismatchError(
                    f"Unit '{unit}' is not permitted for property '{property_key}'. Allowed units: {schema.allowed_units}",
                    {"property_key": property_key, "unit": unit, "allowed_units": schema.allowed_units},
                )
