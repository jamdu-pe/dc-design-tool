"""냉각 엔진: 액냉/공냉 분배, 냉각수 유량, CDU·칠러 사이징."""
from __future__ import annotations

from typing import Optional

from . import calc
from .catalog import load_rule, resolve
from .models import Block, LineItem, Spec


def liquid_air_split(it_kw: float, liquid_fraction: float) -> tuple[float, float]:
    """IT 발열을 액냉/공냉으로 분배한다.

    Raises:
        ValueError: 액냉 비율이 0~1 범위를 벗어날 때.
    """
    if not 0.0 <= liquid_fraction <= 1.0:
        raise ValueError(f"액냉 비율은 0~1 이어야 함 (현재 {liquid_fraction})")
    q_liq = it_kw * liquid_fraction
    return q_liq, it_kw - q_liq


def size_cooling(it_kw: float, rack: Block, spec: Spec, blocks: dict[str, Block],
                 redundancy_rules: Optional[dict] = None,
                 selections: Optional[dict[str, str]] = None
                 ) -> tuple[dict, list[LineItem]]:
    """냉각 사이징 결과(dict)와 BOM(list) 반환.

    Args:
        selections: 역할 → block_id. `cdu`·`chiller` 를 교체할 수 있다.
            미지정 역할은 카탈로그 첫 후보를 쓴다. 교체해도 수량·유량은
            아래 `calc.*` 로 재산정한다.

    Raises:
        KeyError: CDU/칠러 블록이 카탈로그에 없거나 선택한 id 가 유효하지 않을 때.
        ValueError: 액냉 비율 또는 ΔT가 유효하지 않을 때.
    """
    red = redundancy_rules or load_rule("redundancy.yaml", spec.region)
    if spec.mechanical_redundancy not in red:
        raise KeyError(f"정의되지 않은 이중화 등급: '{spec.mechanical_redundancy}'")
    rule = red[spec.mechanical_redundancy]

    q_liq, q_air = liquid_air_split(it_kw, rack.interface.liquid_fraction)
    flow = calc.coolant_flow_lpm(q_liq, spec.chw_delta_t_k)
    rt = calc.rt_from_kw(it_kw)

    cdu = resolve("cooling", "cdu", blocks, selections)
    chiller = resolve("cooling", "chiller", blocks, selections)
    n_cdu = calc.redundant_qty(q_liq, cdu.interface.capacity_kw, rule)
    n_chiller = calc.redundant_qty(it_kw, chiller.interface.capacity_kw, rule)

    result = {
        "it_heat_kw": round(it_kw, 1),
        "liquid_kw": round(q_liq, 1),
        "air_kw": round(q_air, 1),
        "liquid_fraction": rack.interface.liquid_fraction,
        "supply_water_c": rack.interface.supply_water_c,
        "chw_delta_t_k": spec.chw_delta_t_k,
        "coolant_flow_lpm": round(flow, 1),
        "total_rt": round(rt, 1),
        "cdu_qty": n_cdu,
        "cdu_unit_kw": cdu.interface.capacity_kw,
        "chiller_qty": n_chiller,
        "chiller_unit_kw": chiller.interface.capacity_kw,
        "redundancy": spec.mechanical_redundancy,
        "selected": {"cdu": cdu.id, "chiller": chiller.id},
    }
    bom = [
        LineItem(domain="기계", item="CDU", model=cdu.model, block_id=cdu.id,
                 unit_capacity=f"{cdu.interface.capacity_kw}kW", qty=n_cdu,
                 note=spec.mechanical_redundancy),
        LineItem(domain="기계", item="칠러", model=chiller.model, block_id=chiller.id,
                 unit_capacity=f"{int(chiller.interface.capacity_kw)}kW", qty=n_chiller,
                 note=spec.mechanical_redundancy),
    ]
    return result, bom
