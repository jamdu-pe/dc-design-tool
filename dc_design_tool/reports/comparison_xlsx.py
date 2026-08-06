"""시나리오 비교표 Excel 산출."""
from __future__ import annotations

import pathlib
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font

from ..engine.scenario import METRICS

HEADERS = {
    "scenario": "시나리오", "rack_id": "랙 모델", "rack_count": "랙 수",
    "it_power_kw": "IT부하(kW)", "accel_total": "가속기 수", "pue": "PUE(추정)",
    "total_building_m2": "총 건축면적(m2)", "total_rt": "냉동톤(RT)",
    "coolant_flow_lpm": "냉각수 유량(L/min)",
    "transformer_installed_kva": "변압기 설치용량(kVA)", "ups_qty": "UPS 수",
    "generator_qty": "발전기 수", "switch_qty": "스위치 수",
    "m2_per_accel": "가속기당 면적(m2)", "kw_per_accel": "가속기당 부하(kW)",
    "capex_usd": "CAPEX(USD)", "capex_missing": "비용 미상 블록 수",
    "violations": "규격 위반", "warnings": "경고", "error": "오류",
}


def write_comparison(rows: list[dict[str, Any]], project: str, out_dir: str) -> str:
    """비교표를 xlsx로 저장하고 경로를 반환한다."""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    s = wb.active
    s.title = "시나리오비교"
    s.append([HEADERS[m] for m in METRICS])
    for c in s[1]:
        c.font = Font(bold=True)
    for row in rows:
        s.append([row.get(m) for m in METRICS])
    s.freeze_panes = "B2"

    n = wb.create_sheet("판독 안내")
    n.append(["항목", "내용"])
    for c in n[1]:
        c.font = Font(bold=True)
    priced = any(r.get("capex_usd") is not None for r in rows)
    n.append(["프로젝트", project])
    n.append([
        "CAPEX",
        ("일부 장비만 카탈로그에 단가가 있어 부분 합계다. '비용 미상 블록 수'만큼 누락돼 있다."
         if priced else
         "카탈로그에 장비 단가(capex_usd)가 없어 산출하지 않았다. "
         "임의 단가를 지어내지 않으며, data/*.yaml 에 출처 있는 capex_usd 를 채우면 자동 반영된다."),
    ])
    n.append(["규격 위반", "위반이 1건 이상인 안은 설계 변경 또는 등급 재설정이 필요하다."])
    n.append(["오류", "카탈로그 부재 등으로 사이징이 불가능했던 조합. 나머지 비교에는 영향 없다."])
    n.append(["고지", "개념설계/타당성 수준. 실시설계·인허가는 면허기술자 검토 필요."])

    path = out / "시나리오비교.xlsx"
    wb.save(path)
    return str(path)
