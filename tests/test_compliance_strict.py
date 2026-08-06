"""규격 자동검증 강화 테스트: 이중화 실효성·PDU 용량·부속실 면적·정합성·신선도."""
import datetime as dt

import pytest

from dc_design_tool.engine import compliance
from dc_design_tool.engine.catalog import load_blocks
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


def _report(**kw):
    base = dict(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0, tier="III",
                electrical_redundancy="N+1", mechanical_redundancy="N+1",
                target_pue=1.6)
    base.update(kw)
    spec = Spec(**base)
    return compliance.check(size(spec), spec)


def _find(report, code):
    return next((f for f in report.findings if f.code == code), None)


def _codes(report, severity):
    return {f.code for f in report.findings if f.severity == severity}


# ---------- 이중화 실효성 (1대 고장 후 잔여 용량) ----------

def test_n_plus_1_survives_single_unit_failure():
    """N+1은 1대 고장 후에도 필요 용량을 만족해야 한다."""
    r = _report(electrical_redundancy="N+1")
    f = _find(r, "REDUNDANCY_EFFECTIVE_ELECTRICAL")
    assert f is not None and f.severity == "info"


def test_2n_survives_loss_of_an_entire_bus():
    """2N은 한 계통(설치대수의 절반) 전체를 잃어도 필요 용량을 만족해야 한다."""
    r = _report(electrical_redundancy="2N")
    assert _find(r, "REDUNDANCY_EFFECTIVE_ELECTRICAL").severity == "info"


def test_plain_n_has_no_spare_capacity_and_is_warned():
    """N은 여유가 없다 — 단일 고장 시 용량 부족을 경고해야 한다."""
    r = _report(electrical_redundancy="N", mechanical_redundancy="N")
    assert _find(r, "REDUNDANCY_EFFECTIVE_ELECTRICAL").severity == "warning"
    assert _find(r, "REDUNDANCY_EFFECTIVE_MECHANICAL").severity == "warning"


def test_redundancy_effectiveness_reports_surviving_capacity():
    f = _find(_report(electrical_redundancy="N+1"),
              "REDUNDANCY_EFFECTIVE_ELECTRICAL")
    assert "kVA" in f.actual


# ---------- PDU 용량 ----------

def test_pdu_capacity_covers_rack_load():
    """랙당 설치 PDU 용량 합이 랙 부하 이상이어야 한다."""
    f = _find(_report(), "PDU_CAPACITY")
    assert f is not None and f.severity == "info"


def test_pdu_quantity_is_sized_by_capacity_not_a_fixed_count():
    """120kW 랙을 50kW PDU로 급전하려면 랙당 1대로는 불가능하다."""
    e = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=20,
                  electrical_redundancy="N+1")).electrical
    assert e["pdu_per_rack"] >= 3          # ceil(120/50)
    assert e["pdu_qty"] == 20 * e["pdu_per_rack"]


def test_2n_doubles_pdu_because_each_feed_carries_full_load():
    n = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=20,
                  electrical_redundancy="N+1")).electrical
    two_n = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=20,
                      electrical_redundancy="2N")).electrical
    assert two_n["pdu_qty"] == n["pdu_qty"] * 2


# ---------- 부속실 면적 ----------

def test_me_room_area_is_derived_from_installed_equipment():
    """전기실/기계실 면적은 설치 장비 footprint와 이격계수로 산정되어야 한다."""
    r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    s = r.space
    assert s["electrical_equipment_m2"] > 0
    assert s["electrical_room_m2"] >= s["electrical_equipment_m2"]
    assert s["mechanical_room_m2"] >= s["mechanical_equipment_m2"]


def test_outdoor_equipment_excluded_from_indoor_room_area():
    """발전기는 옥외 설치이므로 전기실 면적에 포함되지 않는다."""
    blocks = load_blocks()
    gen = next(b for b in blocks.values() if b.subtype == "generator")
    assert gen.interface.location == "yard"

    r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    gen_area = gen.interface.footprint_m2 * r.electrical["generator_qty"]
    assert r.space["electrical_equipment_m2"] < gen_area


def test_me_room_area_check_passes_when_area_is_equipment_based():
    assert _find(_report(), "ME_ROOM_AREA").severity == "info"


# ---------- 정합성 ----------

def test_port_speed_mismatch_between_rack_and_switch_is_flagged():
    """Rubin 1600G 랙에 800G 스위치를 물리면 정합성 경고가 나야 한다."""
    r = _report(rack_id="nvidia_vera_rubin_nvl144")
    assert "PORT_SPEED_MATCH" in _codes(r, "warning")


def test_matching_port_speed_is_not_flagged():
    assert "PORT_SPEED_MATCH" not in _codes(_report(), "warning")


def test_network_switch_rack_space_is_reported():
    """스위치도 랙을 차지한다 — IT 랙 수에 포함되지 않은 별도 랙 수를 알려야 한다."""
    f = _find(_report(), "NETWORK_RACK_SPACE")
    assert f is not None
    assert int(f.actual.split("랙")[0].strip()) > 0


# ---------- 카탈로그 신선도 ----------

def test_stale_catalog_entries_are_warned():
    r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    spec = Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    report = compliance.check(r, spec, today=dt.date(2031, 1, 1))
    assert "CATALOG_FRESHNESS" in _codes(report, "warning")


def test_fresh_catalog_entries_are_not_warned():
    r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    spec = Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    report = compliance.check(r, spec, today=dt.date(2025, 6, 1))
    assert "CATALOG_FRESHNESS" not in _codes(report, "warning")


# ---------- BOM 추적성 ----------

def test_every_bom_line_traces_back_to_a_catalog_block():
    """BOM 각 줄은 카탈로그 블록 id를 달고 있어야 한다(지어낸 장비 차단)."""
    r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    blocks = load_blocks()
    traced = [li for li in r.bom if li.block_id]
    assert len(traced) == len(r.bom)
    assert all(li.block_id in blocks for li in r.bom)


@pytest.mark.parametrize("code", [
    "REDUNDANCY_EFFECTIVE_ELECTRICAL", "REDUNDANCY_EFFECTIVE_MECHANICAL",
    "PDU_CAPACITY", "ME_ROOM_AREA", "PORT_SPEED_MATCH",
    "NETWORK_RACK_SPACE", "CATALOG_FRESHNESS",
])
def test_new_checks_are_present_and_cite_rules(code):
    f = _find(_report(), code)
    assert f is not None, f"{code} 검증 누락"
    assert f.rule
