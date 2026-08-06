"""설계 계수가 코드가 아니라 rules/*.yaml 에서 오는지 검증한다 (CLAUDE.md 절대규칙 6).

두 가지를 본다.
  1. 기본값이 이관 전 하드코딩 값과 같다 → 수치가 바뀌지 않았다.
  2. 규칙을 바꾸면 결과가 따라 바뀐다 → 코드에 박혀 있지 않다.
"""
import copy

import pytest

from dc_design_tool.engine import catalog
from dc_design_tool.engine.catalog import load_rule
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


def _spec(**kw):
    base = dict(project="factors", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    base.update(kw)
    return Spec(**base)


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@pytest.fixture
def override_rules(monkeypatch):
    """지정한 규칙 파일에 값을 덮어쓴 상태로 사이징한다.

    엔진 모듈은 `from .catalog import load_rule` 로 이름을 바인딩하므로
    모듈별 바인딩을 갈아끼운다.
    """
    def apply(**by_file):
        def fake(name, region=None):
            data = load_rule(name, region)
            stem = name.rsplit(".", 1)[0]
            return _merge(data, by_file[stem]) if stem in by_file else data

        for module in ("sizing", "power", "cooling", "network", "space"):
            target = f"dc_design_tool.engine.{module}.load_rule"
            try:
                monkeypatch.setattr(target, fake)
            except AttributeError:
                pass          # 그 모듈이 load_rule 을 쓰지 않으면 건너뛴다
    return apply


# ---------- 규칙 파일에 항목이 있는가 ----------

def test_cooling_rule_file_exists_with_power_ratio():
    assert "cooling_power_ratio" in load_rule("cooling.yaml")


def test_electrical_rule_file_carries_the_moved_factors():
    el = load_rule("electrical.yaml")
    assert "power_factor" in el["distribution"]
    assert "house_load_ratio" in el["demand"]
    assert "distribution_loss_ratio" in el["demand"]
    assert "start_margin" in el["generator"]


# ---------- 기본값이 이관 전과 같은가(수치 무변화) ----------

def test_default_values_match_the_previously_hardcoded_ones():
    el = load_rule("electrical.yaml")
    assert load_rule("cooling.yaml")["cooling_power_ratio"] == 0.35
    assert el["distribution"]["power_factor"] == 0.95
    assert el["demand"]["house_load_ratio"] == 0.10
    assert el["demand"]["distribution_loss_ratio"] == 0.08
    assert el["generator"]["start_margin"] == 0.15


def test_house_load_matches_the_rule():
    r = size(_spec())
    ratio = load_rule("electrical.yaml")["demand"]["house_load_ratio"]
    assert r.electrical["house_kw"] == pytest.approx(r.it_power_kw * ratio, rel=1e-3)


# ---------- 규칙을 바꾸면 결과가 바뀌는가(하드코딩 아님) ----------

def test_cooling_power_ratio_drives_facility_load_and_pue(override_rules):
    base = size(_spec())
    override_rules(cooling={"cooling_power_ratio": 0.70})
    hi = size(_spec())
    assert hi.electrical["facility_kw"] > base.electrical["facility_kw"]
    assert hi.electrical["pue_estimate"] > base.electrical["pue_estimate"]


def test_house_load_ratio_drives_house_kw(override_rules):
    base = size(_spec())
    override_rules(electrical={"demand": {"house_load_ratio": 0.20}})
    hi = size(_spec())
    assert hi.electrical["house_kw"] == pytest.approx(base.electrical["house_kw"] * 2,
                                                      rel=1e-3)


def test_distribution_loss_ratio_drives_pue(override_rules):
    base = size(_spec())
    override_rules(electrical={"demand": {"distribution_loss_ratio": 0.20}})
    hi = size(_spec())
    assert hi.electrical["pue_estimate"] > base.electrical["pue_estimate"]


def test_power_factor_drives_currents_and_ups_sizing(override_rules):
    base = size(_spec())
    override_rules(electrical={"distribution": {"power_factor": 0.80}})
    low_pf = size(_spec())
    # 역률이 낮으면 같은 유효전력에 더 큰 전류·용량이 필요하다
    assert low_pf.electrical["mv_current_a"] > base.electrical["mv_current_a"]
    assert low_pf.electrical["ups_need_kva"] > base.electrical["ups_need_kva"]


def test_generator_start_margin_drives_generator_sizing(override_rules):
    base = size(_spec())
    override_rules(electrical={"generator": {"start_margin": 0.50}})
    hi = size(_spec())
    assert hi.electrical["generator_need_kw"] > base.electrical["generator_need_kw"]


# ---------- 지역 규격 팩으로도 바꿀 수 있는가 ----------

def test_moved_factors_are_reachable_by_region_overrides():
    """rules/ 로 옮겼으므로 지역 팩(overrides)에서도 교체할 수 있어야 한다."""
    merged = catalog._deep_merge(
        load_rule("electrical.yaml"),
        {"distribution": {"power_factor": 0.90}})
    assert merged["distribution"]["power_factor"] == 0.90
    assert merged["demand"]["house_load_ratio"] == 0.10      # 나머지는 보존


# ---------- 코드에 상수가 남아 있지 않은가 ----------

def test_cooling_power_ratio_constant_is_gone_from_sizing():
    from dc_design_tool.engine import sizing
    assert not hasattr(sizing, "COOLING_POWER_RATIO"), \
        "설계 계수는 rules/cooling.yaml 에만 있어야 한다"
