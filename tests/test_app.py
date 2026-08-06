"""Streamlit UI 테스트 (streamlit.testing.v1.AppTest).

화면 코드가 engine 을 올바로 호출하고 예외 없이 렌더되는지 확인한다.
streamlit 이 없는 환경(CLI 전용 설치)에서는 건너뛴다.

app.py 는 로그인 게이트 뒤에 있으므로, 각 테스트는 테스트 전용 자격증명을 secrets 에
주입하고 실제로 로그인한 뒤 화면을 검증한다(배포 형상과 같은 경로를 지난다).
게이트 자체의 동작은 tests/test_auth.py 가 덮는다.
"""
import pathlib

import pytest

pytest.importorskip("streamlit", reason="웹 UI 전용 — pip install -e '.[ui]'")
pytest.importorskip("streamlit_authenticator", reason="로그인 게이트 전용")

from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.auth_fixtures import TEST_PASSWORD, TEST_USER, auth_secrets  # noqa: E402

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


def _login(at: AppTest) -> AppTest:
    next(t for t in at.text_input if t.label == "사번").set_value(TEST_USER)
    next(t for t in at.text_input if t.label == "비밀번호").set_value(TEST_PASSWORD)
    next(b for b in at.button if b.label == "로그인").click().run()
    return at


def _run_design(at: AppTest) -> AppTest:
    """사이드바 '설계 실행' 클릭. 로그아웃 버튼이 함께 있으므로 라벨로 고른다."""
    next(b for b in at.sidebar.button if b.label == "설계 실행").click().run()
    return at


def _fresh(timeout: float = 60) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=timeout)
    at.secrets["auth"] = auth_secrets()
    at.run()
    return _login(at)


def test_app_renders_without_exception():
    at = _fresh()
    assert not at.exception, at.exception


def test_rack_dropdown_is_populated_from_catalog():
    """옵션 라벨은 format_func 적용 결과라 벤더·모델·확신도가 함께 보여야 한다."""
    at = _fresh()
    rack_select = next(s for s in at.sidebar.selectbox if s.label == "랙 모델")
    joined = " | ".join(rack_select.options)
    assert "GB200 NVL72" in joined
    assert "[projected]" in joined      # 미출시 사양이 목록에서 구분된다


def test_tier_and_redundancy_options_come_from_rules():
    at = _fresh()
    labels = {s.label: s.options for s in at.sidebar.selectbox}
    assert set(labels["Uptime Tier"]) == {"I", "II", "III", "IV"}
    assert {"N", "N+1", "N+2", "2N"} == set(labels["전기 이중화"])


def test_region_pack_options_are_offered():
    at = _fresh()
    region = next(s for s in at.sidebar.selectbox if s.label == "규격 팩")
    joined = " | ".join(region.options)
    assert "KEC" in joined
    assert "generic" in joined


def test_before_running_the_app_prompts_for_input():
    at = _fresh()
    assert any("설계 실행" in i.value for i in at.info)


def test_run_design_produces_metrics_and_no_exception():
    at = _fresh()
    _run_design(at)
    assert not at.exception, at.exception
    metric_labels = [m.label for m in at.metric]
    assert "랙 수량" in metric_labels
    assert "총 IT부하" in metric_labels


def test_run_design_renders_all_result_tables():
    """기계·전기·통신·공간·규격검증·BOM 6개 표가 채워진다."""
    at = _fresh()
    _run_design(at)
    assert not at.exception, at.exception
    assert len(at.dataframe) >= 6


def test_download_section_is_rendered_after_a_run():
    """다운로드 위젯 자체는 AppTest 가 노출하지 않으므로 섹션 렌더로 확인한다.

    실제 파일 생성은 tests/test_reports.py 가 write_bom/write_design_basis 로 덮는다.
    """
    at = _fresh()
    _run_design(at)
    assert not at.exception, at.exception
    assert any("산출물" in s.value for s in at.subheader)


def test_compliance_summary_metrics_are_shown():
    at = _fresh()
    _run_design(at)
    assert {"위반", "경고", "정보"} <= {m.label for m in at.metric}


def test_rack_form_is_available_before_any_design_run():
    """신규 랙을 먼저 등록하는 흐름을 막지 않아야 한다(초기 화면에서도 폼 접근 가능)."""
    at = _fresh()
    labels = {t.label for t in at.text_input}
    assert {"id *", "vendor *", "model *", "source_url *"} <= labels


def test_rack_form_rejects_missing_source_url():
    """출처 없는 사양은 UI 에서도 등록되지 않는다(엔진 규칙이 그대로 적용)."""
    at = _fresh()
    for field, value in (("id *", "ui_test_rack"), ("vendor *", "ACME"),
                         ("model *", "T-1"), ("as_of_date * (YYYY-MM)", "2026-08")):
        next(t for t in at.text_input if t.label == field).set_value(value)
    next(t for t in at.text_input if t.label == "source_url *").set_value("")
    next(b for b in at.button if "카탈로그에 추가" in b.label).click().run()
    assert not at.exception, at.exception
    assert any("source_url" in e.value for e in at.error)


def test_rack_form_rejects_duplicate_id():
    at = _fresh()
    for field, value in (("id *", "nvidia_gb200_nvl72"), ("vendor *", "ACME"),
                         ("model *", "T-1"), ("as_of_date * (YYYY-MM)", "2026-08"),
                         ("source_url *", "https://example.com/x")):
        next(t for t in at.text_input if t.label == field).set_value(value)
    next(b for b in at.button if "카탈로그에 추가" in b.label).click().run()
    assert not at.exception, at.exception
    assert any("중복 블록 id" in e.value for e in at.error)
