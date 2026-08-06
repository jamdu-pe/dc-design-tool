"""IT 부하 엔진: 칩→노드→랙 구성으로부터 랙 정격과 총 IT부하를 산출한다."""
from __future__ import annotations

import math

from . import compose
from .catalog import get_block
from .models import Block, Spec


def rack_power_kw(rack: Block, blocks: dict[str, Block]) -> float:
    """랙 1대의 전력[kW].

    벤더 선언 정격(`power_kw_typical`)이 있으면 그것을 쓰고, 없으면 구성 합으로 산출한다.
    (선언값이 권위 있고, 구성 합은 교차검증용이다.)

    Raises:
        ValueError: 선언값도 구성도 없어 전력을 결정할 수 없을 때.
    """
    declared = rack.interface.power_kw_typical
    if declared:
        return float(declared)
    if rack.composed_of:
        return compose.composed_power_kw(rack.id, blocks)
    raise ValueError(f"{rack.id}: power_kw_typical 또는 composed_of 중 하나는 필요")


def rack_count_for(spec: Spec, rack_kw: float) -> int:
    """목표 IT부하 또는 명시 랙수로부터 랙 수량 산정.

    Raises:
        ValueError: 목표가 없거나 랙 전력이 0 이하일 때.
    """
    if spec.rack_count:
        return spec.rack_count
    if not spec.it_power_mw:
        raise ValueError("it_power_mw 또는 rack_count 중 하나는 필요")
    if rack_kw <= 0:
        raise ValueError("랙 전력은 0보다 커야 함")
    return math.ceil(spec.it_power_mw * 1000 / rack_kw)


def size_it_load(spec: Spec, blocks: dict[str, Block]) -> dict:
    """IT 부하 사이징 결과 반환(랙 정격·수량·총 부하·가속기 수·경고).

    선언 정격과 구성 합이 어긋나면 경고를 남긴다(카탈로그 품질 신호).
    """
    rack = get_block(blocks, spec.rack_id)
    declared = rack.interface.power_kw_typical
    rack_kw = rack_power_kw(rack, blocks)
    n_rack = rack_count_for(spec, rack_kw)

    warnings: list[str] = []
    consistency = compose.check_consistency(rack.id, blocks)
    if consistency["has_composition"] and not consistency["ok"]:
        warnings.append(
            f"{rack.model}: 선언 정격 {consistency['declared_kw']}kW와 "
            f"구성 합 {consistency['composed_kw']}kW가 "
            f"{consistency['delta_pct']:+.1f}% 어긋난다 — 카탈로그 확인 필요")

    accel_per_rack = rack.interface.accel_count or (
        compose.composed_accel_count(rack.id, blocks) if rack.composed_of else 0)

    return {
        "rack_id": rack.id,
        "rack_kw": rack_kw,
        "rack_count": n_rack,
        "it_power_kw": round(n_rack * rack_kw, 1),
        "accel_per_rack": accel_per_rack,
        "accel_total": n_rack * accel_per_rack,
        "power_source": "declared" if declared else "composed",
        "composition": consistency,
        "warnings": warnings,
    }
