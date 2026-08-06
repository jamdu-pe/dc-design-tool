"""전력 엔진 테스트 (Phase 3): 이중화 규칙·배터리·고조파·수전.

완료조건: "이중화 등급 변경 시 장비 수량이 규칙대로 변동".
"""
import pytest

from dc_design_tool.engine import calc
from dc_design_tool.engine.catalog import load_rule
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


def _elec(redundancy: str = "N+1", tier: str = "III", mw: float = 5.0) -> dict:
    spec = Spec(project="power-test", rack_id="nvidia_gb200_nvl72", it_power_mw=mw,
                tier=tier, electrical_redundancy=redundancy)
    return size(spec).electrical


# ---------- 이중화 규칙 연동 ----------

def test_ups_qty_follows_redundancy_rules():
    """N을 기준으로 N+1은 +1, N+2는 +2, 2N은 2배가 된다."""
    base = _elec("N")["ups_qty"]
    assert _elec("N+1")["ups_qty"] == base + 1
    assert _elec("N+2")["ups_qty"] == base + 2
    assert _elec("2N")["ups_qty"] == base * 2


def test_generator_and_transformer_qty_follow_redundancy():
    n, two_n = _elec("N"), _elec("2N")
    assert two_n["generator_qty"] == n["generator_qty"] * 2
    assert two_n["transformer_qty"] == n["transformer_qty"] * 2


def test_redundancy_does_not_change_required_capacity():
    """이중화는 '설치 대수'만 바꾼다. 필요 용량(kVA)은 동일해야 한다."""
    n, two_n = _elec("N"), _elec("2N")
    assert n["ups_need_kva"] == two_n["ups_need_kva"]
    assert n["transformer_need_kva"] == two_n["transformer_need_kva"]


def test_unknown_redundancy_grade_raises():
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=10,
                electrical_redundancy="N+3")
    with pytest.raises(KeyError):
        size(spec)


# ---------- 배터리 ----------

def test_battery_autonomy_comes_from_tier_rule():
    rule = load_rule("electrical.yaml")["autonomy_min_by_tier"]
    assert _elec(tier="III")["battery_autonomy_min"] == rule["III"]
    assert _elec(tier="IV")["battery_autonomy_min"] == rule["IV"]


def test_battery_energy_matches_formula():
    e = _elec(tier="III")
    bat = load_rule("electrical.yaml")["battery"]
    expected = calc.battery_energy_kwh(5040.0, e["battery_autonomy_min"],
                                       bat["depth_of_discharge"], bat["inverter_eff"])
    assert e["battery_energy_kwh"] == pytest.approx(expected, abs=0.5)


# ---------- 고조파 ----------

def test_transformer_capacity_includes_harmonic_margin():
    """변압기 필요용량은 (부하/PF)에 고조파·설계여유가 곱해진 값이다."""
    e = _elec()
    harm = load_rule("electrical.yaml")["harmonic"]
    margin = load_rule("electrical.yaml")["demand"]["design_margin"]
    plain_kva = e["facility_kw"] / 0.95
    assert e["transformer_need_kva"] == pytest.approx(
        plain_kva * harm["transformer_factor"] * (1 + margin), rel=0.01)


def test_generator_capacity_includes_step_load_margin():
    e = _elec()
    harm = load_rule("electrical.yaml")["harmonic"]
    plain_kw = calc.generator_kw(5040.0, 5040.0 * 0.35)
    assert e["generator_need_kw"] == pytest.approx(
        plain_kw * harm["generator_factor"], rel=0.01)


# ---------- 수전(MV) ----------

def test_mv_current_is_based_on_facility_demand_not_installed_redundancy():
    """지시서 §4: MV = (총부하 × 여유) / (√3 × V × PF).

    2N 이중화로 변압기를 2배 설치해도 수전 전류는 부하 기준이므로 변하지 않는다.
    """
    n, two_n = _elec("N"), _elec("2N")
    margin = load_rule("electrical.yaml")["demand"]["design_margin"]
    expected = calc.line_current_a(n["facility_kw"] * (1 + margin),
                                   n["primary_kv"] * 1000, 0.95)
    assert n["mv_current_a"] == pytest.approx(expected, rel=0.01)
    assert two_n["mv_current_a"] == pytest.approx(n["mv_current_a"], rel=0.01)


# ---------- 랙 급전 ----------

def test_busway_rating_is_standard_size():
    e = _elec()
    standards = load_rule("electrical.yaml")["distribution"]["busway_standard_a"]
    assert e["busway_rating_a"] in standards


def test_busway_is_sized_for_the_whole_row_not_a_single_rack():
    """버스웨이는 열(row) 전체 랙을 급전하므로 열 전류 기준으로 정격을 잡아야 한다."""
    e = _elec()
    racks_per_row = load_rule("space.yaml")["white_space"]["racks_per_row"]
    assert e["busway_row_current_a"] == pytest.approx(
        e["rack_current_a"] * racks_per_row, rel=0.01)
    assert e["busway_rating_a"] >= e["busway_row_current_a"]


def test_busway_qty_matches_row_count_from_space_rules():
    racks_per_row = load_rule("space.yaml")["white_space"]["racks_per_row"]
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42, electrical_redundancy="N+1")
    e = size(spec).electrical
    assert e["busway_qty"] == -(-42 // racks_per_row)          # ceil(42/10) = 5


def test_busway_qty_doubles_for_2n_dual_feed():
    n = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=42,
                  electrical_redundancy="N+1")).electrical
    two_n = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=42,
                      electrical_redundancy="2N")).electrical
    assert two_n["busway_qty"] == n["busway_qty"] * 2


def test_row_current_exceeding_max_standard_is_reported():
    """열 전류가 최대 표준정격을 넘으면 그 사실이 결과에 남아야 한다(조용한 축소 금지)."""
    e = _elec(mw=8.0)  # GB200 기준으로는 표준 내
    standards = load_rule("electrical.yaml")["distribution"]["busway_standard_a"]
    assert e["busway_rating_sufficient"] == (e["busway_rating_a"] >= e["busway_row_current_a"])
    assert e["busway_rating_a"] <= max(standards)


def test_generator_unit_rating_is_reported_separately_from_total_need():
    """발전기 '대당 정격'과 '총 필요용량'은 다른 값이다(다이어그램·문서 오표기 방지)."""
    e = _elec()
    assert e["generator_unit_kw"] < e["generator_need_kw"]
    assert e["generator_unit_kw"] * e["generator_qty"] >= e["generator_need_kw"]


def test_pdu_count_doubles_for_2n_dual_feed():
    """2N은 급전 경로가 2개 — 경로당 PDU 대수는 랙 부하/PDU 용량으로 결정된다."""
    n = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=20,
                  electrical_redundancy="N+1")).electrical
    two_n = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=20,
                      electrical_redundancy="2N")).electrical
    assert n["feeds_per_rack"] == 1 and two_n["feeds_per_rack"] == 2
    assert n["pdu_qty"] == 20 * n["pdu_per_feed"]
    assert two_n["pdu_qty"] == n["pdu_qty"] * 2


def test_bom_contains_all_electrical_domains():
    spec = Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    items = {li.item for li in size(spec).bom if li.domain == "전기"}
    assert {"UPS", "배터리", "발전기", "변압기", "버스웨이", "랙 PDU"} <= items
