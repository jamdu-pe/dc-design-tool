"""공간/구조 사이징: 화이트스페이스·부속실 면적·바닥하중·층고.

계수는 `rules/space.yaml`에서 읽는다(하드코딩 금지).
"""
from __future__ import annotations

import math
from typing import Optional

from .catalog import load_rule
from .models import Block, LineItem, Spec


def white_space_m2(rack_count: int, footprint_m2: float, aisle_factor: float) -> float:
    """화이트스페이스 면적[m2] = 랙수 × 랙 점유면적 × 통로계수.

    Raises:
        ValueError: 통로계수가 0 이하일 때.
    """
    if aisle_factor <= 0:
        raise ValueError("통로계수(aisle_factor)는 0보다 커야 함")
    return rack_count * footprint_m2 * aisle_factor


def floor_load_kg_per_m2(weight_kg: float, footprint_m2: float) -> float:
    """랙 점유면적 기준 바닥하중[kg/m2].

    Raises:
        ValueError: 점유면적이 0 이하일 때.
    """
    if footprint_m2 <= 0:
        raise ValueError("랙 점유면적(footprint_m2)은 0보다 커야 함")
    return weight_kg / footprint_m2


def rack_rows(rack_count: int, racks_per_row: int) -> int:
    """랙 열(row) 수 = ceil(랙수 / 열당 랙수).

    Raises:
        ValueError: 열당 랙수가 0 이하일 때.
    """
    if racks_per_row <= 0:
        raise ValueError("열당 랙수(racks_per_row)는 0보다 커야 함")
    return math.ceil(rack_count / racks_per_row)


def indoor_equipment_area_m2(bom: list[LineItem], blocks: dict[str, Block],
                             domain: str) -> float:
    """해당 도메인 BOM 중 **실내 설치** 장비의 footprint 합[m2].

    옥외/야드 설치(발전기·냉각탑 등)는 실내 부속실 면적에 포함하지 않는다.
    """
    total = 0.0
    for li in bom:
        if li.domain != domain or not li.block_id:
            continue
        block = blocks.get(li.block_id)
        if block is None or block.interface.location != "indoor":
            continue
        total += (block.interface.footprint_m2 or 0.0) * li.qty
    return total


def size_space(rack_count: int, rack: Block, spec: Optional[Spec] = None,
               rules: Optional[dict] = None,
               bom: Optional[list[LineItem]] = None,
               blocks: Optional[dict[str, Block]] = None) -> dict:
    """공간/구조 사이징 결과(dict) 반환.

    Args:
        rack_count: 랙 수량.
        rack: 랙 블록(footprint_m2·weight_kg 사용).
        spec: 요구사항(현재는 미사용, 지역 규정 확장 대비).
        rules: `rules/space.yaml` 대체 계수(테스트/시나리오용).
        bom: 장비 BOM. 주어지면 부속실 면적을 실제 장비 footprint 기반으로 산정한다.
        blocks: 카탈로그(bom 과 함께 필요).
    """
    r = rules or load_rule("space.yaml", spec.region if spec else None)
    ws_rule, sup, st = r["white_space"], r["support_area"], r["structure"]

    fp = rack.interface.footprint_m2 or 1.2
    weight = rack.interface.weight_kg or 0.0

    rack_area = rack_count * fp
    white = white_space_m2(rack_count, fp, ws_rule["aisle_factor"])

    # 부속실: 비율 추정과 장비 기반 소요면적 중 큰 값(장비가 안 들어가는 면적 방지)
    clearance = sup["equipment_clearance_factor"]
    elec_equip = mech_equip = 0.0
    if bom and blocks:
        elec_equip = indoor_equipment_area_m2(bom, blocks, "전기")
        mech_equip = indoor_equipment_area_m2(bom, blocks, "기계")
    elec_room = max(white * sup["electrical_room_factor"], elec_equip * clearance)
    mech_room = max(white * sup["mechanical_room_factor"], mech_equip * clearance)
    support = white * sup["support_factor"]

    load = floor_load_kg_per_m2(weight, fp)
    limit = st["floor_load_limit_kg_per_m2"]

    return {
        "rack_footprint_m2": round(rack_area, 1),
        "white_space_m2": round(white, 1),
        "electrical_room_m2": round(elec_room, 1),
        "electrical_equipment_m2": round(elec_equip, 1),
        "mechanical_room_m2": round(mech_room, 1),
        "mechanical_equipment_m2": round(mech_equip, 1),
        "equipment_clearance_factor": clearance,
        "support_area_m2": round(support, 1),
        "total_building_m2": round(white + elec_room + mech_room + support, 1),
        "rack_rows": rack_rows(rack_count, ws_rule["racks_per_row"]),
        "racks_per_row": ws_rule["racks_per_row"],
        "floor_load_kg_per_m2": round(load, 0),
        "floor_load_limit_kg_per_m2": limit,
        "floor_load_ok": load <= limit,
        "clear_height_mm": st["clear_height_mm"],
    }
