"""
Universal Brain - Measurement Units & Dimensional Safety
Implements Sections 21-23 of Milestone M8 Specification (M8-INV-17).
"""

from __future__ import annotations

from typing import Any, Dict, NamedTuple, Optional
from universal_brain.world.errors import UnitDimensionError


class UnitConversionResult(NamedTuple):
    original_value: float
    original_unit: str
    target_unit: str
    converted_value: float
    conversion_factor: float
    provenance: str
    conversion_policy_version: int


class UnitDefinition(NamedTuple):
    unit: str
    dimension: str  # e.g., "length", "angle", "time", "mass", "temperature", "ratio", "electric_potential"
    scale_to_base: float  # multiplied by original to reach base SI unit
    offset_to_base: float = 0.0  # added to reach base SI unit


class MeasurementUnitRegistry:
    """
    Guarantees physical dimensional safety and provides deterministic,
    provenance-preserving unit conversions.
    """

    POLICY_VERSION = 1

    _BASE_UNITS: Dict[str, str] = {
        "length": "m",
        "angle": "rad",
        "time": "s",
        "mass": "kg",
        "ratio": "percent",
        "electric_potential": "V",
        "electric_current": "A",
        "frequency": "Hz",
        "velocity": "m/s",
    }

    _REGISTRY: Dict[str, UnitDefinition] = {
        # Length
        "m": UnitDefinition("m", "length", 1.0),
        "meter": UnitDefinition("meter", "length", 1.0),
        "meters": UnitDefinition("meters", "length", 1.0),
        "cm": UnitDefinition("cm", "length", 0.01),
        "centimeter": UnitDefinition("centimeter", "length", 0.01),
        "centimeters": UnitDefinition("centimeters", "length", 0.01),
        "mm": UnitDefinition("mm", "length", 0.001),
        "millimeter": UnitDefinition("millimeter", "length", 0.001),
        "km": UnitDefinition("km", "length", 1000.0),
        
        # Angle
        "rad": UnitDefinition("rad", "angle", 1.0),
        "radian": UnitDefinition("radian", "angle", 1.0),
        "radians": UnitDefinition("radians", "angle", 1.0),
        "deg": UnitDefinition("deg", "angle", 3.141592653589793 / 180.0),
        "degree": UnitDefinition("degree", "angle", 3.141592653589793 / 180.0),
        "degrees": UnitDefinition("degrees", "angle", 3.141592653589793 / 180.0),

        # Time
        "s": UnitDefinition("s", "time", 1.0),
        "sec": UnitDefinition("sec", "time", 1.0),
        "second": UnitDefinition("second", "time", 1.0),
        "seconds": UnitDefinition("seconds", "time", 1.0),
        "ms": UnitDefinition("ms", "time", 0.001),
        "millisecond": UnitDefinition("millisecond", "time", 0.001),
        "min": UnitDefinition("min", "time", 60.0),
        "minute": UnitDefinition("minute", "time", 60.0),

        # Mass
        "kg": UnitDefinition("kg", "mass", 1.0),
        "kilogram": UnitDefinition("kilogram", "mass", 1.0),
        "g": UnitDefinition("g", "mass", 0.001),
        "gram": UnitDefinition("gram", "mass", 0.001),

        # Ratio / Percentage
        "percent": UnitDefinition("percent", "ratio", 1.0),
        "pct": UnitDefinition("pct", "ratio", 1.0),
        "fraction": UnitDefinition("fraction", "ratio", 100.0),

        # Electric
        "V": UnitDefinition("V", "electric_potential", 1.0),
        "volt": UnitDefinition("volt", "electric_potential", 1.0),
        "volts": UnitDefinition("volts", "electric_potential", 1.0),
        "A": UnitDefinition("A", "electric_current", 1.0),
        "amp": UnitDefinition("amp", "electric_current", 1.0),
        "amps": UnitDefinition("amps", "electric_current", 1.0),

        # Frequency
        "Hz": UnitDefinition("Hz", "frequency", 1.0),
        "hertz": UnitDefinition("hertz", "frequency", 1.0),

        # Velocity
        "m/s": UnitDefinition("m/s", "velocity", 1.0),
        "km/h": UnitDefinition("km/h", "velocity", 1.0 / 3.6),
    }

    @classmethod
    def get_dimension(cls, unit: str) -> str:
        """Returns the physical dimension for the given unit, or raises UnitDimensionError."""
        u = unit.strip().lower()
        if u in cls._REGISTRY:
            return cls._REGISTRY[u].dimension
        # Dimensionless / custom string units
        return "custom"

    @classmethod
    def validate_dimension_match(cls, unit1: str, unit2: str) -> None:
        """Verifies two units have matching physical dimensions."""
        dim1 = cls.get_dimension(unit1)
        dim2 = cls.get_dimension(unit2)
        if dim1 != dim2 and dim1 != "custom" and dim2 != "custom":
            raise UnitDimensionError(
                f"Incompatible unit dimensions: '{unit1}' ({dim1}) cannot be combined with '{unit2}' ({dim2}).",
                {"unit1": unit1, "unit2": unit2, "dimension1": dim1, "dimension2": dim2},
            )

    @classmethod
    def convert(cls, value: float, source_unit: str, target_unit: str) -> UnitConversionResult:
        """Converts value between compatible physical units, preserving conversion provenance."""
        s = source_unit.strip().lower()
        t = target_unit.strip().lower()
        if s not in cls._REGISTRY:
            raise UnitDimensionError(f"Unknown source unit '{source_unit}'.", {"unit": source_unit})
        if t not in cls._REGISTRY:
            raise UnitDimensionError(f"Unknown target unit '{target_unit}'.", {"unit": target_unit})

        cls.validate_dimension_match(s, t)

        s_defn = cls._REGISTRY[s]
        t_defn = cls._REGISTRY[t]

        # Convert to base SI then to target
        base_val = (value * s_defn.scale_to_base) + s_defn.offset_to_base
        target_val = (base_val - t_defn.offset_to_base) / t_defn.scale_to_base
        factor = s_defn.scale_to_base / t_defn.scale_to_base

        return UnitConversionResult(
            original_value=value,
            original_unit=source_unit,
            target_unit=target_unit,
            converted_value=round(target_val, 9),
            conversion_factor=factor,
            provenance=f"{source_unit} -> {target_unit} (factor={factor})",
            conversion_policy_version=cls.POLICY_VERSION,
        )

    @classmethod
    def normalize_to_base(cls, value: float, unit: str) -> UnitConversionResult:
        """
        Converts a value to its canonical base SI unit, preserving conversion provenance.
        """
        u = unit.strip().lower()
        if u not in cls._REGISTRY:
            return UnitConversionResult(
                original_value=value,
                original_unit=unit,
                target_unit=unit,
                converted_value=value,
                conversion_factor=1.0,
                provenance=f"{unit} -> {unit} (unregistered)",
                conversion_policy_version=cls.POLICY_VERSION,
            )

        defn = cls._REGISTRY[u]
        base_unit = cls._BASE_UNITS[defn.dimension]
        return cls.convert(value, unit, base_unit)
