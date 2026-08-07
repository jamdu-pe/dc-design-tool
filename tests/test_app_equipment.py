"""화면에서 장비를 교체하면 결과가 따라 바뀌는지 확인한다.

수치는 전부 engine 이 낸다. 여기서 보는 것은 '선택이 engine 에 전달되고,
그 결과가 화면에 반영되는가'다.
"""
import math
import pathlib

import pytest

pytest.importorskip("streamlit", reason="웹 UI 전용 — pip install -e '.[ui]'")
pytest.importorskip("streamlit_authenticator", reason="로그인 게이트 전용")

from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.auth_fixtures import TEST_PASSWORD, TEST_USER, auth_secrets  # noqa: E402

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")

ROLE_LABELS = ["CDU", "칠러", "공냉장비", "UPS", "배터리", "발전기", "변압기",
               "랙 PDU", "버스웨이", "Leaf 스위치", "Spine 스위치", "트랜시버"]


def _logged_in() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["auth"] = auth_secrets()
    at.run()
    next(t for t in at.text_input if t.label == "이름").set_value(TEST_USER)
    next(t for t in at.text_input if t.label == "비밀번호").set_value(TEST_PASSWORD)
    next(b for b in at.button if b.label == "로그인").click().run()
    return at


def _after_design_run() -> AppTest:
    at = _logged_in()
    next(b for b in at.sidebar.button if b.label == "설계 실행").click().run()
    return at


def _picker(at: AppTest, label: str):
    return next(s for s in at.selectbox if s.label == label)


def _cell(at: AppTest, table_index: int, item: str) -> str:
    """(항목, 값) 2열 표에서 값 하나를 꺼낸다."""
    df = at.dataframe[table_index].value
    return df.loc[df["항목"] == item, "값"].iloc[0]


COOLING_TABLE, ELECTRICAL_TABLE, NETWORK_TABLE = 0, 1, 2


# ---------- 노출 ----------

def test_pickers_are_not_shown_before_a_design_run():
    at = _logged_in()
    labels = {s.label for s in at.selectbox}
    assert not (set(ROLE_LABELS) & labels)


def test_every_selectable_role_gets_a_picker():
    at = _after_design_run()
    assert not at.exception, at.exception
    labels = {s.label for s in at.selectbox}
    assert set(ROLE_LABELS) <= labels


def test_picker_options_carry_vendor_model_and_confidence():
    at = _after_design_run()
    joined = " | ".join(_picker(at, "UPS").options)
    assert "Schneider" in joined or "Vertiv" in joined
    assert "projected" in " | ".join(_picker(at, "칠러").options)


def test_pickers_default_to_the_default_flagged_block():
    at = _after_design_run()
    assert _picker(at, "CDU").value == "cdu_liquid_1300kw"
    assert _picker(at, "UPS").value == "ups_1250kva"


# ---------- 교체가 결과에 반영되는가 ----------

def test_swapping_the_cdu_updates_the_cooling_table():
    at = _after_design_run()
    before_qty = _cell(at, COOLING_TABLE, "CDU 수량")

    _picker(at, "CDU").set_value("cdu_coolit_chx1000").run()
    assert not at.exception, at.exception

    assert _cell(at, COOLING_TABLE, "CDU 단위용량 (kW)") == "1000.0"
    assert _cell(at, COOLING_TABLE, "CDU 수량") != before_qty


def test_swapping_the_ups_updates_quantity_and_bom():
    at = _after_design_run()
    before_qty = int(_cell(at, ELECTRICAL_TABLE, "UPS 수량"))

    _picker(at, "UPS").set_value("ups_schneider_galaxy_vx_500kva").run()
    assert not at.exception, at.exception

    assert _cell(at, ELECTRICAL_TABLE, "UPS 단위용량 (kVA)") == "500"
    assert int(_cell(at, ELECTRICAL_TABLE, "UPS 수량")) > before_qty

    bom = at.dataframe[-1].value
    assert "Galaxy VX" in " ".join(bom.loc[bom["품목"] == "UPS", "모델"])


def test_swapping_the_leaf_switch_updates_the_network_table():
    """포트가 2배(64→128)인 스위치로 바꾸면 leaf 대수가 절반이 된다.

    기본 랙에 의존하지 않도록 절대값이 아니라 이 관계를 검증한다.
    """
    at = _after_design_run()
    before = int(_cell(at, NETWORK_TABLE, "Leaf 스위치"))

    _picker(at, "Leaf 스위치").set_value("leaf_arista_7060x6_128x400g").run()
    assert not at.exception, at.exception

    after = int(_cell(at, NETWORK_TABLE, "Leaf 스위치"))
    assert after == math.ceil(before / 2)
    # spine 은 안 건드렸으므로 그대로여야 한다
    assert _picker(at, "Spine 스위치").value == "spine_switch_64x800g"


def test_unchanged_roles_keep_their_default_block():
    at = _after_design_run()
    _picker(at, "CDU").set_value("cdu_coolit_chx1000").run()
    assert _picker(at, "변압기").value == "tx_2500kva"
    assert _cell(at, ELECTRICAL_TABLE, "변압기 단위용량 (kVA)") == "2500"


def test_swap_survives_across_reruns():
    """다른 위젯을 건드려도 선택이 유지돼야 한다."""
    at = _after_design_run()
    _picker(at, "UPS").set_value("ups_vertiv_exl_s1_800kva").run()
    _picker(at, "칠러").set_value("chiller_carrier_19dv_500rt").run()
    assert _picker(at, "UPS").value == "ups_vertiv_exl_s1_800kva"
    assert _cell(at, ELECTRICAL_TABLE, "UPS 단위용량 (kVA)") == "800"


# ---------- 되돌리기 ----------

def test_reset_button_restores_catalog_defaults():
    at = _after_design_run()
    _picker(at, "UPS").set_value("ups_schneider_galaxy_vx_500kva").run()
    assert _cell(at, ELECTRICAL_TABLE, "UPS 단위용량 (kVA)") == "500"

    next(b for b in at.button if "기본 장비로" in b.label).click().run()
    assert not at.exception, at.exception
    assert _picker(at, "UPS").value == "ups_1250kva"
    assert _cell(at, ELECTRICAL_TABLE, "UPS 단위용량 (kVA)") == "1250"


# ---------- 교체해도 규격검증이 따라오는가 ----------

def test_compliance_is_recomputed_after_a_swap():
    """장비를 바꾸면 규격검증도 다시 돌아야 한다(결과가 낡으면 안 된다)."""
    at = _after_design_run()
    _picker(at, "UPS").set_value("ups_schneider_galaxy_vx_500kva").run()
    assert not at.exception, at.exception
    assert {"위반", "경고", "정보"} <= {m.label for m in at.metric}


def test_air_cooling_dropdown_is_present():
    """공냉장비도 화면에서 교체할 수 있어야 한다."""
    at = _after_design_run()
    assert _picker(at, "공냉장비") is not None


def test_cooling_table_shows_air_cooling_quantity():
    """냉각 표에 공냉장비 수량이 보인다(값은 엔진이 만든 것을 그대로)."""
    at = _after_design_run()
    assert _cell(at, COOLING_TABLE, "공냉장비 수량")
