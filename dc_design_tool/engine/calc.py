"""결정론적 계산식 모음. 모든 수치는 여기서 계산되고 테스트로 검증된다."""
from __future__ import annotations
import math

WATER_C_KJ_PER_L_K = 4.186   # 물 비열×밀도 근사
KW_PER_RT = 3.517            # 냉동톤
SQRT3 = math.sqrt(3)


def line_current_a(power_kw: float, voltage_v: float, pf: float = 0.95) -> float:
    """3상 선전류[A] = P[W] / (√3 × V × PF)."""
    if voltage_v <= 0 or pf <= 0:
        raise ValueError("전압·역률은 0보다 커야 함")
    return power_kw * 1000.0 / (SQRT3 * voltage_v * pf)


def next_standard(value: float, sizes: list) -> float:
    """표준 규격 중 value 이상 최소값(없으면 최대값)."""
    for s in sorted(sizes):
        if s >= value:
            return s
    return max(sizes)


def battery_energy_kwh(load_kw: float, autonomy_min: float,
                       dod: float = 0.8, inv_eff: float = 0.95) -> float:
    """UPS 배터리 필요 에너지[kWh] (방전심도·인버터효율 반영)."""
    return load_kw * (autonomy_min / 60.0) / (dod * inv_eff)


def transformer_kva(facility_kw: float, pf: float = 0.95,
                    harmonic_factor: float = 1.10, margin: float = 0.15) -> float:
    """수배전 변압기 필요용량[kVA] (고조파·설계여유 반영)."""
    return facility_kw / pf * harmonic_factor * (1 + margin)


def coolant_flow_lpm(power_kw: float, delta_t_k: float = 10.0) -> float:
    """냉각수 유량[L/min] = P[kW]×60 / (4.186×ΔT)."""
    if delta_t_k <= 0:
        raise ValueError("ΔT는 0보다 커야 함")
    return power_kw * 60.0 / (WATER_C_KJ_PER_L_K * delta_t_k)


def rt_from_kw(power_kw: float) -> float:
    """열량[kW] → 냉동톤[RT]."""
    return power_kw / KW_PER_RT


def ups_kva(it_kw: float, pf: float = 0.95, eff: float = 0.97, margin: float = 0.1) -> float:
    """UPS 필요용량[kVA]."""
    return it_kw * (1 + margin) / pf / eff


def redundant_qty(need: float, unit_capacity: float, rule: dict) -> int:
    """이중화 규칙 적용 설치대수. rule={'multiplier','extra'}."""
    if unit_capacity <= 0:
        raise ValueError("단위 용량은 0보다 커야 함")
    base = math.ceil(need / unit_capacity)
    return math.ceil(base * rule.get("multiplier", 1.0)) + int(rule.get("extra", 0))


def generator_kw(it_kw: float, cooling_kw: float, house_factor: float = 0.1,
                 start_margin: float = 0.15) -> float:
    """발전기 필요용량[kW] = (IT+냉각+하우스)×기동여유."""
    base = it_kw + cooling_kw + it_kw * house_factor
    return base * (1 + start_margin)


def pue(it_kw: float, cooling_kw: float, loss_kw: float) -> float:
    return (it_kw + cooling_kw + loss_kw) / it_kw


# 리프-스파인 대수 산정은 engine/network.py 로 이관(오버섭스크립션·패브릭링크 반영).
