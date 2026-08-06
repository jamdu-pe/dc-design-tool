"""공간/구조 엔진 테스트 (Phase 3)."""
import pytest

from dc_design_tool.engine import space
from dc_design_tool.engine.catalog import get_block, load_blocks
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


def test_white_space_applies_aisle_factor():
    # 랙 10대 × 1.2m2 = 12m2 점유, 통로계수 3.0 → 36m2
    assert space.white_space_m2(10, 1.2, 3.0) == pytest.approx(36.0)


def test_white_space_rejects_nonpositive_aisle_factor():
    with pytest.raises(ValueError):
        space.white_space_m2(10, 1.2, 0.0)


def test_floor_load_is_weight_over_footprint():
    assert space.floor_load_kg_per_m2(1360, 1.2) == pytest.approx(1133.3, abs=0.5)


def test_floor_load_rejects_zero_footprint():
    with pytest.raises(ValueError):
        space.floor_load_kg_per_m2(1360, 0.0)


def test_rack_rows_rounds_up():
    assert space.rack_rows(42, 10) == 5
    assert space.rack_rows(10, 10) == 1


def test_size_space_reports_me_rooms_and_total():
    blocks = load_blocks()
    rack = get_block(blocks, "nvidia_gb200_nvl72")
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    s = space.size_space(42, rack, spec)

    # 화이트스페이스는 랙 점유면적보다 크다
    assert s["white_space_m2"] > s["rack_footprint_m2"]
    # 전기실·기계실·지원공간이 개별 산출된다
    for key in ("electrical_room_m2", "mechanical_room_m2", "support_area_m2"):
        assert s[key] > 0
    # 총 건축면적 = 화이트스페이스 + M/E실 + 지원공간
    assert s["total_building_m2"] == pytest.approx(
        s["white_space_m2"] + s["electrical_room_m2"]
        + s["mechanical_room_m2"] + s["support_area_m2"], abs=0.2)


def test_size_space_flags_floor_load_over_limit():
    """고밀도 랙(Rubin 1800kg/1.4m2)은 일반 슬래브 허용하중을 초과해 경고된다."""
    blocks = load_blocks()
    rack = get_block(blocks, "nvidia_vera_rubin_nvl144")
    spec = Spec(rack_id="nvidia_vera_rubin_nvl144", rack_count=10)
    s = space.size_space(10, rack, spec)

    assert s["floor_load_kg_per_m2"] > s["floor_load_limit_kg_per_m2"]
    assert s["floor_load_ok"] is False


def test_sizing_uses_space_engine():
    """sizing.size()가 공간 엔진 결과(신규 키 포함)를 그대로 싣는다."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    r = size(spec)
    for key in ("rack_footprint_m2", "white_space_m2", "floor_load_kg_per_m2",
                "total_building_m2", "rack_rows", "floor_load_ok"):
        assert key in r.space
