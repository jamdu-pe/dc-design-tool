"""레고 그래프 솔버: 칩 → 노드 → 랙 롤업과 선언값 일관성 검증.

블록은 `composed_of`(하위 블록 참조 목록)로 상위 블록을 조립한다.
구성이 없는 블록은 `interface`의 선언값을 그대로 돌려주는 리프다.
"""
from __future__ import annotations

from typing import Optional

from .models import Block

# 구성 합과 선언값의 허용 오차(%)
DEFAULT_TOLERANCE_PCT = 5.0


def _get(block_id: str, blocks: dict[str, Block]) -> Block:
    if block_id not in blocks:
        raise KeyError(f"카탈로그 부재: '{block_id}' — data/*.yaml 에 블록 추가 필요")
    return blocks[block_id]


def _rollup(block_id: str, blocks: dict[str, Block], field: str,
            _path: Optional[tuple[str, ...]] = None) -> float:
    """구성 트리를 따라 합산. 리프는 선언값, 상위는 (하위 합 + overhead)."""
    _path = _path or ()
    if block_id in _path:
        raise ValueError(f"구성에 순환 참조가 있다: {' → '.join(_path + (block_id,))}")

    block = _get(block_id, blocks)
    if not block.composed_of:
        return float(getattr(block.interface, field) or 0.0)

    total = 0.0
    for comp in block.composed_of:
        if comp.count <= 0:
            raise ValueError(f"{block_id}: '{comp.id}' 구성 수량은 1 이상이어야 함 "
                             f"(현재 {comp.count})")
        total += _rollup(comp.id, blocks, field, _path + (block_id,)) * comp.count

    if field == "power_kw_typical":
        total += block.interface.overhead_kw
    return total


def composed_power_kw(block_id: str, blocks: dict[str, Block]) -> float:
    """구성으로부터 산출한 전력[kW].

    Raises:
        KeyError: 하위 블록이 카탈로그에 없을 때.
        ValueError: 순환 참조 또는 구성 수량 오류.
    """
    return _rollup(block_id, blocks, "power_kw_typical")


def composed_accel_count(block_id: str, blocks: dict[str, Block]) -> int:
    """구성으로부터 산출한 가속기 수량."""
    return int(_rollup(block_id, blocks, "accel_count"))


def composition_tree(block_id: str, blocks: dict[str, Block],
                     _depth: int = 0, _count: int = 1,
                     _path: Optional[tuple[str, ...]] = None
                     ) -> list[tuple[int, Block, int]]:
    """구성 트리를 (깊이, 블록, 누적 수량) 목록으로 펼친다."""
    _path = _path or ()
    if block_id in _path:
        raise ValueError(f"구성에 순환 참조가 있다: {' → '.join(_path + (block_id,))}")

    block = _get(block_id, blocks)
    rows = [(_depth, block, _count)]
    for comp in block.composed_of:
        rows += composition_tree(comp.id, blocks, _depth + 1,
                                 _count * comp.count, _path + (block_id,))
    return rows


def check_consistency(block_id: str, blocks: dict[str, Block],
                      tolerance_pct: float = DEFAULT_TOLERANCE_PCT) -> dict:
    """선언된 랙 정격과 구성 합이 일치하는지 검증한다.

    구성이 정의되지 않은 블록은 검증 대상이 아니므로 ok=True 로 본다.
    """
    block = _get(block_id, blocks)
    declared = block.interface.power_kw_typical

    if not block.composed_of:
        return {"block_id": block_id, "has_composition": False, "ok": True,
                "declared_kw": declared, "composed_kw": None, "delta_pct": 0.0,
                "declared_accel": block.interface.accel_count,
                "composed_accel": None}

    composed = composed_power_kw(block_id, blocks)
    delta = 0.0 if not declared else (composed - declared) / declared * 100.0
    return {
        "block_id": block_id,
        "has_composition": True,
        "declared_kw": declared,
        "composed_kw": round(composed, 2),
        "delta_pct": round(delta, 2),
        "ok": abs(delta) <= tolerance_pct,
        "declared_accel": block.interface.accel_count,
        "composed_accel": composed_accel_count(block_id, blocks),
    }
