"""시나리오 비교 엔진: 칩세대·이중화·냉각 조건을 스윕해 설계안을 나란히 비교한다.

CAPEX는 카탈로그에 `capex_usd`가 있는 블록만 합산한다. 값이 없으면 지어내지 않고
'비용 미상 블록 수'로 보고한다(CLAUDE.md 절대규칙 3).
"""
from __future__ import annotations

import itertools
from typing import Any, Optional

from .catalog import load_blocks
from .models import Block, SizingResult, Spec
from .sizing import size

# 비교표에 싣는 지표(순서 유지)
METRICS = ["scenario", "rack_id", "rack_count", "it_power_kw", "accel_total",
           "pue", "total_building_m2", "total_rt", "coolant_flow_lpm",
           "transformer_installed_kva", "ups_qty", "generator_qty", "switch_qty",
           "m2_per_accel", "kw_per_accel", "capex_usd", "capex_missing",
           "violations", "warnings", "error"]


def expand(base: dict, sweep: dict[str, list]) -> list[tuple[str, Spec]]:
    """기준 spec에 스윕 축을 곱해 (시나리오명, Spec) 목록을 만든다.

    Raises:
        ValueError: Spec에 없는 스윕 키이거나 값 목록이 비었을 때.
    """
    valid = set(Spec.model_fields)
    for key, values in sweep.items():
        if key not in valid:
            raise ValueError(f"스윕 키가 Spec 필드에 없다: '{key}' "
                             f"(가능: {', '.join(sorted(valid))})")
        if not values:
            raise ValueError(f"스윕 키 '{key}'의 값 목록이 비었다")

    if not sweep:
        return [("base", Spec(**base))]

    keys = list(sweep)
    rows = []
    for combo in itertools.product(*(sweep[k] for k in keys)):
        overrides = dict(zip(keys, combo))
        name = ", ".join(_axis_label(k, v) for k, v in overrides.items())
        rows.append((name, Spec(**{**base, **overrides})))
    return rows


def _axis_label(key: str, value: Any) -> str:
    """비교표에 실을 축 표기.

    장비 축(selections)은 dict 라 그대로 찍으면 중괄호·따옴표로 표가 읽히지 않는다.
    역할=블록 쌍만 남긴다.
    """
    if isinstance(value, dict):
        return ", ".join(f"{role}={block}" for role, block in value.items()) or key
    return f"{key}={value}"


def size_scenario(base: dict, blocks: Optional[dict[str, Block]] = None) -> SizingResult:
    """단일 시나리오 사이징(비교 엔진 내부용 헬퍼)."""
    return size(Spec(**base), blocks)


def capex(result: SizingResult, blocks: dict[str, Block]) -> tuple[Optional[float], int]:
    """BOM 기준 개산 CAPEX[USD]와 '비용 미상' 블록 수.

    가격이 있는 블록이 하나도 없으면 (None, 미상 수)를 돌려준다.
    """
    total = 0.0
    priced = 0
    missing: set[str] = set()
    for li in result.bom:
        block = blocks.get(li.block_id)
        price = block.interface.capex_usd if block else None
        if price is None:
            if li.block_id:
                missing.add(li.block_id)
            continue
        total += price * li.qty
        priced += 1
    return (total if priced else None), len(missing)


def evaluate(name: str, spec: Spec,
             blocks: Optional[dict[str, Block]] = None) -> dict[str, Any]:
    """한 시나리오를 사이징하고 비교 지표를 뽑는다.

    사이징이 실패해도 예외를 올리지 않고 `error`에 사유를 담아 스윕을 계속한다.
    """
    row: dict[str, Any] = {k: None for k in METRICS}
    row["scenario"] = name
    row["rack_id"] = spec.rack_id
    row["error"] = ""

    blocks = blocks if blocks is not None else load_blocks()
    try:
        r = size(spec, blocks)
    except (KeyError, ValueError) as exc:
        row["error"] = str(exc).strip("'")
        return row

    e, c, s, n = r.electrical, r.cooling, r.space, r.network
    accel = r.it_load.get("accel_total") or 0
    cost, missing = capex(r, blocks)

    row.update({
        "rack_count": r.rack_count,
        "it_power_kw": r.it_power_kw,
        "accel_total": accel,
        "pue": e["pue_estimate"],
        "total_building_m2": s["total_building_m2"],
        "total_rt": c["total_rt"],
        "coolant_flow_lpm": c["coolant_flow_lpm"],
        "transformer_installed_kva": e["transformer_installed_kva"],
        "ups_qty": e["ups_qty"],
        "generator_qty": e["generator_qty"],
        "switch_qty": n["leaf_qty"] + n["spine_qty"],
        "m2_per_accel": round(s["total_building_m2"] / accel, 4) if accel else None,
        "kw_per_accel": round(r.it_power_kw / accel, 3) if accel else None,
        "capex_usd": cost,
        "capex_missing": missing,
        "violations": len(r.compliance.violations) if r.compliance else 0,
        "warnings": len(r.warnings),
    })
    return row


def run_sweep(base: dict, sweep: dict[str, list],
              blocks: Optional[dict[str, Block]] = None) -> list[dict[str, Any]]:
    """스윕 전체를 실행해 비교표 행 목록을 만든다."""
    blocks = blocks if blocks is not None else load_blocks()
    return [evaluate(name, spec, blocks) for name, spec in expand(base, sweep)]


def rank(rows: list[dict[str, Any]], metric: str,
         descending: bool = False) -> list[dict[str, Any]]:
    """지표 기준 정렬. 실패한 시나리오는 항상 뒤로 보낸다.

    Raises:
        ValueError: 비교표에 없는 지표.
    """
    if metric not in METRICS:
        raise ValueError(f"비교 지표가 아니다: '{metric}' (가능: {', '.join(METRICS)})")

    def key(row):
        value = row.get(metric)
        failed = bool(row.get("error")) or value is None
        return (1, 0) if failed else (0, -value if descending else value)

    return sorted(rows, key=key)
