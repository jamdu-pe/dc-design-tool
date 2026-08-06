"""서브에이전트 정의 테스트 (Phase 5).

에이전트 md는 `dc_design_tool/agents/`가 원본, `.claude/agents/`는 설치본이다.
둘이 어긋나면 대화형 오케스트레이션이 원본과 다르게 동작하므로 동기화를 검증한다.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "dc_design_tool" / "agents"
INSTALLED = ROOT / ".claude" / "agents"

EXPECTED = {"intake", "mechanical", "electrical", "ict", "compliance", "reporter"}


def _frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: frontmatter 없음"
    block = text.split("---\n")[1]
    out = {}
    for line in block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def test_all_orchestration_agents_exist():
    assert {p.stem for p in SRC.glob("*.md")} == EXPECTED


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_agent_frontmatter_declares_name_and_description(stem):
    fm = _frontmatter(SRC / f"{stem}.md")
    assert fm.get("name") == stem
    assert len(fm.get("description", "")) > 20


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_agent_forbids_direct_calculation(stem):
    """모든 에이전트는 '수치는 engine 호출' 규칙을 명시해야 한다(CLAUDE.md 절대규칙 1)."""
    text = (SRC / f"{stem}.md").read_text(encoding="utf-8")
    assert "engine" in text
    assert "계산" in text


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_installed_agent_matches_source(stem):
    src = (SRC / f"{stem}.md").read_text(encoding="utf-8")
    inst = INSTALLED / f"{stem}.md"
    assert inst.is_file(), f".claude/agents/{stem}.md 미설치"
    assert inst.read_text(encoding="utf-8") == src


def test_install_agents_command_copies_all_definitions(tmp_path):
    """`dc-design install-agents`가 원본을 지정 폴더로 복사한다."""
    from typer.testing import CliRunner

    from dc_design_tool.cli import app

    dest = tmp_path / "agents"
    res = CliRunner().invoke(app, ["install-agents", "--dest", str(dest)])
    assert res.exit_code == 0, res.output
    assert {p.stem for p in dest.glob("*.md")} == EXPECTED
    assert (dest / "intake.md").read_text(encoding="utf-8") == \
        (SRC / "intake.md").read_text(encoding="utf-8")


def test_root_claude_md_documents_orchestration_order():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for stem in EXPECTED:
        assert stem in text, f"CLAUDE.md에 {stem} 에이전트 절차 누락"
    assert "engine" in text
