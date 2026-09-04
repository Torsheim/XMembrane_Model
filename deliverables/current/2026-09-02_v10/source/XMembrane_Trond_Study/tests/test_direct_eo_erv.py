from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from heiq.wp1.airside.properties import activity_from_t_w
from heiq.wp1.studies.direct_eo_erv import (
    build_direct_eo_endpoints,
    build_passive_baseline,
    build_segments,
    segment_balance_audit,
    states_from_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "direct_eo_erv_study_v1.json"


@pytest.fixture(scope="module")
def config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def states(config):
    return states_from_config(config)


def test_native_psychrometric_and_passive_erv_regression(config, states):
    assert states["outdoor"].w == pytest.approx(0.024273737476945743)
    assert states["exhaust"].w == pytest.approx(0.00726028059345441)
    baseline = build_passive_baseline(config, states, 0.75)
    assert baseline.passive_erv.oa_out.t_c == pytest.approx(23.0)
    assert baseline.passive_erv.oa_out.w == pytest.approx(
        0.013214990502676377
    )
    assert baseline.passive_erv.exhaust_out.t_c == pytest.approx(
        29.155171407470398
    )
    assert baseline.passive_erv.exhaust_out.w == pytest.approx(
        0.018319027567723776
    )
    assert baseline.total_power_kw == pytest.approx(
        543.740590648886, abs=5.0e-4
    )


def _endpoints(config, states, target_w: float):
    mass_flow = float(config["boundary"]["process_outdoor_dry_air_kg_s"])
    return build_direct_eo_endpoints(
        process_in=states["outdoor"],
        exhaust_in=states["exhaust"],
        process_dry_air_kg_s=mass_flow,
        exhaust_dry_air_kg_s=mass_flow,
        process_out_w=target_w,
        sensible_effectiveness=0.75,
    )


def test_active_10g_endpoint_closes_water_and_enthalpy(config, states):
    endpoints = _endpoints(config, states, 0.010)
    assert endpoints.valid
    assert endpoints.water_transfer_kg_h == pytest.approx(4049.819480522128)
    assert endpoints.exhaust_out.w == pytest.approx(0.021534018070400153)
    assert endpoints.exhaust_out.t_c == pytest.approx(29.119984671099683)
    assert endpoints.active_latent_effectiveness == pytest.approx(
        0.8389675052338117
    )
    assert abs(endpoints.water_balance_residual_kg_s) <= 1.0e-12
    assert abs(endpoints.base_enthalpy_balance_residual_kw) <= 1.0e-10


@pytest.mark.parametrize("segment_count", [1, 2, 4, 8])
def test_countercurrent_segments_have_exact_continuity(
    config, states, segment_count
):
    endpoints = _endpoints(config, states, 0.010)
    segments = build_segments(endpoints, segment_count)
    audit = segment_balance_audit(endpoints, segments)
    assert audit["pass"]
    assert audit["process_continuity_error_w"] <= 1.0e-12
    assert audit["receiver_continuity_error_w"] <= 1.0e-12
    assert audit["receiver_segment_balance_error_kg_h"] <= 1.0e-8
    assert segments[0].process_in_w == pytest.approx(endpoints.process_in.w)
    assert segments[0].receiver_out_w == pytest.approx(endpoints.exhaust_out.w)
    assert segments[-1].process_out_w == pytest.approx(endpoints.process_out.w)
    assert segments[-1].receiver_in_w == pytest.approx(endpoints.exhaust_in.w)
    for left, right in zip(segments[:-1], segments[1:]):
        assert left.receiver_in_w == pytest.approx(right.receiver_out_w)


def test_integrated_endpoint_equal_to_passive_erv_outlet_still_has_full_raw_air_duty(
    config, states
):
    target_w = 0.013214990502676377
    endpoints = _endpoints(config, states, target_w)
    assert endpoints.water_transfer_kg_h == pytest.approx(3137.6455535137384)
    assert endpoints.water_transfer_kg_h > 0.0


def test_full_supply_humidity_target_is_countercurrent_pinch(config, states):
    endpoints = _endpoints(config, states, states["supply"].w)
    last = build_segments(endpoints, 4)[-1]
    membrane_t = last.membrane_temperature_c
    process_activity = activity_from_t_w(
        membrane_t, last.process_out_w, endpoints.process_in.pressure_pa
    )
    receiver_activity = activity_from_t_w(
        membrane_t, last.receiver_in_w, endpoints.process_in.pressure_pa
    )
    assert math.isclose(process_activity - receiver_activity, 0.0, abs_tol=1.0e-14)
