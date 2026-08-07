"""Streamlit 화면의 이름+비밀번호 로그인 게이트.

로그인 ID 는 사용자의 실명이다(`[auth.credentials.usernames."홍길동"]`) — 사번이 아니므로
`secrets.toml` 의 테이블 키도 이름으로 적는다. 실제 이름·해시는 저장소에 두지 않는다.

자격증명은 코드에 두지 않고 `st.secrets["auth"]`(로컬은 `.streamlit/secrets.toml`,
Streamlit Community Cloud 는 앱 설정의 Secrets)에서만 읽는다.

**설정이 없으면 화면을 열지 않는다(fail closed).** secrets 누락 시 인증을 건너뛰게
만들면, Cloud 에 Secrets 를 빠뜨린 순간 앱이 통째로 공개된다. 그래서 안내 문구를
띄우고 멈춘다.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

# 템플릿을 그대로 올린 경우를 잡기 위한 표식.
_PLACEHOLDER_HINTS = ("여기에", "example", "changeme")
_MIN_COOKIE_KEY_LEN = 32


def _plain(value: Any) -> Any:
    """st.secrets 의 읽기 전용 매핑을 평범한 dict 로 복사한다.

    streamlit-authenticator 는 넘겨받은 credentials 에 로그인 시도 횟수·상태를
    직접 써넣는다. st.secrets 객체를 그대로 주면 쓰기 시점에 터진다.
    """
    if hasattr(value, "items"):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _read_auth_config() -> dict:
    """secrets 에서 인증 설정을 읽는다. 없거나 형식이 틀리면 ValueError."""
    try:
        raw = st.secrets["auth"]
    except Exception as exc:                      # 파일 부재·키 부재 모두 여기로
        raise ValueError("secrets 에 [auth] 설정이 없습니다") from exc

    cfg = _plain(raw)
    cookie = cfg.get("cookie") or {}
    credentials = cfg.get("credentials") or {}
    users = credentials.get("usernames") or {}

    if not users:
        raise ValueError("등록된 사용자가 없습니다 ([auth.credentials.usernames])")
    if not cookie.get("name") or not cookie.get("key"):
        raise ValueError("쿠키 설정이 없습니다 ([auth.cookie] name·key)")
    return cfg


def _config_warnings(cfg: dict) -> list[str]:
    """설정이 살아는 있지만 위험한 상태를 짚는다(로그인 화면에 함께 표시)."""
    import streamlit_authenticator as stauth

    notes: list[str] = []
    key = str(cfg["cookie"]["key"])
    if len(key) < _MIN_COOKIE_KEY_LEN or any(h in key.lower() for h in _PLACEHOLDER_HINTS):
        notes.append("쿠키 key 가 템플릿 값이거나 너무 짧습니다 — "
                     "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` 로 교체하세요.")

    for username, entry in cfg["credentials"]["usernames"].items():
        password = str((entry or {}).get("password", ""))
        if not stauth.Hasher.is_hash(password):
            notes.append(f"'{username}' 의 password 가 bcrypt 해시가 아닙니다 — "
                         "`python scripts/hash_password.py` 로 만든 값을 넣으세요.")
    return notes


def require_login() -> tuple[str, str]:
    """로그인된 사용자의 (로그인 ID, 표시 이름)을 반환한다. 아니면 화면을 멈춘다.

    로그인 ID 는 실명이므로 보통 두 값이 같다.

    Returns:
        (username, name) — 인증 성공 시에만 반환된다.
    """
    import streamlit_authenticator as stauth

    try:
        cfg = _read_auth_config()
    except ValueError as exc:
        st.error(
            f"로그인 설정을 읽지 못했습니다: {exc}\n\n"
            "- 로컬: `.streamlit/secrets.toml.example` 을 `.streamlit/secrets.toml` 로 "
            "복사해 채우세요.\n"
            "- Streamlit Cloud: 앱 **Settings → Secrets** 에 같은 내용을 붙여 넣으세요.\n\n"
            "자격증명이 설정되기 전에는 화면을 열지 않습니다."
        )
        st.stop()

    authenticator = stauth.Authenticate(
        cfg["credentials"],
        cfg["cookie"]["name"],
        cfg["cookie"]["key"],
        float(cfg["cookie"].get("expiry_days", 1)),
        auto_hash=False,          # secrets 에는 해시만 둔다(평문 저장을 유도하지 않는다)
    )

    status = st.session_state.get("authentication_status")
    if not status:
        st.title("데이터센터 M&E 개념설계")
        st.caption("사내 공유용 도구입니다. 이름과 비밀번호로 로그인하세요.")
        for note in _config_warnings(cfg):
            st.warning(note)
        authenticator.login(location="main",
                            fields={"Form name": "로그인", "Username": "이름",
                                    "Password": "비밀번호", "Login": "로그인"})
        status = st.session_state.get("authentication_status")

    if status is False:
        st.error("이름 또는 비밀번호가 올바르지 않습니다.")
        st.stop()
    if status is None:
        st.info("이름과 비밀번호를 입력하세요.")
        st.stop()

    username = st.session_state.get("username", "")
    name = st.session_state.get("name", "")
    authenticator.logout("로그아웃", location="sidebar")
    # 로그인 ID 가 실명이면 둘이 같다 — "조일두 (조일두)" 로 겹쳐 찍지 않는다.
    who = name if name == username or not username else f"{name} ({username})"
    st.sidebar.caption(f"{who} 님으로 접속 중")
    return username, name
