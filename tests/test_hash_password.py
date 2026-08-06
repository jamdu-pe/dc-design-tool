"""scripts/hash_password.py 테스트.

관리자가 사용자를 등록할 때 유일하게 쓰는 도구다. 여기서 잘못된 해시가 나오면
로그인이 통째로 막히므로, 출력 해시가 실제로 검증을 통과하는지까지 확인한다.
"""
import pathlib
import runpy
import sys

import pytest

pytest.importorskip("streamlit_authenticator", reason="로그인 게이트 전용")

import streamlit_authenticator as stauth  # noqa: E402

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "hash_password.py"


def _run(monkeypatch, capsys, *, username: str, passwords: list[str]) -> tuple[int, str]:
    """스크립트를 실행하고 (종료코드, 표준출력)을 준다."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": username)
    supplied = iter(passwords)
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(supplied))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])

    try:
        runpy.run_path(str(SCRIPT), run_name="__main__")
        code = 0
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, capsys.readouterr().out


def test_emits_a_hash_that_verifies_against_the_password(monkeypatch, capsys):
    password = "correct-horse-battery"
    code, out = _run(monkeypatch, capsys, username="20240101",
                     passwords=[password, password])
    assert code == 0

    line = next(l for l in out.splitlines() if l.startswith("password = "))
    digest = line.split('"')[1]
    assert stauth.Hasher.is_hash(digest)
    assert stauth.Hasher.check_pw(password, digest)
    assert not stauth.Hasher.check_pw("wrong", digest)


def test_output_is_a_pastable_secrets_block(monkeypatch, capsys):
    _, out = _run(monkeypatch, capsys, username="20240102", passwords=["pw", "pw"])
    assert '[auth.credentials.usernames."20240102"]' in out


def test_mismatched_confirmation_is_rejected(monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, username="20240101",
                     passwords=["aaa", "bbb"])
    assert code == 2
    assert "password = " not in out


def test_empty_password_is_rejected(monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, username="20240101", passwords=["", ""])
    assert code == 2
    assert "password = " not in out


def test_empty_username_is_rejected(monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, username="   ", passwords=["pw", "pw"])
    assert code == 2
    assert "password = " not in out


def test_the_password_itself_is_never_printed(monkeypatch, capsys):
    password = "super-secret-value"
    _, out = _run(monkeypatch, capsys, username="20240101",
                  passwords=[password, password])
    assert password not in out
