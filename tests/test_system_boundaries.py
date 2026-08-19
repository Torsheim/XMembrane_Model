import math

import pytest

from heiq.wp1.studies.system_boundaries import (
    CANONICAL_POWER_COMPONENTS,
    ClaimLevel,
    ConditionalBreakEven,
    ExhaustAllocation,
    PowerLedger,
    PrearchitectureGates,
    ReceiverArchitecture,
    STUDY_CONTRACTS,
)


EXPECTED_STUDIES = {
    "gross_no_erv_o80_to_o30",
    "eo_gas_receiver_no_erv",
    "eo_saturation_drain_no_erv",
    "eo_direct_pure_liquid_no_erv",
    "eo_low_activity_liquid_no_erv",
    "material_transport_mechanisms",
    "module_geometry",
    "modern_ac_erv_reference",
    "eo_erv_hybrid",
}


def test_all_required_study_boundaries_are_declared():
    assert set(STUDY_CONTRACTS) == EXPECTED_STUDIES


def test_erv_is_not_applied_to_all_models():
    erv_studies = {
        study_id
        for study_id, contract
        in STUDY_CONTRACTS.items()
        if contract.includes_erv
    }

    assert erv_studies == {
        "modern_ac_erv_reference",
        "eo_erv_hybrid",
    }


def test_pure_liquid_and_saturation_drain_are_distinct():
    direct = STUDY_CONTRACTS[
        "eo_direct_pure_liquid_no_erv"
    ]
    triggered = STUDY_CONTRACTS[
        "eo_saturation_drain_no_erv"
    ]

    assert direct.receiver_architecture is (
        ReceiverArchitecture.DIRECT_PURE_LIQUID
    )
    assert triggered.receiver_architecture is (
        ReceiverArchitecture
        .SATURATION_TRIGGERED_DRAIN
    )
    assert direct.receiver_activity == 1.0
    assert triggered.receiver_activity is None


def test_mechanism_studies_cannot_make_system_claims():
    for study_id in (
        "material_transport_mechanisms",
        "module_geometry",
    ):
        assert STUDY_CONTRACTS[
            study_id
        ].claim_level is ClaimLevel.MECHANISM_ONLY


def test_conditional_no_erv_break_even_numbers():
    result = ConditionalBreakEven(
        baseline_compressor_kw=1167.33,
        target_compressor_kw=382.44,
        predryer_water_kg_h=4365.92,
        accounted_predryer_power_kw=115.02,
    )

    assert math.isclose(
        result.gross_opportunity_kw,
        784.89,
        rel_tol=0.0,
        abs_tol=1.0e-10,
    )
    assert math.isclose(
        result.gross_break_even_wh_l_approx,
        179.78,
        rel_tol=0.0,
        abs_tol=0.005,
    )
    assert math.isclose(
        result.remaining_budget_kw,
        669.87,
        rel_tol=0.0,
        abs_tol=1.0e-10,
    )
    assert math.isclose(
        result.remaining_budget_wh_l_approx,
        153.43,
        rel_tol=0.0,
        abs_tol=0.005,
    )


def test_selected_o30_case_fails_new_current_gate():
    gates = PrearchitectureGates(
        max_current_density_a_m2=21.0,
        max_active_area_m2=9000.0,
        max_terminal_voltage_v=2.0,
    )

    violations = gates.violations(
        maximum_local_current_density_a_m2=21.224,
        required_active_area_m2=8922.21,
        terminal_voltage_v=0.98,
    )

    assert len(violations) == 1
    assert (
        "maximum_local_current_density_a_m2"
        in violations[0]
    )


def test_exhaust_resource_cannot_be_double_counted():
    allocation = ExhaustAllocation(
        available_exhaust_dry_air_kg_s=10.0,
        erv_allocated_dry_air_kg_s=10.0,
        receiver_dry_air_kg_s=5.0,
    )

    with pytest.raises(
        ValueError,
        match="over-allocate",
    ):
        allocation.validate()


def test_external_receiver_source_can_close_balance():
    allocation = ExhaustAllocation(
        available_exhaust_dry_air_kg_s=10.0,
        erv_allocated_dry_air_kg_s=10.0,
        receiver_dry_air_kg_s=5.0,
        external_receiver_source_kg_s=5.0,
    )

    allocation.validate()
    assert allocation.margin_kg_s == 0.0


def test_power_ledger_distinguishes_missing_from_zero():
    partial = PowerLedger(
        reference_plane="facility_grid",
        components_kw={
            "downstream_hvac": 382.44,
            "eo_grid": 70.69,
            "process_fan": 6.16,
            "receiver_fan": 38.17,
        },
    )

    assert not partial.is_complete
    assert partial.known_total_kw == pytest.approx(
        497.46
    )

    with pytest.raises(
        ValueError,
        match="missing components",
    ):
        partial.total_kw()

    complete = PowerLedger(
        reference_plane="facility_grid",
        components_kw={
            name: 0.0
            for name
            in CANONICAL_POWER_COMPONENTS
        }
        | {
            "downstream_hvac": 382.44,
            "eo_grid": 70.69,
            "process_fan": 6.16,
            "receiver_fan": 38.17,
        },
    )

    assert complete.is_complete
    assert complete.total_kw() == pytest.approx(
        497.46
    )
