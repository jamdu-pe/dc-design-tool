"""MCP 서버: 설계 엔진을 MCP 툴로 노출한다.

CLAUDE.md 절대규칙 1에 따라 **모든 수치는 engine 이 산출한다.** 이 모듈은 입력 검증과
JSON 직렬화만 담당하며, 툴 설명에도 "직접 계산 금지"를 명시해 호출하는 LLM 이 결과를
해설만 하도록 유도한다.

툴 페이로드 함수는 mcp 패키지 없이도 동작하는 순수 함수다(테스트·재사용 용이).
FastMCP 조립은 `build_server()` 안에서만 mcp 를 import 한다.

실행: `dc-design-mcp` (stdio 전송)
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import ValidationError

from .engine import compliance as compliance_engine
from .engine import scenario
from .engine.catalog import (append_user_block, available_regions, load_blocks,
                             load_region)
from .engine.models import Spec
from .engine.sizing import size
from .reports.bom_xlsx import write_bom
from .reports.design_basis_docx import write_design_basis
from .reports.diagram_mermaid import write_diagrams

# 엔진이 올리는 예외를 사람이 읽을 오류로 바꾼다(MCP 는 예외보다 구조화 응답이 낫다).
ENGINE_ERRORS = (KeyError, ValueError, ValidationError)

DISCLAIMER = ("개념설계/타당성 수준 결과. 실시설계·인허가는 면허기술자(정보통신·전기·기계) "
              "검토 필요. confidence=projected 사양은 추정치다.")


def _error(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc).strip("'"), "disclaimer": DISCLAIMER}


def _spec(raw: dict[str, Any]) -> Spec:
    return Spec(**raw)


def _findings(report) -> list[dict[str, Any]]:
    return [f.model_dump() for f in report.findings]


# ---------------------------------------------------------------- 툴 페이로드

def size_design(spec: dict[str, Any]) -> dict[str, Any]:
    """사이징 + 규격검증 전체 결과."""
    try:
        result = size(_spec(spec))
    except ENGINE_ERRORS as exc:
        return _error(exc)

    report = result.compliance
    return {
        "summary": {
            "project": result.project,
            "rack_id": result.rack_id,
            "rack_count": result.rack_count,
            "it_power_kw": result.it_power_kw,
            "pue_estimate": result.electrical["pue_estimate"],
            "total_building_m2": result.space["total_building_m2"],
            "accel_total": result.it_load.get("accel_total"),
        },
        "it_load": result.it_load,
        "cooling": result.cooling,
        "electrical": result.electrical,
        "network": result.network,
        "space": result.space,
        "bom": [li.model_dump() for li in result.bom],
        "compliance": {
            "tier": report.tier, "ok": report.ok,
            "summary": report.summary(), "findings": _findings(report),
        } if report else None,
        "assumptions": result.assumptions,
        "warnings": result.warnings,
        "disclaimer": DISCLAIMER,
    }


def check_compliance(spec: dict[str, Any]) -> dict[str, Any]:
    """규격검증만 수행(산출물 생성 없음)."""
    try:
        parsed = _spec(spec)
        report = compliance_engine.check(size(parsed), parsed)
    except ENGINE_ERRORS as exc:
        return _error(exc)
    return {"tier": report.tier, "ok": report.ok, "summary": report.summary(),
            "findings": _findings(report), "disclaimer": DISCLAIMER}


def list_catalog(block_type: Optional[str] = None,
                 subtype: Optional[str] = None) -> dict[str, Any]:
    """카탈로그 블록 조회(없는 장비를 지어내지 않기 위한 근거)."""
    try:
        blocks = load_blocks()
    except ENGINE_ERRORS as exc:
        return _error(exc)
    rows = [b for b in blocks.values()
            if (block_type is None or b.type == block_type)
            and (subtype is None or b.subtype == subtype)]
    return {
        "count": len(rows),
        "blocks": [{
            "id": b.id, "type": b.type, "subtype": b.subtype, "vendor": b.vendor,
            "model": b.model, "confidence": b.confidence, "as_of_date": b.as_of_date,
            "source_url": b.source_url,
            "interface": b.interface.model_dump(exclude_none=True),
        } for b in sorted(rows, key=lambda x: (x.type, x.id))],
    }


def list_regions() -> dict[str, Any]:
    """적용 가능한 국가별 규격 팩 목록."""
    packs = []
    for code in available_regions():
        pack = load_region(code)
        packs.append({
            "code": code, "name": pack.get("name"),
            "reference": pack.get("reference"),
            "standards": pack.get("standards") or {},
            "override_count": sum(len(v) for v in (pack.get("overrides") or {}).values()),
        })
    return {"regions": packs}


def compare_scenarios(base: dict[str, Any], sweep: dict[str, list],
                      sort: str = "total_building_m2",
                      descending: bool = False) -> dict[str, Any]:
    """조건을 스윕해 설계안을 비교."""
    try:
        rows = scenario.rank(scenario.run_sweep(base, sweep), sort, descending)
    except ENGINE_ERRORS as exc:
        return _error(exc)
    return {"metrics": scenario.METRICS, "sort": sort, "scenarios": rows,
            "disclaimer": DISCLAIMER}


def build_reports(spec: dict[str, Any], out_dir: str) -> dict[str, Any]:
    """산출물 3종(xlsx/docx/mermaid) 생성 후 경로 반환."""
    try:
        result = size(_spec(spec))
        files = {"xlsx": write_bom(result, out_dir),
                 "docx": write_design_basis(result, out_dir),
                 "diagram": write_diagrams(result, out_dir)}
    except ENGINE_ERRORS as exc:
        return _error(exc)
    except OSError as exc:
        return {"error": f"산출물 저장 실패: {exc}", "disclaimer": DISCLAIMER}
    return {"files": files, "warnings": result.warnings, "disclaimer": DISCLAIMER}


def add_rack(block: dict[str, Any]) -> dict[str, Any]:
    """신규 랙 블록을 사용자 카탈로그에 등록."""
    try:
        saved = append_user_block(block)
    except ENGINE_ERRORS as exc:
        return _error(exc)
    from .engine.catalog import USER_DATA
    return {"block": saved.model_dump(exclude_none=True), "saved_to": str(USER_DATA),
            "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------- 서버 조립

TOOL_DOCS = {
    "size_design": (
        "데이터센터 M&E 개념설계를 산정한다. 랙 모델·규모·Tier·이중화를 담은 spec 을 받아 "
        "IT부하, 냉각(유량/CDU/칠러), 전기(UPS/배터리/발전기/변압기/버스웨이/PDU), "
        "통신(leaf-spine/트랜시버), 공간(면적/바닥하중), BOM, 규격검증 결과를 돌려준다. "
        "사용자가 데이터센터 용량·장비 수량·면적을 물으면 이 툴을 호출하고, 반환된 수치를 "
        "그대로 인용하라. 절대 직접 계산하거나 값을 추정하지 마라."),
    "check_compliance": (
        "설계안의 규격 적합성만 검증한다(산출물 파일은 만들지 않는다). Uptime Tier 이중화, "
        "이중화 실효성(단일 고장 후 잔여 용량), ASHRAE 수온·공기 등급, 프리쿨링 가능성, "
        "PUE 목표, 바닥하중, 버스웨이·PDU 용량, 부속실 면적, 지역 규격(KEC 등), "
        "카탈로그 신뢰도·신선도를 대조한다. '이 설계가 Tier IV 요건을 만족하는가' 류의 "
        "질문에 사용하라. 각 판정의 rule 필드(근거 규칙 파일)를 함께 인용하라."),
    "list_catalog": (
        "사용 가능한 장비 카탈로그를 조회한다. block_type(chip|node|rack|cooling|electrical|"
        "network)과 subtype 으로 거를 수 있다. **카탈로그에 없는 장비를 지어내지 말고** "
        "먼저 이 툴로 실재 여부를 확인하라. 각 블록의 confidence(measured|vendor|projected)와 "
        "source_url 을 함께 보고해 추정치 여부를 밝혀라."),
    "list_regions": (
        "적용 가능한 국가별 규격 팩(generic, KR 등)과 각 팩의 근거 표준·지역 표준값을 조회한다. "
        "설계에 어느 관할 규정을 적용할지 정하기 전에 호출하라. spec 의 region 필드에 code 를 "
        "넣으면 수전전압·저압전압 등이 해당 규정으로 교체되고 지역 검증이 추가된다."),
    "compare_scenarios": (
        "여러 설계 조건을 한 번에 비교한다. base(공통 조건)와 sweep(축별 값 목록)의 곱집합을 "
        "사이징해 랙 수·PUE·총 면적·설비 수량·가속기당 면적·규격 위반 건수를 표로 돌려준다. "
        "'GB200 과 GB300 중 무엇이 유리한가', 'N+1 과 2N 의 차이' 같은 비교 질문에 사용하라. "
        "CAPEX 는 카탈로그에 단가가 있는 블록만 합산하며, 없으면 null 로 보고된다 — "
        "임의 단가를 지어내지 마라."),
    "build_reports": (
        "설계 산출물 3종(BOM·부하요약 xlsx, 설계기준서 docx, 계통도 mermaid)을 out_dir 에 "
        "생성하고 파일 경로를 돌려준다. 사용자가 문서·보고서·BOM 파일을 요청할 때 호출하라. "
        "파일명이 고정이므로 실행마다 다른 out_dir 을 지정하라."),
    "add_rack": (
        "카탈로그에 없는 신규 랙을 사용자 카탈로그(data/user_racks.yaml)에 등록한다. "
        "id·type·vendor·model·interface.power_kw_typical 과 **source_url(출처)** 이 필수이며, "
        "출처 없는 사양은 거부된다. 사용자가 새 장비 사양을 제공했을 때만 호출하고, "
        "사양값을 추정해서 채우지 마라. 등록 후에는 size_design 에서 해당 id 를 쓸 수 있다."),
}


def build_server():
    """FastMCP 서버 인스턴스 생성(툴 등록 포함).

    Raises:
        ImportError: mcp 패키지 미설치 시.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(
        "dc-design-tool",
        instructions=(
            "AI 데이터센터 M&E 개념설계 엔진. 모든 수치는 이 서버의 툴이 결정론적으로 "
            "산출한다. 직접 계산하거나 장비 사양을 지어내지 말고, 툴 결과를 인용해 해설하라. "
            + DISCLAIMER),
    )

    # 툴 이름은 name= 로 명시한다(내부 레지스트리를 건드리지 않기 위해).
    @server.tool(name="size_design", description=TOOL_DOCS["size_design"])
    def _size_design(spec: dict) -> dict:
        return size_design(spec)

    @server.tool(name="check_compliance", description=TOOL_DOCS["check_compliance"])
    def _check_compliance(spec: dict) -> dict:
        return check_compliance(spec)

    @server.tool(name="list_catalog", description=TOOL_DOCS["list_catalog"])
    def _list_catalog(block_type: Optional[str] = None,
                      subtype: Optional[str] = None) -> dict:
        return list_catalog(block_type, subtype)

    @server.tool(name="list_regions", description=TOOL_DOCS["list_regions"])
    def _list_regions() -> dict:
        return list_regions()

    @server.tool(name="compare_scenarios", description=TOOL_DOCS["compare_scenarios"])
    def _compare_scenarios(base: dict, sweep: dict,
                           sort: str = "total_building_m2",
                           descending: bool = False) -> dict:
        return compare_scenarios(base, sweep, sort, descending)

    @server.tool(name="build_reports", description=TOOL_DOCS["build_reports"])
    def _build_reports(spec: dict, out_dir: str) -> dict:
        return build_reports(spec, out_dir)

    @server.tool(name="add_rack", description=TOOL_DOCS["add_rack"])
    def _add_rack(block: dict) -> dict:
        return add_rack(block)

    return server


def main() -> None:
    """stdio 전송으로 MCP 서버 실행(`dc-design-mcp`)."""
    build_server().run()


if __name__ == "__main__":
    main()
