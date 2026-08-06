"""MCP 서버 테스트.

툴 페이로드 함수는 mcp 패키지 없이도 동작해야 한다(순수 dict 반환).
서버 조립(FastMCP)만 mcp 의존이므로 해당 테스트는 importorskip 한다.
"""
import json
import pathlib

import pytest

from dc_design_tool import mcp_server as srv

SPEC = {"project": "mcp-test", "rack_id": "nvidia_gb200_nvl72", "it_power_mw": 5.0,
        "tier": "III", "electrical_redundancy": "N+1", "target_pue": 1.6}


def _json_roundtrip(payload) -> dict:
    """MCP는 JSON으로 직렬화해 보낸다 — 모든 반환값이 직렬화 가능해야 한다."""
    return json.loads(json.dumps(payload, ensure_ascii=False))


# ---------- size_design ----------

def test_size_design_returns_summary_and_domains():
    r = _json_roundtrip(srv.size_design(SPEC))
    assert r["summary"]["rack_count"] == 42
    assert r["summary"]["it_power_kw"] == 5040.0
    for key in ("cooling", "electrical", "network", "space", "it_load"):
        assert key in r


def test_size_design_includes_compliance_summary():
    r = srv.size_design(SPEC)
    assert r["compliance"]["summary"]["violation"] == 0
    assert r["compliance"]["findings"]


def test_size_design_includes_bom_with_block_ids():
    r = srv.size_design(SPEC)
    assert r["bom"]
    assert all(li["block_id"] for li in r["bom"])


def test_size_design_reports_catalog_absence_as_error_not_exception():
    r = srv.size_design({**SPEC, "rack_id": "ghost_rack"})
    assert "카탈로그 부재" in r["error"]
    assert "summary" not in r


def test_size_design_reports_validation_error():
    r = srv.size_design({"project": "no-rack"})
    assert "error" in r


def test_size_design_reports_missing_target():
    r = srv.size_design({"rack_id": "nvidia_gb200_nvl72"})
    assert "it_power_mw" in r["error"]


# ---------- check_compliance ----------

def test_check_compliance_returns_findings_only():
    r = _json_roundtrip(srv.check_compliance(SPEC))
    assert "findings" in r and "summary" in r
    assert "bom" not in r
    assert all({"code", "severity", "message", "rule"} <= set(f) for f in r["findings"])


def test_check_compliance_flags_tier_violation():
    r = srv.check_compliance({**SPEC, "tier": "IV", "electrical_redundancy": "N+1"})
    assert r["ok"] is False
    assert "TIER_ELECTRICAL" in {f["code"] for f in r["findings"]}


def test_check_compliance_ok_when_no_violation():
    assert srv.check_compliance(SPEC)["ok"] is True


# ---------- catalog ----------

def test_list_catalog_returns_all_blocks_with_provenance():
    r = _json_roundtrip(srv.list_catalog())
    assert r["count"] == len(r["blocks"])
    sample = next(b for b in r["blocks"] if b["id"] == "nvidia_gb200_nvl72")
    assert sample["confidence"] == "vendor"
    assert sample["source_url"]


def test_list_catalog_filters_by_type_and_subtype():
    # 후보가 여러 개일 수 있으므로 '개수'가 아니라 '필터가 걸러낸다'를 검증한다.
    r = srv.list_catalog(block_type="electrical", subtype="ups")
    ids = {b["id"] for b in r["blocks"]}
    assert "ups_1250kva" in ids
    assert all(b["type"] == "electrical" and b["subtype"] == "ups" for b in r["blocks"])
    assert r["count"] == len(ids)


def test_list_catalog_unknown_filter_returns_empty_not_error():
    r = srv.list_catalog(block_type="chip", subtype="nope")
    assert r["count"] == 0
    assert "error" not in r


# ---------- regions ----------

def test_list_regions_returns_packs_with_reference():
    r = _json_roundtrip(srv.list_regions())
    codes = {p["code"] for p in r["regions"]}
    assert {"generic", "KR"} <= codes
    kr = next(p for p in r["regions"] if p["code"] == "KR")
    assert "KEC" in kr["reference"]


# ---------- compare_scenarios ----------

def test_compare_scenarios_returns_ranked_rows():
    r = _json_roundtrip(srv.compare_scenarios(
        base=SPEC, sweep={"electrical_redundancy": ["N+1", "2N"]},
        sort="total_building_m2"))
    assert len(r["scenarios"]) == 2
    areas = [row["total_building_m2"] for row in r["scenarios"]]
    assert areas == sorted(areas)


def test_compare_scenarios_reports_bad_sweep_key():
    r = srv.compare_scenarios(base=SPEC, sweep={"nope": [1, 2]})
    assert "스윕 키" in r["error"]


# ---------- build_reports ----------

def test_build_reports_writes_three_files(tmp_path):
    r = _json_roundtrip(srv.build_reports(SPEC, str(tmp_path)))
    assert set(r["files"]) == {"xlsx", "docx", "diagram"}
    for path in r["files"].values():
        assert pathlib.Path(path).is_file()


def test_build_reports_reports_error_for_bad_spec(tmp_path):
    r = srv.build_reports({**SPEC, "rack_id": "ghost"}, str(tmp_path))
    assert "카탈로그 부재" in r["error"]


# ---------- add_rack ----------

def test_add_rack_rejects_missing_source_url(tmp_path, monkeypatch):
    from dc_design_tool.engine import catalog
    monkeypatch.setattr(catalog, "USER_DATA", tmp_path / "user_racks.yaml")
    r = srv.add_rack({"id": "x", "type": "rack", "vendor": "A", "model": "B",
                      "interface": {"power_kw_typical": 100.0}, "source_url": ""})
    assert "source_url" in r["error"]


def test_add_rack_registers_and_returns_block(tmp_path, monkeypatch):
    from dc_design_tool.engine import catalog
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for src in catalog.DATA.glob("*.yaml"):
        (data_dir / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(catalog, "DATA", data_dir)
    monkeypatch.setattr(catalog, "USER_DATA", data_dir / "user_racks.yaml")

    r = srv.add_rack({
        "id": "mcp_test_rack", "type": "rack", "vendor": "ACME", "model": "M-1",
        "interface": {"power_kw_typical": 100.0, "liquid_fraction": 0.9},
        "as_of_date": "2026-08", "confidence": "vendor",
        "source_url": "https://example.com/ds"})
    assert r["block"]["id"] == "mcp_test_rack"
    assert "user_racks.yaml" in r["saved_to"]


# ---------- 서버 조립 ----------

def test_server_registers_all_tools():
    pytest.importorskip("mcp", reason="MCP SDK 미설치 — pip install -e '.[mcp]'")
    server = srv.build_server()
    import anyio
    names = {t.name for t in anyio.run(server.list_tools)}
    assert {"size_design", "check_compliance", "list_catalog", "list_regions",
            "compare_scenarios", "build_reports", "add_rack"} <= names


def test_every_tool_has_a_prescriptive_description():
    pytest.importorskip("mcp", reason="MCP SDK 미설치")
    import anyio
    for tool in anyio.run(srv.build_server().list_tools):
        assert tool.description and len(tool.description) > 60, tool.name
