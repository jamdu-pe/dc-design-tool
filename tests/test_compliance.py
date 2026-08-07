"""규격검증 엔진 테스트 (Phase 4): Tier·ASHRAE·PUE·구조 대조."""
import pytest

from dc_design_tool.engine import compliance
from dc_design_tool.engine.catalog import list_candidates, load_blocks
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


def _check(**kw):
    base = dict(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0, tier="III",
                electrical_redundancy="N+1", mechanical_redundancy="N+1")
    base.update(kw)
    spec = Spec(**base)
    return compliance.check(size(spec), spec)


def _codes(report, severity=None):
    return {f.code for f in report.findings
            if severity is None or f.severity == severity}


# ---------- 이중화 등급 서열(데이터 기반) ----------

def test_redundancy_rank_orders_grades():
    assert compliance.redundancy_rank("N") < compliance.redundancy_rank("N+1")
    assert compliance.redundancy_rank("N+1") < compliance.redundancy_rank("N+2")
    assert compliance.redundancy_rank("N+2") < compliance.redundancy_rank("2N")


def test_redundancy_rank_rejects_unknown_grade():
    with pytest.raises(KeyError):
        compliance.redundancy_rank("N+9")


# ---------- Tier 대조 ----------

def test_tier3_with_n_plus_1_has_no_tier_violation():
    report = _check(tier="III")
    assert "TIER_ELECTRICAL" not in _codes(report, "violation")
    assert "TIER_MECHANICAL" not in _codes(report, "violation")


def test_tier4_with_single_path_electrical_is_violation():
    """Tier IV는 전기 2N이 최소 요건 — N+1이면 위반."""
    report = _check(tier="IV", electrical_redundancy="N+1")
    assert "TIER_ELECTRICAL" in _codes(report, "violation")
    assert not report.ok


def test_tier4_with_2n_and_n_plus_2_passes_tier_checks():
    report = _check(tier="IV", electrical_redundancy="2N", mechanical_redundancy="N+2")
    assert "TIER_ELECTRICAL" not in _codes(report, "violation")
    assert "TIER_MECHANICAL" not in _codes(report, "violation")


def test_unknown_tier_raises():
    with pytest.raises(KeyError):
        _check(tier="VII")


# ---------- ASHRAE ----------

def test_liquid_loop_is_classified_into_ashrae_water_class():
    """GB200 공급수온 32C → W32 등급으로 분류된다."""
    report = _check()
    finding = next(f for f in report.findings if f.code == "ASHRAE_WATER_CLASS")
    assert finding.actual.startswith("32")
    assert "W32" in finding.required or "W32" in finding.message


def test_free_cooling_infeasible_at_high_ambient_is_flagged():
    """외기 40C + 접근온도로는 32C 공급수를 만들 수 없다 → 경고."""
    report = _check(ambient_design_c=40)
    assert "FREE_COOLING" in _codes(report, "warning")


def test_free_cooling_feasible_at_low_ambient_is_not_warned():
    report = _check(ambient_design_c=15)
    assert "FREE_COOLING" not in _codes(report, "warning")


# ---------- 성능·구조·카탈로그 ----------

def test_pue_above_target_is_flagged():
    report = _check(target_pue=1.05)
    assert "PUE_TARGET" in _codes(report, "warning")


def test_pue_within_target_is_not_flagged():
    report = _check(target_pue=1.60)
    assert "PUE_TARGET" not in _codes(report, "warning")


def test_floor_load_over_limit_is_violation():
    report = _check(rack_id="nvidia_vera_rubin_nvl144")
    assert "FLOOR_LOAD" in _codes(report, "violation")


def test_projected_catalog_confidence_is_warned():
    """미출시(projected) 랙은 '추정' 워터마크 경고를 남긴다."""
    report = _check(rack_id="nvidia_vera_rubin_nvl144")
    assert "CATALOG_PROJECTED" in _codes(report, "warning")


def test_vendor_confidence_rack_has_no_projected_warning():
    report = _check(rack_id="nvidia_gb200_nvl72")
    assert "CATALOG_PROJECTED" not in _codes(report, "warning")


def test_busway_rating_covers_rack_current():
    report = _check()
    assert "BUSWAY_RATING" not in _codes(report, "violation")


# ---------- 리포트 형식 ----------

def test_report_summary_counts_by_severity():
    report = _check(tier="IV", electrical_redundancy="N")
    s = report.summary()
    assert s["violation"] >= 1
    assert set(s) == {"violation", "warning", "info"}


def test_every_finding_cites_a_rule_source():
    """모든 판정은 rules/*.yaml 근거를 명시해야 한다."""
    report = _check()
    assert report.findings
    assert all(f.rule for f in report.findings)


def test_sizing_result_carries_compliance_report():
    r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    assert r.compliance is not None
    assert r.compliance.tier == "III"


# ---------- 공냉 판정 ----------

def _result_codes(result) -> set[str]:
    return {f.code for f in result.compliance.findings}


def _result_finding(result, code):
    return next(f for f in result.compliance.findings if f.code == code)


def test_rack_mounted_air_cooling_gets_capacity_finding_not_redundancy():
    """랙 장착형은 이중화 실효성 대상이 아니다 — 랙당 용량만 본다."""
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    codes = _result_codes(r)
    assert "AIR_COOLING_RACK_CAPACITY" in codes
    assert "REDUNDANCY_EFFECTIVE_AIR_COOLING" not in codes


def test_rack_air_load_within_unit_capacity_passes():
    """GB200 은 랙당 18kW 로 60kW 도어에 들어간다."""
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    assert _result_finding(r, "AIR_COOLING_RACK_CAPACITY").severity == "info"


def test_rack_air_load_exceeding_unit_capacity_is_violation():
    """단위용량 미달이면 대수로 보완할 수 없으므로 위반이다."""
    blocks = load_blocks()
    shrunk = dict(blocks)
    door = blocks["rdhx_60kw"]
    shrunk["rdhx_60kw"] = door.model_copy(update={
        "interface": door.interface.model_copy(update={"capacity_kw": 5.0})})
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0),
             blocks=shrunk)
    f = _result_finding(r, "AIR_COOLING_RACK_CAPACITY")
    assert f.severity == "violation"
    assert f.domain == "기계"


def test_room_mounted_air_cooling_gets_redundancy_finding():
    """실 장착형은 UPS·CDU 와 나란히 단일고장 후 잔여용량 검사를 받는다."""
    blocks = load_blocks()
    room = next(b for b in list_candidates("cooling", "air_cooling", blocks)
                if b.interface.mounting == "room")
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0),
             selections={"air_cooling": room.id})
    codes = _result_codes(r)
    assert "REDUNDANCY_EFFECTIVE_AIR_COOLING" in codes
    assert "AIR_COOLING_RACK_CAPACITY" not in codes
