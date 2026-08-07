"""오케스트레이션: Spec → SizingResult.

계산은 각 도메인 엔진이 한다. 이 모듈은 순서와 데이터 전달만 담당한다.
  it_load → cooling → power → network → space → compliance
"""
from __future__ import annotations

from typing import Optional

from . import (compliance, cooling as cooling_engine, it_load,
               network as network_engine, power, space as space_engine)
from .catalog import get_block, list_candidates, load_blocks, load_rule
from .models import Block, SizingResult, Spec

# 교체 가능한 역할(subtype) → 블록 종류(type).
# 이 표가 "설계에서 바꿀 수 있는 장비 축"의 정의다. 도메인 엔진이 실제로 소비하는
# 역할만 싣는다. 역할을 추가하면 해당 subtype 후보 중 하나에 `default: true` 가
# 있어야 한다(tests/test_selection.py 가 강제).
SELECTABLE_ROLES: dict[str, str] = {
    "cdu": "cooling", "chiller": "cooling", "air_cooling": "cooling",
    "ups": "electrical", "battery": "electrical", "generator": "electrical",
    "transformer": "electrical", "pdu": "electrical", "busway": "electrical",
    "leaf": "network", "spine": "network", "transceiver": "network",
}


def _capacity_label(block: Block) -> str:
    """후보 드롭다운에 띄울 용량 표기. 역할마다 의미 있는 필드가 다르다."""
    i = block.interface
    if i.ports and i.port_speed_gbps:
        return f"{i.ports}p x {i.port_speed_gbps}G"
    for value, unit in ((i.capacity_kva, "kVA"), (i.capacity_kw, "kW"),
                        (i.capacity_kwh, "kWh"), (i.rating_a, "A")):
        if value:
            return f"{value:g}{unit}"
    if i.port_speed_gbps:
        return f"{i.port_speed_gbps}G"
    return "-"


def merge_selections(spec: Spec,
                     override: Optional[dict[str, str]] = None) -> dict[str, str]:
    """spec 에 적힌 장비 선택 위에 호출부 선택을 얹는다.

    spec 은 '설계안에 기록된 선택'(spec.yaml·시나리오 스윕), override 는 '지금 화면에서
    바꾼 선택'이다. 역할 단위로 override 가 이긴다.

    Raises:
        ValueError: 교체 가능한 역할이 아닌 키가 섞여 있을 때(오타를 조용히 삼키지 않는다).
    """
    merged = {**(spec.selections or {}), **(override or {})}
    unknown = sorted(set(merged) - set(SELECTABLE_ROLES))
    if unknown:
        raise ValueError(
            f"교체 가능한 역할이 아니다: {', '.join(unknown)} — "
            f"가능: {', '.join(sorted(SELECTABLE_ROLES))}")
    return merged


def _candidate_table(blocks: dict[str, Block],
                     selections: dict[str, str]) -> dict[str, list[dict]]:
    """역할별 후보 목록(UI 드롭다운용). 표시 순서는 카탈로그 등재 순서를 쓰고,
    기본값 표시는 `default` 플래그를 따른다(플래그가 없으면 첫 후보)."""
    table: dict[str, list[dict]] = {}
    for role, type_ in SELECTABLE_ROLES.items():
        candidates = list_candidates(type_, role, blocks)
        default_id = next((b.id for b in candidates if b.default),
                          candidates[0].id if candidates else None)
        table[role] = [{
            "id": b.id, "vendor": b.vendor, "model": b.model,
            "capacity": _capacity_label(b), "confidence": b.confidence,
            "is_default": b.id == default_id,
            "is_selected": b.id == selections.get(role),
        } for b in candidates]
    return table


def size(spec: Spec, blocks: Optional[dict] = None,
         selections: Optional[dict[str, str]] = None) -> SizingResult:
    """요구사항으로부터 M/E/ICT/공간 사이징과 규격검증 결과를 만든다.

    Args:
        spec: 요구사항.
        blocks: 카탈로그 주입(미지정 시 `data/*.yaml` 로드). 시나리오 비교·테스트용.
        selections: 역할(subtype) → block_id. `spec.selections` 위에 얹히며 역할
            단위로 이쪽이 이긴다. 지정하지 않은 역할은 `default: true`가 붙은
            블록을 쓴다. 장비를 바꿔도 수량·용량은 각 도메인 엔진이 `calc.*` 로 재산정한다
            (CLAUDE.md 절대규칙 1). 가능한 역할은 `SELECTABLE_ROLES` 참고.

    Raises:
        KeyError: 카탈로그·규칙에 없는 랙/장비/등급을 참조하거나, 선택한 block_id
            가 없거나 그 역할의 후보가 아닐 때.
        ValueError: 목표(it_power_mw/rack_count) 미지정, 교체 불가 역할 키 등 입력 오류.
    """
    blocks = blocks if blocks is not None else load_blocks()
    rack = get_block(blocks, spec.rack_id)
    selections = merge_selections(spec, selections)

    assumptions: list[str] = []
    warnings: list[str] = []
    bom = []

    # ---- 1) IT 부하 (칩→노드→랙 롤업) ----
    load = it_load.size_it_load(spec, blocks)
    n_rack, rack_kw, it_kw = load["rack_count"], load["rack_kw"], load["it_power_kw"]
    warnings += load["warnings"]
    if rack.confidence == "projected":
        warnings.append(f"{rack.model}: 미출시/추정 사양(projected) — 결과는 개략 추정치")

    # ---- 2) 기계(냉각) ----
    cooling, c_bom = cooling_engine.size_cooling(it_kw, rack, spec, blocks,
                                                 selections=selections,
                                                 rack_count=n_rack, rack_kw=rack_kw)
    bom += c_bom

    # ---- 3) 전기 ----
    # 냉각 소비전력 계수는 rules/cooling.yaml 에서 읽는다(하드코딩 금지).
    cooling_ratio = load_rule("cooling.yaml", spec.region)["cooling_power_ratio"]
    cooling_kw = it_kw * cooling_ratio
    electrical, e_bom = power.size_electrical(
        it_kw, cooling_kw, n_rack, rack_kw, spec, blocks, selections=selections)
    bom += e_bom

    # ---- 4) 통신(ICT) ----
    network, n_bom = network_engine.size_network(n_rack, rack, spec, blocks,
                                                 selections=selections)
    bom += n_bom

    # ---- 5) 공간/구조 ----
    space = space_engine.size_space(n_rack, rack, spec, bom=bom, blocks=blocks)
    if not space["floor_load_ok"]:
        warnings.append(
            f"바닥하중 {space['floor_load_kg_per_m2']}kg/m2 > 허용 "
            f"{space['floor_load_limit_kg_per_m2']}kg/m2 — 구조 보강 검토 필요")

    assumptions += [
        f"랙 정격 {rack_kw}kW({load['power_source']}) 기준, "
        f"액냉비율 {cooling['liquid_fraction']}, 가속기 {load['accel_total']}개",
        f"냉각수 ΔT {spec.chw_delta_t_k}K, "
        f"냉각소비전력 IT의 {int(cooling_ratio * 100)}% 가정(rules/cooling.yaml)",
        "본 산출물은 개념설계/타당성 수준. 실시설계·인허가는 면허기술자 검토 필요.",
    ]

    # 각 도메인이 실제로 고른 블록을 모은다(요청한 selections 가 아니라 결과 기준).
    used = {**cooling["selected"], **electrical["selected"], **network["selected"]}

    result = SizingResult(
        project=spec.project, rack_id=spec.rack_id, rack_count=n_rack,
        it_power_kw=it_kw,
        it_load={k: v for k, v in load.items() if k != "warnings"},
        cooling=cooling, electrical=electrical,
        space=space, network=network, bom=bom,
        assumptions=assumptions, warnings=warnings,
        selections=used, candidates=_candidate_table(blocks, used),
    )

    # ---- 6) 규격검증 ----
    result.compliance = compliance.check(result, spec, blocks)
    warnings.extend(f"[{f.code}] {f.message}" for f in result.compliance.violations)
    return result
