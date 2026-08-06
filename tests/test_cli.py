"""CLI 테스트 (Phase 5): build / check / catalog."""
import pathlib

import pytest
import yaml
from typer.testing import CliRunner

from dc_design_tool.cli import app

runner = CliRunner()

COMPLIANT = {"project": "cli-ok", "rack_id": "nvidia_gb200_nvl72", "it_power_mw": 5.0,
             "tier": "III", "electrical_redundancy": "N+1",
             "mechanical_redundancy": "N+1", "target_pue": 1.6}
VIOLATING = {**COMPLIANT, "project": "cli-bad", "tier": "IV",
             "electrical_redundancy": "N+1"}


def _spec(tmp_path: pathlib.Path, data: dict) -> str:
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(p)


# ---------- build ----------

def test_build_creates_xlsx_docx_and_mermaid(tmp_path):
    out = tmp_path / "out"
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, COMPLIANT),
                              "--out", str(out)])
    assert res.exit_code == 0, res.output
    names = {p.name for p in out.iterdir()}
    assert {"BOM_부하요약.xlsx", "설계기준서.docx", "계통도.md"} <= names


def test_build_reports_compliance_summary(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, COMPLIANT),
                              "--out", str(tmp_path / "out")])
    assert "규격검증" in res.output


def test_build_succeeds_by_default_even_with_violations(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, VIOLATING),
                              "--out", str(tmp_path / "out")])
    assert res.exit_code == 0
    assert "위반" in res.output


def test_build_strict_fails_on_violation(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, VIOLATING),
                              "--out", str(tmp_path / "out"), "--strict"])
    assert res.exit_code == 1


def test_build_strict_passes_when_compliant(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, COMPLIANT),
                              "--out", str(tmp_path / "out"), "--strict"])
    assert res.exit_code == 0, res.output


# ---------- check ----------

def test_check_exits_nonzero_on_violation_without_writing_files(tmp_path):
    out = tmp_path / "out"
    res = runner.invoke(app, ["check", "--spec", _spec(tmp_path, VIOLATING)])
    assert res.exit_code == 1
    assert "TIER_ELECTRICAL" in res.output
    assert not out.exists()


def test_check_exits_zero_when_compliant(tmp_path):
    res = runner.invoke(app, ["check", "--spec", _spec(tmp_path, COMPLIANT)])
    assert res.exit_code == 0, res.output


# ---------- 오류 처리 ----------

def test_missing_spec_file_reports_clean_error(tmp_path):
    res = runner.invoke(app, ["build", "--spec", str(tmp_path / "nope.yaml"),
                              "--out", str(tmp_path / "out")])
    assert res.exit_code != 0
    assert "찾을 수 없" in res.output


def test_unknown_rack_reports_catalog_absence(tmp_path):
    bad = {**COMPLIANT, "rack_id": "acme_super9000"}
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, bad),
                              "--out", str(tmp_path / "out")])
    assert res.exit_code != 0
    assert "카탈로그 부재" in res.output


def test_invalid_spec_field_reports_validation_error(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, {"project": "no-rack"}),
                              "--out", str(tmp_path / "out")])
    assert res.exit_code != 0
    assert "spec" in res.output.lower()


# ---------- catalog ----------

def test_catalog_lists_blocks_with_confidence(tmp_path):
    res = runner.invoke(app, ["catalog"])
    assert res.exit_code == 0
    assert "nvidia_gb200_nvl72" in res.output
    assert "projected" in res.output


def test_catalog_filters_by_type(tmp_path):
    res = runner.invoke(app, ["catalog", "--type", "network"])
    assert res.exit_code == 0
    assert "leaf_switch_64x800g" in res.output
    assert "nvidia_gb200_nvl72" not in res.output


# ---------- regions ----------

def test_regions_lists_available_packs():
    res = runner.invoke(app, ["regions"])
    assert res.exit_code == 0
    assert "generic" in res.output
    assert "KR" in res.output
    assert "KEC" in res.output


def test_build_reports_the_applied_region_pack(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, {**COMPLIANT, "region": "KR"}),
                              "--out", str(tmp_path / "out")])
    assert res.exit_code == 0, res.output
    assert "규격 팩" in res.output and "KR" in res.output


def test_unknown_region_reports_clean_error(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _spec(tmp_path, {**COMPLIANT, "region": "ZZ"}),
                              "--out", str(tmp_path / "out")])
    assert res.exit_code != 0
    assert "규격 팩 부재" in res.output


@pytest.mark.parametrize("cmd", ["build", "check", "catalog", "regions", "compare"])
def test_subcommands_are_addressable_by_name(cmd):
    """단일 커맨드일 때 typer가 이름을 삼키는 문제 방지 회귀 테스트."""
    res = runner.invoke(app, [cmd, "--help"])
    assert res.exit_code == 0
