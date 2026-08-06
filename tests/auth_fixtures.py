"""테스트 전용 자격증명.

실제 사번·비밀번호가 아니며 저장소에 커밋되는 값이다. 운영 자격증명은
`.streamlit/secrets.toml`(gitignore) 또는 Streamlit Cloud 의 Secrets 에만 둔다.
"""
from __future__ import annotations

import functools

TEST_USER = "20240101"
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
