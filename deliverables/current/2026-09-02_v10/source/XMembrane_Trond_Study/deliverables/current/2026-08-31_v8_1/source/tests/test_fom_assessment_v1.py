from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "calculate_fom_assessment_v1.py"


def load_script():
    specification = importlib.util.spec_from_file_location("fom_assessment_v1", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_fom_assessment_outputs_and_identities(tmp_path: Path) -> None:
    module = load_script()
    config = module.read_json(ROOT / "config" / "fom_assessment_v1.json")
    module.prepare_output(tmp_path, overwrite=False)
    summary = module.calculate(config, tmp_path)

    device = pd.read_csv(tmp_path / "device_fom.csv")
    system = pd.read_csv(tmp_path / "system_fom.csv")
    register = pd.read_csv(tmp_path / "thirteen_fom_register.csv")
    workshop_bar = pd.read_csv(tmp_path / "workshop_ac_erv_eo_bar.csv")

    assert len(device) == 3
    assert len(system) == 4
    assert len(register) == 26
    assert len(workshop_bar) == 3
    assert register.groupby("architecture_id")["fom_id"].nunique().eq(13).all()
    assert register.loc[register["fom_id"].eq("FOM-13"), "numeric_value"].isna().all()
    assert ((device["known_core_fom_kg_kwh"] * device["known_core_sec_kwh_kg"] - 1.0).abs() < 1e-10).all()
    assert (device["unallocated_sec_budget_kwh_kg"] > 0.0).all()

    post = device.loc[device["architecture_id"].eq("post_erv_o30_common_voltage")].iloc[0]
    direct = device.loc[device["architecture_id"].eq("direct_eo_erv_full")].iloc[0]
    assert abs(post["known_core_fom_kg_kwh"] - 40.86) < 0.02
    assert abs(post["break_even_core_sec_kwh_kg"] - 0.1567008074) < 1e-9
    assert abs(direct["known_core_fom_kg_kwh"] - 76.116) < 0.01
    o30_bar = workshop_bar.loc[workshop_bar["state_id"].eq("O30 target")].iloc[0]
    assert abs(o30_bar["total_power_kw"] - 381.3267194665535) < 1e-9
    assert abs(o30_bar["saving_vs_no_eo_kw"] - 162.41384472123582) < 1e-9
    assert summary["claim_boundary"]["full_system_claim_allowed"] is False

    audit = module.read_json(tmp_path / "audit.json")
    assert audit["all_pass"] is True
    assert all(audit["checks"].values())
