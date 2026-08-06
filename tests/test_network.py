"""통신(ICT) 엔진 테스트 (Phase 4): 포트→leaf/spine→트랜시버·케이블 BOM."""
import pytest

from dc_design_tool.engine import network
from dc_design_tool.engine.catalog import get_block, load_blocks
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


def test_scaleout_ports_scale_with_rack_count():
    assert network.scaleout_port_count(42, 72) == 3024


def test_downlinks_split_by_oversubscription():
    """비차단(1:1)이면 포트의 절반이 다운링크, 3:1이면 3/4이 다운링크."""
    assert network.downlinks_per_leaf(64, 1.0) == 32
    assert network.downlinks_per_leaf(64, 3.0) == 48


def test_downlinks_rejects_nonpositive_oversubscription():
    with pytest.raises(ValueError):
        network.downlinks_per_leaf(64, 0.0)


def test_leaf_qty_covers_all_host_ports():
    """leaf 대수 × 다운링크 ≥ 총 호스트 포트."""
    leaf = network.leaf_count(3024, 64, 1.0)
    assert leaf * network.downlinks_per_leaf(64, 1.0) >= 3024
    assert leaf == 95


def test_oversubscription_reduces_switch_count():
    """오버섭스크립션을 높이면 leaf·spine 대수가 줄어든다."""
    nb = network.leaf_count(3024, 64, 1.0)
    over = network.leaf_count(3024, 64, 3.0)
    assert over < nb
    assert network.spine_count(3024, 64, 3.0) < network.spine_count(3024, 64, 1.0)


def test_nonblocking_fabric_uplinks_match_downlinks():
    """비차단이면 업링크 총수 = 호스트 포트 총수."""
    assert network.uplink_count(3024, 1.0) == 3024
    assert network.uplink_count(3024, 3.0) == 1008


def test_transceivers_count_both_ends_plus_spare():
    """트랜시버 = (호스트링크 + 패브릭링크) × 양단 2개 × (1+예비율)."""
    assert network.transceiver_count(72, 72, spare_ratio=0.0) == 288
    assert network.transceiver_count(72, 72, spare_ratio=0.05) == 303


def test_size_network_returns_result_and_bom():
    blocks = load_blocks()
    rack = get_block(blocks, "nvidia_gb200_nvl72")
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    result, bom = network.size_network(42, rack, spec, blocks)

    assert result["scaleout_ports"] == 3024
    assert result["port_speed_gbps"] == 800
    assert result["leaf_qty"] > 0 and result["spine_qty"] > 0
    assert result["fabric_link_qty"] == result["scaleout_ports"]  # 비차단 기본값
    assert result["cable_qty"] > 0
    items = {li.item for li in bom}
    assert {"Leaf 스위치", "Spine 스위치", "트랜시버", "광케이블"} <= items


def test_transceiver_bom_uses_catalog_model_not_invented():
    """카탈로그의 트랜시버 블록 모델명을 사용한다(임의 생성 금지)."""
    blocks = load_blocks()
    rack = get_block(blocks, "nvidia_gb200_nvl72")
    _, bom = network.size_network(10, rack, Spec(rack_id="nvidia_gb200_nvl72",
                                                 rack_count=10), blocks)
    xcvr = next(li for li in bom if li.item == "트랜시버")
    assert xcvr.model == blocks["transceiver_800g_osfp"].model


def test_sizing_uses_network_engine():
    r = size(Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    for key in ("scaleout_ports", "leaf_qty", "spine_qty", "transceiver_qty",
                "fabric_link_qty", "cable_qty", "oversubscription"):
        assert key in r.network
