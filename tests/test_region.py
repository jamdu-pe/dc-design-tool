"""국가별 규격 팩 테스트: 오버레이 병합 + 지역 검증."""
import pytest

from dc_design_tool.engine import compliance
from dc_design_tool.engine.catalog import (available_regions, load_blocks,
                                           load_region, load_rule)
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


# ---------- 병합 로직 ----------

def test_deep_merge_preserves_keys_not_mentioned_in_override():
    from dc_design_tool.engine.catalog import _deep_merge
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    merged = _deep_merge(base, {"a": {"y": 99}})
    assert merged == {"a": {"x": 1, "y": 99}, "b": 3}


def test_deep_merge_does_not_mutate_base():
    from dc_design_tool.engine.catalog import _deep_merge
    base = {"a": {"x": 1}}
    _deep_merge(base, {"a": {"x": 2}})
    assert base["a"]["x"] == 1


# ---------- 팩 로드 ----------

def test_generic_and_kr_packs_are_available():
    assert {"generic", "KR"} <= set(available_regions())


def test_unknown_region_raises():
    with pytest.raises(KeyError, match="규격 팩"):
        load_region("ZZ")


def test_region_pack_declares_name_and_reference():
    kr = load_region("KR")
    assert kr["name"]
    assert "KEC" in kr["reference"]


# ---------- 오버레이 적용 ----------

def test_kr_pack_overrides_rack_voltage():
    base = load_rule("electrical.yaml")
    kr = load_rule("electrical.yaml", region="KR")
    assert kr["distribution"]["rack_voltage_v"] == 380
    assert base["distribution"]["rack_voltage_v"] != 380


def test_override_keeps_untouched_keys_in_the_same_file():
    base = load_rule("electrical.yaml")
    kr = load_rule("electrical.yaml", region="KR")
    assert kr["autonomy_min_by_tier"] == base["autonomy_min_by_tier"]
    assert kr["distribution"]["busway_standard_a"] == \
        base["distribution"]["busway_standard_a"]


def test_generic_pack_is_identical_to_base_rules():
    for name in ("electrical.yaml", "space.yaml", "redundancy.yaml"):
        assert load_rule(name, region="generic") == load_rule(name)


def test_no_region_argument_keeps_backward_compatible_behaviour():
    assert load_rule("tiers.yaml", region=None) == load_rule("tiers.yaml")


# ---------- 지역 검증 ----------

def _report(**kw):
    base = dict(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0, tier="III",
                electrical_redundancy="N+1", mechanical_redundancy="N+1",
                target_pue=1.6)
    base.update(kw)
    spec = Spec(**base)
    return compliance.check(size(spec), spec)


def _find(report, code):
    return next((f for f in report.findings if f.code == code), None)


def test_region_pack_finding_names_the_applied_pack():
    f = _find(_report(region="KR"), "REGION_PACK")
    assert f is not None and f.severity == "info"
    assert "KEC" in f.message or "KEC" in f.actual


def test_generic_region_reports_no_jurisdiction_pack():
    f = _find(_report(region="generic"), "REGION_PACK")
    assert f is not None
    assert f.severity == "info"


def test_default_thd_assumption_exceeds_kr_limit():
    """기본 THD 가정 10%는 KR 한계(5%)를 초과하므로 경고여야 한다."""
    f = _find(_report(region="KR"), "REGION_THD")
    assert f is not None and f.severity == "warning"


def test_thd_is_not_checked_without_a_jurisdiction_pack():
    f = _find(_report(region="generic"), "REGION_THD")
    assert f is None or f.severity == "info"


def test_nonstandard_incoming_voltage_is_warned_under_kr_pack():
    blocks = load_blocks()
    tx = next(b for b in blocks.values() if b.subtype == "transformer")
    patched = dict(blocks)
    patched[tx.id] = tx.model_copy(update={"interface": tx.interface.model_copy(
        update={"primary_kv": 6.6})})

    spec = Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0, region="KR",
                target_pue=1.6)
    report = compliance.check(size(spec, patched), spec, patched)
    f = _find(report, "REGION_VOLTAGE")
    assert f is not None and f.severity == "warning"
    assert "6.6" in f.actual


def test_standard_incoming_voltage_passes_under_kr_pack():
    assert _find(_report(region="KR"), "REGION_VOLTAGE").severity == "info"


def test_region_findings_cite_the_pack_file():
    for code in ("REGION_PACK", "REGION_VOLTAGE", "REGION_THD"):
        f = _find(_report(region="KR"), code)
        assert f is not None and "regions" in f.rule


# ---------- 회귀 ----------

def test_region_pack_does_not_change_golden_sizing():
    """규격 팩은 전압·검증에만 영향을 준다. 부하·랙수 골든값은 불변."""
    for region in ("generic", "KR"):
        r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0, region=region))
        assert r.rack_count == 42
        assert r.it_power_kw == 5040.0


def test_kr_rack_voltage_raises_rack_current():
    """415V→380V 로 낮아지면 같은 부하에서 랙 전류는 커진다."""
    generic = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=10)).electrical
    kr = size(Spec(rack_id="nvidia_gb200_nvl72", rack_count=10,
                   region="KR")).electrical
    assert kr["rack_current_a"] > generic["rack_current_a"]
