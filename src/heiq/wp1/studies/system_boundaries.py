"""Contracts for separating WP1 study and system boundaries.

This module does not calculate membrane or HVAC performance.
It prevents results from different boundaries from being
combined or described as though they were equivalent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from types import MappingProxyType
from typing import Mapping


class StudyPurpose(str, Enum):
    GROSS_OPPORTUNITY = "gross_opportunity"
    EO_CORE = "eo_core"
    RECEIVER_ARCHITECTURE = (
        "receiver_architecture"
    )
    MATERIAL_MECHANISM = "material_mechanism"
    MODULE_GEOMETRY = "module_geometry"
    SYSTEM_COMPARISON = "system_comparison"
    HYBRID_INCREMENT = "hybrid_increment"


class HVACReference(str, Enum):
    NONE = "none"
    NO_ERV_AC = "no_erv_ac"
    MODERN_AC_ERV = "modern_ac_erv"


class ReceiverArchitecture(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    COUPLED_GAS = "coupled_gas"
    SATURATION_TRIGGERED_DRAIN = (
        "saturation_triggered_drain"
    )
    DIRECT_PURE_LIQUID = "direct_pure_liquid"
    LOW_ACTIVITY_LIQUID = (
        "low_activity_liquid"
    )
    TOPOLOGY_DEPENDENT = "topology_dependent"


class ClaimLevel(str, Enum):
    MECHANISM_ONLY = "mechanism_only"
    UPPER_BOUND = "upper_bound"
    CONDITIONAL_SYSTEM = "conditional_system"
    FULL_SYSTEM = "full_system"


class ReductionDefinition(str, Enum):
    RELATIVE_SYSTEM_POWER = (
        "relative_system_power"
    )
    SAVING_PERCENTAGE_POINTS = (
        "saving_percentage_points"
    )
    RH_PERCENTAGE_POINTS = (
        "rh_percentage_points"
    )


@dataclass(frozen=True)
class StudyContract:
    study_id: str
    purpose: StudyPurpose
    hvac_reference: HVACReference
    receiver_architecture: (
        ReceiverArchitecture
    )
    claim_level: ClaimLevel
    includes_erv: bool
    requires_exhaust_resource_gate: bool
    receiver_activity: float | None = None
    omitted_physics_or_loads: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not self.study_id.strip():
            raise ValueError(
                "study_id must not be empty"
            )

        if (
            self.includes_erv
            and self.hvac_reference
            is not HVACReference.MODERN_AC_ERV
        ):
            raise ValueError(
                "ERV studies must use the modern "
                "AC+ERV reference"
            )

        if (
            self.receiver_architecture
            is ReceiverArchitecture.DIRECT_PURE_LIQUID
        ):
            if self.receiver_activity is None:
                raise ValueError(
                    "Direct pure-liquid contact "
                    "requires an explicit activity"
                )

            if not math.isclose(
                self.receiver_activity,
                1.0,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise ValueError(
                    "Pure liquid water must have "
                    "receiver activity approximately one"
                )

        if (
            self.claim_level
            is ClaimLevel.FULL_SYSTEM
            and self.omitted_physics_or_loads
        ):
            raise ValueError(
                "A full-system contract cannot declare "
                "omitted physics or loads"
            )


_CONTRACT_LIST = (
    StudyContract(
        study_id="gross_no_erv_o80_to_o30",
        purpose=StudyPurpose.GROSS_OPPORTUNITY,
        hvac_reference=HVACReference.NO_ERV_AC,
        receiver_architecture=(
            ReceiverArchitecture.NOT_APPLICABLE
        ),
        claim_level=ClaimLevel.UPPER_BOUND,
        includes_erv=False,
        requires_exhaust_resource_gate=False,
        omitted_physics_or_loads=(
            "predryer electricity",
            "predryer pressure drop",
            "receiver handling",
            "predryer auxiliaries",
        ),
        description=(
            "Free-predrying upper bound against the "
            "equal-service no-ERV AC reference."
        ),
    ),
    StudyContract(
        study_id="eo_gas_receiver_no_erv",
        purpose=StudyPurpose.EO_CORE,
        hvac_reference=HVACReference.NO_ERV_AC,
        receiver_architecture=(
            ReceiverArchitecture.COUPLED_GAS
        ),
        claim_level=(
            ClaimLevel.CONDITIONAL_SYSTEM
        ),
        includes_erv=False,
        requires_exhaust_resource_gate=False,
        omitted_physics_or_loads=(
            "receiver regeneration",
            "final receiver water disposal",
            "receiver heat rejection",
        ),
        description=(
            "EO prearchitecture with a coupled gas "
            "receiver and no ERV comparator."
        ),
    ),
    StudyContract(
        study_id=(
            "eo_saturation_drain_no_erv"
        ),
        purpose=(
            StudyPurpose.RECEIVER_ARCHITECTURE
        ),
        hvac_reference=HVACReference.NO_ERV_AC,
        receiver_architecture=(
            ReceiverArchitecture
            .SATURATION_TRIGGERED_DRAIN
        ),
        claim_level=(
            ClaimLevel.CONDITIONAL_SYSTEM
        ),
        includes_erv=False,
        requires_exhaust_resource_gate=False,
        omitted_physics_or_loads=(
            "finite liquid-film resistance",
            "nucleation",
            "flooding and drainage geometry",
            "wet-electrode kinetics",
            "conjugate thermal solution",
        ),
        description=(
            "Gas receiver that first saturates and "
            "then partitions excess water to liquid."
        ),
    ),
    StudyContract(
        study_id=(
            "eo_direct_pure_liquid_no_erv"
        ),
        purpose=(
            StudyPurpose.RECEIVER_ARCHITECTURE
        ),
        hvac_reference=HVACReference.NO_ERV_AC,
        receiver_architecture=(
            ReceiverArchitecture.DIRECT_PURE_LIQUID
        ),
        claim_level=(
            ClaimLevel.CONDITIONAL_SYSTEM
        ),
        includes_erv=False,
        requires_exhaust_resource_gate=False,
        receiver_activity=1.0,
        omitted_physics_or_loads=(
            "finite liquid-film resistance",
            "capillary and drainage geometry",
            "flooding",
            "wet-electrode kinetics",
            "electrolysis and corrosion",
            "conjugate thermal solution",
        ),
        description=(
            "Direct contact with pure liquid water "
            "from the first active-area step."
        ),
    ),
    StudyContract(
        study_id=(
            "eo_low_activity_liquid_no_erv"
        ),
        purpose=(
            StudyPurpose.RECEIVER_ARCHITECTURE
        ),
        hvac_reference=HVACReference.NO_ERV_AC,
        receiver_architecture=(
            ReceiverArchitecture.LOW_ACTIVITY_LIQUID
        ),
        claim_level=(
            ClaimLevel.CONDITIONAL_SYSTEM
        ),
        includes_erv=False,
        requires_exhaust_resource_gate=False,
        omitted_physics_or_loads=(
            "sorbent regeneration",
            "solution circulation design",
            "finite liquid-film resistance",
            "conjugate thermal solution",
        ),
        description=(
            "Low-activity liquid or sorbent study; "
            "not equivalent to pure water."
        ),
    ),
    StudyContract(
        study_id="material_transport_mechanisms",
        purpose=(
            StudyPurpose.MATERIAL_MECHANISM
        ),
        hvac_reference=HVACReference.NONE,
        receiver_architecture=(
            ReceiverArchitecture.TOPOLOGY_DEPENDENT
        ),
        claim_level=ClaimLevel.MECHANISM_ONLY,
        includes_erv=False,
        requires_exhaust_resource_gate=False,
        description=(
            "Material, diffusivity, drag, "
            "conductivity, thickness and ASR study."
        ),
    ),
    StudyContract(
        study_id="module_geometry",
        purpose=StudyPurpose.MODULE_GEOMETRY,
        hvac_reference=HVACReference.NONE,
        receiver_architecture=(
            ReceiverArchitecture.TOPOLOGY_DEPENDENT
        ),
        claim_level=ClaimLevel.MECHANISM_ONLY,
        includes_erv=False,
        requires_exhaust_resource_gate=False,
        description=(
            "Joint length, width and channel-depth "
            "study with films and fan work."
        ),
    ),
    StudyContract(
        study_id="modern_ac_erv_reference",
        purpose=(
            StudyPurpose.SYSTEM_COMPARISON
        ),
        hvac_reference=(
            HVACReference.MODERN_AC_ERV
        ),
        receiver_architecture=(
            ReceiverArchitecture.NOT_APPLICABLE
        ),
        claim_level=ClaimLevel.FULL_SYSTEM,
        includes_erv=True,
        requires_exhaust_resource_gate=True,
        description=(
            "Equal-service conventional modern "
            "AC+ERV reference."
        ),
    ),
    StudyContract(
        study_id="eo_erv_hybrid",
        purpose=StudyPurpose.HYBRID_INCREMENT,
        hvac_reference=(
            HVACReference.MODERN_AC_ERV
        ),
        receiver_architecture=(
            ReceiverArchitecture.TOPOLOGY_DEPENDENT
        ),
        claim_level=ClaimLevel.FULL_SYSTEM,
        includes_erv=True,
        requires_exhaust_resource_gate=True,
        description=(
            "EO+ERV topology compared with ERV alone "
            "using one declared exhaust resource."
        ),
    ),
)


_contracts = {
    contract.study_id: contract
    for contract in _CONTRACT_LIST
}

if len(_contracts) != len(_CONTRACT_LIST):
    raise RuntimeError(
        "Duplicate study_id in contract registry"
    )


STUDY_CONTRACTS: Mapping[
    str,
    StudyContract,
] = MappingProxyType(_contracts)


def get_study_contract(
    study_id: str,
) -> StudyContract:
    try:
        return STUDY_CONTRACTS[study_id]
    except KeyError as exc:
        known = ", ".join(
            sorted(STUDY_CONTRACTS)
        )
        raise KeyError(
            f"Unknown study_id {study_id!r}. "
            f"Known studies: {known}"
        ) from exc


def _finite_nonnegative(
    name: str,
    value: float,
) -> float:
    result = float(value)

    if (
        not math.isfinite(result)
        or result < 0.0
    ):
        raise ValueError(
            f"{name} must be finite and nonnegative"
        )

    return result


@dataclass(frozen=True)
class ConditionalBreakEven:
    baseline_compressor_kw: float
    target_compressor_kw: float
    predryer_water_kg_h: float
    accounted_predryer_power_kw: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "baseline_compressor_kw",
            "target_compressor_kw",
            "accounted_predryer_power_kw",
        ):
            _finite_nonnegative(
                name,
                getattr(self, name),
            )

        water = float(
            self.predryer_water_kg_h
        )

        if (
            not math.isfinite(water)
            or water <= 0.0
        ):
            raise ValueError(
                "predryer_water_kg_h must be "
                "finite and positive"
            )

        if self.gross_opportunity_kw <= 0.0:
            raise ValueError(
                "The target must provide a positive "
                "gross compressor opportunity"
            )

    @property
    def gross_opportunity_kw(self) -> float:
        return (
            float(self.baseline_compressor_kw)
            - float(self.target_compressor_kw)
        )

    @property
    def gross_break_even_kwh_kg(
        self,
    ) -> float:
        return (
            self.gross_opportunity_kw
            / float(self.predryer_water_kg_h)
        )

    @property
    def gross_break_even_wh_l_approx(
        self,
    ) -> float:
        return (
            1000.0
            * self.gross_break_even_kwh_kg
        )

    @property
    def remaining_budget_kw(self) -> float:
        return (
            self.gross_opportunity_kw
            - float(
                self.accounted_predryer_power_kw
            )
        )

    @property
    def remaining_budget_kwh_kg(
        self,
    ) -> float:
        return (
            self.remaining_budget_kw
            / float(self.predryer_water_kg_h)
        )

    @property
    def remaining_budget_wh_l_approx(
        self,
    ) -> float:
        return (
            1000.0
            * self.remaining_budget_kwh_kg
        )


@dataclass(frozen=True)
class PrearchitectureGates:
    """Optional engineering screens for a pre-architecture result.

    Current density is diagnostic in the active system study. A current-density
    limit is therefore applied only when a caller supplies one explicitly.
    """

    max_current_density_a_m2: float | None = None
    max_active_area_m2: float = 9000.0
    max_terminal_voltage_v: float = 2.0

    def violations(
        self,
        *,
        maximum_local_current_density_a_m2: float,
        required_active_area_m2: float,
        terminal_voltage_v: float,
    ) -> tuple[str, ...]:
        values = {
            "maximum_local_current_density_a_m2":
                maximum_local_current_density_a_m2,
            "required_active_area_m2":
                required_active_area_m2,
            "terminal_voltage_v":
                terminal_voltage_v,
        }

        cleaned = {
            name: _finite_nonnegative(name, value)
            for name, value in values.items()
        }

        violations: list[str] = []

        comparisons: list[tuple[str, float]] = [
            (
                "required_active_area_m2",
                self.max_active_area_m2,
            ),
            (
                "terminal_voltage_v",
                self.max_terminal_voltage_v,
            ),
        ]

        if self.max_current_density_a_m2 is not None:
            comparisons.insert(
                0,
                (
                    "maximum_local_current_density_a_m2",
                    self.max_current_density_a_m2,
                ),
            )

        for name, limit in comparisons:
            value = cleaned[name]
            tolerance = (
                1.0e-12
                * max(1.0, abs(limit))
            )

            if value > limit + tolerance:
                violations.append(
                    f"{name}={value:.12g} exceeds "
                    f"limit={limit:.12g}"
                )

        return tuple(violations)


@dataclass(frozen=True)
class ExhaustAllocation:
    available_exhaust_dry_air_kg_s: float
    erv_allocated_dry_air_kg_s: float
    receiver_dry_air_kg_s: float
    external_receiver_source_kg_s: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "available_exhaust_dry_air_kg_s",
            "erv_allocated_dry_air_kg_s",
            "receiver_dry_air_kg_s",
            "external_receiver_source_kg_s",
        ):
            _finite_nonnegative(
                name,
                getattr(self, name),
            )

    @property
    def available_total_kg_s(self) -> float:
        return (
            self.available_exhaust_dry_air_kg_s
            + self.external_receiver_source_kg_s
        )

    @property
    def allocated_total_kg_s(self) -> float:
        return (
            self.erv_allocated_dry_air_kg_s
            + self.receiver_dry_air_kg_s
        )

    @property
    def margin_kg_s(self) -> float:
        return (
            self.available_total_kg_s
            - self.allocated_total_kg_s
        )

    def validate(self) -> None:
        if self.margin_kg_s < -1.0e-12:
            raise ValueError(
                "ERV and EO receiver over-allocate "
                "the declared exhaust/external resource "
                f"by {-self.margin_kg_s:.12g} kg/s"
            )


CANONICAL_POWER_COMPONENTS = (
    "downstream_hvac",
    "eo_grid",
    "process_fan",
    "receiver_fan",
    "erv_fans",
    "erv_wheel",
    "liquid_pump",
    "heat_rejection",
    "receiver_regeneration",
    "other_auxiliaries",
    "upstream_electrical_losses",
)


@dataclass(frozen=True)
class PowerLedger:
    """Explicit electrical-power ledger at one reference plane.

    Missing and zero are deliberately different. A component
    that does not apply must be entered explicitly as 0.0.
    """

    reference_plane: str
    components_kw: Mapping[
        str,
        float | None,
    ]

    def __post_init__(self) -> None:
        if not self.reference_plane.strip():
            raise ValueError(
                "reference_plane must not be empty"
            )

        unexpected = (
            set(self.components_kw)
            - set(CANONICAL_POWER_COMPONENTS)
        )

        if unexpected:
            names = ", ".join(
                sorted(unexpected)
            )
            raise ValueError(
                "Unexpected power components: "
                f"{names}"
            )

        cleaned: dict[
            str,
            float | None,
        ] = {}

        for name in CANONICAL_POWER_COMPONENTS:
            value = self.components_kw.get(name)

            if value is None:
                cleaned[name] = None
            else:
                cleaned[name] = (
                    _finite_nonnegative(
                        name,
                        value,
                    )
                )

        object.__setattr__(
            self,
            "components_kw",
            MappingProxyType(cleaned),
        )

    @property
    def missing_components(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            name
            for name in CANONICAL_POWER_COMPONENTS
            if self.components_kw[name] is None
        )

    @property
    def is_complete(self) -> bool:
        return not self.missing_components

    @property
    def known_total_kw(self) -> float:
        return sum(
            float(value)
            for value in self.components_kw.values()
            if value is not None
        )

    def total_kw(self) -> float:
        missing = self.missing_components

        if missing:
            raise ValueError(
                "Cannot calculate full-system total; "
                "missing components: "
                + ", ".join(missing)
            )

        return self.known_total_kw


__all__ = [
    "CANONICAL_POWER_COMPONENTS",
    "ClaimLevel",
    "ConditionalBreakEven",
    "ExhaustAllocation",
    "HVACReference",
    "PowerLedger",
    "PrearchitectureGates",
    "ReceiverArchitecture",
    "ReductionDefinition",
    "STUDY_CONTRACTS",
    "StudyContract",
    "StudyPurpose",
    "get_study_contract",
]
