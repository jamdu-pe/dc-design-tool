"""전기 상세 사이징: UPS·배터리·발전기·변압기/수전·버스웨이/PDU·고조파·이중화."""
from __future__ import annotations
import math
from typing import Optional
from .models import LineItem, Block
from . import calc
from .catalog import load_rule, resolve


def size_electrical(it_kw: float, cooling_kw: float, rack_count: int,
                    rack_kw: float, spec, blocks: dict[str, Block],
                    selections: Optional[dict[str, str]] = None):
    """전기 상세 결과(dict)와 BOM(list) 반환.

    Args:
        selections: 역할 → block_id. `ups`·`battery`·`generator`·`transformer`
            ·`pdu`·`busway` 를 교체할 수 있다. 미지정 역할은 카탈로그 첫 후보를
            쓴다. 교체해도 필요용량·대수는 아래 `calc.*` 로 재산정한다.
    """
    red = load_rule("redundancy.yaml", spec.region)
    el = load_rule("electrical.yaml", spec.region)
    e_rule = red[spec.electrical_redundancy]

    pf = 0.95
    dist = el["distribution"]
    harm = el["harmonic"]
    house_kw = it_kw * 0.10
    facility_kw = it_kw + cooling_kw + house_kw

    bom: list[LineItem] = []

    # --- UPS ---
    ups = resolve("electrical", "ups", blocks, selections)
    need_kva = calc.ups_kva(it_kw, pf, ups.interface.efficiency,
                            el["demand"]["design_margin"])
    n_ups = calc.redundant_qty(need_kva, ups.interface.capacity_kva, e_rule)
    bom.append(LineItem(domain="전기", item="UPS", model=ups.model, block_id=ups.id,
                        unit_capacity=f"{int(ups.interface.capacity_kva)}kVA",
                        qty=n_ups, note=spec.electrical_redundancy))

    # --- 배터리(자립시간) ---
    autonomy = el["autonomy_min_by_tier"].get(spec.tier, 10)
    e_kwh = calc.battery_energy_kwh(it_kw, autonomy,
                                    el["battery"]["depth_of_discharge"],
                                    el["battery"]["inverter_eff"])
    bat = resolve("electrical", "battery", blocks, selections)
    n_bat = calc.redundant_qty(e_kwh, bat.interface.capacity_kwh, e_rule)
    bom.append(LineItem(domain="전기", item="배터리", model=bat.model, block_id=bat.id,
                        unit_capacity=f"{int(bat.interface.capacity_kwh)}kWh",
                        qty=n_bat, note=f"자립 {autonomy}분"))

    # --- 발전기(고조파/스텝부하 여유) ---
    gen = resolve("electrical", "generator", blocks, selections)
    gen_kw = calc.generator_kw(it_kw, cooling_kw) * harm["generator_factor"]
    n_gen = calc.redundant_qty(gen_kw, gen.interface.capacity_kw, e_rule)
    bom.append(LineItem(domain="전기", item="발전기", model=gen.model, block_id=gen.id,
                        unit_capacity=f"{int(gen.interface.capacity_kw)}kW",
                        qty=n_gen, note=f"고조파여유 x{harm['generator_factor']}"))

    # --- 변압기/수전 ---
    tx = resolve("electrical", "transformer", blocks, selections)
    tx_kva = calc.transformer_kva(facility_kw, pf, harm["transformer_factor"],
                                  el["demand"]["design_margin"])
    n_tx = calc.redundant_qty(tx_kva, tx.interface.capacity_kva, e_rule)
    primary_kv = tx.interface.primary_kv or dist["primary_kv"]
    # 수전 전류는 §4 식대로 '부하 기준'이다. 이중화로 변압기를 2배 설치해도
    # 수전 계약전력·인입 케이블은 부하로 결정되므로 설치용량으로 계산하지 않는다.
    mv_demand_kw = facility_kw * (1 + el["demand"]["design_margin"])
    mv_current = calc.line_current_a(mv_demand_kw, primary_kv * 1000, pf)
    bom.append(LineItem(domain="전기", item="변압기", model=tx.model, block_id=tx.id,
                        unit_capacity=f"{int(tx.interface.capacity_kva)}kVA",
                        qty=n_tx, note=f"수전 {primary_kv}kV"))

    # --- 랙 급전(버스웨이/PDU) ---
    v_rack = dist["rack_voltage_v"]
    i_rack = calc.line_current_a(rack_kw, v_rack, pf)
    # 랙 PDU: 급전 경로 수 × (랙 부하 / PDU 용량). 고밀도 랙은 경로당 여러 대가 필요하다.
    pdu = resolve("electrical", "pdu", blocks, selections)
    feeds = dist["feeds_per_rack"].get(spec.electrical_redundancy,
                                       dist["feeds_per_rack"]["default"])
    pdu_per_feed = math.ceil(rack_kw / pdu.interface.capacity_kw)
    pdu_per_rack = pdu_per_feed * feeds
    n_pdu = rack_count * pdu_per_rack

    # 버스웨이는 열(row) 단위로 급전한다 → 정격은 '랙 1대'가 아니라 '열 전체' 전류 기준.
    # 열당 랙수는 rules/space.yaml(배치 계수)에서 읽는다.
    racks_per_row = load_rule("space.yaml", spec.region)["white_space"]["racks_per_row"]
    n_row = math.ceil(rack_count / racks_per_row)
    i_row = i_rack * min(rack_count, racks_per_row)
    busway = resolve("electrical", "busway", blocks, selections)
    busway_a = calc.next_standard(i_row, dist["busway_standard_a"])
    busway_ok = busway_a >= i_row
    n_busway = n_row * (2 if spec.electrical_redundancy == "2N" else 1)
    note = f"열당 {racks_per_row}랙 / 열전류 {round(i_row)}A"
    if not busway_ok:
        note += f" — 표준 최대 {int(busway_a)}A 초과, 열당 랙수 축소 필요"
    bom.append(LineItem(domain="전기", item="버스웨이", model=busway.model,
                        block_id=busway.id, unit_capacity=f"{int(busway_a)}A",
                        qty=n_busway, note=note))
    bom.append(LineItem(domain="전기", item="랙 PDU", model=pdu.model, block_id=pdu.id,
                        unit_capacity=f"{int(pdu.interface.capacity_kw)}kW",
                        qty=n_pdu,
                        note=f"랙당 {pdu_per_rack} (경로 {feeds} x 경로당 {pdu_per_feed})"))

    pue_est = calc.pue(it_kw, cooling_kw, it_kw * 0.08)

    electrical = {
        "facility_kw": round(facility_kw, 1),
        "house_kw": round(house_kw, 1),
        "demand_factor": el["demand"]["demand_factor"],
        "ups_need_kva": round(need_kva, 1),
        "ups_unit_kva": int(ups.interface.capacity_kva),
        "ups_qty": n_ups,
        "battery_autonomy_min": autonomy,
        "battery_energy_kwh": round(e_kwh, 1),
        "battery_qty": n_bat,
        "generator_need_kw": round(gen_kw, 1),
        "generator_unit_kw": int(gen.interface.capacity_kw),
        "generator_qty": n_gen,
        "transformer_need_kva": round(tx_kva, 1),
        "transformer_unit_kva": int(tx.interface.capacity_kva),
        "transformer_qty": n_tx,
        "transformer_installed_kva": int(n_tx * tx.interface.capacity_kva),
        "primary_kv": primary_kv,
        "mv_demand_kw": round(mv_demand_kw, 1),
        "mv_current_a": round(mv_current, 1),
        "rack_current_a": round(i_rack, 1),
        "rack_kw": rack_kw,
        "racks_per_row": racks_per_row,
        "busway_row_current_a": round(i_row, 1),
        "busway_rating_a": int(busway_a),
        "busway_rating_sufficient": busway_ok,
        "busway_qty": n_busway,
        "pdu_qty": n_pdu,
        "pdu_per_rack": pdu_per_rack,
        "pdu_per_feed": pdu_per_feed,
        "pdu_unit_kw": int(pdu.interface.capacity_kw),
        "feeds_per_rack": feeds,
        "ups_unit_capacity_kva": int(ups.interface.capacity_kva),
        "ups_installed_kva": int(n_ups * ups.interface.capacity_kva),
        "thd_i_assumed": harm["thd_i_assumed"],
        "harmonic_transformer_factor": harm["transformer_factor"],
        "pue_estimate": round(pue_est, 3),
        "redundancy": spec.electrical_redundancy,
        "selected": {"ups": ups.id, "battery": bat.id, "generator": gen.id,
                     "transformer": tx.id, "pdu": pdu.id, "busway": busway.id},
    }
    return electrical, bom
