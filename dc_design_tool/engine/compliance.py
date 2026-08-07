"""규격검증: Uptime Tier / ASHRAE / 성능목표 / 구조 / 카탈로그 신뢰도 대조.

판정 기준은 모두 `rules/*.yaml`에서 읽는다. 각 Finding은 근거 규칙을 명시한다.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Optional

from .catalog import get_block, load_blocks, load_region, load_rule
from .models import Block, ComplianceReport, Finding, SizingResult, Spec


def redundancy_rank(grade: str) -> tuple[float, int]:
    """이중화 등급의 서열. `rules/redundancy.yaml`의 계수로부터 유도한다.

    (multiplier, extra) 사전식 비교로 N < N+1 < N+2 < 2N 순서가 된다.

    Raises:
        KeyError: 정의되지 않은 이중화 등급.
    """
    rules = load_rule("redundancy.yaml")
    if grade not in rules:
        raise KeyError(f"정의되지 않은 이중화 등급: '{grade}' — rules/redundancy.yaml 확인")
    r = rules[grade]
    return (float(r.get("multiplier", 1.0)), int(r.get("extra", 0)))


def water_class(supply_water_c: float, classes: dict) -> Optional[str]:
    """공급수온을 수용하는 최소 ASHRAE 수온등급(없으면 None)."""
    for name, limit in sorted(classes.items(), key=lambda kv: kv[1]):
        if supply_water_c <= limit:
            return name
    return None


def surviving_capacity(installed_qty: int, unit_capacity: float, grade: str) -> float:
    """단일 고장(2N은 한 계통 상실) 후 남는 용량.

    N/N+1/N+2 는 1대 상실, 2N 은 설치대수의 절반(한 계통) 상실을 가정한다.
    """
    if grade == "2N":
        return (installed_qty // 2) * unit_capacity
    return max(0, installed_qty - 1) * unit_capacity


def check(result: SizingResult, spec: Spec,
          blocks: Optional[dict[str, Block]] = None,
          today: Optional[dt.date] = None) -> ComplianceReport:
    """사이징 결과를 규격과 대조해 위반·경고·정보 목록을 만든다.

    Args:
        result: 사이징 결과.
        spec: 요구사항.
        blocks: 카탈로그(미지정 시 로드).
        today: 카탈로그 신선도 판정 기준일(미지정 시 오늘).

    Raises:
        KeyError: 정의되지 않은 Tier 또는 이중화 등급.
    """
    blocks = blocks if blocks is not None else load_blocks()
    rack = get_block(blocks, spec.rack_id)

    tiers = load_rule("tiers.yaml", spec.region)["tiers"]
    if spec.tier not in tiers:
        raise KeyError(f"정의되지 않은 Tier: '{spec.tier}' — rules/tiers.yaml 확인")
    tier = tiers[spec.tier]
    ashrae = load_rule("ashrae.yaml", spec.region)
    thresholds = load_rule("compliance.yaml", spec.region)
    region_pack = load_region(spec.region)

    f: list[Finding] = []
    f += _check_region(result, spec, region_pack)
    f += _check_tier(spec, tier)
    f += _check_ashrae(spec, rack, ashrae)
    f += _check_performance(result, spec)
    f += _check_structure(result)
    f += _check_distribution(result)
    f += _check_redundancy_effectiveness(result, spec, thresholds)
    f += _check_air_cooling_rack_capacity(result)
    f += _check_pdu_capacity(result)
    f += _check_room_area(result, thresholds)
    f += _check_network_consistency(result, rack, blocks, thresholds)
    f += _check_catalog(result, rack, blocks)
    f += _check_catalog_freshness(result, rack, blocks, thresholds,
                                  today or dt.date.today())

    return ComplianceReport(tier=spec.tier, findings=f)


# ---------- 개별 검증 ----------

def _check_region(result: SizingResult, spec: Spec, pack: dict) -> list[Finding]:
    """적용 규격 팩과 지역 표준(수전전압·전류 왜형률) 대조.

    `standards`가 비어 있는 팩(generic)은 판정하지 않고 정보만 남긴다.
    """
    rule_src = f"rules/regions/{spec.region}.yaml"
    standards = pack.get("standards") or {}
    e = result.electrical
    out = [Finding(
        code="REGION_PACK", severity="info", domain="전기",
        message=(f"규격 팩 '{pack.get('name', spec.region)}' 적용 "
                 f"— 근거: {pack.get('reference', '미지정')}."
                 + ("" if standards else
                    " 관할 규정이 지정되지 않아 지역 검증(수전전압·왜형률)은 판정하지 않는다.")),
        actual=f"{spec.region} ({pack.get('name', '-')})",
        required="관할 규정 확인 필요", rule=rule_src)]

    kv_list = standards.get("primary_kv")
    if kv_list:
        ok = e["primary_kv"] in kv_list
        out.append(Finding(
            code="REGION_VOLTAGE", severity="info" if ok else "warning", domain="전기",
            message=(f"수전전압 {e['primary_kv']}kV가 지역 표준전압 "
                     f"{kv_list}에 " + ("포함된다." if ok else
                     "없다 — 표준전압으로 재선정하거나 특수 수전 협의가 필요하다.")),
            actual=f"{e['primary_kv']}kV", required=f"{kv_list} 중 하나",
            rule=f"{rule_src}:standards.primary_kv"))

    thd_limit = standards.get("thd_i_limit")
    if thd_limit is not None:
        thd = e["thd_i_assumed"]
        ok = thd <= thd_limit
        out.append(Finding(
            code="REGION_THD", severity="info" if ok else "warning", domain="전기",
            message=(f"가정한 전류 왜형률 {thd * 100:.0f}%가 지역 한계 "
                     f"{thd_limit * 100:.0f}%를 "
                     + ("만족한다." if ok else
                        "초과한다 — 능동필터·K-factor 변압기·12펄스 정류 등 저감대책을 "
                        "반영하고 rules/electrical.yaml 의 가정값을 갱신해야 한다.")),
            actual=f"THD_i {thd * 100:.0f}%", required=f"≤ {thd_limit * 100:.0f}%",
            rule=f"{rule_src}:standards.thd_i_limit"))
    return out


def _check_tier(spec: Spec, tier: dict) -> list[Finding]:
    out = []
    for domain, key, applied in (
        ("전기", "electrical_min", spec.electrical_redundancy),
        ("기계", "mechanical_min", spec.mechanical_redundancy),
    ):
        required = tier[key]
        code = f"TIER_{'ELECTRICAL' if domain == '전기' else 'MECHANICAL'}"
        meets = redundancy_rank(applied) >= redundancy_rank(required)
        out.append(Finding(
            code=code,
            severity="info" if meets else "violation",
            domain=domain,
            message=(f"Tier {spec.tier} {domain} 이중화 요건 {'충족' if meets else '미달'}"
                     + ("" if meets else f" — {required} 이상 필요")),
            actual=applied, required=f"{required} 이상",
            rule="rules/tiers.yaml:tiers"))

    if tier.get("concurrently_maintainable"):
        out.append(Finding(
            code="TIER_CONCURRENT_MAINT", severity="info", domain="전기",
            message=("동시유지보수(concurrently maintainable) 등급 — 모든 급전·냉각 경로에 "
                     "무중단 점검 절체 수단이 필요하다."),
            actual=spec.electrical_redundancy, required="유지보수 절체 경로 확보",
            rule="rules/tiers.yaml:tiers"))
    return out


def _check_ashrae(spec: Spec, rack: Block, ashrae: dict) -> list[Finding]:
    out = []
    classes = ashrae["water_classes"]
    design = ashrae["design"]
    sw = rack.interface.supply_water_c

    if sw is not None:
        cls = water_class(sw, classes)
        max_cls = design["max_water_class"]
        if cls is None:
            out.append(Finding(
                code="ASHRAE_WATER_CLASS", severity="violation", domain="기계",
                message=f"공급수온 {sw}°C가 최고 수온등급({max_cls})을 초과한다.",
                actual=f"{sw}°C", required=f"{max_cls} 이하",
                rule="rules/ashrae.yaml:water_classes"))
        else:
            ok = classes[cls] <= classes[max_cls]
            out.append(Finding(
                code="ASHRAE_WATER_CLASS", severity="info" if ok else "violation",
                domain="기계",
                message=f"액냉 공급수온 {sw}°C → ASHRAE {cls} 등급으로 분류된다.",
                actual=f"{sw}°C ({cls})", required=f"{max_cls} 이하",
                rule="rules/ashrae.yaml:water_classes"))

        approach = design["dry_cooler_approach_k"]
        needed = spec.ambient_design_c + approach
        feasible = needed <= sw
        out.append(Finding(
            code="FREE_COOLING", severity="info" if feasible else "warning",
            domain="기계",
            message=(f"설계외기 {spec.ambient_design_c}°C + 접근온도 {approach}K = {needed}°C "
                     + (f"≤ 공급수온 {sw}°C → 프리쿨링(무냉동기) 운전 가능."
                        if feasible else
                        f"> 공급수온 {sw}°C → 설계조건에서 프리쿨링 불가, 냉동기 상시 운전 전제.")),
            actual=f"외기 {spec.ambient_design_c}°C", required=f"≤ {sw - approach}°C",
            rule="rules/ashrae.yaml:design.dry_cooler_approach_k"))

    air = ashrae["air_classes"][design["air_class"]]
    out.append(Finding(
        code="ASHRAE_AIR_CLASS", severity="info", domain="기계",
        message=(f"잔열 공냉부는 {design['air_class']} 등급 "
                 f"(권장 흡입 {air['recommended_min_c']}~{air['recommended_max_c']}°C, "
                 f"허용 최대 {air['allowable_max_c']}°C)을 적용한다."),
        actual=design["air_class"],
        required=f"흡입 ≤ {air['allowable_max_c']}°C",
        rule="rules/ashrae.yaml:air_classes"))
    return out


def _check_performance(result: SizingResult, spec: Spec) -> list[Finding]:
    est = result.electrical["pue_estimate"]
    ok = est <= spec.target_pue
    return [Finding(
        code="PUE_TARGET", severity="info" if ok else "warning", domain="기계",
        message=(f"추정 PUE {est}가 목표 {spec.target_pue}를 "
                 + ("만족한다." if ok else "초과한다 — 냉각방식·수온·프리쿨링 재검토 필요.")),
        actual=str(est), required=f"≤ {spec.target_pue}",
        rule="spec.target_pue / engine.calc.pue")]


def _check_structure(result: SizingResult) -> list[Finding]:
    s = result.space
    ok = s["floor_load_ok"]
    return [Finding(
        code="FLOOR_LOAD", severity="info" if ok else "violation", domain="공간",
        message=(f"랙 바닥하중 {s['floor_load_kg_per_m2']}kg/m2가 허용 "
                 f"{s['floor_load_limit_kg_per_m2']}kg/m2를 "
                 + ("만족한다." if ok else "초과한다 — 슬래브 보강 또는 랙 분산배치 필요.")),
        actual=f"{s['floor_load_kg_per_m2']}kg/m2",
        required=f"≤ {s['floor_load_limit_kg_per_m2']}kg/m2",
        rule="rules/space.yaml:structure.floor_load_limit_kg_per_m2")]


def _check_distribution(result: SizingResult) -> list[Finding]:
    e = result.electrical
    ok = e["busway_rating_sufficient"]
    return [Finding(
        code="BUSWAY_RATING", severity="info" if ok else "violation", domain="전기",
        message=(f"버스웨이 정격 {e['busway_rating_a']}A가 열(row) 부하전류 "
                 f"{e['busway_row_current_a']}A(랙 {e['rack_current_a']}A x "
                 f"{e['racks_per_row']}대)를 "
                 + ("수용한다." if ok else
                    "수용하지 못한다 — 표준 정격 상한 초과. 열당 랙수 축소, "
                    "열당 버스웨이 분할, 또는 급전전압 상향이 필요하다.")),
        actual=f"{e['busway_rating_a']}A", required=f"≥ {e['busway_row_current_a']}A",
        rule="rules/electrical.yaml:distribution.busway_standard_a "
             "+ rules/space.yaml:white_space.racks_per_row")]


def _check_redundancy_effectiveness(result: SizingResult, spec: Spec,
                                    th: dict) -> list[Finding]:
    """단일 고장 후 잔여 용량이 필요 용량을 감당하는지 실제로 계산해 확인한다.

    이중화 '등급 표기'가 아니라 '올림 처리 후 실제 설치대수'로 판정하므로,
    N+1 표기인데 사실상 여유가 없는 경우를 잡아낸다.
    """
    min_ratio = th["redundancy"]["min_surviving_ratio"]
    e, c = result.electrical, result.cooling
    out = []

    cases = [
        ("ELECTRICAL", "전기", spec.electrical_redundancy, "UPS",
         e["ups_qty"], e["ups_unit_capacity_kva"], e["ups_need_kva"], "kVA"),
        ("MECHANICAL", "기계", spec.mechanical_redundancy, "CDU",
         c["cdu_qty"], c["cdu_unit_kw"], c["liquid_kw"], "kW"),
    ]
    # 실 장착형 공냉장비만 이중화 대상이다. 랙 장착형은 랙당 1대라 여분을 둘 수 없어
    # 아래 _check_air_cooling_rack_capacity 가 대신 본다.
    if c.get("air_cooling_mounting") == "room":
        cases.append(
            ("AIR_COOLING", "기계", spec.mechanical_redundancy, "공냉장비",
             c["air_cooling_qty"], c["air_cooling_unit_kw"], c["air_kw"], "kW"))
    for suffix, domain, grade, item, qty, unit, need, unit_label in cases:
        surviving = surviving_capacity(qty, unit, grade)
        ok = need <= 0 or surviving >= need * min_ratio
        lost = "한 계통" if grade == "2N" else "1대"
        out.append(Finding(
            code=f"REDUNDANCY_EFFECTIVE_{suffix}",
            severity="info" if ok else "warning", domain=domain,
            message=(f"{item} {qty}대({grade}) 중 {lost} 상실 시 잔여 "
                     f"{surviving:g}{unit_label} — 필요 {need:g}{unit_label}를 "
                     + ("감당한다." if ok else
                        "감당하지 못한다. 등급 상향 또는 단위용량 조정이 필요하다.")),
            actual=f"잔여 {surviving:g}{unit_label}",
            required=f"≥ {need * min_ratio:g}{unit_label}",
            rule="rules/redundancy.yaml + rules/compliance.yaml:redundancy"))
    return out


def _check_air_cooling_rack_capacity(result: SizingResult) -> list[Finding]:
    """랙 장착형 공냉장비의 단위용량이 랙당 공냉 부하를 감당하는지 확인.

    랙 후면에 1대만 붙으므로 대수를 늘려 보완할 수 없다 — 미달이면 위반이다.
    실 장착형은 이 검사 대상이 아니다(_check_redundancy_effectiveness 가 본다).
    """
    c = result.cooling
    if c.get("air_cooling_mounting") != "rack":
        return []
    unit, need = c["air_cooling_unit_kw"], c["rack_air_kw"]
    ok = unit >= need
    return [Finding(
        code="AIR_COOLING_RACK_CAPACITY", severity="info" if ok else "violation",
        domain="기계",
        message=(f"랙 장착형 공냉장비 단위용량 {unit}kW가 랙당 공냉 잔열 "
                 f"{need}kW를 "
                 + ("감당한다." if ok else
                    "감당하지 못한다 — 랙당 1대만 설치할 수 있어 대수로 보완할 수 "
                    "없다. 상위 용량 도어 또는 실 단위 방식(CRAH)으로 교체해야 한다.")
                 + f" (랙 {c['air_cooling_qty']}대에 각 1대)"),
        actual=f"{unit}kW/랙", required=f">= {need}kW",
        rule="data/cooling.yaml:air_cooling.capacity_kw "
             "+ data/racks.yaml:liquid_fraction")]


def _check_pdu_capacity(result: SizingResult) -> list[Finding]:
    """랙당 급전 경로별 PDU 용량이 랙 부하를 감당하는지 확인."""
    e = result.electrical
    per_feed_kw = e["pdu_per_feed"] * e["pdu_unit_kw"]
    ok = per_feed_kw >= e["rack_kw"]
    return [Finding(
        code="PDU_CAPACITY", severity="info" if ok else "violation", domain="전기",
        message=(f"급전 경로당 PDU {e['pdu_per_feed']}대 x {e['pdu_unit_kw']}kW "
                 f"= {per_feed_kw}kW가 랙 부하 {e['rack_kw']}kW를 "
                 + ("감당한다." if ok else "감당하지 못한다 — 상위 용량 PDU가 필요하다.")
                 + f" (경로 {e['feeds_per_rack']}, 랙당 총 {e['pdu_per_rack']}대)"),
        actual=f"{per_feed_kw}kW/경로", required=f"≥ {e['rack_kw']}kW",
        rule="data/electrical.yaml:pdu.capacity_kw "
             "+ rules/electrical.yaml:distribution.feeds_per_rack")]


def _check_room_area(result: SizingResult, th: dict) -> list[Finding]:
    """부속실 면적 대비 장비 점유율 — 통로 없이 장비만 꽉 찬 면적을 차단."""
    s = result.space
    limit = th["area"]["max_equipment_utilization"]
    worst_ratio, worst_name = 0.0, ""
    for name, equip, room in (("전기실", s["electrical_equipment_m2"], s["electrical_room_m2"]),
                              ("기계실", s["mechanical_equipment_m2"], s["mechanical_room_m2"])):
        ratio = equip / room if room else 0.0
        if ratio > worst_ratio:
            worst_ratio, worst_name = ratio, name
    ok = worst_ratio <= limit
    return [Finding(
        code="ME_ROOM_AREA", severity="info" if ok else "violation", domain="공간",
        message=(f"부속실 장비 점유율 최대 {worst_ratio * 100:.0f}%"
                 + (f" ({worst_name})" if worst_name else "")
                 + (f" — 허용 {limit * 100:.0f}% 이내." if ok else
                    f" — 허용 {limit * 100:.0f}%를 초과한다. 유지보수 통로·반입동선 확보 불가.")
                 + f" 전기실 {s['electrical_equipment_m2']}/{s['electrical_room_m2']}m2, "
                   f"기계실 {s['mechanical_equipment_m2']}/{s['mechanical_room_m2']}m2 "
                   f"(옥외 설치 장비 제외)"),
        actual=f"{worst_ratio * 100:.0f}%", required=f"≤ {limit * 100:.0f}%",
        rule="rules/space.yaml:support_area + rules/compliance.yaml:area")]


def _check_network_consistency(result: SizingResult, rack: Block,
                               blocks: dict[str, Block], th: dict) -> list[Finding]:
    """랙/스위치 포트속도 정합 + 스위치가 차지하는 별도 랙 공간."""
    n = result.network
    out = []

    leaf = next((b for b in blocks.values()
                 if b.type == "network" and b.subtype == "leaf"), None)
    rack_speed = rack.interface.port_speed_gbps
    sw_speed = leaf.interface.port_speed_gbps if leaf else None
    if rack_speed and sw_speed:
        ok = rack_speed == sw_speed
        out.append(Finding(
            code="PORT_SPEED_MATCH", severity="info" if ok else "warning", domain="통신",
            message=(f"랙 포트속도 {rack_speed}G와 스위치 포트속도 {sw_speed}G가 "
                     + ("일치한다." if ok else
                        "불일치한다 — 브레이크아웃 케이블 또는 상위 속도 스위치 블록이 필요하다.")),
            actual=f"랙 {rack_speed}G / 스위치 {sw_speed}G",
            required="동일 속도 또는 브레이크아웃 설계",
            rule="data/racks.yaml:port_speed_gbps + data/network.yaml:port_speed_gbps"))

    u_per_rack = th["network"]["rack_units_per_network_rack"]
    sw_u = sum((blocks[li.block_id].interface.rack_units or 0) * li.qty
               for li in result.bom
               if li.domain == "통신" and li.block_id in blocks
               and blocks[li.block_id].subtype in ("leaf", "spine"))
    n_net_rack = math.ceil(sw_u / u_per_rack) if sw_u else 0
    out.append(Finding(
        code="NETWORK_RACK_SPACE", severity="info", domain="통신",
        message=(f"Leaf {n['leaf_qty']}대 + Spine {n['spine_qty']}대 = {sw_u}U → "
                 f"네트워크 랙 약 {n_net_rack}대가 추가로 필요하다. "
                 "이 수량은 IT 랙 수·화이트스페이스에 포함되어 있지 않다."),
        actual=f"{n_net_rack} 랙 ({sw_u}U)",
        required=f"화이트스페이스에 별도 반영 (랙당 {u_per_rack}U)",
        rule="data/network.yaml:rack_units + rules/compliance.yaml:network"))
    return out


def _check_catalog_freshness(result: SizingResult, rack: Block,
                             blocks: dict[str, Block], th: dict,
                             today: dt.date) -> list[Finding]:
    """`as_of_date`가 오래된 블록 경고 — 사양은 세대교체가 빠르다."""
    max_age = th["catalog"]["max_age_months"]
    used_ids = {li.block_id for li in result.bom if li.block_id} | {rack.id}
    stale = []
    for bid in sorted(used_ids):
        b = blocks.get(bid)
        if b is None or not b.as_of_date:
            continue
        try:
            y, m = (int(x) for x in b.as_of_date.split("-")[:2])
        except ValueError:
            continue
        age = (today.year - y) * 12 + (today.month - m)
        if age > max_age:
            stale.append(f"{b.model}({b.as_of_date}, {age}개월)")
    if not stale:
        return [Finding(
            code="CATALOG_FRESHNESS", severity="info", domain="카탈로그",
            message=f"사용된 카탈로그 블록의 사양 기준일이 모두 {max_age}개월 이내다.",
            actual=f"기준일 {today.isoformat()}", required=f"≤ {max_age}개월",
            rule="data/*.yaml:as_of_date + rules/compliance.yaml:catalog")]
    return [Finding(
        code="CATALOG_FRESHNESS", severity="warning", domain="카탈로그",
        message=(f"사양 기준일이 {max_age}개월을 초과한 블록: {', '.join(stale)}. "
                 "벤더 최신 사양으로 갱신해야 한다."),
        actual=f"{len(stale)}종 노후", required=f"≤ {max_age}개월",
        rule="data/*.yaml:as_of_date + rules/compliance.yaml:catalog")]


def _check_catalog(result: SizingResult, rack: Block,
                   blocks: dict[str, Block]) -> list[Finding]:
    """`projected`(미출시 추정) 블록 사용 시 '추정' 워터마크 경고."""
    used_models = {li.model for li in result.bom}
    projected = [b for b in blocks.values()
                 if b.confidence == "projected"
                 and (b.id == rack.id or b.model in used_models)]
    if not projected:
        return []
    names = ", ".join(sorted(b.model for b in projected))
    return [Finding(
        code="CATALOG_PROJECTED", severity="warning", domain="카탈로그",
        message=(f"추정(projected) 사양 사용: {names}. 결과는 개략 추정치이므로 "
                 "벤더 확정값으로 갱신해야 한다."),
        actual="confidence=projected", required="measured 또는 vendor",
        rule="data/*.yaml:confidence")]
