"""레고 그래프 솔버 테스트: 칩 → 노드 → 랙 롤업."""
import pytest

from dc_design_tool.engine import compose
from dc_design_tool.engine.catalog import load_blocks
from dc_design_tool.engine.models import Block, Component, Interface


@pytest.fixture(scope="module")
def blocks():
    return load_blocks()


# ---------- 카탈로그 구조 ----------

def test_chip_and_node_catalogs_are_loaded(blocks):
    assert any(b.type == "chip" for b in blocks.values())
    assert any(b.type == "node" for b in blocks.values())


def test_gb200_rack_declares_its_composition(blocks):
    rack = blocks["nvidia_gb200_nvl72"]
    assert rack.composed_of, "GB200 랙에 composed_of 정의 없음"
    assert {c.id for c in rack.composed_of} <= set(blocks)


# ---------- 롤업 ----------

def test_node_power_rolls_up_from_chips(blocks):
    """컴퓨트 트레이 = 칩 × 개수 + 트레이 오버헤드."""
    tray = blocks["nvidia_gb200_compute_tray"]
    chip = blocks[tray.composed_of[0].id]
    expected = (chip.interface.power_kw_typical * tray.composed_of[0].count
                + tray.interface.overhead_kw)
    assert compose.composed_power_kw("nvidia_gb200_compute_tray", blocks) == \
        pytest.approx(expected)


def test_rack_power_rolls_up_through_two_levels(blocks):
    """랙 = 컴퓨트 트레이 + NVLink 스위치 트레이 + 오버헤드 = 선언값 120kW."""
    assert compose.composed_power_kw("nvidia_gb200_nvl72", blocks) == \
        pytest.approx(120.0, abs=0.1)


def test_accelerator_count_rolls_up_to_72(blocks):
    assert compose.composed_accel_count("nvidia_gb200_nvl72", blocks) == 72


def test_switch_tray_contributes_power_but_no_accelerators(blocks):
    assert compose.composed_power_kw("nvidia_nvlink_switch_tray", blocks) > 0
    assert compose.composed_accel_count("nvidia_nvlink_switch_tray", blocks) == 0


def test_leaf_block_without_composition_returns_declared_value(blocks):
    """구성이 없는 블록(칩)은 선언된 인터페이스 값을 그대로 돌려준다."""
    chip = blocks["nvidia_b200"]
    assert compose.composed_power_kw("nvidia_b200", blocks) == \
        pytest.approx(chip.interface.power_kw_typical)


# ---------- 일관성 검증 ----------

def test_consistency_check_passes_for_gb200(blocks):
    c = compose.check_consistency("nvidia_gb200_nvl72", blocks)
    assert c["has_composition"] is True
    assert c["ok"] is True
    assert abs(c["delta_pct"]) < 5.0


def test_consistency_check_detects_mismatch(blocks):
    """구성 합이 선언값과 크게 다르면 불일치로 보고한다."""
    tweaked = dict(blocks)
    rack = tweaked["nvidia_gb200_nvl72"]
    tweaked["nvidia_gb200_nvl72"] = rack.model_copy(
        update={"interface": rack.interface.model_copy(
            update={"power_kw_typical": 200.0})})
    c = compose.check_consistency("nvidia_gb200_nvl72", tweaked)
    assert c["ok"] is False
    assert c["declared_kw"] == 200.0


def test_block_without_composition_is_reported_as_such(blocks):
    c = compose.check_consistency("nvidia_vera_rubin_nvl144", blocks)
    assert c["has_composition"] is False
    assert c["ok"] is True   # 구성 미정의는 불일치가 아니다


# ---------- 그래프 조회 ----------

def test_composition_tree_lists_levels(blocks):
    tree = compose.composition_tree("nvidia_gb200_nvl72", blocks)
    depths = {d for d, _, _ in tree}
    assert depths == {0, 1, 2}          # 랙 → 트레이 → 칩
    ids = [b.id for _, b, _ in tree]
    assert ids[0] == "nvidia_gb200_nvl72"
    assert "nvidia_b200" in ids


# ---------- 오류 처리 ----------

def test_missing_child_block_reports_catalog_absence(blocks):
    broken = dict(blocks)
    broken["ghost_rack"] = Block(
        id="ghost_rack", type="rack", vendor="X", model="Ghost",
        interface=Interface(), source_url="test",
        composed_of=[Component(id="does_not_exist", count=1)])
    with pytest.raises(KeyError, match="카탈로그 부재"):
        compose.composed_power_kw("ghost_rack", broken)


def test_cycle_in_composition_raises():
    a = Block(id="a", type="node", vendor="X", model="A", interface=Interface(),
              source_url="t", composed_of=[Component(id="b", count=1)])
    b = Block(id="b", type="node", vendor="X", model="B", interface=Interface(),
              source_url="t", composed_of=[Component(id="a", count=1)])
    with pytest.raises(ValueError, match="순환"):
        compose.composed_power_kw("a", {"a": a, "b": b})


def test_zero_or_negative_count_rejected():
    bad = Block(id="bad", type="node", vendor="X", model="Bad", interface=Interface(),
                source_url="t", composed_of=[Component(id="x", count=0)])
    x = Block(id="x", type="chip", vendor="X", model="X",
              interface=Interface(power_kw_typical=1.0), source_url="t")
    with pytest.raises(ValueError):
        compose.composed_power_kw("bad", {"bad": bad, "x": x})
