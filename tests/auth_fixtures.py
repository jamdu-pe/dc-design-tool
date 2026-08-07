"""테스트 전용 자격증명.

실제 이름·비밀번호가 아니며 저장소에 커밋되는 값이다. 운영 자격증명은
`.streamlit/secrets.toml`(gitignore) 또는 Streamlit Cloud 의 Secrets 에만 둔다.

로그인 ID 는 실명이다. 여기서는 표시 이름(TEST_NAME)과 일부러 다르게 두어
사이드바가 두 값을 어떻게 합치는지까지 검증한다 — 둘이 같은 흔한 경우는
`test_auth.py::test_caption_does_not_repeat_identical_name_and_id` 가 덮는다.
"""
from __future__ import annotations

import functools

TEST_USER = "테스트사용자"
TEST_PASSWORD = "test-password-1234"
TEST_NAME = "테스트 사용자"


@functools.lru_cache(maxsize=1)
def _hashed() -> str:
    """bcrypt 해시는 생성 비용이 크다(테스트 12개 × 매번이면 체감된다) — 한 번만 만든다."""
    import streamlit_authenticator as stauth
    return stauth.Hasher.hash(TEST_PASSWORD)


def auth_secrets(password_hash: str | None = None) -> dict:
    """AppTest.secrets["auth"] 에 넣을 설정."""
    return {
        "cookie": {"name": "dc_design_test",
                   "key": "test-cookie-key-with-enough-entropy-0123456789",
                   "expiry_days": 1},
        "credentials": {"usernames": {
            TEST_USER: {"name": TEST_NAME, "email": "test@example.com",
                        "password": password_hash or _hashed()},
        }},
    }
