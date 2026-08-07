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


# ---------- 공냉 장비 (air_cooling) ----------

def test_rack_mounted_air_cooling_is_one_per_rack(blocks):
    """랙 후면 장착형은 랙당 1대다. 용량으로 대수를 줄이거나 늘리지 않는다."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    c, _ = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                rack_count=42, rack_kw=120.0)
    assert c["air_cooling_mounting"] == "rack"
    assert c["air_cooling_qty"] == 42


def test_rack_mounted_air_cooling_ignores_redundancy_grade(blocks):
    """여분 도어를 매달 수 없으므로 이중화 등급에 불변이다."""
    rack = blocks["nvidia_gb200_nvl72"]
    qty = []
    for grade in ("N", "N+2", "2N"):
        c, _ = cooling.size_cooling(5040.0, rack, Spec(
            rack_id="x", rack_count=42, mechanical_redundancy=grade), blocks,
            rack_count=42, rack_kw=120.0)
        qty.append(c["air_cooling_qty"])
    assert qty == [42, 42, 42]


def test_rack_air_load_is_reported(blocks):
    """랙당 공냉 부하 = 랙 부하 x (1 - 액냉비율). GB200 은 120 x 0.15 = 18kW."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    c, _ = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                rack_count=42, rack_kw=120.0)
    assert c["rack_air_kw"] == pytest.approx(18.0, abs=0.1)


def test_air_cooling_defaults_to_rdhx(blocks):
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    c, _ = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                rack_count=42, rack_kw=120.0)
    assert c["selected"]["air_cooling"] == "rdhx_60kw"
    assert c["air_cooling_method"] == "rear_door_hx"


def test_air_cooling_appears_in_bom(blocks):
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    _, bom = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                  rack_count=42, rack_kw=120.0)
    line = next(li for li in bom if li.item == "공냉장비")
    assert line.block_id == "rdhx_60kw"
    assert line.qty == 42
    assert line.note == "랙당 1대"


def test_rack_count_falls_back_to_spec(blocks):
    """엔진을 직접 부를 때는 spec.rack_count 로 폴백한다."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=7)
    c, _ = cooling.size_cooling(840.0, blocks["nvidia_gb200_nvl72"], spec, blocks)
    assert c["air_cooling_qty"] == 7


def test_rack_mounted_without_rack_count_raises(blocks):
    """랙 수량을 알 수 없으면 조용히 0대로 넘기지 않는다."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    with pytest.raises(ValueError, match="랙 수량"):
        cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks)
