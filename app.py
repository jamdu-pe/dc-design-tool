"""데이터센터 M&E 개념설계 도구 — Streamlit UI.

CLAUDE.md 절대규칙 1에 따라 **이 파일은 계산하지 않는다.**
입력 수집 → engine 함수 호출 → 결과 표시(라벨 매핑·포맷)만 담당한다.
수치가 필요하면 engine 을 다시 호출하고, 화면에서 사칙연산·단위환산을 하지 않는다.

저장소 루트에서 바로 실행된다(`streamlit run app.py`). Streamlit 이 이 파일의
디렉터리를 sys.path 에 넣어주므로 `dc_design_tool` 패키지는 설치 없이도 잡힌다
— Streamlit Community Cloud 배포가 requirements.txt 만으로 성립하는 이유다.
"""
from __future__ import annotations

import pathlib
import tempfile

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from dc_design_tool.engine.catalog import (append_user_block, available_regions,
                                           load_blocks, load_region, load_rule)
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size
from dc_design_tool.reports.bom_xlsx import write_bom
from dc_design_tool.reports.design_basis_docx import write_design_basis
from dc_design_tool.ui_auth import require_login

st.set_page_config(page_title="DC M&E 개념설계", page_icon="🏢", layout="wide")

# 로그인 게이트. 인증 전에는 아래 화면 코드가 아예 실행되지 않는다(st.stop).
require_login()

# ---------------------------------------------------------------- 라벨 매핑
# 값은 engine 이 만든 것을 그대로 표시한다. 여기서는 이름만 붙인다.
COOLING_LABELS = {
    "it_heat_kw": "총 발열 (kW)", "liquid_kw": "액냉 열량 (kW)",
    "air_kw": "공냉 잔열 (kW)", "liquid_fraction": "액냉 비율",
    "supply_water_c": "공급수온 (°C)", "chw_delta_t_k": "냉각수 ΔT (K)",
    "coolant_flow_lpm": "냉각수 유량 (L/min)", "total_rt": "총 냉동톤 (RT)",
    "cdu_qty": "CDU 수량", "cdu_unit_kw": "CDU 단위용량 (kW)",
    "chiller_qty": "칠러 수량", "chiller_unit_kw": "칠러 단위용량 (kW)",
    "redundancy": "기계 이중화",
}
ELECTRICAL_LABELS = {
    "facility_kw": "설비 총부하 (kW)", "house_kw": "하우스 부하 (kW)",
    "demand_factor": "수용률", "pue_estimate": "PUE (추정)",
    "ups_need_kva": "UPS 필요용량 (kVA)", "ups_unit_kva": "UPS 단위용량 (kVA)",
    "ups_qty": "UPS 수량", "ups_installed_kva": "UPS 설치용량 (kVA)",
    "battery_autonomy_min": "배터리 자립시간 (분)",
    "battery_energy_kwh": "배터리 필요에너지 (kWh)", "battery_qty": "배터리 수량",
    "generator_need_kw": "발전기 필요용량 (kW)",
    "generator_unit_kw": "발전기 단위정격 (kW)", "generator_qty": "발전기 수량",
    "transformer_need_kva": "변압기 필요용량 (kVA)",
    "transformer_unit_kva": "변압기 단위용량 (kVA)", "transformer_qty": "변압기 수량",
    "transformer_installed_kva": "변압기 설치용량 (kVA)",
    "primary_kv": "수전 전압 (kV)", "mv_demand_kw": "수전 부하 (kW)",
    "mv_current_a": "수전 전류 (A)", "rack_kw": "랙 부하 (kW)",
    "rack_current_a": "랙 전류 (A)", "racks_per_row": "열당 랙 수",
    "busway_row_current_a": "열 전류 (A)", "busway_rating_a": "버스웨이 정격 (A)",
    "busway_rating_sufficient": "버스웨이 정격 충족", "busway_qty": "버스웨이 수량",
    "pdu_qty": "랙 PDU 총수량", "pdu_per_rack": "랙당 PDU",
    "pdu_per_feed": "급전경로당 PDU", "pdu_unit_kw": "PDU 단위용량 (kW)",
    "feeds_per_rack": "랙당 급전 경로", "thd_i_assumed": "가정 전류 THD",
    "harmonic_transformer_factor": "변압기 고조파 여유", "redundancy": "전기 이중화",
}
NETWORK_LABELS = {
    "topology": "토폴로지", "oversubscription": "오버섭스크립션",
    "scaleout_ports": "스케일아웃 포트", "port_speed_gbps": "포트 속도 (Gbps)",
    "leaf_qty": "Leaf 스위치", "spine_qty": "Spine 스위치",
    "fabric_link_qty": "패브릭 링크", "transceiver_qty": "트랜시버",
    "cable_qty": "광케이블", "fabric_bandwidth_tbps": "패브릭 대역폭 (Tbps)",
}
SPACE_LABELS = {
    "rack_footprint_m2": "랙 점유면적 (m²)", "white_space_m2": "화이트스페이스 (m²)",
    "electrical_room_m2": "전기실 (m²)", "electrical_equipment_m2": "전기실 장비면적 (m²)",
    "mechanical_room_m2": "기계실 (m²)", "mechanical_equipment_m2": "기계실 장비면적 (m²)",
    "support_area_m2": "지원공간 (m²)", "total_building_m2": "총 건축면적 (m²)",
    "equipment_clearance_factor": "장비 이격계수", "rack_rows": "랙 열 수",
    "racks_per_row": "열당 랙 수", "floor_load_kg_per_m2": "바닥하중 (kg/m²)",
    "floor_load_limit_kg_per_m2": "허용 바닥하중 (kg/m²)",
    "floor_load_ok": "바닥하중 충족", "clear_height_mm": "유효 층고 (mm)",
}
SEVERITY_LABEL = {"violation": "위반", "warning": "경고", "info": "정보"}
SEVERITY_ORDER = {"violation": 0, "warning": 1, "info": 2}


# ---------------------------------------------------------------- 데이터 로드
@st.cache_data(show_spinner=False)
def _catalog() -> dict:
    """카탈로그를 (표시용으로) 캐싱해 읽는다. 랙 등록 후에는 캐시를 비운다."""
    blocks = load_blocks()
    racks = {bid: b for bid, b in blocks.items() if b.type == "rack"}
    return {
        "rack_options": sorted(racks),
        "rack_labels": {bid: f"{b.vendor} {b.model} · {b.interface.power_kw_typical}kW "
                             f"[{b.confidence}]" for bid, b in racks.items()},
        "tiers": list(load_rule("tiers.yaml")["tiers"]),
        "redundancy": list(load_rule("redundancy.yaml")),
        "regions": available_regions(),
        "region_names": {c: load_region(c).get("name", c) for c in available_regions()},
    }


def _kv_frame(data: dict, labels: dict) -> pd.DataFrame:
    """engine 결과 dict 를 (항목, 값) 2열 표로.

    값은 계산하지 않고 문자열로만 바꾼다. 한 컬럼에 수치·문자열·불린이 섞이면
    Arrow 직렬화가 실패하므로 표시 단계에서 타입을 통일한다.
    """
    rows = [(label, str(data[key])) for key, label in labels.items() if key in data]
    return pd.DataFrame(rows, columns=["항목", "값"])


# ---------------------------------------------------------------- 사이드바
try:
    cat = _catalog()
except (ValueError, ValidationError) as exc:
    st.error(f"카탈로그 로드 실패: {exc}")
    st.stop()

st.sidebar.header("설계 조건")
project = st.sidebar.text_input("프로젝트명", "AI DC 개념설계")
region = st.sidebar.selectbox(
    "규격 팩", cat["regions"],
    index=cat["regions"].index("generic") if "generic" in cat["regions"] else 0,
    format_func=lambda c: f"{c} — {cat['region_names'][c]}")
rack_id = st.sidebar.selectbox("랙 모델", cat["rack_options"],
                               format_func=lambda b: cat["rack_labels"][b])

mode = st.sidebar.radio("규모 입력", ["IT 부하 (MW)", "랙 수"], horizontal=True)
if mode == "IT 부하 (MW)":
    it_power_mw = st.sidebar.number_input("IT 부하 (MW)", 0.1, 500.0, 5.0, 0.1)
    rack_count = None
else:
    rack_count = st.sidebar.number_input("랙 수", 1, 5000, 42, 1)
    it_power_mw = None

tier = st.sidebar.selectbox("Uptime Tier", cat["tiers"],
                            index=cat["tiers"].index("III") if "III" in cat["tiers"] else 0)
col_a, col_b = st.sidebar.columns(2)
e_red = col_a.selectbox("전기 이중화", cat["redundancy"],
                        index=cat["redundancy"].index("N+1") if "N+1" in cat["redundancy"] else 0)
m_red = col_b.selectbox("기계 이중화", cat["redundancy"],
                        index=cat["redundancy"].index("N+1") if "N+1" in cat["redundancy"] else 0)
delta_t = st.sidebar.number_input("냉각수 ΔT (K)", 1.0, 30.0, 10.0, 0.5)
target_pue = st.sidebar.number_input("목표 PUE", 1.0, 3.0, 1.25, 0.01)
ambient = st.sidebar.number_input("설계 외기 (°C)", -20.0, 55.0, 33.0, 0.5)

if st.sidebar.button("설계 실행", type="primary", use_container_width=True):
    try:
        spec = Spec(project=project, rack_id=rack_id, it_power_mw=it_power_mw,
                    rack_count=rack_count, tier=tier, electrical_redundancy=e_red,
                    mechanical_redundancy=m_red, chw_delta_t_k=delta_t,
                    target_pue=target_pue, ambient_design_c=ambient, region=region)
        st.session_state["result"] = size(spec)
        st.session_state["error"] = None
    except ValidationError as exc:
        st.session_state["result"] = None
        st.session_state["error"] = f"입력 검증 실패:\n\n{exc}"
    except (KeyError, ValueError) as exc:
        st.session_state["result"] = None
        st.session_state["error"] = str(exc).strip("'")

# ---------------------------------------------------------------- 본문
st.title("데이터센터 M&E 개념설계")
st.caption("모든 수치는 결정론적 엔진(`dc_design_tool.engine`)이 산출한다. "
           "개념설계/타당성 수준이며 실시설계·인허가는 면허기술자 검토가 필요하다.")

if st.session_state.get("error"):
    st.error(st.session_state["error"])

result = st.session_state.get("result")

if result is None:
    st.info("왼쪽에서 조건을 고르고 **설계 실행**을 누르세요. "
            "아래 `랙 추가`로 카탈로그에 없는 랙을 먼저 등록할 수도 있습니다.")
else:
    # 상단 경고 — projected 사양·규격 위반
    for warning in result.warnings:
        (st.error if warning.startswith("[") else st.warning)(warning)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("랙 수량", f"{result.rack_count} 대")
    m2.metric("총 IT부하", f"{result.it_power_kw:,.1f} kW")
    m3.metric("PUE (추정)", result.electrical["pue_estimate"])
    m4.metric("총 건축면적", f"{result.space['total_building_m2']:,.1f} m²")

    tab_m, tab_e, tab_n, tab_s, tab_c, tab_bom = st.tabs(
        ["기계", "전기", "통신", "공간", "규격검증", "BOM"])

    with tab_m:
        st.dataframe(_kv_frame(result.cooling, COOLING_LABELS),
                     hide_index=True, width="stretch")
    with tab_e:
        st.dataframe(_kv_frame(result.electrical, ELECTRICAL_LABELS),
                     hide_index=True, width="stretch")
    with tab_n:
        st.dataframe(_kv_frame(result.network, NETWORK_LABELS),
                     hide_index=True, width="stretch")
    with tab_s:
        st.dataframe(_kv_frame(result.space, SPACE_LABELS),
                     hide_index=True, width="stretch")

    with tab_c:
        report = result.compliance
        if report is None:
            st.info("규격검증이 수행되지 않았다.")
        else:
            summary = report.summary()
            c1, c2, c3 = st.columns(3)
            c1.metric("위반", summary["violation"])
            c2.metric("경고", summary["warning"])
            c3.metric("정보", summary["info"])
            findings = sorted(report.findings, key=lambda f: SEVERITY_ORDER[f.severity])
            st.dataframe(pd.DataFrame([{
                "심각도": SEVERITY_LABEL[f.severity], "코드": f.code, "도메인": f.domain,
                "판정": f.message, "설계값": f.actual, "요구값": f.required,
                "근거": f.rule,
            } for f in findings]), hide_index=True, width="stretch")

    with tab_bom:
        st.dataframe(pd.DataFrame([{
            "도메인": li.domain, "품목": li.item, "모델": li.model,
            "단위용량": li.unit_capacity, "수량": str(li.qty), "비고": li.note,
            "블록 id": li.block_id,
        } for li in result.bom]), hide_index=True, width="stretch")

    # ------------------------------------------------------------ 산출물 다운로드
    st.subheader("산출물")
    out_dir = tempfile.mkdtemp(prefix="dc_design_")  # 실행마다 분리(파일명이 고정)
    try:
        xlsx_path = write_bom(result, out_dir)
        docx_path = write_design_basis(result, out_dir)
        d1, d2 = st.columns(2)
        d1.download_button(
            "BOM·부하요약 (xlsx)", pathlib.Path(xlsx_path).read_bytes(),
            file_name="BOM_부하요약.xlsx", width="stretch",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        d2.download_button(
            "설계기준서 (docx)", pathlib.Path(docx_path).read_bytes(),
            file_name="설계기준서.docx", width="stretch",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except OSError as exc:
        st.error(f"산출물 생성 실패: {exc}")

# ---------------------------------------------------------------- 랙 등록
# 설계 실행 여부와 무관하게 항상 열려 있어야 한다(신규 랙을 먼저 등록하는 흐름 지원).
with st.expander("랙 추가 — 카탈로그에 없는 랙 등록"):
    st.markdown("저장 위치는 `data/user_racks.yaml` 이며 CLI 에서도 즉시 보인다. "
                "**출처(source_url)가 없으면 등록할 수 없다.**")
    with st.form("add_rack"):
        f1, f2, f3 = st.columns(3)
        new_id = f1.text_input("id *", placeholder="acme_super_rack")
        vendor = f2.text_input("vendor *", placeholder="ACME")
        model = f3.text_input("model *", placeholder="SUPER-1")

        g1, g2, g3, g4 = st.columns(4)
        p_typ = g1.number_input("power_kw_typical * (kW)", 0.1, 2000.0, 120.0, 1.0)
        p_peak = g2.number_input("power_kw_peak (kW, 0=미기입)", 0.0, 2000.0, 0.0, 1.0)
        liq = g3.number_input("liquid_fraction *", 0.0, 1.0, 0.85, 0.01)
        accel = g4.number_input("accel_count (0=미기입)", 0, 10000, 72, 1)

        h1, h2, h3, h4 = st.columns(4)
        water_c = h1.number_input("supply_water_c (°C, 0=미기입)", 0.0, 60.0, 32.0, 0.5)
        footprint = h2.number_input("footprint_m2 (0=미기입)", 0.0, 20.0, 1.2, 0.1)
        weight = h3.number_input("weight_kg (0=미기입)", 0.0, 10000.0, 1360.0, 10.0)
        rack_units = h4.number_input("rack_units (0=미기입)", 0, 60, 48, 1)

        i1, i2, i3, i4 = st.columns(4)
        ports = i1.number_input("scaleout_ports (0=미기입)", 0, 10000, 72, 1)
        speed = i2.selectbox("port_speed_gbps", [400, 800, 1600], index=1)
        as_of = i3.text_input("as_of_date * (YYYY-MM)", placeholder="2026-08")
        confidence = i4.selectbox("confidence *", ["measured", "vendor", "projected"],
                                  index=1)
        source_url = st.text_input("source_url *", placeholder="https://vendor.example/datasheet")

        if st.form_submit_button("카탈로그에 추가", type="primary"):
            iface = {"power_kw_typical": p_typ, "liquid_fraction": liq,
                     "port_speed_gbps": speed}
            for key, value in (("power_kw_peak", p_peak), ("accel_count", accel),
                               ("supply_water_c", water_c), ("footprint_m2", footprint),
                               ("weight_kg", weight), ("rack_units", rack_units),
                               ("scaleout_ports", ports)):
                if value:                      # 0 은 '미기입'으로 보고 키를 넣지 않는다
                    iface[key] = value
            raw = {"id": new_id.strip(), "type": "rack", "vendor": vendor.strip(),
                   "model": model.strip(), "interface": iface,
                   "as_of_date": as_of.strip(), "confidence": confidence,
                   "source_url": source_url.strip()}
            try:
                block = append_user_block(raw)
                _catalog.clear()
                st.success(f"등록 완료: {block.id} — 왼쪽 랙 모델 목록에서 선택할 수 있다.")
                st.rerun()
            except ValidationError as exc:
                st.error(f"입력 검증 실패:\n\n{exc}")
            except ValueError as exc:
                st.error(str(exc))
