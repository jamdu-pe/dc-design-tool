"""골든 회귀테스트: 앵커값으로 엔진 sanity 확인."""
from dc_design_tool.engine import calc
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size


def test_flow_formula():
    # 100kW, ΔT10K → 143.3 L/min 부근
    f = calc.coolant_flow_lpm(100, 10)
    assert abs(f - 143.33) < 1.0


def test_rt():
    assert abs(calc.rt_from_kw(3517) - 1000) < 1.0


def test_redundancy_2n_doubles():
    rule_2n = {"multiplier": 2.0, "extra": 0}
    rule_n1 = {"multiplier": 1.0, "extra": 1}
    assert calc.redundant_qty(1000, 300, rule_2n) == 8   # ceil(1000/300)=4 → 8
    assert calc.redundant_qty(1000, 300, rule_n1) == 5   # 4 + 1


def test_gb200_single_rack():
    spec = Spec(project="golden", rack_id="nvidia_gb200_nvl72", rack_count=1,
                tier="III", electrical_redundancy="N+1", mechanical_redundancy="N+1")
    r = size(spec)
    assert 118 <= r.it_power_kw <= 132          # 랙부하 앵커
    assert r.cooling["liquid_kw"] > r.cooling["air_kw"]  # 액냉 지배
    assert r.electrical["ups_qty"] >= 2         # N+1
    assert r.network["scaleout_ports"] == 72


def test_gb200_5mw():
    spec = Spec(project="golden5mw", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    r = size(spec)
    assert r.rack_count == 42                    # ceil(5000/120)
    assert 1.1 <= r.electrical["pue_estimate"] <= 1.6


def test_battery_formula():
    # 5040kW, 자립 10분, DoD0.8, eff0.95 → 1105kWh 부근
    e = calc.battery_energy_kwh(5040, 10, 0.8, 0.95)
    assert abs(e - 1105.3) < 2.0


def test_electrical_detail_keys():
    spec = Spec(project="e", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0,
                tier="III", electrical_redundancy="2N")
    r = size(spec)
    e = r.electrical
    # 필수 상세 키 존재
    for k in ("battery_energy_kwh", "battery_qty", "transformer_qty",
              "mv_current_a", "busway_rating_a", "pdu_qty", "thd_i_assumed"):
        assert k in e
    # Tier III → 자립 10분, 2N → 급전 경로 2개(경로당 PDU는 랙 부하로 결정)
    assert e["battery_autonomy_min"] == 10
    assert e["feeds_per_rack"] == 2
    assert e["pdu_qty"] == r.rack_count * e["pdu_per_rack"]
    # 버스웨이 정격은 랙전류 이상 표준값
    assert e["busway_rating_a"] >= e["rack_current_a"]


def test_higher_tier_more_autonomy():
    base = Spec(rack_id="nvidia_gb200_nvl72", rack_count=10, tier="III")
    hi = Spec(rack_id="nvidia_gb200_nvl72", rack_count=10, tier="IV")
    assert size(hi).electrical["battery_energy_kwh"] > size(base).electrical["battery_energy_kwh"]
