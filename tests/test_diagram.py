"""계통도(mermaid) 산출 테스트 (Phase 4)."""
import pathlib

import pytest

from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size
from dc_design_tool.reports import diagram_mermaid as dg


@pytest.fixture(scope="module")
def result():
    return size(Spec(project="diagram-test", rack_id="nvidia_gb200_nvl72",
                     it_power_mw=5.0, electrical_redundancy="2N"))


def test_electrical_single_line_starts_with_flowchart(result):
    src = dg.electrical_single_line(result)
    assert src.splitlines()[0].startswith("flowchart")


def test_electrical_single_line_shows_incoming_to_rack_path(result):
    """수전→변압기→UPS→PDU→랙 경로와 발전기가 모두 표기된다."""
    src = dg.electrical_single_line(result)
    for token in ("수전", "변압기", "UPS", "PDU", "랙", "발전기"):
        assert token in src
    assert "-->" in src


def test_electrical_diagram_carries_engine_quantities(result):
    """다이어그램 수치는 엔진 결과에서 온다(임의 표기 금지)."""
    e = result.electrical
    src = dg.electrical_single_line(result)
    assert f"{e['ups_qty']}" in src
    assert f"{e['primary_kv']}" in src


def test_cooling_loop_shows_liquid_and_air_branches(result):
    src = dg.cooling_loop(result)
    for token in ("CDU", "칠러", "액냉", "공냉"):
        assert token in src
    assert str(result.cooling["cdu_qty"]) in src


def test_network_fabric_shows_leaf_spine(result):
    src = dg.network_fabric(result)
    assert "Leaf" in src and "Spine" in src
    assert str(result.network["spine_qty"]) in src


def test_write_diagrams_creates_markdown_with_three_fenced_blocks(result, tmp_path):
    path = dg.write_diagrams(result, str(tmp_path))
    text = pathlib.Path(path).read_text(encoding="utf-8")
    assert path.endswith(".md")
    assert text.count("```mermaid") == 3
    assert text.count("```") == 6


def test_write_diagrams_includes_disclaimer(result, tmp_path):
    text = pathlib.Path(dg.write_diagrams(result, str(tmp_path))).read_text(encoding="utf-8")
    assert "개념설계" in text


def test_labels_are_quoted_so_parentheses_do_not_break_mermaid(result):
    """괄호가 든 라벨은 따옴표로 감싸야 mermaid 파싱이 깨지지 않는다."""
    for src in (dg.electrical_single_line(result), dg.cooling_loop(result),
                dg.network_fabric(result)):
        for line in src.splitlines():
            if "(" in line and "-->" not in line:
                assert '"' in line, f"라벨 미인용: {line}"


def test_cooling_loop_shows_selected_air_equipment():
    """공냉 노드가 하드코딩 문구가 아니라 실제 선택 장비를 보여준다."""
    from dc_design_tool.engine.models import Spec
    from dc_design_tool.engine.sizing import size
    from dc_design_tool.reports.diagram_mermaid import cooling_loop
    result = size(Spec(project="d", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    src = cooling_loop(result)
    assert "(CRAH/RDHx)" not in src          # 하드코딩 제거 확인
    assert str(result.cooling["air_cooling_qty"]) in src
    assert result.cooling["air_cooling_method"] in src
