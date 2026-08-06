"""CLI: dc-design build / check / catalog.

수치·판정은 모두 engine 이 만든다. CLI 는 입출력과 표시만 담당한다.
"""
from __future__ import annotations

import pathlib
from typing import Optional

import typer
import yaml
from pydantic import ValidationError

from .engine import scenario
from .engine.catalog import available_regions, load_blocks, load_region
from .engine.models import ComplianceReport, Spec
from .engine.sizing import size
from .reports.bom_xlsx import write_bom
from .reports.comparison_xlsx import write_comparison
from .reports.design_basis_docx import write_design_basis
from .reports.diagram_mermaid import write_diagrams

app = typer.Typer(add_completion=False, help="데이터센터 M&E 개념설계 도구")

SEVERITY_LABEL = {"violation": "위반", "warning": "경고", "info": "정보"}


def _load_spec(spec_path: str) -> Spec:
    """spec.yaml 을 읽어 검증된 Spec 반환. 실패 시 typer.Exit(2)."""
    p = pathlib.Path(spec_path)
    if not p.is_file():
        typer.echo(f"[오류] spec 파일을 찾을 수 없습니다: {spec_path}", err=True)
        raise typer.Exit(2)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        typer.echo(f"[오류] spec YAML 파싱 실패: {exc}", err=True)
        raise typer.Exit(2)
    try:
        return Spec(**raw)
    except ValidationError as exc:
        typer.echo(f"[오류] spec 필드 검증 실패:\n{exc}", err=True)
        raise typer.Exit(2)


def _size_or_exit(spec: Spec):
    """사이징 실행. 카탈로그 부재·규칙 오류는 사람이 읽을 메시지로 변환."""
    try:
        return size(spec)
    except (KeyError, ValueError) as exc:
        typer.echo(f"[오류] {str(exc).strip(chr(39))}", err=True)
        raise typer.Exit(2)


def _region_label(result) -> str:
    """결과에 실린 REGION_PACK 판정에서 적용 팩 표시를 뽑는다."""
    if result.compliance:
        for f in result.compliance.findings:
            if f.code == "REGION_PACK":
                return f.actual
    return "-"


def _echo_compliance(report: Optional[ComplianceReport], verbose: bool) -> int:
    """규격검증 요약(및 상세) 출력. 위반 건수 반환."""
    if report is None:
        typer.echo("규격검증: 미수행")
        return 0
    s = report.summary()
    typer.echo(f"규격검증 [Tier {report.tier}]: "
               f"위반 {s['violation']} / 경고 {s['warning']} / 정보 {s['info']}")
    for f in report.findings:
        if f.severity == "info" and not verbose:
            continue
        typer.echo(f"  - [{SEVERITY_LABEL[f.severity]}][{f.code}] {f.message}")
        if verbose:
            typer.echo(f"      설계 {f.actual} / 요구 {f.required} / 근거 {f.rule}")
    return s["violation"]


@app.command()
def build(spec: str = typer.Option(..., help="spec.yaml 경로"),
          out: str = typer.Option("out", help="산출물 폴더"),
          strict: bool = typer.Option(False, "--strict",
                                      help="규격 위반이 있으면 종료코드 1"),
          verbose: bool = typer.Option(False, "--verbose", "-v",
                                       help="정보(info) 판정까지 표시")):
    """사이징 → 규격검증 → 산출물(xlsx·docx·mermaid) 생성."""
    result = _size_or_exit(_load_spec(spec))

    xlsx = write_bom(result, out)
    docx = write_design_basis(result, out)
    mmd = write_diagrams(result, out)

    e = result.electrical
    typer.echo(f"규격 팩: {_region_label(result)}")
    typer.echo(f"랙 {result.rack_count}대 / IT {result.it_power_kw}kW / PUE {e['pue_estimate']}")
    typer.echo(f"UPS {e['ups_qty']}대 / 배터리 {e['battery_energy_kwh']}kWh "
               f"/ 변압기 {e['transformer_qty']}대 / 수전 {e['primary_kv']}kV {e['mv_current_a']}A")
    c, n, sp = result.cooling, result.network, result.space
    typer.echo(f"CDU {c['cdu_qty']}대 / 칠러 {c['chiller_qty']}대 / {c['total_rt']}RT "
               f"/ 유량 {c['coolant_flow_lpm']}L/min")
    typer.echo(f"Leaf {n['leaf_qty']}대 / Spine {n['spine_qty']}대 "
               f"/ 트랜시버 {n['transceiver_qty']}개 / 총면적 {sp['total_building_m2']}m2")

    violations = _echo_compliance(result.compliance, verbose)
    for w in result.warnings:
        typer.echo(f"[경고] {w}")
    for path in (xlsx, docx, mmd):
        typer.echo(f"산출물: {path}")

    if strict and violations:
        typer.echo(f"[중단] --strict: 규격 위반 {violations}건", err=True)
        raise typer.Exit(1)


@app.command()
def check(spec: str = typer.Option(..., help="spec.yaml 경로"),
          verbose: bool = typer.Option(False, "--verbose", "-v",
                                       help="정보(info) 판정까지 표시")):
    """산출물 생성 없이 규격검증만 수행. 위반이 있으면 종료코드 1."""
    result = _size_or_exit(_load_spec(spec))
    violations = _echo_compliance(result.compliance, verbose)
    if violations:
        raise typer.Exit(1)
    typer.echo("규격 위반 없음.")


@app.command()
def catalog(type_: Optional[str] = typer.Option(None, "--type",
                                                help="chip|node|rack|cooling|electrical|network"),
            subtype: Optional[str] = typer.Option(None, "--subtype", help="예: ups, cdu, leaf")):
    """카탈로그 블록 목록 출력(없는 장비는 지어내지 말고 여기서 확인)."""
    blocks = load_blocks()
    rows = [b for b in blocks.values()
            if (type_ is None or b.type == type_)
            and (subtype is None or b.subtype == subtype)]
    if not rows:
        typer.echo("조건에 맞는 블록 없음 — data/*.yaml 에 블록 추가 필요")
        raise typer.Exit(0)
    typer.echo(f"{'id':38} {'type':11} {'subtype':14} {'confidence':11} model")
    for b in sorted(rows, key=lambda x: (x.type, x.id)):
        typer.echo(f"{b.id:38} {b.type:11} {b.subtype or '-':14} "
                   f"{b.confidence:11} {b.model}")
    typer.echo(f"\n총 {len(rows)}개 블록")


@app.command()
def regions():
    """사용 가능한 국가별 규격 팩(rules/regions/*.yaml) 목록."""
    typer.echo(f"{'code':10} {'name':32} {'오버라이드':10} 근거")
    for code in available_regions():
        pack = load_region(code)
        n_override = sum(len(v) for v in (pack.get("overrides") or {}).values())
        typer.echo(f"{code:10} {pack.get('name', '-'):32} "
                   f"{n_override:<10} {pack.get('reference', '-')}")
    typer.echo("\nspec.yaml 의 `region:` 에 code 를 적으면 적용된다.")


@app.command()
def compare(spec: str = typer.Option(..., help="스윕 yaml 경로(project/base/sweep)"),
            out: str = typer.Option("out", help="산출물 폴더"),
            sort: str = typer.Option("total_building_m2", "--sort",
                                     help="정렬 지표(예: pue, rack_count, violations)"),
            desc: bool = typer.Option(False, "--desc", help="내림차순 정렬")):
    """칩세대·이중화·냉각 조건을 스윕해 설계안을 비교한다."""
    p = pathlib.Path(spec)
    if not p.is_file():
        typer.echo(f"[오류] 스윕 파일을 찾을 수 없습니다: {spec}", err=True)
        raise typer.Exit(2)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        typer.echo(f"[오류] 스윕 YAML 파싱 실패: {exc}", err=True)
        raise typer.Exit(2)

    base, sweep = raw.get("base", {}), raw.get("sweep", {})
    project = raw.get("project", "시나리오 비교")
    try:
        rows = scenario.run_sweep(base, sweep)
        rows = scenario.rank(rows, sort, descending=desc)
    except (ValidationError, ValueError, KeyError) as exc:
        typer.echo(f"[오류] {str(exc).strip(chr(39))}", err=True)
        raise typer.Exit(2)

    cols = ["scenario", "rack_count", "it_power_kw", "pue",
            "total_building_m2", "ups_qty", "switch_qty", "violations"]
    widths = {"scenario": 52, "rack_count": 4, "it_power_kw": 9, "pue": 5,
              "total_building_m2": 9, "ups_qty": 4, "switch_qty": 6, "violations": 4}
    head = {"scenario": "시나리오", "rack_count": "랙", "it_power_kw": "IT부하kW",
            "pue": "PUE", "total_building_m2": "면적m2", "ups_qty": "UPS",
            "switch_qty": "스위치", "violations": "위반"}

    def cell(value: object, width: int) -> str:
        text = str(value)
        return f"{text[:width]:<{width}}"

    typer.echo(f"[{project}] {len(rows)}개 시나리오 (정렬: {sort})")
    typer.echo(" ".join(cell(head[c], widths[c]) for c in cols))
    for row in rows:
        if row["error"]:
            typer.echo(f"{cell(row['scenario'], widths['scenario'])} [오류] {row['error']}")
            continue
        typer.echo(" ".join(cell(row[c], widths[c]) for c in cols))

    missing = max((r.get("capex_missing") or 0) for r in rows) if rows else 0
    if missing:
        typer.echo(f"\nCAPEX: 카탈로그 단가(capex_usd) 미보유 블록 {missing}종 — "
                   "비용 비교는 산출하지 않았다(임의 단가 사용 금지).")

    path = write_comparison(rows, project, out)
    typer.echo(f"산출물: {path}")


@app.command("install-agents")
def install_agents(dest: str = typer.Option(".claude/agents", "--dest",
                                            help="설치 폴더(기본: .claude/agents)")):
    """서브에이전트 정의(`dc_design_tool/agents/*.md`)를 대화형 설치 폴더로 복사."""
    src_dir = pathlib.Path(__file__).resolve().parent / "agents"
    dest_dir = pathlib.Path(dest)
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src in sorted(src_dir.glob("*.md")):
        (dest_dir / src.name).write_text(src.read_text(encoding="utf-8"),
                                         encoding="utf-8")
        typer.echo(f"설치: {dest_dir / src.name}")
        copied += 1
    if not copied:
        typer.echo(f"[오류] 에이전트 정의를 찾을 수 없습니다: {src_dir}", err=True)
        raise typer.Exit(2)
    typer.echo(f"에이전트 {copied}종 설치 완료 → {dest_dir}")


if __name__ == "__main__":
    app()
