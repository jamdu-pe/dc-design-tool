# 공냉 역할 신설 + 잔여 정리 3건 — 설계

작성일: 2026-08-07
상태: 승인됨 (구현 계획 대기)

## 배경

`engine.cooling.size_cooling` 은 IT 발열을 액냉/공냉으로 나눠 `air_kw` 를 계산하지만,
그 공냉 잔열을 처리할 장비를 아무도 산정하지 않는다. 랙 카탈로그의 액냉 비율이
0.85~0.92 이므로 IT 부하의 8~15% 가 설계서에서 무주공산으로 남는다. 5MW 설계라면
약 600~750kW 다.

카탈로그에는 공냉측 블록 `rdhx_60kw`(subtype `rear_door_hx`)가 있으나 어떤 엔진도
소비하지 않는 유령 블록이다. `sizing.SELECTABLE_ROLES` 주석이 이 사실을 명시한다.

이 설계는 그 구멍을 메우고, 같은 세션에서 처리하기로 한 잔여 정리 3건을 함께 담는다.

## 목표

1. 공냉 잔열을 처리하는 장비를 **교체 가능한 역할**로 만들어 BOM·공간·규격검증에 태운다.
2. 첫 화면 기본 랙을 대표 모델(GB200)로 지정한다.
3. Windows 기본 콘솔에서 CLI 출력이 죽지 않게 한다.
4. 기본 장비 선택이 YAML 줄 순서에 의존하는 구조를 명시적 플래그로 바꾼다.

## 비목표

- CAPEX 데이터 확보 (공개 데이터시트에 단가가 없어 별도 경로가 필요하다).
- Streamlit Cloud 배포 (브라우저 작업).
- 공냉 장비의 소비전력을 별도로 모델링하는 것. 냉각 소비전력은 지금처럼
  `rules/cooling.yaml` 의 `cooling_power_ratio` 로 일괄 추정한다. PUE 계산식은
  **바뀌지 않는다**.

---

## 1. 공냉 역할 `air_cooling` 신설

### 1.1 역할 모델링 결정

`SELECTABLE_ROLES` 의 키는 곧 `subtype` 이고 `catalog.resolve()` 는 subtype 으로 후보를
찾는다. 따라서 RDHx 와 CRAH 가 서로 다른 subtype 이면 **한 드롭다운에서 서로 교체할 수
없다**.

채택: **subtype 을 역할명 `air_cooling` 하나로 통합**하고, 기술 방식은 인터페이스 필드로
내린다.

- `SELECTABLE_ROLES` 주석이 이미 "역할 = 도메인 엔진이 실제로 소비하는 자리"로
  정의하고 있고, 공냉 잔열을 받는 자리는 하나다.
- 방식이 다른 장비를 한 드롭다운에서 비교하는 것이 목적에 정확히 맞는다.
- 시나리오 스윕에서 `selections: [{air_cooling: rdhx_60kw}, {air_cooling: crah_...}]`
  한 축으로 방식 비교가 된다.
- UI·CLI·스윕·MCP 는 구조 변경 없이 그대로 흡수한다.

기각한 대안:
- spec 에 `air_cooling_method` 축을 신설 — 교체 축이 두 종류가 되어 `merge_selections`·
  UI·CLI·스윕·MCP 전부에 새 개념이 퍼진다. 얻는 것은 subtype 명명 일관성뿐이다.
- 두 subtype 을 모두 역할로 등록 — 안 쓰는 역할이 드롭다운에 계속 노출된다.

부작용으로 `dc-design catalog --type cooling` 출력에서 `rear_door_hx` 라는 subtype 이름이
사라진다. 방식은 `interface.method` 로 확인한다.

### 1.2 데이터 모델 (`engine/models.py`)

`Interface` 에 두 필드를 추가한다.

| 필드 | 타입 | 기본값 | 용도 |
|---|---|---|---|
| `mounting` | `Literal["rack", "room"]` | `"room"` | 수량 산정식 분기 |
| `method` | `Optional[str]` | `None` | 기술 방식 표기(`rear_door_hx`/`crah`/`in_row`) |

`method` 는 표시·추적용이고 계산에 쓰지 않는다. 계산이 보는 것은 `mounting` 뿐이다.
둘을 나누는 이유는, 같은 `mounting: room` 이라도 CRAH 와 인로우는 다른 이름으로
보고돼야 하기 때문이다.

### 1.3 카탈로그 (`data/cooling.yaml`)

`rdhx_60kw` 를 수정한다. **파일 내 위치는 그대로 둔다**(기본값 유지).

```yaml
- id: rdhx_60kw
  subtype: air_cooling          # rear_door_hx 에서 변경
  interface:
    capacity_kw: 60
    medium: liquid_to_air
    method: rear_door_hx
    mounting: rack
    footprint_m2: 0.0
```

교체 후보를 파일 뒤쪽 "교체용 후보" 절에 추가한다. 최소 구성:

| 방식 | mounting | 후보 |
|---|---|---|
| 후면도어 열교환기 | rack | Motivair ChilledDoor 계열, nVent 계열 |
| CRAH | room | Vertiv Liebert CRV 계열, STULZ CyberAir 계열 |

정격은 **공개 데이터시트 확인값만** 쓴다(절대규칙 2). 확인하지 못한 항목은
`confidence: projected` 로 두고 `source_url` 에 추정 근거를 밝힌다. `footprint_m2` 는
CRAH 의 경우 부속실 면적에 직접 영향을 주므로, 미확인이면 `# 미확인` 주석을 단다.

구현 시점에 실제 데이터시트를 조사한다. 이 문서에 수치를 미리 적지 않는다 —
확인하지 않은 값이 스펙에 박히면 그대로 카탈로그에 들어간다.

### 1.4 엔진 (`engine/cooling.py`)

`size_cooling` 시그니처에 `rack_count: int`, `rack_kw: float` 를 추가한다.
`sizing.size()` 는 냉각보다 먼저 `it_load` 를 돌리므로 두 값이 이미 손에 있다.
호출 순서는 바뀌지 않는다.

블록 결정은 다른 역할과 동일하게 `resolve("cooling", "air_cooling", blocks, selections)`.

**수량은 장착 방식에 따라 다른 식으로 구한다.**

- `mounting == "rack"` — 랙 후면에 붙는 장비라 랙마다 1대이고, 여분 도어를 매달 수
  없으므로 이중화 배수를 적용하지 않는다.

  ```
  qty = rack_count
  ```

  대신 **랙당 공냉 부하**가 단위용량을 넘는지 본다:

  ```
  rack_air_kw = rack_kw * (1 - liquid_fraction)
  ```

  GB200(120kW, 액냉 0.85)이면 18kW 로 60kW 도어에 충분히 들어간다. 넘으면 그 방식으로는
  물리적으로 불가능하므로 규격검증에서 잡는다(1.6절).

- `mounting == "room"` — 실 단위 장비이므로 CDU·칠러와 동일하게 처리한다.

  ```
  qty = calc.redundant_qty(air_kw, capacity_kw, 이중화규칙)
  ```

새 계산식은 도입하지 않는다. `calc.redundant_qty` 를 그대로 쓴다(절대규칙 1).

결과 dict 에 추가하는 키:

| 키 | 값 |
|---|---|
| `air_cooling_qty` | 산정 수량 |
| `air_cooling_unit_kw` | 단위 용량 |
| `air_cooling_method` | `interface.method` (없으면 `mounting` 값) |
| `air_cooling_mounting` | `rack` \| `room` |
| `rack_air_kw` | 랙당 공냉 부하 (rack 장착형 판정 근거, 항상 채운다) |
| `selected["air_cooling"]` | 쓰인 block_id |

BOM 에 한 줄을 더한다: `domain="기계"`, `item="공냉장비"`, `note` 는 rack 장착형이면
`"랙당 1대"`, room 장착형이면 이중화 등급.

### 1.5 오케스트레이션 (`engine/sizing.py`)

- `SELECTABLE_ROLES` 에 `"air_cooling": "cooling"` 추가.
- 같은 표의 주석에서 "예: rear_door_hx 는 아직 어떤 엔진도 쓰지 않아 제외" 문구를
  삭제한다(더 이상 사실이 아니다).
- `cooling_engine.size_cooling(...)` 호출에 `n_rack`, `rack_kw` 전달.

### 1.6 규격검증 (`engine/compliance.py`)

장착 방식에 따라 **서로 다른 판정**이 붙는다. 설치용량이 필요량 이상인지는
`redundant_qty` 가 이미 보장하므로 그것만 다시 확인하는 검사는 두지 않는다.

- `mounting == "room"` — `_check_redundancy_effectiveness` 의 `cases` 목록에 한 줄
  추가한다. UPS·CDU 와 동일하게 **1대 상실 후 잔여 용량**이 `air_kw × min_surviving_ratio`
  이상인지 본다. 코드는 `REDUNDANCY_EFFECTIVE_AIR_COOLING`, severity 는 기존과 같이
  통과 시 `info` / 미달 시 `warning`.

- `mounting == "rack"` — 이중화 개념이 없으므로 위 검사 대상이 아니다. 대신 단위용량이
  `rack_air_kw` 이상인지 보는 판정을 새로 둔다. 미달이면 랙당 1대라는 물리 제약상
  대수를 늘려 보완할 수 없으므로 `violation` 이고, 메시지는 단위용량이 큰 도어 또는
  실 단위 방식(CRAH)으로의 교체를 제시한다. 코드는 `AIR_COOLING_RACK_CAPACITY`,
  domain 은 `기계`, 통과 시 `info`.

두 판정은 상호배타적이다 — 한 설계에서 둘 중 하나만 나온다.

### 1.7 표시·산출물

계산이 아니라 표시만 바꾼다.

| 대상 | 변경 |
|---|---|
| `app.py` | 냉각 표 라벨에 `air_cooling_*` 추가, 장비 교체 드롭다운에 `air_cooling` 역할 라벨 |
| `reports/diagram_mermaid.py` | `"공냉 잔열 {air_kw}kW (CRAH/RDHx)"` 의 하드코딩 문구를 실제 선택 장비·수량으로 교체 |
| `reports/design_basis_docx.py` | 냉각 절에 "공냉 구성" 행 추가 |
| `cli.py` | 냉각 요약 한 줄에 공냉 장비 수량 추가 |

`reports/bom_xlsx.py` 는 BOM 을 그대로 쓰므로 변경 없다.

### 1.8 기존 수치에 대한 영향

기본 선택이 `rdhx_60kw`(footprint 0, indoor)로 유지되므로:

- IT 부하·전기·통신·PUE — 변화 없음.
- 공간 — `mechanical_equipment_m2` 는 footprint 0 이라 변화 없음. 단 CRAH 를 **선택했을
  때는** 부속실 면적이 늘어난다(의도된 동작).
- BOM — 줄 하나 추가.

골든 테스트의 앵커는 IT 부하·PUE 범위·UPS 수량·포트 수라 영향받지 않는다.

---

## 2. 사이드바 기본 랙 → GB200

`app.py` `_catalog()` 가 `default_rack` 키를 함께 반환한다. 값은
`nvidia_gb200_nvl72`, 카탈로그에 없으면 `rack_options[0]` 으로 폴백한다.
`st.sidebar.selectbox("랙 모델", ...)` 에 그 인덱스를 넘긴다.

화면은 계산하지 않는다는 원칙은 유지된다 — 목록도 기본값도 카탈로그에서 온다.
상수 `nvidia_gb200_nvl72` 는 "대표 모델" 이라는 표시상의 판단이므로 화면에 둔다.

## 3. CLI cp949 인코딩

Windows 기본 콘솔(cp949)에서 규격검증 메시지의 em-dash 같은 문자가
`UnicodeEncodeError` 를 낸다. 한글 자체는 cp949 로 정상 인코딩되므로 문제는 일부
문장부호다.

그 문자는 엔진·규칙 파일·설명 문자열 곳곳에 흩어져 있어 하나씩 치환하는 것은
두더지잡기다. **`cli.py` 진입점 한 곳에서** `sys.stdout`/`sys.stderr` 를
`errors="replace"` 로 재설정한다. 콘솔 인코딩은 그대로 두므로 한글은 정상 출력되고
인코딩 불가 문자만 `?` 로 떨어진다.

UTF-8 로 강제 전환하지 않는 이유: cp949 콘솔에 UTF-8 바이트를 흘리면 한글 전체가
깨진다. 지금은 특수문자 하나만 깨지는 상태이므로 그쪽이 더 나쁘다.

재설정은 스트림이 `reconfigure` 를 지원할 때만 시도하고(파이프·캡처된 스트림 대비),
실패해도 CLI 가 죽지 않게 한다.

## 4. 기본 장비 선택의 YAML 순서 의존 제거

현재 `catalog.resolve()` 는 선택이 없으면 `candidates[0]` 을 쓴다. 즉 `data/*.yaml` 의
줄 순서가 기본 설계를 정한다. 기존 블록 앞에 새 블록을 끼워 넣으면 모든 결과가
조용히 바뀐다. 세 파일 상단에 경고 주석이 있으나 코드가 막지는 않는다.

`Block` 에 `default: bool = False` 를 추가하고, `resolve()` 가 선택 미지정 시
**플래그가 붙은 후보**를 쓴다.

플래그가 하나도 없으면 기존대로 첫 후보로 폴백한다. 테스트가 주입하는 임시 카탈로그
(`blocks=` 인자)에는 플래그가 없기 때문이고, 이 폴백이 없으면 기존 테스트가 대량으로
깨진다. 대신 **배포 카탈로그**에 대해 `SELECTABLE_ROLES` 의 모든 역할이 정확히 하나의
`default: true` 를 갖는지 검사하는 테스트를 둔다. 이로써 실제 설계 경로에서는 순서
의존이 사라지고, 실수는 테스트가 잡는다.

`sizing._candidate_table` 의 `is_default` 도 인덱스 0 이 아니라 이 플래그를 본다
(플래그가 없으면 인덱스 0 폴백).

`data/cooling.yaml`·`electrical.yaml`·`network.yaml` 의 현재 첫 후보들에 `default: true`
를 붙인다. 어느 블록이 기본인지는 지금 동작을 그대로 보존하도록 정한다.

문서도 함께 고친다 — 이것은 문서화된 규칙의 변경이다.

- `CLAUDE.md` 「장비 교체」 절의 "카탈로그 등재 순서상 첫 후보" 서술
- `data/*.yaml` 세 파일 상단의 `[순서 주의]` 경고 주석
- `status.md` 의 "알려진 제약" 항목

---

## 테스트

새 테스트는 기존 파일 배치를 따른다.

| 대상 | 파일 | 내용 |
|---|---|---|
| 공냉 수량식 | `test_cooling.py` | rack 장착형은 랙 수와 같고 이중화에 불변 / room 장착형은 이중화 등급에 반응 |
| 공냉 교체 | `test_selection.py` | `air_cooling` 교체 시 수량·BOM·부속실 면적이 재산정된다 |
| 공냉 규격검증 | `test_compliance*.py` | 랙당 부하 초과 시 `AIR_COOLING_RACK_CAPACITY` violation / room 장착형 선택 시 `REDUNDANCY_EFFECTIVE_AIR_COOLING` 산출 |
| 기본값 불변 | `test_golden_gb200.py` | 기본 선택이 `rdhx_60kw` 이고 IT·전기·PUE 앵커가 그대로 |
| 기본 랙 | `test_app.py` | 첫 화면 기본 랙이 GB200 |
| CLI 인코딩 | `test_cli.py` | cp949 스트림에 em-dash 포함 출력을 흘려도 예외 없음 |
| default 플래그 | `test_selection.py` | 모든 SELECTABLE_ROLES 가 정확히 하나의 `default: true` / 플래그가 선택을 이긴다 / 플래그 없으면 첫 후보 폴백 |

## 검증

- `pytest` 전량 통과 (현재 333개 + 신규).
- `dc-design build --spec examples/spec_gb200_5mw_tier3.yaml --out out/` 이 공냉 장비를
  BOM 에 포함해 산출한다.
- Windows 기본 콘솔에서 `dc-design check --verbose` 가 예외 없이 끝난다.

## 위험

- **공냉 카탈로그의 데이터 품질** — 벤더 정격을 확인하지 못하면 `projected` 블록만
  늘어난다. 확인값이 없으면 후보를 추가하지 않는 편이 낫다(절대규칙 3의 정신).
- **`subtype` 이름 변경** — `rear_door_hx` 를 문자열로 참조하는 곳이 남아 있으면
  조용히 후보 0건이 된다. `resolve()` 는 이 경우 `KeyError` 를 내므로 조용히 틀리지는
  않는다.
- `default` 플래그의 폴백 경로가 남아 있어, 배포 카탈로그에 플래그를 빠뜨리면 다시
  순서 의존이 된다. 이를 막는 것이 위 테스트 1건이다.
