"""장비 교체(selections) 테스트.

역할(subtype)별 후보 조회와, 특정 블록을 지정했을 때 수량·용량이 기존 engine
계산식으로 재산정되는지 확인한다. 기본 실행(selections 미지정)은 리팩터 전과
동일해야 한다(회귀).
"""
import pytest

from dc_design_tool.engine import calc
from dc_design_tool.engine.catalog import (list_candidates, load_blocks,
                                           load_rule, resolve)
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import SELECTABLE_ROLES, size


def _spec(**kw):
    base = dict(project="sel", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    base.update(kw)
    return Spec(**base)


# ---------- list_candidates ----------

def test_list_candidates_returns_only_matching_role():
    ups = list_candidates("electrical", "ups")
    assert len(ups) >= 3
    assert all(b.type == "electrical" and b.subtype == "ups" for b in ups)


def test_list_candidates_first_is_current_default():
    """[0]이 곧 기본값이다. 이 순서가 바뀌면 모든 설계 결과가 바뀐다."""
    assert list_candidates("electrical", "ups")[0].id == "ups_1250kva"
    assert list_candidates("cooling", "cdu")[0].id == "cdu_liquid_1300kw"
    assert list_candidates("network", "leaf")[0].id == "leaf_switch_64x800g"


def test_list_candidates_unknown_role_returns_empty_not_error():
    assert list_candidates("electrical", "nope") == []


def test_list_candidates_accepts_injected_blocks():
    blocks = load_blocks()
    assert list_candidates("cooling", "chiller", blocks) == \
        list_candidates("cooling", "chiller")


# ---------- resolve ----------

def test_resolve_without_selection_returns_first_candidate():
    blocks = load_blocks()
    assert resolve("electrical", "ups", blocks).id == "ups_1250kva"


def test_resolve_uses_selected_block():
    blocks = load_blocks()
    picked = resolve("electrical", "ups", blocks,
                     {"ups": "ups_vertiv_exl_s1_800kva"})
    assert picked.id == "ups_vertiv_exl_s1_800kva"


def test_resolve_ignores_selections_for_other_roles():
    blocks = load_blocks()
    assert resolve("electrical", "ups", blocks, {"cdu": "cdu_coolit_chx1000"}).id \
        == "ups_1250kva"


def test_resolve_rejects_unknown_block_id_and_lists_candidates():
    blocks = load_blocks()
    with pytest.raises(KeyError, match="ups_1250kva"):
        resolve("electrical", "ups", blocks, {"ups": "ups_does_not_exist"})


def test_resolve_rejects_block_of_wrong_role():
    """UPS 자리에 CDU를 넣는 오입력이 조용히 통과하면 안 된다."""
    blocks = load_blocks()
    with pytest.raises(KeyError, match="ups"):
        resolve("electrical", "ups", blocks, {"ups": "cdu_coolit_chx1000"})


def test_resolve_missing_role_keeps_catalog_absent_message():
    with pytest.raises(KeyError, match="카탈로그 부재"):
        resolve("electrical", "nonexistent_role", load_blocks())


# ---------- size(): 기본 경로 회귀 ----------

def test_default_selection_unchanged():
    r = size(_spec())
    assert r.electrical["ups_qty"] == 7
    assert r.selections["ups"] == "ups_1250kva"
    assert r.selections["cdu"] == "cdu_liquid_1300kw"


# ---------- size(): 교체가 모델과 수량을 모두 바꾸는가 ----------

def test_smaller_ups_changes_model_and_increases_quantity():
    base = size(_spec())
    swapped = size(_spec(), selections={"ups": "ups_schneider_galaxy_vx_500kva"})

    assert swapped.selections["ups"] == "ups_schneider_galaxy_vx_500kva"
    assert swapped.electrical["ups_unit_kva"] == 500
    assert swapped.electrical["ups_qty"] > base.electrical["ups_qty"]

    ups_bom = next(li for li in swapped.bom if li.item == "UPS")
    assert ups_bom.block_id == "ups_schneider_galaxy_vx_500kva"
    assert ups_bom.model != next(li for li in base.bom if li.item == "UPS").model


def test_swapped_ups_quantity_comes_from_engine_formula():
    """교체해도 수량은 calc.redundant_qty 결과여야 한다(직접 계산 금지)."""
    r = size(_spec(), selections={"ups": "ups_vertiv_exl_s1_800kva"})
    rule = load_rule("redundancy.yaml")["N+1"]
    assert r.electrical["ups_qty"] == calc.redundant_qty(
        r.electrical["ups_need_kva"], 800, rule)


def test_smaller_cdu_increases_cdu_quantity():
    base = size(_spec())
    swapped = size(_spec(), selections={"cdu": "cdu_coolit_chx1000"})
    assert swapped.cooling["cdu_unit_kw"] == 1000
    assert swapped.cooling["cdu_qty"] > base.cooling["cdu_qty"]


def test_higher_port_count_leaf_reduces_leaf_quantity():
    base = size(_spec())
    swapped = size(_spec(), selections={"leaf": "leaf_arista_7060x6_128x400g"})
    assert swapped.network["leaf_qty"] < base.network["leaf_qty"]


def test_generator_and_transformer_are_swappable():
    r = size(_spec(), selections={"generator": "genset_cat_c175_16_3000kw",
                                  "transformer": "tx_ls_cast_resin_1500kva"})
    assert r.electrical["generator_unit_kw"] == 3000
    assert r.electrical["transformer_unit_kva"] == 1500


def test_invalid_selection_raises_with_candidate_list():
    with pytest.raises(KeyError, match="cdu_liquid_1300kw"):
        size(_spec(), selections={"cdu": "no_such_cdu"})


# ---------- SizingResult: UI 드롭다운용 데이터 ----------

def test_result_reports_selection_for_every_role():
    r = size(_spec())
    assert set(r.selections) == set(SELECTABLE_ROLES)


def test_result_reports_candidates_for_every_role():
    r = size(_spec())
    assert set(r.candidates) == set(SELECTABLE_ROLES)
    assert len(r.candidates["ups"]) >= 3


def test_candidate_entries_carry_dropdown_fields():
    r = size(_spec())
    entry = r.candidates["ups"][0]
    assert set(entry) == {"id", "vendor", "model", "capacity",
                          "confidence", "is_default", "is_selected"}
    assert entry["is_default"] is True


def test_candidate_flags_follow_the_selection():
    r = size(_spec(), selections={"ups": "ups_vertiv_exl_s1_800kva"})
    by_id = {c["id"]: c for c in r.candidates["ups"]}
    assert by_id["ups_1250kva"]["is_default"] is True
    assert by_id["ups_1250kva"]["is_selected"] is False
    assert by_id["ups_vertiv_exl_s1_800kva"]["is_selected"] is True


def test_candidates_are_json_serializable():
    """MCP·웹 UI 응답에 그대로 실린다."""
    import json
    json.dumps(size(_spec()).candidates, ensure_ascii=False)
