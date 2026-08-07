"""계통 다이어그램(mermaid) 자동생성: 전기 단선도·냉각 계통·통신 패브릭.

수치는 모두 SizingResult(엔진 산출물)에서 가져온다. 다이어그램에서 값을 새로 만들지 않는다.
"""
from __future__ import annotations

import pathlib

from ..engine.models import SizingResult


def _node(node_id: str, label: str, shape: str = "box") -> str:
    """라벨을 항상 따옴표로 감싼 mermaid 노드 선언(괄호·단위 기호 안전)."""
    open_b, close_b = {"box": ("[", "]"), "round": ("(", ")"),
                       "cyl": ("[(", ")]")}[shape]
    return f'    {node_id}{open_b}"{label}"{close_b}'


def electrical_single_line(result: SizingResult) -> str:
    """전기 단선도(개념): 수전 → 변압기 → UPS → 버스웨이/PDU → 랙, 발전기 백업."""
    e = result.electrical
    lines = [
        "flowchart LR",
        _node("UTIL", f"수전 {e['primary_kv']}kV / {e['mv_current_a']}A", "round"),
        _node("MVSG", "특고압 수배전반 (MV SWGR)"),
        _node("TX", f"변압기 {e['transformer_unit_kva']}kVA x {e['transformer_qty']}대"),
        _node("LVSG", "저압 배전반 (LV SWGR)"),
        _node("GEN", f"발전기 {e['generator_unit_kw']}kW x {e['generator_qty']}대 "
                     f"(필요 {e['generator_need_kw']}kW)"),
        _node("ATS", "절체장치 (ATS/STS)"),
        _node("UPS", f"UPS {e['ups_unit_kva']}kVA x {e['ups_qty']}대 ({e['redundancy']})"),
        _node("BAT", f"배터리 {e['battery_energy_kwh']}kWh / 자립 {e['battery_autonomy_min']}분", "cyl"),
        _node("BUS", f"버스웨이 {e['busway_rating_a']}A x {e['busway_qty']}조 "
                     f"(열전류 {e['busway_row_current_a']}A)"),
        _node("PDU", f"랙 PDU {e['pdu_qty']}대"),
        _node("RACK", f"IT 랙 {result.rack_count}대 / {result.it_power_kw}kW"),
        "    UTIL --> MVSG --> TX --> LVSG --> ATS --> UPS --> BUS --> PDU --> RACK",
        "    GEN --> ATS",
        "    UPS --- BAT",
    ]
    return "\n".join(lines)


def cooling_loop(result: SizingResult) -> str:
    """냉각 계통도(개념): 랙 D2C 액냉 루프 + 잔열 공냉 루프 → 열원."""
    c = result.cooling
    lines = [
        "flowchart LR",
        _node("RACK", f"IT 랙 {result.rack_count}대 / 발열 {c['it_heat_kw']}kW"),
        _node("TCS", f"액냉 TCS 루프 {c['liquid_kw']}kW / {c['coolant_flow_lpm']}L/min"),
        _node("AIR", f"공냉 잔열 {c['air_kw']}kW / "
                     f"{c['air_cooling_method']} {c['air_cooling_qty']}대"),
        _node("CDU", f"CDU {c['cdu_qty']}대 ({c['redundancy']})"),
        _node("CHW", "냉수 (FWS/CHW) 헤더"),
        _node("CH", f"칠러 {c['chiller_qty']}대 / {c['total_rt']}RT"),
        _node("CT", "냉각탑·드라이쿨러 (열방출)", "round"),
        "    RACK --> TCS --> CDU --> CHW",
        "    RACK --> AIR --> CHW",
        "    CHW --> CH --> CT",
    ]
    return "\n".join(lines)


def network_fabric(result: SizingResult) -> str:
    """스케일아웃 패브릭도(개념): 랙 → Leaf → Spine."""
    n = result.network
    lines = [
        "flowchart TB",
        _node("SPINE", f"Spine 스위치 {n['spine_qty']}대"),
        _node("LEAF", f"Leaf 스위치 {n['leaf_qty']}대 (오버섭 {n['oversubscription']}:1)"),
        _node("RACK", f"IT 랙 {result.rack_count}대 / 호스트포트 {n['scaleout_ports']}p"),
        _node("XCVR", f"트랜시버 {n['transceiver_qty']}개 / 광링크 {n['cable_qty']}본", "round"),
        f"    SPINE ---|\"패브릭링크 {n['fabric_link_qty']}\"| LEAF",
        f"    LEAF ---|\"{n['port_speed_gbps']}G 다운링크\"| RACK",
        "    XCVR -.-> LEAF",
    ]
    return "\n".join(lines)


def write_diagrams(result: SizingResult, out_dir: str) -> str:
    """3종 계통도를 mermaid 코드블록으로 담은 마크다운 파일 생성. 경로 반환."""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sections = [
        ("1. 전기 단선도 (Single Line Diagram)", electrical_single_line(result)),
        ("2. 냉각 계통도 (Cooling Loop)", cooling_loop(result)),
        ("3. 통신 패브릭 (Leaf-Spine Fabric)", network_fabric(result)),
    ]
    body = [f"# 계통 다이어그램 — {result.project}", "",
            f"랙 {result.rack_count}대 / IT부하 {result.it_power_kw}kW "
            f"/ PUE(추정) {result.electrical['pue_estimate']}", ""]
    for title, src in sections:
        body += [f"## {title}", "", "```mermaid", src, "```", ""]
    body += ["---", "",
             "> 본 계통도는 개념설계/타당성 수준의 개략도이며, 보호협조·차단용량·배관 상세는 "
             "포함하지 않는다. 실시설계·인허가는 면허기술자 검토가 필요하다."]

    path = out / "계통도.md"
    path.write_text("\n".join(body), encoding="utf-8")
    return str(path)
