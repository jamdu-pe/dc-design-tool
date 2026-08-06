"""냉각 엔진 테스트: 액냉/공냉 분배, 유량, CDU·칠러 사이징."""
import pytest

from dc_design_tool.engine import cooling
from dc_design_tool.engine.catalog import load_blocks
from dc_design_tool.engine.models import Spec


@pytest.fixture(scope="module")
def blocks():
    return load_blocks()


def test_liquid_air_split_uses_rack_liquid_fraction():
    q_liq, q_air = cooling.liquid_air_split(1000.0, 0.85)
    assert q_liq == pytest.approx(850.0)
    assert q_air == pytest.approx(150.0)


def test_full_air_cooled_rack_has_no_liquid_load():
    q_liq, q_air = cooling.liquid_air_split(1000.0, 0.0)
    assert q_liq == 0.0 and q_air == pytest.approx(1000.0)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_invalid_liquid_fraction_raises(bad):
    with pytest.raises(ValueError):
        cooling.liquid_air_split(1000.0, bad)


def test_size_cooling_matches_flow_formula(blocks):
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42, chw_delta_t_k=10)
    c, _ = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks)
    # 액냉 4284kW, ΔT10K → 4284×60/(4.186×10)
    assert c["coolant_flow_lpm"] == pytest.approx(4284 * 60 / (4.186 * 10), rel=0.01)
    assert c["liquid_kw"] > c["air_kw"]


def test_narrower_delta_t_needs_more_flow(blocks):
    rack = blocks["nvidia_gb200_nvl72"]
    wide, _ = cooling.size_cooling(5040.0, rack, Spec(
        rack_id="x", rack_count=42, chw_delta_t_k=20), blocks)
    narrow, _ = cooling.size_cooling(5040.0, rack, Spec(
        rack_id="x", rack_count=42, chw_delta_t_k=5), blocks)
    assert narrow["coolant_flow_lpm"] > wide["coolant_flow_lpm"]


def test_redundancy_grade_changes_cdu_quantity(blocks):
    rack = blocks["nvidia_gb200_nvl72"]
    n = cooling.size_cooling(5040.0, rack, Spec(rack_id="x", rack_count=42,
                                                mechanical_redundancy="N"), blocks)[0]
    n2 = cooling.size_cooling(5040.0, rack, Spec(rack_id="x", rack_count=42,
                                                 mechanical_redundancy="N+2"), blocks)[0]
    two_n = cooling.size_cooling(5040.0, rack, Spec(rack_id="x", rack_count=42,
                                                    mechanical_redundancy="2N"), blocks)[0]
    assert n2["cdu_qty"] == n["cdu_qty"] + 2
    assert two_n["cdu_qty"] == n["cdu_qty"] * 2


def test_size_cooling_emits_traceable_bom(blocks):
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    _, bom = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks)
    items = {li.item for li in bom}
    assert {"CDU", "칠러"} <= items
    assert all(li.block_id in blocks for li in bom)


def test_rt_conversion_is_reported(blocks):
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    c, _ = cooling.size_cooling(3517.0, blocks["nvidia_gb200_nvl72"], spec, blocks)
    assert c["total_rt"] == pytest.approx(1000.0, abs=1.0)


def test_missing_cooling_block_reports_catalog_absence(blocks):
    only_chiller = {k: v for k, v in blocks.items() if v.subtype != "cdu"}
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=1)
    with pytest.raises(KeyError, match="카탈로그 부재"):
        cooling.size_cooling(120.0, blocks["nvidia_gb200_nvl72"], spec, only_chiller)
