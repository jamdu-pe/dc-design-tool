"""IT 부하 엔진 테스트: 칩/노드/랙 → 총 IT부하."""
import pytest

from dc_design_tool.engine import it_load
from dc_design_tool.engine.catalog import load_blocks
from dc_design_tool.engine.models import Spec


@pytest.fixture(scope="module")
def blocks():
    return load_blocks()


def test_rack_count_from_target_it_power_rounds_up(blocks):
    assert it_load.rack_count_for(Spec(rack_id="x", it_power_mw=5.0), 120.0) == 42


def test_rack_count_from_explicit_count_wins(blocks):
    spec = Spec(rack_id="x", rack_count=7, it_power_mw=5.0)
    assert it_load.rack_count_for(spec, 120.0) == 7


def test_missing_target_raises(blocks):
    with pytest.raises(ValueError, match="it_power_mw"):
        it_load.rack_count_for(Spec(rack_id="x"), 120.0)


def test_zero_rack_power_raises(blocks):
    with pytest.raises(ValueError):
        it_load.rack_count_for(Spec(rack_id="x", it_power_mw=5.0), 0.0)


def test_declared_rack_rating_is_authoritative(blocks):
    """벤더 선언 정격이 있으면 그것을 쓴다(구성 합은 교차검증용)."""
    assert it_load.rack_power_kw(blocks["nvidia_gb200_nvl72"], blocks) == 120.0


def test_composed_value_used_when_rating_absent(blocks):
    """정격 미선언 랙은 구성 합으로 전력을 산출한다."""
    rack = blocks["nvidia_gb200_nvl72"]
    stripped = rack.model_copy(update={"interface": rack.interface.model_copy(
        update={"power_kw_typical": None})})
    assert it_load.rack_power_kw(stripped, blocks) == pytest.approx(120.0, abs=0.1)


def test_size_it_load_returns_totals_and_accelerators(blocks):
    r = it_load.size_it_load(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0), blocks)
    assert r["rack_count"] == 42
    assert r["rack_kw"] == 120.0
    assert r["it_power_kw"] == 5040.0
    assert r["accel_total"] == 42 * 72
    assert r["power_source"] == "declared"


def test_composition_mismatch_is_warned(blocks):
    """선언 정격과 구성 합이 어긋나면 경고를 남긴다."""
    tweaked = dict(blocks)
    rack = tweaked["nvidia_gb200_nvl72"]
    tweaked["nvidia_gb200_nvl72"] = rack.model_copy(
        update={"interface": rack.interface.model_copy(
            update={"power_kw_typical": 200.0})})
    r = it_load.size_it_load(Spec(rack_id="nvidia_gb200_nvl72", rack_count=1), tweaked)
    assert any("구성" in w for w in r["warnings"])


def test_consistent_rack_produces_no_warning(blocks):
    r = it_load.size_it_load(Spec(rack_id="nvidia_gb200_nvl72", rack_count=1), blocks)
    assert r["warnings"] == []


def test_rack_without_composition_is_not_warned(blocks):
    r = it_load.size_it_load(Spec(rack_id="nvidia_vera_rubin_nvl144", rack_count=1), blocks)
    assert r["warnings"] == []
