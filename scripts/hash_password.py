"""secrets.toml 에 넣을 bcrypt 비밀번호 해시를 만든다.

    python scripts/hash_password.py

비밀번호를 명령행 인자로 받지 않는다 — 인자로 주면 셸 히스토리와 프로세스 목록에
평문이 남는다. 입력은 화면에 표시되지 않으며 확인을 위해 두 번 받는다.
"""
from __future__ import annotations

import getpass
import sys


def main() -> int:
    try:
        import streamlit_authenticator as stauth
    except ImportError:
        print("streamlit-authenticator 가 없습니다: pip install -r requirements.txt",
              file=sys.stderr)
        return 2

    username = input("이름(로그인 ID): ").strip()
    if not username:
        print("이름이 비어 있습니다.", file=sys.stderr)
        return 2

    password = getpass.getpass("비밀번호: ")
    if not password:
        print("비밀번호가 비어 있습니다.", file=sys.stderr)
        return 2
    if password != getpass.getpass("비밀번호 확인: "):
        print("두 입력이 다릅니다.", file=sys.stderr)
        return 2

    print("\n아래 블록을 .streamlit/secrets.toml (또는 Cloud 의 Settings → Secrets)에 붙여넣으세요.\n")
    print(f'[auth.credentials.usernames."{username}"]')
    print(f'name = "{username}"')
    print('email = "user@example.com"')
    print(f'password = "{stauth.Hasher.hash(password)}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
