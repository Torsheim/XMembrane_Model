from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import heiq_pre_receiver_model as model  # noqa: E402


class CoupledPreReceiverModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = model.load_config(ROOT / "config" / "default.json")

    def parameter_row(
        self,
        *,
        drag: float = 10.0,
        diffusivity: float = 1.0e-10,
        conductivity: float = 3.0,
        thickness_um: float = 100.0,
        voltage: float = 0.1,
        capacity: float = 41700.0,
        p_d: float = 0.0,
        p_sigma: float = 0.0,
        p_capacity: float = 0.0,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "water_drag": [drag],
                "water_diffusivity_m2_s": [diffusivity],
                "conductivity_s_m": [conductivity],
                "dry_thickness_um": [thickness_um],
                "applied_voltage_v": [voltage],
                "water_capacity_mol_m3_activity": [capacity],
                "diffusivity_activity_exponent": [p_d],
                "conductivity_activity_exponent": [p_sigma],
                "capacity_activity_exponent": [p_capacity],
            }
        )

    def test_constant_property_flux_reproduces_reference(self) -> None:
        activity = 0.8
        hydration = float(model.nafion_lambda(activity))
        temperature_k = 32.0 + 273.15
        parameters = self.parameter_row(
            drag=0.82,
            diffusivity=float(
                model.nafion_diffusivity_m2_s(hydration, temperature_k)
            ),
            conductivity=float(
                model.nafion_conductivity_s_m(hydration, temperature_k)
            ),
            thickness_um=10.0,
            capacity=(
                1980.0
                / 1.1
                * float(model.nafion_dlambda_da(activity))
            ),
        )
        state = model.solve_powerlaw_at_current(
            parameters,
            np.asarray([2000.0]),
            self.config,
            "symmetric_80_80",
        )
        flux = (
            float(state["net_flux_mol_m2_s"][0])
            * model.WATER_MOLAR_MASS_KG_MOL
            * 3600.0
        )
        # Regression value from the earlier nonlinear H-Nafion report.
        self.assertAlmostEqual(flux, 1.0241168, delta=0.003)

    def test_voltage_control_closes_required_voltage(self) -> None:
        parameters = self.parameter_row(voltage=0.25)
        solved = model.solve_powerlaw_voltage_control(
            parameters, self.config, "symmetric_80_80"
        )
        self.assertTrue(bool(solved.loc[0, "voltage_current_solution_ok"]))
        self.assertAlmostEqual(
            float(solved.loc[0, "cell_voltage_signed_v"]), 0.25, places=5
        )
        self.assertGreater(float(solved.loc[0, "current_density_a_m2"]), 0.0)

    def test_ideal_faraday_sec_limit_uses_actual_applied_voltage(self) -> None:
        config = json.loads(json.dumps(self.config))
        config["model"][
            "source_film_coefficient_mol_m2_s_activity"
        ] = 1.0e20
        config["model"][
            "receiver_film_coefficient_mol_m2_s_activity"
        ] = 1.0e20
        parameters = self.parameter_row(
            drag=10.0,
            diffusivity=1.0e-30,
            conductivity=1.0,
            thickness_um=100.0,
            voltage=0.1,
            capacity=1.0,
        )
        transport = model.solve_powerlaw_voltage_control(
            parameters, config, "symmetric_80_80"
        )
        result = model.apply_scenario_gates(transport, config, "O50")
        expected = (
            model.FARADAY_C_MOL
            * 0.1
            / (10.0 * model.WATER_MOLAR_MASS_KG_MOL * 3.6e6)
        )
        self.assertAlmostEqual(
            float(result.loc[0, "eo_grid_sec_kwh_kg"]),
            expected,
            places=7,
        )

    def test_o30_area_scales_with_water_load(self) -> None:
        transport = model.solve_powerlaw_voltage_control(
            self.parameter_row(), self.config, "symmetric_80_80"
        )
        o50 = model.apply_scenario_gates(transport, self.config, "O50")
        o30 = model.apply_scenario_gates(transport, self.config, "O30")
        ratio = float(o30.loc[0, "required_active_area_m2"]) / float(
            o50.loc[0, "required_active_area_m2"]
        )
        expected = (
            self.config["scenarios"]["O30"]["water_load_kg_h"]
            / self.config["scenarios"]["O50"]["water_load_kg_h"]
        )
        self.assertAlmostEqual(ratio, expected, places=12)

    def test_bulk_activity_gradient_changes_flux(self) -> None:
        parameters = self.parameter_row(voltage=0.1)
        dry = model.solve_powerlaw_voltage_control(
            parameters, self.config, "dry_receiver_80_50"
        )
        wet = model.solve_powerlaw_voltage_control(
            parameters, self.config, "wet_receiver_80_95"
        )
        self.assertTrue(bool(dry.loc[0, "voltage_current_solution_ok"]))
        self.assertTrue(bool(wet.loc[0, "voltage_current_solution_ok"]))
        self.assertGreater(
            float(dry.loc[0, "net_flux_mol_m2_s"]),
            float(wet.loc[0, "net_flux_mol_m2_s"]),
        )

    def test_activity_dependent_permeability_gives_nonlinear_profile(self) -> None:
        parameters = self.parameter_row(
            voltage=0.1, p_d=2.0, p_sigma=4.0
        )
        solved = model.solve_powerlaw_voltage_control(
            parameters, self.config, "wet_receiver_80_95"
        )
        self.assertTrue(bool(solved.loc[0, "voltage_current_solution_ok"]))
        profile = model.reconstruct_powerlaw_profile(
            solved.iloc[0], self.config, nodes=101
        )
        midpoint = float(profile.loc[50, "water_activity"])
        linear_midpoint = 0.5 * (
            float(profile.loc[0, "water_activity"])
            + float(profile.loc[100, "water_activity"])
        )
        self.assertGreater(abs(midpoint - linear_midpoint), 1.0e-4)
        self.assertGreater(
            float(profile["conductivity_s_m"].max()),
            float(profile["conductivity_s_m"].min()),
        )

    def test_nafion_bvp_solves_local_profile_and_voltage(self) -> None:
        record, profile = model.solve_nafion_voltage_state(
            source_bulk_activity=0.8,
            receiver_bulk_activity=0.95,
            temperature_c=32.0,
            dry_thickness_um=100.0,
            applied_voltage_v=0.1,
            drag_scale_factor=1.0,
            config=self.config,
            return_profile=True,
        )
        self.assertTrue(record["solver_success"])
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertAlmostEqual(record["cell_voltage_signed_v"], 0.1, delta=2e-4)
        self.assertGreater(
            float(profile["water_activity"].max()),
            float(profile["water_activity"].min()),
        )
        self.assertGreater(
            float(profile["conductivity_s_m"].max()),
            float(profile["conductivity_s_m"].min()),
        )
        self.assertGreater(
            float(profile["water_drag"].max()),
            float(profile["water_drag"].min()),
        )

    def test_nafion_reference_correlations_unchanged(self) -> None:
        activity = 0.8
        hydration = float(model.nafion_lambda(activity))
        conductivity = float(
            model.nafion_conductivity_s_m(hydration, 32.0 + 273.15)
        )
        drag = float(model.nafion_drag_prior(hydration))
        self.assertAlmostEqual(hydration, 7.2198, delta=0.001)
        self.assertAlmostEqual(conductivity, 3.478, delta=0.02)
        self.assertAlmostEqual(drag, 0.8204, delta=0.002)


if __name__ == "__main__":
    unittest.main()
