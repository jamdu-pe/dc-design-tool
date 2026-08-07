"""핵심 데이터 모델(레고 블록 인터페이스 + 요구사항 + 결과)."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Confidence = Literal["measured", "vendor", "projected"]


class Interface(BaseModel):
    """블록이 노출하는 '레고 돌기'. 필드는 블록 종류에 따라 부분 사용."""
    model_config = {"extra": "allow"}
    # 전력
    power_kw_typical: Optional[float] = None
    power_kw_peak: Optional[float] = None
    power_factor: float = 0.95
    # 발열/냉각
    cooling: Optional[str] = None
    liquid_fraction: float = 0.0
    supply_water_c: Optional[float] = None
    # 냉각장비 설치 형태. 수량 산정식이 갈리는 유일한 기준이다.
    #   rack = 랙 후면 장착(랙당 1대, 이중화 대수 증설 불가)
    #   room = 실 단위 설치(필요 용량 + 이중화 규칙으로 대수 산정)
    mounting: Literal["rack", "room"] = "room"
    # 기술 방식 표기(rear_door_hx | crah | in_row 등). 표시·추적용이고 계산에 쓰지 않는다.
    # 같은 mounting 이라도 방식 이름이 달라야 보고서에서 구분되기 때문에 따로 둔다.
    method: Optional[str] = None
    # 물리
    rack_units: Optional[int] = None
    footprint_m2: Optional[float] = None
    weight_kg: Optional[float] = None
    location: Literal["indoor", "outdoor", "yard"] = "indoor"  # 실내 부속실 면적 산정 대상 여부
    # 통신
    accel_count: Optional[int] = None
    scaleout_ports: Optional[int] = None
    port_speed_gbps: Optional[int] = None
    # 구성품으로 환산되지 않는 잔여 소비(전원셸프 손실·팬·CPU 등)
    overhead_kw: float = 0.0
    # 개산 단가[USD]. 출처 있는 값만 채운다. 없으면 None 으로 두고 '비용 미상'으로 보고한다.
    capex_usd: Optional[float] = None
    # capacity 장비
    capacity_kw: Optional[float] = None
    capacity_kva: Optional[float] = None
    capacity_kwh: Optional[float] = None
    rating_a: Optional[float] = None
    primary_kv: Optional[float] = None
    secondary_v: Optional[float] = None
    efficiency: float = 0.97
    ports: Optional[int] = None


class Component(BaseModel):
    """상위 블록이 품는 하위 블록 참조(레고 결합부)."""
    id: str
    count: int


class Block(BaseModel):
    id: str
    type: Literal["chip", "node", "rack", "cooling", "electrical", "network"]
    vendor: str = "Unknown"
    model: str = ""
    subtype: Optional[str] = None
    interface: Interface
    composed_of: list[Component] = Field(default_factory=list)
    # 역할(subtype) 안에서 이 블록이 기본 선택인가. selections 로 지정하지 않은 역할에
    # 무엇을 쓸지는 YAML 줄 순서가 아니라 이 플래그가 정한다.
    # 역할마다 정확히 하나만 true 여야 한다(tests/test_selection.py 가 강제).
    default: bool = False
    as_of_date: Optional[str] = None
    confidence: Confidence = "projected"
    source_url: Optional[str] = None


class Spec(BaseModel):
    """사용자 입력(요구사항)."""
    project: str = "untitled"
    it_power_mw: Optional[float] = None
    rack_count: Optional[int] = None
    rack_id: str
    tier: str = "III"
    electrical_redundancy: str = "N+1"
    mechanical_redundancy: str = "N+1"
    chw_delta_t_k: float = 10.0
    target_pue: float = 1.25
    ambient_design_c: float = 33.0
    climate: str = "KR"
    region: str = "generic"   # 규격 팩(rules/regions/*.yaml). 예: "KR" = KEC 기반
    # 역할(subtype) → block_id. 비워 두면 `default: true`가 붙은 블록을 쓴다.
    # 가능한 역할은 engine.sizing.SELECTABLE_ROLES 참고. 예: {"ups": "ups_1250kva"}
    selections: dict[str, str] = Field(default_factory=dict)


class LineItem(BaseModel):
    domain: str
    item: str
    model: str
    unit_capacity: str
    qty: int
    note: str = ""
    block_id: str = ""   # 카탈로그 추적성: 이 줄이 어느 블록에서 나왔는지


Severity = Literal["violation", "warning", "info"]


class Finding(BaseModel):
    """규격검증 판정 1건."""
    code: str                   # 기계판독용 코드(예: TIER_ELECTRICAL)
    severity: Severity
    domain: str                 # 전기 | 기계 | 통신 | 공간 | 카탈로그
    message: str                # 사람이 읽을 설명
    actual: str = ""            # 설계값
    required: str = ""          # 요구값
    rule: str = ""              # 근거 규칙 파일/항목


class ComplianceReport(BaseModel):
    """규격검증 결과 묶음."""
    tier: str
    findings: list[Finding] = Field(default_factory=list)

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "violation"]

    @property
    def ok(self) -> bool:
        """위반(violation)이 하나도 없으면 True."""
        return not self.violations

    def summary(self) -> dict[str, int]:
        """심각도별 건수."""
        return {s: sum(1 for f in self.findings if f.severity == s)
                for s in ("violation", "warning", "info")}


class SizingResult(BaseModel):
    project: str
    rack_id: str
    rack_count: int
    it_power_kw: float
    it_load: dict = Field(default_factory=dict)
    cooling: dict
    electrical: dict
    space: dict
    network: dict
    bom: list[LineItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    compliance: Optional[ComplianceReport] = None
    # 역할(subtype) → 이번 설계에 실제로 쓰인 block_id
    selections: dict[str, str] = Field(default_factory=dict)
    # 역할 → 교체 가능한 후보 목록(UI 드롭다운용 최소 필드).
    # Block 전체가 아니라 라벨에 필요한 값만 담는다 — MCP·웹 응답에 그대로 실린다.
    candidates: dict[str, list[dict]] = Field(default_factory=dict)
