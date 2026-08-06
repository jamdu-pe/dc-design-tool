"""spec.yaml 에 적은 장비 선택이 CLI·시나리오 스윕까지 전달되는지 확인한다.

`size(spec, selections=...)` 인자는 화면 전용이라 spec 파일·스윕에서는 쓸 수 없었다.
Spec 필드로 올려 세 경로(엔진·CLI·비교)가 같은 선택을 공유하게 한다.
"""
import pathlib

import pytest
import yaml
from typer.testing import CliRunner

from dc_design_tool.cli import app
from dc_design_tool.engine import scenario
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size

runner = CliRunner()

BASE = {"project": "sel", "rack_id": "nvidia_gb200_nvl72", "it_power_mw": 5.0}


def _spec(**kw):
    return Spec(**{**BASE, **kw})


# ---------- Spec 필드 ----------

def test_spec_defaults_to_no_selection():
    assert _spec().selections == {}


def test_spec_accepts_selections():
    spec = _spec(selections={"ups": "ups_vertiv_exl_s1_800kva"})
    assert spec.selections["ups"] == "ups_vertiv_exl_s1_800kva"


def test_spec_selections_drive_sizing_without_any_argument():
    r = size(_spec(selections={"ups": "ups_schneider_galaxy_vx_500kva"}))
    assert r.selections["ups"] == "ups_schneider_galaxy_vx_500kva"
    assert r.electrical["ups_unit_kva"] == 500


def test_argument_overrides_the_spec_field_per_role():
    """화면에서 고른 값이 spec 에 적힌 값을 이긴다. 지정 안 한 역할은 spec 을 따른다."""
    spec = _spec(selections={"ups": "ups_schneider_galaxy_vx_500kva",
                             "cdu": "cdu_coolit_chx1000"})
    r = size(spec, selections={"ups": "ups_vertiv_exl_s1_800kva"})
    assert r.electrical["ups_unit_kva"] == 800        # 인자가 이긴다
    assert r.cooling["cdu_unit_kw"] == 1000           # spec 이 남는다


def test_unknown_role_key_is_rejected_with_the_valid_list():
    with pytest.raises(ValueError, match="transformer"):
        size(_spec(selections={"transfomer": "tx_2500kva"}))   # 오타


def test_unknown_block_id_in_spec_is_rejected():
    with pytest.raises(KeyError, match="ups_1250kva"):
        size(_spec(selections={"ups": "no_such_ups"}))


# ---------- CLI (spec.yaml) ----------

def _write_spec(tmp_path: pathlib.Path, **kw) -> str:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump({**BASE, **kw}, allow_unicode=True),
                    encoding="utf-8")
    return str(path)


def test_cli_build_honours_selections_from_the_spec_file(tmp_path):
    spec = _write_spec(tmp_path, selections={"generator": "genset_cat_c175_16_3000kw"})
    res = runner.invoke(app, ["build", "--spec", spec, "--out", str(tmp_path / "out")])
    assert res.exit_code == 0, res.output
    assert "genset_cat_c175_16_3000kw" in res.output


def test_cli_stays_quiet_when_every_role_uses_the_catalog_default(tmp_path):
    res = runner.invoke(app, ["build", "--spec", _write_spec(tmp_path),
                              "--out", str(tmp_path / "out")])
    assert res.exit_code == 0, res.output
    assert "장비 교체:" not in res.output


def test_cli_reports_a_bad_block_id_in_the_spec_file(tmp_path):
    spec = _write_spec(tmp_path, selections={"ups": "nope"})
    res = runner.invoke(app, ["check", "--spec", spec])
    assert res.exit_code == 2
    assert "선택 불가" in res.output


def test_cli_reports_a_bad_role_key_in_the_spec_file(tmp_path):
    spec = _write_spec(tmp_path, selections={"upss": "ups_1250kva"})
    res = runner.invoke(app, ["check", "--spec", spec])
    assert res.exit_code == 2
    assert "upss" in res.output


# ---------- 시나리오 스윕 ----------

def test_sweep_over_equipment_produces_different_designs():
    rows = scenario.run_sweep(BASE, {"selections": [
        {"ups": "ups_1250kva"},
        {"ups": "ups_schneider_galaxy_vx_500kva"},
    ]})
    assert len(rows) == 2
    assert all(not r["error"] for r in rows), [r["error"] for r in rows]
    assert rows[0]["ups_qty"] != rows[1]["ups_qty"]


def test_sweep_scenario_names_stay_readable_for_equipment_axes():
    """dict 를 그대로 찍으면 따옴표·중괄호로 표가 읽히지 않는다."""
    (name, _), = scenario.expand(BASE, {"selections": [{"ups": "ups_1250kva"}]})
    assert name == "ups=ups_1250kva"


def test_sweep_can_combine_equipment_with_other_axes():
    rows = scenario.run_sweep(BASE, {
        "electrical_redundancy": ["N+1", "2N"],
        "selections": [{"ups": "ups_1250kva"},
                       {"ups": "ups_vertiv_exl_s1_800kva"}],
    })
    assert len(rows) == 4
    assert all(not r["error"] for r in rows), [r["error"] for r in rows]
