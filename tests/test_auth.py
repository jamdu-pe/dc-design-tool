"""로그인 게이트 테스트.

핵심은 '설정이 없거나 로그인에 실패하면 설계 화면이 렌더되지 않는다'는 것이다.
자격증명이 코드에 없고 st.secrets 에서만 온다는 점도 함께 확인한다.
"""
import pathlib

import pytest

pytest.importorskip("streamlit", reason="웹 UI 전용 — pip install -e '.[ui]'")
pytest.importorskip("streamlit_authenticator", reason="로그인 게이트 전용")

from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.auth_fixtures import TEST_NAME, TEST_PASSWORD, TEST_USER, auth_secrets  # noqa: E402

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")

# 로그인 후에만 나타나는 화면 요소. 게이트가 열렸는지 판정하는 기준으로 쓴다.
GATED_WIDGET = "랙 모델"


def _app(secrets: dict | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    if secrets is not None:
        at.secrets["auth"] = secrets
    at.run()
    return at


def _design_ui_visible(at: AppTest) -> bool:
    return any(s.label == GATED_WIDGET for s in at.sidebar.selectbox)


def _submit(at: AppTest, user: str, password: str) -> AppTest:
    next(t for t in at.text_input if t.label == "이름").set_value(user)
    next(t for t in at.text_input if t.label == "비밀번호").set_value(password)
    next(b for b in at.button if b.label == "로그인").click().run()
    return at


# ---------- 설정 부재: fail closed ----------

@pytest.fixture
def no_local_secrets(tmp_path, monkeypatch):
    """로컬에 자격증명이 설정돼 있어도 '설정 없음' 경로를 시험하게 만든다.

    Streamlit 은 `.streamlit/secrets.toml` 을 **작업 디렉터리 기준**으로 찾는다.
    이 파일은 gitignore 라 새로 받은 저장소에는 없지만, 로그인을 한 번이라도 설정한
    PC 에서는 존재한다. 그대로 두면 아래 fail-closed 테스트가 실제 자격증명을 읽어
    "설정이 없으면 화면을 열지 않는다"는 성질을 전혀 검증하지 못한 채 통과한다.
    빈 디렉터리로 옮겨서 secrets 를 못 찾는 상태를 실제로 만든다.
    """
    monkeypatch.chdir(tmp_path)


def test_without_secrets_the_app_refuses_to_open(no_local_secrets):
    """Secrets 를 빠뜨린 채 배포해도 화면이 공개되면 안 된다."""
    at = _app()
    assert not at.exception, at.exception
    assert not _design_ui_visible(at)
    assert any("로그인 설정" in e.value for e in at.error)


def test_missing_secrets_message_tells_where_to_fix_it(no_local_secrets):
    at = _app()
    guidance = " ".join(e.value for e in at.error)
    assert "secrets.toml" in guidance
    assert "Secrets" in guidance          # Streamlit Cloud 설정 위치 안내


def test_empty_user_list_is_treated_as_unconfigured():
    at = _app({"cookie": {"name": "c", "key": "k" * 40, "expiry_days": 1},
               "credentials": {"usernames": {}}})
    assert not _design_ui_visible(at)
    assert any("사용자가 없습니다" in e.value for e in at.error)


# ---------- 로그인 판정 ----------

def test_login_form_is_shown_before_authentication():
    at = _app(auth_secrets())
    assert not at.exception, at.exception
    assert {"이름", "비밀번호"} <= {t.label for t in at.text_input}
    assert not _design_ui_visible(at)


def test_wrong_password_does_not_open_the_design_ui():
    at = _submit(_app(auth_secrets()), TEST_USER, "wrong-password")
    assert not at.exception, at.exception
    assert not _design_ui_visible(at)
    assert any("올바르지 않습니다" in e.value for e in at.error)


def test_unknown_name_does_not_open_the_design_ui():
    at = _submit(_app(auth_secrets()), "등록되지않은사람", TEST_PASSWORD)
    assert not _design_ui_visible(at)


def test_correct_credentials_open_the_design_ui():
    at = _submit(_app(auth_secrets()), TEST_USER, TEST_PASSWORD)
    assert not at.exception, at.exception
    assert _design_ui_visible(at)


def test_signed_in_user_is_shown_and_can_log_out():
    at = _submit(_app(auth_secrets()), TEST_USER, TEST_PASSWORD)
    captions = " ".join(c.value for c in at.sidebar.caption)
    assert TEST_USER in captions and TEST_NAME in captions
    assert any(b.label == "로그아웃" for b in at.sidebar.button)


def test_caption_does_not_repeat_identical_name_and_id():
    """로그인 ID 가 실명이면 이름과 ID 가 같다 — '홍길동 (홍길동)' 으로 겹쳐 찍지 않는다."""
    same = "홍길동"
    secrets = auth_secrets()
    entry = secrets["credentials"]["usernames"].pop(TEST_USER)
    secrets["credentials"]["usernames"][same] = {**entry, "name": same}

    at = _submit(_app(secrets), same, TEST_PASSWORD)
    captions = " ".join(c.value for c in at.sidebar.caption)
    assert f"{same} 님으로 접속 중" in captions
    assert f"{same} ({same})" not in captions


# ---------- 설정 품질 경고 ----------

def test_plaintext_password_in_secrets_is_flagged():
    """평문 비밀번호를 넣어두면 로그인도 안 되고 경고가 뜬다."""
    at = _app(auth_secrets(password_hash="평문비밀번호"))
    assert any("bcrypt 해시가 아닙니다" in w.value for w in at.warning)


def test_placeholder_cookie_key_is_flagged():
    secrets = auth_secrets()
    secrets["cookie"]["key"] = "여기에-무작위-문자열-48자-이상"
    at = _app(secrets)
    assert any("쿠키 key" in w.value for w in at.warning)


# ---------- 자격증명이 코드에 없는가 ----------

def test_no_credentials_are_hardcoded_in_the_ui_modules():
    """비밀번호·해시가 소스에 섞여 들어가는 회귀를 막는다."""
    root = pathlib.Path(__file__).resolve().parent.parent
    for path in (root / "app.py", root / "dc_design_tool" / "ui_auth.py"):
        source = path.read_text(encoding="utf-8")
        assert "$2b$" not in source, f"{path.name} 에 bcrypt 해시가 들어 있다"
        assert TEST_PASSWORD not in source
