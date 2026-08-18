from pathlib import Path

from heiq.wp1.engineering import (
    add_geometry_and_stack,
    channel_pressure_drop_and_fan,
    stack_topology,
)
from heiq.wp1.receiver import (
    MATERIAL_COLUMNS,
    ReceiverBasis,
    integrate_coupled_receiver_case,
    legacy_v12_module,
    legacy_v12_path,
    load_json,
    make_receiver_basis,
    validate_unchanged_solver_sources,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v12_package_api_uses_canonical_source():
    expected = (
        ROOT / "scripts" / "make_wp1_closed_receiver_system_v12.py"
    ).resolve()
    assert legacy_v12_path().resolve() == expected
    assert expected.is_file()


def test_v12_material_columns_are_preserved():
    assert MATERIAL_COLUMNS == [
        "water_drag",
        "water_diffusivity_m2_s",
        "conductivity_s_m",
        "dry_thickness_um",
        "water_capacity_mol_m3_activity",
        "diffusivity_activity_exponent",
        "conductivity_activity_exponent",
        "capacity_activity_exponent",
    ]


def test_receiver_basis_public_dataclass_is_preserved():
    r = ReceiverBasis(
        band_id="test",
        receiver_sizing_target="O30",
        flow_arrangement="counter_current",
        temperature_c=32.0,
        pressure_pa=101325.0,
        inlet_activity=0.4,
        maximum_outlet_activity=0.6,
        inlet_humidity_ratio_kg_kg_da=0.01,
        maximum_outlet_humidity_ratio_kg_kg_da=0.02,
        target_outlet_humidity_ratio_kg_kg_da=0.019,
        minimum_dry_air_mass_flow_kg_s=1.0,
        selected_dry_air_mass_flow_kg_s=1.01,
        selected_actual_volume_flow_m3_s=1.0,
        selected_actual_airflow_cfm=2118.88,
        capacity_multiplier=1.01,
        receiver_geometry_mode="test",
        receiver_total_channel_width_m=10.0,
        receiver_velocity_m_s=2.0,
        receiver_to_process_dry_air_ratio=1.0,
        target_capacity_sufficient=True,
    )
    assert r.band_id == "test"
    assert r.temperature_c == 32.0
    assert r.target_capacity_sufficient is True


def test_receiver_and_engineering_wrappers_are_callable():
    assert callable(make_receiver_basis)
    assert callable(integrate_coupled_receiver_case)
    assert callable(add_geometry_and_stack)
    assert callable(channel_pressure_drop_and_fan)
    assert callable(stack_topology)


def test_v12_load_json_matches_legacy_exactly():
    path = ROOT / "config" / "closed_receiver_system_v12_config.json"
    wrapped = load_json(path)
    legacy = legacy_v12_module().load_json(path)
    assert wrapped == legacy


def test_solver_source_provenance_gate_passes_clean_repo():
    source_dir = (
        ROOT
        / "outputs"
        / "axial_independent_material_sweep_v8"
        / "coarse"
        / "voltage_refinement_v11"
    )
    axial_script = ROOT / "scripts" / "make_wp1_pre_receiver_axial_v3.py"
    v2_root = ROOT / "heiq_pre_receiver_material_analyses"

    result = validate_unchanged_solver_sources(
        source_dir,
        axial_script,
        v2_root,
    )

    assert isinstance(result, dict)
    assert result
