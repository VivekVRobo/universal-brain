"""
Universal Brain - Unit Tests for M8 Units, Dimensions & Ontology
"""

import pytest

from universal_brain.world.errors import (
    OntologyMismatchError,
    UnitDimensionError,
)
from universal_brain.world.ontology import WorldOntology
from universal_brain.world.units import MeasurementUnitRegistry


def test_measurement_unit_scaling_and_provenance() -> None:
    # Convert mm to m
    res = MeasurementUnitRegistry.convert(500.0, "mm", "m")
    assert res.converted_value == 0.5
    assert res.target_unit == "m"
    assert res.conversion_factor == 0.001
    assert "mm -> m" in res.provenance

    # Convert deg to rad
    res_deg = MeasurementUnitRegistry.convert(180.0, "deg", "rad")
    assert round(res_deg.converted_value, 4) == 3.1416


def test_measurement_unit_incompatible_dimensions_raise() -> None:
    # Attempting to convert kg (mass) to m (length)
    with pytest.raises(UnitDimensionError) as exc_info:
        MeasurementUnitRegistry.convert(10.0, "kg", "m")
    assert "Incompatible unit dimensions" in str(exc_info.value)


def test_ontology_property_validation_and_frame_requirements() -> None:
    ontology = WorldOntology.get_canonical_ontology()

    # Valid pose assignment requires coordinate_frame
    ontology.validate_property_assignment(
        entity_class="ROBOT",
        property_key="pose",
        value={"x": 1.0, "y": 2.0, "z": 0.0},
        coordinate_frame="odom",
    )

    # Missing coordinate_frame for spatial property must raise
    with pytest.raises(OntologyMismatchError) as exc_info:
        ontology.validate_property_assignment(
            entity_class="ROBOT",
            property_key="pose",
            value={"x": 1.0, "y": 2.0, "z": 0.0},
            coordinate_frame=None,  # Missing frame!
        )
    assert "requires coordinate_frame" in str(exc_info.value)


def test_ontology_version_mismatch_raises() -> None:
    ontology = WorldOntology.get_canonical_ontology()
    with pytest.raises(OntologyMismatchError):
        ontology.validate_property_assignment(
            entity_class="ROBOT",
            property_key="pose",
            value={"x": 1.0, "y": 2.0, "z": 0.0},
            coordinate_frame="odom",
            version=999,  # Unsupported future version
        )
