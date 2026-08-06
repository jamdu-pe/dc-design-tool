"""시나리오 비교 엔진 테스트: 스윕 전개 → 사이징 → 비교 메트릭 → CAPEX(선택)."""
import pytest

from dc_design_tool.engine import scenario
from dc_design_tool.engine.catalog import load_blocks


BASE = {"project": "sweep-test", "it_power_mw": 5.0, "rack_id": "nvidia_gb200_nvl72",
        "tier": "III", "electrical_redundancy": "N+1", "mechanical_redundancy": "N+1",
        "target_pue": 1.6}


# ---------- 스윕 전개 ----------

def test_empty_sweep_yields_single_base_scenario():
    rows = scenario.expand(BASE, {})
    assert len(rows) == 1
    assert rows[0][1].rack_id == "nvidia_gb200_nvl72"


def test_sweep_is_a_cartesian_product():
    rows = scenario.expand(BASE, {
        "rack_id": ["nvidia_gb200_nvl72", "nvidia_gb300_nvl72"],
        "electrical_redundancy": ["N+1", "2N"]})
    assert len(rows) == 4
    assert len({name for name, _ in rows}) == 4      # 이름이 서로 구분된다


def test_scenario_name_shows_the_varied_axes():
    rows = scenario.expand(BASE, {"electrical_redundancy": ["N+1", "2N"]})
    names = {name for name, _ in rows}
    assert any("2N" in n for n in names)
    assert all("electrical_redundancy" in n for n in names)


def test_unknown_sweep_key_raises():
    with pytest.raises(ValueError, match="스윕 키"):
        scenario.expand(BASE, {"not_a_spec_field": [1, 2]})


def test_empty_sweep_value_list_raises():
    with pytest.raises(ValueError):
        scenario.expand(BASE, {"electrical_redundancy": []})


# ---------- 평가 메트릭 ----------

@pytest.fixture(scope="module")
def sweep_rows():
    return scenario.run_sweep(BASE, {"electrical_redundancy": ["N+1", "2N"]})


def test_every_scenario_reports_the_comparison_metrics(sweep_rows):
    for row in sweep_rows:
        for key in ("scenario", "rack_id", "rack_count", "it_power_kw", "accel_total",
                    "pue", "total_building_m2", "total_rt", "transformer_installed_kva",
                    "ups_qty", "switch_qty", "violations", "warnings"):
            assert key in row, f"{key} 누락"


def test_redundancy_upgrade_increases_equipment_but_not_it_load(sweep_rows):
    n1 = next(r for r in sweep_rows if "N+1" in r["scenario"])
    n2 = next(r for r in sweep_rows if "2N" in r["scenario"])
    assert n2["ups_qty"] > n1["ups_qty"]
    assert n2["total_building_m2"] > n1["total_building_m2"]
    assert n2["it_power_kw"] == n1["it_power_kw"]


def test_denser_rack_generation_needs_fewer_racks_for_same_load():
    rows = scenario.run_sweep(BASE, {
        "rack_id": ["nvidia_gb200_nvl72", "nvidia_gb300_nvl72"]})
    gb200 = next(r for r in rows if r["rack_id"] == "nvidia_gb200_nvl72")
    gb300 = next(r for r in rows if r["rack_id"] == "nvidia_gb300_nvl72")
    assert gb300["rack_count"] < gb200["rack_count"]


def test_scenario_with_violations_is_counted_not_crashed():
    rows = scenario.run_sweep({**BASE, "tier": "IV"}, {
        "electrical_redundancy": ["N+1", "2N"]})
    bad = next(r for r in rows if "N+1" in r["scenario"])
    assert bad["violations"] >= 1


def test_failed_scenario_is_reported_without_aborting_the_sweep():
    """한 조합이 실패해도 나머지 결과는 나와야 한다."""
    rows = scenario.run_sweep(BASE, {
        "rack_id": ["nvidia_gb200_nvl72", "does_not_exist"]})
    assert len(rows) == 2
    ok = next(r for r in rows if r["rack_id"] == "nvidia_gb200_nvl72")
    failed = next(r for r in rows if r["rack_id"] == "does_not_exist")
    assert ok["error"] == ""
    assert "카탈로그 부재" in failed["error"]
    assert failed["rack_count"] is None


# ---------- CAPEX (데이터가 있을 때만) ----------

def test_capex_is_none_when_catalog_has_no_cost_data():
    """비용은 카탈로그에 없으면 지어내지 않고 '부재'로 보고한다."""
    rows = scenario.run_sweep(BASE, {})
    assert rows[0]["capex_usd"] is None
    assert rows[0]["capex_missing"] > 0


def test_capex_sums_when_blocks_carry_cost():
    blocks = load_blocks()
    priced = dict(blocks)
    for bid in ("ups_1250kva", "genset_2500kw"):
        b = priced[bid]
        priced[bid] = b.model_copy(update={"interface": b.interface.model_copy(
            update={"capex_usd": 100_000.0})})

    rows = scenario.run_sweep(BASE, {}, blocks=priced)
    r = rows[0]
    expected = 100_000.0 * (r["ups_qty"] + r["generator_qty"])
    assert r["capex_usd"] == pytest.approx(expected)
    assert r["capex_missing"] > 0          # 나머지 장비는 여전히 비용 미상


def test_capex_missing_counts_distinct_blocks_without_price():
    rows = scenario.run_sweep(BASE, {})
    assert rows[0]["capex_missing"] == len({li.block_id for li in
                                            scenario.size_scenario(BASE).bom})


# ---------- 랭킹 ----------

def test_rank_orders_scenarios_by_metric(sweep_rows):
    ranked = scenario.rank(sweep_rows, "total_building_m2")
    areas = [r["total_building_m2"] for r in ranked]
    assert areas == sorted(areas)


def test_rank_puts_failed_scenarios_last():
    rows = scenario.run_sweep(BASE, {"rack_id": ["nvidia_gb200_nvl72", "does_not_exist"]})
    ranked = scenario.rank(rows, "total_building_m2")
    assert ranked[-1]["error"] != ""
