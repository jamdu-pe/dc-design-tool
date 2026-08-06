# Claude Code 작업지시서 — 데이터센터 M&E 설계 TOOL 구축

> 이 문서를 Claude Code 프로젝트 루트에 넣고 그대로 실행시키면 도구가 만들어진다.
> "숫자는 파이썬 엔진이, 판단·해설은 에이전트가" 원칙을 반드시 지킬 것.
> 작성일 2026-08-05

---

## 0. 실행 방법 (사람이 하는 일)

1. 빈 폴더 생성 후 이 지시서와 함께 제공된 `scaffold/` 내용을 복사.
2. 터미널에서 `claude` 실행 → 아래 "Phase 0~5"를 순서대로 지시(또는 이 문서를 붙여넣고 "Phase 0부터 순서대로 구현해줘"라고 지시).
3. 각 Phase 종료마다 `pytest`가 녹색인지 확인 후 다음 Phase 진행.

---

## 1. 프로젝트 목표 (Claude Code에게)

너는 데이터센터 M&E(기계·전기·통신) **개념설계 자동화 도구**를 만든다. 사용자가 AI 가속기 랙(GB200/GB300/Rubin/TPU/Trainium 등)과 규모·이중화·기후를 입력하면, 냉각·전력·네트워크·공간 용량을 산정하고 장비 BOM과 설계기준서를 산출한다. 부품은 YAML "레고 블록"으로 정의되어 블록 추가만으로 확장된다.

**절대 규칙**
- 모든 수치 계산은 `engine/` 의 순수 파이썬 함수로 구현하고 단위테스트로 검증한다. LLM/에이전트는 수치를 직접 계산하지 않는다.
- 카탈로그(사양)는 코드가 아니라 `data/*.yaml` 에 둔다. 각 항목에 `as_of_date`, `confidence`, `source_url` 필수.
- 모든 공개 함수는 타입힌트 + docstring + 예외처리. `pydantic` 모델로 입출력 검증.
- 커밋은 Phase 단위로, 테스트 통과 후에만.

---

## 2. 최종 디렉토리 구조 (목표 산출물)

```
dc_design_tool/
├─ CLAUDE.md                     # 에이전트 운영 규칙(제공됨)
├─ pyproject.toml
├─ README.md
├─ data/                         # 레고 블록(카탈로그)
│  ├─ chips.yaml
│  ├─ nodes.yaml
│  ├─ racks.yaml
│  ├─ cooling.yaml
│  ├─ electrical.yaml
│  └─ network.yaml
├─ rules/                        # 규격·계수(데이터화)
│  ├─ redundancy.yaml            # N, N+1, N+2, 2N 계수
│  ├─ ashrae.yaml               # 수온등급/환경등급
│  └─ tiers.yaml                # Uptime Tier / TIA-942
├─ engine/                       # 결정론적 계산 엔진
│  ├─ models.py                  # pydantic 데이터모델(인터페이스)
│  ├─ catalog.py                 # YAML 로더·검증
│  ├─ it_load.py                 # 칩→노드→랙→총 IT부하
│  ├─ cooling.py                 # 냉각 사이징(유량/CDU/칠러/PUE)
│  ├─ power.py                   # UPS/발전기/변압기/배전
│  ├─ space.py                   # 면적/바닥하중/층고
│  ├─ network.py                 # 패브릭/트랜시버/배선 BOM
│  ├─ compliance.py              # 규격 검증
│  └─ compose.py                 # 레고 그래프 솔버(조립·롤업)
├─ agents/                       # 서브에이전트 정의(.claude/agents 로 복사)
│  ├─ intake.md
│  ├─ mechanical.md
│  ├─ electrical.md
│  ├─ ict.md
│  ├─ compliance.md
│  └─ reporter.md
├─ reports/                      # 산출물 생성기
│  ├─ bom_xlsx.py
│  ├─ design_basis_docx.py
│  └─ diagram_mermaid.py
├─ cli.py                        # `dc-design build --spec spec.yaml`
├─ examples/
│  └─ spec_gb200_5mw_tier3.yaml
└─ tests/
   ├─ test_it_load.py
   ├─ test_cooling.py
   ├─ test_power.py
   └─ test_golden_gb200.py       # 골든값 회귀테스트
```

---

## 3. 데이터 스키마 규약 (레고 블록 공통 인터페이스)

모든 블록은 아래 공통 필드를 가진다.

```yaml
- id: <고유id>            # 예: nvidia_gb200_nvl72
  type: chip|node|rack|cooling|electrical|network
  vendor: <제조사>
  model: <모델명>
  interface:              # 다른 블록과 연결되는 "돌기"
    # 전력
    power_kw_typical: <float>
    power_kw_peak: <float>
    power_factor: 0.95
    # 발열/냉각
    cooling: air|liquid_d2c|liquid_rdhx|hybrid
    liquid_fraction: 0.0~1.0     # 액냉이 흡수하는 열 비율
    supply_water_c: 32           # TCS 공급수온(해당 시)
    # 물리
    rack_units: 1~48
    footprint_m2: <float>
    weight_kg: <float>
    # 통신(칩/노드/랙에 한함)
    accel_count: <int>           # GPU/TPU/Trainium 수
    scaleout_ports: <int>
    port_speed_gbps: 400|800|1600
  as_of_date: "YYYY-MM"
  confidence: measured|vendor|projected
  source_url: "<출처>"
```

**capacity 블록(냉각·전기·네트워크 장비)**은 `interface`에 "공급 능력"을 둔다. 예: CDU는 `capacity_kw`, UPS는 `capacity_kva`·`efficiency`, 스위치는 `ports`·`port_speed_gbps`.

---

## 4. 핵심 계산식 (engine에 그대로 구현·테스트)

```
IT 총부하   P_it = Σ(랙 kW)             # 랙 kW = 노드수 × 노드TDP (또는 랙 정격)
액냉 열량   Q_liq = P_it × liquid_fraction
공냉 열량   Q_air = P_it × (1 - liquid_fraction)
냉각수 유량 Flow[L/min] = P[kW] × 60 / (4.186 × ΔT[K])     # ΔT 기본 10K
CDU 대수    n_cdu = ceil(Q_liq / cdu.capacity_kw) → 이중화 계수 적용
칠러 톤수   RT = Q_total[kW] / 3.517
UPS 용량    S_kva = P_it × (1+margin) / PF / eff
UPS 대수    이중화(redundancy.yaml): N+1 → n+1, 2N → 2×n
배터리      E = S_kw × autonomy_min / 60                    # kWh
발전기      P_gen = P_it + P_cooling + P_house + start_margin
변압기/수전 MV = (총부하 × 여유) / (√3 × V × PF)
화이트스페이스 A = 랙수 × rack_pitch_m2 + M/E실계수
바닥하중    kg/m2 = 랙중량 / footprint (고밀도 랙 검증)
PUE(추정)   PUE = (P_it + P_cooling + P_loss) / P_it
```

이중화 규칙은 `rules/redundancy.yaml`에서 계수로 읽어온다(하드코딩 금지).

---

## 5. Phase별 작업 지시 (순서 엄수)

### Phase 0 — 스캐폴드 & 환경
- `pyproject.toml`(의존성: pydantic, pyyaml, openpyxl, python-docx, typer, pytest) 작성.
- 디렉토리 골격 생성, `CLAUDE.md`·에이전트 md 배치.
- `pytest` 실행되게 빈 테스트 통과.
- **완료조건**: `pip install -e .` 성공, `pytest` 0 fail.

### Phase 1 — 데이터모델 & 카탈로그 로더
- `engine/models.py`: `Interface`, `Block`, `Spec`(요구사항), `SizingResult` pydantic 모델.
- `engine/catalog.py`: `data/*.yaml` 로드·스키마검증, `confidence/source_url` 누락 시 경고.
- 최소 카탈로그 시드: 칩 3종(GB200/TPU v7/Trainium3), 랙, CDU 1종, 칠러 1종, UPS 1종, 발전기 1종, leaf/spine 스위치 1종. (제공된 `scaffold/data/*.yaml` 확장)
- **완료조건**: `catalog.load()`가 모든 블록을 검증 통과로 로드. 스키마 위반 YAML은 명확한 에러.

### Phase 2 — IT 부하 & 냉각 엔진
- `engine/it_load.py`, `engine/cooling.py` 구현(§4 식).
- `engine/compose.py`: 칩→노드→랙→총합 롤업 그래프 솔버.
- 테스트: `test_it_load.py`, `test_cooling.py`, **`test_golden_gb200.py`**.
- **완료조건(골든)**: GB200 NVL72 1랙 입력 시 랙부하 120~130kW, ΔT10K 유량이 식과 일치, 오차 ±5% 내.

### Phase 3 — 전력 & 공간 엔진
- `engine/power.py`(UPS/배터리/발전기/변압기), `engine/space.py`.
- 이중화 규칙 `rules/redundancy.yaml` 연동(N/N+1/N+2/2N).
- 테스트: `test_power.py`(2N일 때 UPS 대수 2배 검증 등).
- **완료조건**: 이중화 등급 변경 시 장비 수량이 규칙대로 변동.

### Phase 4 — 네트워크 · 규격검증 · 산출물
- `engine/network.py`: GPU수→스케일아웃 포트→leaf/spine 대수→트랜시버·케이블 BOM.
- `engine/compliance.py`: `rules/tiers.yaml`·`ashrae.yaml` 대조, 위반 리포트.
- `reports/bom_xlsx.py`(openpyxl), `reports/design_basis_docx.py`(python-docx), `reports/diagram_mermaid.py`.
- **완료조건**: `examples/spec_gb200_5mw_tier3.yaml`로 xlsx·docx·mermaid 3종 무오류 생성.

### Phase 5 — CLI & 에이전트 연결
- `cli.py`: `dc-design build --spec <file> --out <dir>` (typer).
- `agents/*.md`를 `.claude/agents/`에 설치, `CLAUDE.md`에 오케스트레이션 절차 명시.
- 대화형 시나리오 검증: "GB200 5MW Tier III 부산 → 설계" 실행 시 오케스트레이터가 intake→sizing→M/E/ICT→compliance→reporter 순으로 엔진 호출.
- **완료조건**: CLI·대화형 양쪽에서 산출물 생성, README에 사용법.

---

## 6. spec.yaml (사용자 입력) 예시

```yaml
project: "AI DC 개념설계 - 예시"
target:
  mode: it_power          # it_power | rack_count | performance
  it_power_mw: 5.0
building:
  climate: "KR-Busan"     # 외기조건 프로파일 키
  ambient_design_c: 33
selection:
  rack: nvidia_gb200_nvl72
resilience:
  tier: "III"             # Uptime Tier
  electrical_redundancy: "2N"
  mechanical_redundancy: "N+1"
cooling:
  strategy: liquid_first  # 액냉 우선, 잔열 공냉
  chw_delta_t_k: 10
  target_pue: 1.25
```

---

## 7. 테스트/검증 요구 (품질 게이트)

- 단위테스트: 각 엔진 함수 최소 2케이스(정상/경계).
- **골든 회귀**: §2 앵커값(GB200 130kW급, Rubin ~600kW 로드맵)으로 상한/하한 sanity check.
- 물성/단위 검사: 유량·kVA·RT 단위 변환 라운드트립.
- 카탈로그 린트: `confidence=projected` 항목은 리포트에 "추정" 워터마크.
- 최종 검증 단계는 **서브에이전트(compliance)** 로 실행해 규격 위반·가정 목록을 사람이 읽을 리포트로 출력.

---

## 8. CLAUDE.md 에 넣을 운영 규칙(요약)

1. 수치는 반드시 `engine.*` 함수를 호출해 얻는다. 직접 계산·암산 금지.
2. 카탈로그에 없는 장비를 임의로 지어내지 않는다. 없으면 "카탈로그 부재"로 표시하고 후보 블록 추가를 제안.
3. 추정 사양(`projected`)은 결과에 반드시 불확실성(범위)과 함께 표기.
4. 산출물에는 "개념설계/타당성 수준이며 실시설계·인허가는 면허기술자 검토 필요" 고지문 삽입.
5. 국내 적용 시 전기설비규정(KEC 등) 관할 규칙으로 교체 가능함을 전제.

---

## 9. 확장(v2 이후)
- 신규 칩/장비: `data/*.yaml`에 블록 추가만으로 반영(코드 변경 없음).
- 시나리오 비교엔진: 칩세대·이중화·냉각방식 스윕 → CAPEX/PUE/면적 비교표.
- MCP 서버화: 엔진을 MCP 툴로 노출해 타 에이전트(예: 견적·일정)에서 호출.
- 국가별 규격 팩: `rules/`에 지역 규정 세트 추가.
