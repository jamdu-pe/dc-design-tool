# 공냉 역할 `air_cooling` 신설 + 잔여 정리 3건 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** IT 부하의 8~15% 를 차지하는 공냉 잔열(`air_kw`)을 처리할 장비를 교체 가능한 역할로 만들어 BOM·공간·규격검증에 태우고, 함께 미뤄둔 정리 3건(기본 랙·CLI 인코딩·YAML 순서 의존)을 끝낸다.

**Architecture:** `subtype` 을 역할명 `air_cooling` 하나로 통합해 RDHx(랙 장착)와 CRAH(실 장착)를 같은 드롭다운에서 교체하게 하고, 수량 산정식만 `interface.mounting` 으로 분기한다. 기본 장비 선택은 YAML 줄 순서 대신 `Block.default` 플래그가 정한다.

**Tech Stack:** Python 3.13, pydantic v2, PyYAML, typer, pytest, Streamlit(UI 테스트는 `streamlit.testing.v1.AppTest`)

**설계 문서:** [docs/superpowers/specs/2026-08-07-air-cooling-role-and-cleanups-design.md](../specs/2026-08-07-air-cooling-role-and-cleanups-design.md)

## Global Constraints

프로젝트 루트 `CLAUDE.md` 의 절대 규칙이 모든 태스크에 적용된다.

- **모든 수치는 `engine.*` 함수 호출로 얻는다.** 새 계산식을 만들지 말고 기존
  `calc.redundant_qty` 등을 재사용한다. 화면(`app.py`)·CLI·리포트에서 사칙연산 금지.
- **카탈로그 각 항목은 `as_of_date`, `confidence`, `source_url` 이 필수다.**
  `catalog.load_blocks()` 가 `source_url` 누락을 `ValueError` 로 막는다.
- **카탈로그에 없는 장비를 지어내지 않는다.** 확인하지 못한 사양은
  `confidence: projected` + 근거 주석.
- **설계 계수는 `rules/*.yaml` 에서 읽는다.** 코드에 상수로 박지 않는다.
- **커밋은 `pytest` 통과 후에만.** 각 태스크 마지막 스텝이 커밋이다.
- 테스트 실행은 `python -X utf8 -m pytest` 를 쓴다(Windows 콘솔 인코딩 때문. 이
  계획의 Task 8 이 그 원인을 고치지만, 그 전까지는 `-X utf8` 이 필요하다).
- 기존 테스트 333개는 전부 통과 상태를 유지해야 한다.

---

## File Structure

| 파일 | 역할 | 태스크 |
|---|---|---|
| `dc_design_tool/engine/models.py` | `Interface.mounting`/`method`, `Block.default` | 1, 3 |
| `dc_design_tool/engine/catalog.py` | `resolve()` 가 `default` 플래그를 본다 | 1 |
| `dc_design_tool/engine/sizing.py` | `_candidate_table.is_default`, `SELECTABLE_ROLES` | 1, 3 |
| `dc_design_tool/engine/cooling.py` | 공냉 장비 결정·수량 산정·BOM | 3 |
| `dc_design_tool/engine/compliance.py` | 공냉 판정 2종 | 5 |
| `dc_design_tool/data/cooling.yaml` | `rdhx_60kw` 전환 + 공냉 후보 | 1, 3, 4 |
| `dc_design_tool/data/electrical.yaml`, `network.yaml` | `default: true` 플래그 | 1 |
| `dc_design_tool/reports/diagram_mermaid.py`, `design_basis_docx.py` | 공냉 표시 | 6 |
| `dc_design_tool/cli.py` | 공냉 요약 한 줄, 콘솔 인코딩 방어 | 6, 8 |
| `app.py` | 공냉 라벨·드롭다운, 기본 랙 | 6, 7 |
| `CLAUDE.md`, `status.md` | 규칙·현황 문서 | 1, 9 |

---

## Task 1: 기본 장비 선택을 `default` 플래그로 (YAML 순서 의존 제거)

지금 `catalog.resolve()` 는 선택이 없으면 `candidates[0]` 을 쓴다. 즉 `data/*.yaml` 의
줄 순서가 기본 설계를 정하고, 기존 블록 앞에 새 블록을 끼워 넣으면 모든 결과가 조용히
바뀐다. 이 태스크가 그 의존을 없앤다. **Task 3 이 공냉 역할을 추가하기 전에 먼저 한다**
— 그래야 새 역할이 처음부터 플래그 규율 안에서 태어난다.

**Files:**
- Modify: `dc_design_tool/engine/models.py` (`Block` 클래스, 50-60행)
- Modify: `dc_design_tool/engine/catalog.py` (`list_candidates` 50-62행, `resolve` 65-95행)
- Modify: `dc_design_tool/engine/sizing.py` (`_candidate_table` 59-73행)
- Modify: `dc_design_tool/data/cooling.yaml`, `electrical.yaml`, `network.yaml`
- Modify: `CLAUDE.md` (「장비 교체」 절)
- Test: `tests/test_selection.py`

**Interfaces:**
- Produces: `Block.default: bool` — 역할 안에서 기본 선택인지. `resolve(type_, subtype, blocks, selections)` 는 선택 미지정 시 `default is True` 인 후보를, 없으면 `candidates[0]` 을 반환한다(시그니처 불변).
- Consumes: 없음.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_selection.py` 끝에 붙인다.

```python
# ---------- default 플래그 (YAML 순서 의존 제거) ----------

def test_every_selectable_role_has_exactly_one_default():
    """배포 카탈로그의 모든 역할에 기본 블록이 정확히 하나여야 한다.

    이 테스트가 있어야 `resolve()` 의 '첫 후보' 폴백 경로가 실제 설계에서 쓰이지
    않는다. 새 역할을 추가하면 여기서 먼저 걸린다.
    """
    blocks = load_blocks()
    for role, type_ in SELECTABLE_ROLES.items():
        flagged = [b.id for b in list_candidates(type_, role, blocks) if b.default]
        assert len(flagged) == 1, f"역할 '{role}' 의 default 블록: {flagged}"


def test_resolve_prefers_default_flag_over_yaml_order():
    """플래그가 붙은 블록이 등재 순서를 이긴다."""
    blocks = load_blocks()
    first, second = list_candidates("electrical", "ups", blocks)[:2]
    moved = dict(blocks)
    moved[first.id] = first.model_copy(update={"default": False})
    moved[second.id] = second.model_copy(update={"default": True})
    assert resolve("electrical", "ups", moved).id == second.id


def test_resolve_falls_back_to_first_when_no_flag():
    """플래그가 하나도 없으면 기존대로 첫 후보. 주입 카탈로그(테스트용)를 위한 폴백."""
    blocks = load_blocks()
    unflagged = {bid: b.model_copy(update={"default": False})
                 for bid, b in blocks.items()}
    expected = list_candidates("cooling", "chiller", unflagged)[0].id
    assert resolve("cooling", "chiller", unflagged).id == expected


def test_candidate_table_marks_flagged_block_as_default():
    """UI 후보표의 is_default 도 인덱스가 아니라 플래그를 본다."""
    result = size(_spec())
    for role in SELECTABLE_ROLES:
        marked = [c["id"] for c in result.candidates[role] if c["is_default"]]
        assert len(marked) == 1, f"{role}: {marked}"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_selection.py -k "default" -v`
Expected: FAIL — `test_every_selectable_role_has_exactly_one_default` 가 `역할 'cdu' 의 default 블록: []` 로 떨어진다(아직 `Block.default` 필드가 없어 `AttributeError` 가 날 수도 있다. 둘 다 정상적인 실패다).

- [ ] **Step 3: `Block` 에 `default` 필드를 더한다**

`dc_design_tool/engine/models.py` 의 `Block` 클래스에서 `confidence` 위에 넣는다.

```python
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
```

- [ ] **Step 4: `resolve()` 가 플래그를 보게 한다**

`dc_design_tool/engine/catalog.py`. `resolve` 의 docstring 첫 줄과 87-89행을 바꾼다.

```python
def resolve(type_: str, subtype: str, blocks: dict[str, Block],
            selections: Optional[dict[str, str]] = None) -> Block:
    """역할에 쓸 블록을 정한다. 선택이 있으면 그것을, 없으면 기본 블록을 쓴다.

    기본 블록은 `default: true` 가 붙은 후보다. 플래그가 하나도 없으면 첫 후보로
    폴백한다(테스트가 주입하는 임시 카탈로그를 위한 것이며, 배포 카탈로그는
    tests/test_selection.py 가 모든 역할에 플래그를 강제한다).

    블록을 고르기만 하고 어떤 계산도 하지 않는다. 수량·용량은 호출한 도메인
    엔진이 `calc.*` 로 재산정한다(CLAUDE.md 절대규칙 1).

    Args:
        type_: 블록 종류(cooling|electrical|network).
        subtype: 역할(ups, cdu, leaf 등).
        blocks: 카탈로그.
        selections: 역할 → block_id. 해당 역할 키가 없으면 기본 블록을 쓴다.

    Raises:
        KeyError: 후보가 하나도 없거나, 지정한 id 가 없거나, 그 id 의 역할이
            요청한 역할과 다를 때(후보 목록을 메시지에 담는다).
    """
    candidates = list_candidates(type_, subtype, blocks)
    if not candidates:
        raise KeyError(f"카탈로그 부재: {type_}/{subtype} — "
                       f"data/{type_}.yaml 에 블록 추가 필요")

    chosen_id = (selections or {}).get(subtype)
    if not chosen_id:
        return next((b for b in candidates if b.default), candidates[0])

    for block in candidates:
        if block.id == chosen_id:
            return block
    raise KeyError(f"선택 불가: 역할 '{subtype}' 에 '{chosen_id}' — 후보: "
                   f"{', '.join(b.id for b in candidates)}")
```

같은 파일 `list_candidates` 의 docstring 2~3행을 고친다(더 이상 [0]이 기본이 아니다).

```python
    """해당 역할을 맡을 수 있는 블록 후보를 카탈로그 등재 순서대로 반환한다.

    순서는 표시 순서일 뿐이고, 기본 선택은 `default: true` 플래그가 정한다
    (`resolve` 참고).

    조건에 맞는 블록이 없으면 예외가 아니라 빈 목록을 준다(UI 가 "후보 없음"을
    그릴 수 있어야 한다). 실제 사용 시점의 부재 판정은 `resolve`가 한다.
    """
```

- [ ] **Step 5: 후보표의 `is_default` 를 플래그 기준으로 바꾼다**

`dc_design_tool/engine/sizing.py` 의 `_candidate_table` 을 통째로 교체한다.

```python
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
```

- [ ] **Step 6: 카탈로그 11개 역할에 `default: true` 를 붙인다**

**현재 동작을 그대로 보존하도록** 지금의 첫 후보에 붙인다. `id:` 바로 아래 줄에
`default: true` 를 넣는다(다른 필드 순서는 건드리지 않는다).

| 파일 | 붙일 블록 |
|---|---|
| `data/cooling.yaml` | `cdu_liquid_1300kw`, `chiller_1000rt` |
| `data/electrical.yaml` | `ups_1250kva`, `battery_cabinet_200kwh`, `genset_2500kw`, `tx_2500kva`, `pdu_rack_50kw`, `busway_800a` |
| `data/network.yaml` | `leaf_switch_64x800g`, `spine_switch_64x800g`, `transceiver_800g_osfp` |

예:

```yaml
- id: cdu_liquid_1300kw
  default: true                # 이 역할의 기본 블록 (줄 순서가 아니라 이 플래그가 정한다)
  type: cooling
  subtype: cdu
```

`rdhx_60kw` 는 아직 역할이 아니므로 **건드리지 않는다**(Task 3 에서 처리).

- [ ] **Step 7: 세 YAML 상단의 `[순서 주의]` 경고를 갱신한다**

`data/cooling.yaml`·`electrical.yaml`·`network.yaml` 상단의 기존 `[순서 주의]` 문단을
아래로 바꾼다(문구는 세 파일 공통).

```yaml
# [기본 블록] 각 subtype 의 기본 선택은 `default: true` 플래그가 정한다. 줄 순서는
# 표시 순서일 뿐이며 설계 결과를 바꾸지 않는다. 역할마다 플래그는 정확히 하나여야
# 하고, tests/test_selection.py 가 이를 강제한다.
```

- [ ] **Step 8: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_selection.py -v`
Expected: PASS (기존 22개 + 신규 4개)

기존 `test_list_candidates_first_is_current_default` 와
`test_resolve_without_selection_returns_first_candidate` 도 통과해야 한다 — 플래그를
첫 후보에 붙였으므로 결과가 같다. 만약 실패한다면 Step 6 에서 잘못된 블록에 플래그를
붙인 것이다.

- [ ] **Step 9: 전량 회귀를 돌린다**

Run: `python -X utf8 -m pytest -q`
Expected: 337 passed (기존 333 + 신규 4). 실패가 있으면 Step 6 의 플래그 위치가 현재
첫 후보와 다르다는 뜻이다.

- [ ] **Step 10: `CLAUDE.md` 의 「장비 교체」 절을 고친다**

기존 문장:

```
지정하지 않은 역할은 **카탈로그 등재 순서상 첫 후보**를 쓴다.
따라서 `data/*.yaml` 안의 순서가 곧 기본 설계다 — 기존 블록 앞에 새 블록을 끼워 넣지 말 것.
```

교체:

```
지정하지 않은 역할은 카탈로그에서 **`default: true` 가 붙은 블록**을 쓴다.
YAML 줄 순서는 표시 순서일 뿐 설계 결과를 바꾸지 않는다. 역할마다 플래그는 정확히
하나여야 하며 `tests/test_selection.py` 가 이를 강제한다. 새 역할을 만들면 후보 하나에
플래그를 붙일 것.
```

- [ ] **Step 11: 커밋**

```bash
git add dc_design_tool/engine/models.py dc_design_tool/engine/catalog.py \
        dc_design_tool/engine/sizing.py dc_design_tool/data/cooling.yaml \
        dc_design_tool/data/electrical.yaml dc_design_tool/data/network.yaml \
        CLAUDE.md tests/test_selection.py
git commit -m "기본 장비 선택을 default 플래그로 — YAML 순서 의존 제거"
```

---

## Task 2: `Interface` 에 `mounting`·`method` 추가

공냉 장비의 수량 산정식은 장착 방식에 따라 갈린다. 그 분기 기준을 인터페이스 필드로
먼저 만든다.

**Files:**
- Modify: `dc_design_tool/engine/models.py` (`Interface` 클래스, 16-19행 "발열/냉각" 구역)
- Test: `tests/test_selection.py`

**Interfaces:**
- Produces: `Interface.mounting: Literal["rack", "room"]`(기본 `"room"`), `Interface.method: Optional[str]`. Task 3 의 `cooling.size_cooling` 과 Task 5 의 규격검증이 이 두 필드를 읽는다.
- Consumes: Task 1 의 `Block.default`(같은 파일을 고치므로 순서 의존).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_selection.py` 끝에 붙인다.

```python
# ---------- 장착 방식 인터페이스 ----------

def test_interface_defaults_to_room_mounting():
    """대부분의 장비는 실 단위 설치다. 랙 장착형만 명시한다."""
    from dc_design_tool.engine.models import Interface
    assert Interface().mounting == "room"
    assert Interface().method is None


def test_interface_rejects_unknown_mounting():
    from pydantic import ValidationError as PydanticError
    from dc_design_tool.engine.models import Interface
    with pytest.raises(PydanticError):
        Interface(mounting="ceiling")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_selection.py -k "mounting" -v`
Expected: FAIL — `Interface().mounting` 에서 `AttributeError`. 두 번째 테스트는
`Interface` 가 `extra="allow"` 라 예외가 나지 않아 실패한다.

- [ ] **Step 3: 필드를 더한다**

`dc_design_tool/engine/models.py` 의 `Interface` "발열/냉각" 구역에 넣는다.

```python
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_selection.py -k "mounting" -v`
Expected: PASS (2개)

- [ ] **Step 5: 전량 회귀**

Run: `python -X utf8 -m pytest -q`
Expected: 339 passed

- [ ] **Step 6: 커밋**

```bash
git add dc_design_tool/engine/models.py tests/test_selection.py
git commit -m "Interface 에 mounting·method 추가 — 냉각장비 설치 형태"
```

---

## Task 3: 공냉 역할 `air_cooling` 을 냉각 엔진에 연결

이 계획의 핵심이다. `rdhx_60kw` 를 유령 블록에서 실제 소비되는 역할로 바꾸고,
`air_kw` 를 처리할 장비 수량을 산정해 BOM 에 태운다.

**Files:**
- Modify: `dc_design_tool/data/cooling.yaml` (`rdhx_60kw`, 24-35행)
- Modify: `dc_design_tool/engine/cooling.py` (`size_cooling`, 23-76행)
- Modify: `dc_design_tool/engine/sizing.py` (`SELECTABLE_ROLES` 15-23행, `size` 108-111행)
- Test: `tests/test_cooling.py`

**Interfaces:**
- Consumes: Task 2 의 `Interface.mounting`/`method`, Task 1 의 `Block.default`.
- Produces:
  - `cooling.size_cooling(it_kw, rack, spec, blocks, redundancy_rules=None, selections=None, rack_count=None, rack_kw=None)` — 뒤 두 인자는 새로 추가된 키워드 인자다. `None` 이면 각각 `spec.rack_count` 와 `rack.interface.power_kw_typical` 로 폴백한다.
  - 결과 dict 신규 키: `air_cooling_qty: int`, `air_cooling_unit_kw: float`, `air_cooling_method: str`, `air_cooling_mounting: str`, `rack_air_kw: float`, 그리고 `selected["air_cooling"]: str`. Task 5·6 이 이 키들을 읽는다.
  - BOM 신규 항목: `item="공냉장비"`.
  - `SELECTABLE_ROLES["air_cooling"] == "cooling"`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_cooling.py` 끝에 붙인다.

```python
# ---------- 공냉 장비 (air_cooling) ----------

def test_rack_mounted_air_cooling_is_one_per_rack(blocks):
    """랙 후면 장착형은 랙당 1대다. 용량으로 대수를 줄이거나 늘리지 않는다."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    c, _ = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                rack_count=42, rack_kw=120.0)
    assert c["air_cooling_mounting"] == "rack"
    assert c["air_cooling_qty"] == 42


def test_rack_mounted_air_cooling_ignores_redundancy_grade(blocks):
    """여분 도어를 매달 수 없으므로 이중화 등급에 불변이다."""
    rack = blocks["nvidia_gb200_nvl72"]
    qty = []
    for grade in ("N", "N+2", "2N"):
        c, _ = cooling.size_cooling(5040.0, rack, Spec(
            rack_id="x", rack_count=42, mechanical_redundancy=grade), blocks,
            rack_count=42, rack_kw=120.0)
        qty.append(c["air_cooling_qty"])
    assert qty == [42, 42, 42]


def test_rack_air_load_is_reported(blocks):
    """랙당 공냉 부하 = 랙 부하 x (1 - 액냉비율). GB200 은 120 x 0.15 = 18kW."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    c, _ = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                rack_count=42, rack_kw=120.0)
    assert c["rack_air_kw"] == pytest.approx(18.0, abs=0.1)


def test_air_cooling_defaults_to_rdhx(blocks):
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    c, _ = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                rack_count=42, rack_kw=120.0)
    assert c["selected"]["air_cooling"] == "rdhx_60kw"
    assert c["air_cooling_method"] == "rear_door_hx"


def test_air_cooling_appears_in_bom(blocks):
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=42)
    _, bom = cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks,
                                  rack_count=42, rack_kw=120.0)
    line = next(li for li in bom if li.item == "공냉장비")
    assert line.block_id == "rdhx_60kw"
    assert line.qty == 42
    assert line.note == "랙당 1대"


def test_rack_count_falls_back_to_spec(blocks):
    """엔진을 직접 부를 때는 spec.rack_count 로 폴백한다."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", rack_count=7)
    c, _ = cooling.size_cooling(840.0, blocks["nvidia_gb200_nvl72"], spec, blocks)
    assert c["air_cooling_qty"] == 7


def test_rack_mounted_without_rack_count_raises(blocks):
    """랙 수량을 알 수 없으면 조용히 0대로 넘기지 않는다."""
    spec = Spec(rack_id="nvidia_gb200_nvl72", it_power_mw=5.0)
    with pytest.raises(ValueError, match="랙 수량"):
        cooling.size_cooling(5040.0, blocks["nvidia_gb200_nvl72"], spec, blocks)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_cooling.py -k "air_cooling or rack_air or rack_count" -v`
Expected: FAIL — `size_cooling() got an unexpected keyword argument 'rack_count'`

- [ ] **Step 3: `rdhx_60kw` 를 역할 블록으로 바꾼다**

`dc_design_tool/data/cooling.yaml` 의 24-35행을 교체한다. **파일 내 위치는 그대로 둔다**
(다른 블록 앞뒤로 옮기지 않는다).

```yaml
- id: rdhx_60kw
  default: true                # air_cooling 역할의 기본 블록
  type: cooling
  subtype: air_cooling         # 공냉 잔열 처리 역할(방식은 interface.method)
  vendor: Generic
  model: RDHx-60
  interface:
    capacity_kw: 60
    medium: liquid_to_air
    method: rear_door_hx       # 후면도어 열교환기
    mounting: rack             # 랙 후면 장착 → 랙당 1대
    footprint_m2: 0.0          # 랙에 붙으므로 별도 바닥면적을 차지하지 않는다
  as_of_date: "2025-06"
  confidence: vendor
  source_url: "generic-industry-typical"
```

- [ ] **Step 4: 냉각 엔진에 공냉 산정을 넣는다**

`dc_design_tool/engine/cooling.py` 의 `size_cooling` 을 통째로 교체한다.

```python
def size_cooling(it_kw: float, rack: Block, spec: Spec, blocks: dict[str, Block],
                 redundancy_rules: Optional[dict] = None,
                 selections: Optional[dict[str, str]] = None,
                 rack_count: Optional[int] = None,
                 rack_kw: Optional[float] = None
                 ) -> tuple[dict, list[LineItem]]:
    """냉각 사이징 결과(dict)와 BOM(list) 반환.

    Args:
        selections: 역할 → block_id. `cdu`·`chiller`·`air_cooling` 을 교체할 수 있다.
            미지정 역할은 카탈로그의 기본 블록(`default: true`)을 쓴다. 교체해도
            수량·유량은 아래 `calc.*` 로 재산정한다.
        rack_count: 랙 수량. 랙 장착형 공냉장비의 대수다. None 이면 `spec.rack_count`.
        rack_kw: 랙 1대의 부하[kW]. 랙당 공냉 부하 판정에 쓴다. None 이면
            `rack.interface.power_kw_typical`.

    Raises:
        KeyError: CDU/칠러/공냉 블록이 카탈로그에 없거나 선택한 id 가 유효하지 않을 때.
        ValueError: 액냉 비율·ΔT가 유효하지 않거나, 랙 장착형 공냉장비인데 랙 수량을
            알 수 없을 때.
    """
    red = redundancy_rules or load_rule("redundancy.yaml", spec.region)
    if spec.mechanical_redundancy not in red:
        raise KeyError(f"정의되지 않은 이중화 등급: '{spec.mechanical_redundancy}'")
    rule = red[spec.mechanical_redundancy]

    q_liq, q_air = liquid_air_split(it_kw, rack.interface.liquid_fraction)
    flow = calc.coolant_flow_lpm(q_liq, spec.chw_delta_t_k)
    rt = calc.rt_from_kw(it_kw)

    cdu = resolve("cooling", "cdu", blocks, selections)
    chiller = resolve("cooling", "chiller", blocks, selections)
    n_cdu = calc.redundant_qty(q_liq, cdu.interface.capacity_kw, rule)
    n_chiller = calc.redundant_qty(it_kw, chiller.interface.capacity_kw, rule)

    # ---- 공냉 잔열 처리 장비 ----
    # 랙 장착형은 랙당 1대라 이중화 배수를 적용하지 않는다(여분 도어를 매달 수 없다).
    # 실 장착형은 CDU·칠러와 같은 규칙으로 대수를 구한다.
    air = resolve("cooling", "air_cooling", blocks, selections)
    n_rack = rack_count if rack_count is not None else spec.rack_count
    kw_rack = rack_kw if rack_kw is not None else rack.interface.power_kw_typical
    rack_air_kw = (kw_rack or 0.0) * (1.0 - rack.interface.liquid_fraction)

    if air.interface.mounting == "rack":
        if not n_rack:
            raise ValueError(
                f"{air.model}: 랙 장착형 공냉장비는 랙 수량이 필요하다 — "
                "rack_count 인자 또는 spec.rack_count 를 지정할 것")
        n_air, air_note = n_rack, "랙당 1대"
    else:
        n_air = calc.redundant_qty(q_air, air.interface.capacity_kw, rule)
        air_note = spec.mechanical_redundancy

    result = {
        "it_heat_kw": round(it_kw, 1),
        "liquid_kw": round(q_liq, 1),
        "air_kw": round(q_air, 1),
        "liquid_fraction": rack.interface.liquid_fraction,
        "supply_water_c": rack.interface.supply_water_c,
        "chw_delta_t_k": spec.chw_delta_t_k,
        "coolant_flow_lpm": round(flow, 1),
        "total_rt": round(rt, 1),
        "cdu_qty": n_cdu,
        "cdu_unit_kw": cdu.interface.capacity_kw,
        "chiller_qty": n_chiller,
        "chiller_unit_kw": chiller.interface.capacity_kw,
        "air_cooling_qty": n_air,
        "air_cooling_unit_kw": air.interface.capacity_kw,
        "air_cooling_method": air.interface.method or air.interface.mounting,
        "air_cooling_mounting": air.interface.mounting,
        "rack_air_kw": round(rack_air_kw, 1),
        "redundancy": spec.mechanical_redundancy,
        "selected": {"cdu": cdu.id, "chiller": chiller.id, "air_cooling": air.id},
    }
    bom = [
        LineItem(domain="기계", item="CDU", model=cdu.model, block_id=cdu.id,
                 unit_capacity=f"{cdu.interface.capacity_kw}kW", qty=n_cdu,
                 note=spec.mechanical_redundancy),
        LineItem(domain="기계", item="칠러", model=chiller.model, block_id=chiller.id,
                 unit_capacity=f"{int(chiller.interface.capacity_kw)}kW", qty=n_chiller,
                 note=spec.mechanical_redundancy),
        LineItem(domain="기계", item="공냉장비", model=air.model, block_id=air.id,
                 unit_capacity=f"{int(air.interface.capacity_kw)}kW", qty=n_air,
                 note=air_note),
    ]
    return result, bom
```

- [ ] **Step 5: 역할을 등록하고 랙 정보를 넘긴다**

`dc_design_tool/engine/sizing.py` 두 곳.

`SELECTABLE_ROLES` (15-23행) 를 교체 — 주석의 "rear_door_hx 제외" 문구가 더 이상
사실이 아니다.

```python
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
```

`size()` 의 냉각 호출(108-111행)을 교체.

```python
    # ---- 2) 기계(냉각) ----
    cooling, c_bom = cooling_engine.size_cooling(it_kw, rack, spec, blocks,
                                                 selections=selections,
                                                 rack_count=n_rack, rack_kw=rack_kw)
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_cooling.py -v`
Expected: PASS (기존 9개 + 신규 7개)

- [ ] **Step 7: 전량 회귀**

Run: `python -X utf8 -m pytest -q`
Expected: 346 passed

`test_selection.py::test_every_selectable_role_has_exactly_one_default` 가 새 역할
`air_cooling` 까지 검사한다 — Step 3 에서 `default: true` 를 붙였으므로 통과한다.
골든 테스트도 통과해야 한다(기본 블록 footprint 0 → 면적·PUE 불변).

- [ ] **Step 8: 커밋**

```bash
git add dc_design_tool/data/cooling.yaml dc_design_tool/engine/cooling.py \
        dc_design_tool/engine/sizing.py tests/test_cooling.py
git commit -m "공냉 역할 air_cooling 신설 — air_kw 를 처리할 장비를 BOM 에 태운다"
```

---

## Task 4: 공냉 교체 후보를 카탈로그에 추가

역할은 만들어졌지만 후보가 하나뿐이라 아직 "교체 가능"하지 않다. 실제 벤더
데이터시트를 조사해 후보를 채운다.

**Files:**
- Modify: `dc_design_tool/data/cooling.yaml` ("교체용 후보" 절 끝)
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: Task 3 의 `subtype: air_cooling`, Task 2 의 `mounting`/`method`.
- Produces: `mounting: room` 인 공냉 후보 최소 1종(Task 5 의 room 판정 테스트가 필요로 한다).

- [ ] **Step 1: 벤더 사양을 조사한다**

WebSearch/WebFetch 로 아래를 찾는다. **공개 데이터시트에서 확인한 값만 쓴다.**

| 방식 | mounting | 조사 대상 | 필요한 값 |
|---|---|---|---|
| 후면도어 열교환기 | `rack` | Motivair ChilledDoor, nVent 계열 | `capacity_kw` |
| CRAH | `room` | Vertiv Liebert CRV, STULZ CyberAir | `capacity_kw`, `footprint_m2` |

규칙:
- 확인한 값 → `confidence: vendor`, `source_url` 에 데이터시트 URL.
- 제품은 실재하나 수치를 확인 못 했으면 → `confidence: projected`, `source_url` 에
  추정 근거를 괄호로 밝힌다(기존 `cdu_coolit_chx750` 항목이 예시다).
- 아예 못 찾으면 **그 후보를 넣지 않는다.** 지어내지 않는다(절대규칙 3).
- `footprint_m2` 미확인 시 동급 통상값 + `# 미확인` 주석. CRAH 는 기계실 면적에
  직접 영향을 주므로 반드시 주석을 단다.

최소 요건: **`mounting: room` 후보를 1종 이상** 확보한다. 못 찾으면 Task 5 의 room
판정을 검증할 수 없다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_selection.py` 끝에 붙인다.

```python
# ---------- 공냉 후보 교체 ----------

def test_air_cooling_has_both_mounting_types():
    """랙 장착형과 실 장착형이 모두 있어야 방식 비교가 성립한다."""
    blocks = load_blocks()
    mountings = {b.interface.mounting
                 for b in list_candidates("cooling", "air_cooling", blocks)}
    assert mountings == {"rack", "room"}


def test_swapping_to_room_air_cooling_changes_quantity_and_area():
    """실 장착형으로 바꾸면 대수가 용량 기준으로 재산정되고 기계실 면적이 는다."""
    blocks = load_blocks()
    room = next(b for b in list_candidates("cooling", "air_cooling", blocks)
                if b.interface.mounting == "room")
    base = size(_spec())
    swapped = size(_spec(), selections={"air_cooling": room.id})

    assert base.cooling["air_cooling_mounting"] == "rack"
    assert swapped.cooling["air_cooling_mounting"] == "room"
    assert swapped.cooling["air_cooling_qty"] != base.cooling["air_cooling_qty"]
    assert swapped.selections["air_cooling"] == room.id
    # 랙 장착형은 footprint 0 → 실 장착형으로 바꾸면 기계실 장비면적이 늘어난다
    assert (swapped.space["mechanical_equipment_m2"]
            > base.space["mechanical_equipment_m2"])


def test_air_cooling_quantity_uses_redundancy_rule_when_room_mounted():
    """실 장착형은 CDU 와 같은 이중화 규칙을 탄다."""
    blocks = load_blocks()
    room = next(b for b in list_candidates("cooling", "air_cooling", blocks)
                if b.interface.mounting == "room")
    rule = load_rule("redundancy.yaml")["N+1"]
    r = size(_spec(), selections={"air_cooling": room.id})
    assert r.cooling["air_cooling_qty"] == calc.redundant_qty(
        r.cooling["air_kw"], r.cooling["air_cooling_unit_kw"], rule)
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_selection.py -k "air_cooling" -v`
Expected: FAIL — `mountings == {"rack"}` (아직 room 후보가 없다), 나머지 둘은
`StopIteration`.

- [ ] **Step 4: 후보를 카탈로그에 넣는다**

`data/cooling.yaml` 의 "교체용 후보" 절 **끝에** 붙인다. `default: true` 는 붙이지
않는다(역할당 하나뿐이고 `rdhx_60kw` 가 갖고 있다).

형식 예시 — 실제 값은 Step 1 조사 결과로 채운다.

```yaml
- id: crah_<vendor>_<model>
  type: cooling
  subtype: air_cooling
  vendor: <조사한 벤더>
  model: <조사한 모델>
  interface:
    capacity_kw: <데이터시트 확인값>
    medium: chilled_water
    method: crah
    mounting: room
    footprint_m2: <값>          # 미확인이면 이 주석을 남길 것
  as_of_date: "2026-08"
  confidence: vendor            # 확인 못 한 값이 있으면 projected
  source_url: "<데이터시트 URL>"
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_selection.py -k "air_cooling" -v`
Expected: PASS (3개)

- [ ] **Step 6: 카탈로그가 검증을 통과하는지 눈으로 본다**

Run: `python -X utf8 -m dc_design_tool.cli catalog --type cooling`
Expected: 새 후보들이 `air_cooling` 역할로 보이고 예외가 없다.

- [ ] **Step 7: 전량 회귀**

Run: `python -X utf8 -m pytest -q`
Expected: 349 passed

- [ ] **Step 8: 커밋**

```bash
git add dc_design_tool/data/cooling.yaml tests/test_selection.py
git commit -m "공냉 교체 후보 추가 — RDHx 계열 + CRAH 계열"
```

---

## Task 5: 공냉 규격검증 판정

설치 용량이 필요량 이상인지는 `redundant_qty` 가 이미 보장하므로 그것만 다시 보는
검사는 두지 않는다. 장착 방식마다 **다른 위험**을 본다.

**Files:**
- Modify: `dc_design_tool/engine/compliance.py` (`check` 74-85행, `_check_redundancy_effectiveness` 254-285행, 새 함수)
- Test: `tests/test_compliance.py`

**Interfaces:**
- Consumes: Task 3 의 `result.cooling["air_cooling_mounting"|"air_cooling_qty"|"air_cooling_unit_kw"|"rack_air_kw"|"air_kw"]`.
- Produces: Finding 코드 `REDUNDANCY_EFFECTIVE_AIR_COOLING`(room 장착형만), `AIR_COOLING_RACK_CAPACITY`(rack 장착형만). Task 6 의 표시 코드는 이 코드들을 특별 취급하지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_compliance.py` 끝에 붙인다. 파일 상단 import 에 없으면
`from dc_design_tool.engine.catalog import list_candidates, load_blocks` 를 더한다.

```python
# ---------- 공냉 판정 ----------

def _codes(result) -> set[str]:
    return {f.code for f in result.compliance.findings}


def _finding(result, code):
    return next(f for f in result.compliance.findings if f.code == code)


def test_rack_mounted_air_cooling_gets_capacity_finding_not_redundancy():
    """랙 장착형은 이중화 실효성 대상이 아니다 — 랙당 용량만 본다."""
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    codes = _codes(r)
    assert "AIR_COOLING_RACK_CAPACITY" in codes
    assert "REDUNDANCY_EFFECTIVE_AIR_COOLING" not in codes


def test_rack_air_load_within_unit_capacity_passes():
    """GB200 은 랙당 18kW 로 60kW 도어에 들어간다."""
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    assert _finding(r, "AIR_COOLING_RACK_CAPACITY").severity == "info"


def test_rack_air_load_exceeding_unit_capacity_is_violation():
    """단위용량 미달이면 대수로 보완할 수 없으므로 위반이다."""
    blocks = load_blocks()
    shrunk = dict(blocks)
    door = blocks["rdhx_60kw"]
    shrunk["rdhx_60kw"] = door.model_copy(update={
        "interface": door.interface.model_copy(update={"capacity_kw": 5.0})})
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0),
             blocks=shrunk)
    f = _finding(r, "AIR_COOLING_RACK_CAPACITY")
    assert f.severity == "violation"
    assert f.domain == "기계"


def test_room_mounted_air_cooling_gets_redundancy_finding():
    """실 장착형은 UPS·CDU 와 나란히 단일고장 후 잔여용량 검사를 받는다."""
    blocks = load_blocks()
    room = next(b for b in list_candidates("cooling", "air_cooling", blocks)
                if b.interface.mounting == "room")
    r = size(Spec(project="ac", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0),
             selections={"air_cooling": room.id})
    codes = _codes(r)
    assert "REDUNDANCY_EFFECTIVE_AIR_COOLING" in codes
    assert "AIR_COOLING_RACK_CAPACITY" not in codes
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_compliance.py -k "air_cooling or rack_air" -v`
Expected: FAIL — `AIR_COOLING_RACK_CAPACITY` 가 findings 에 없다.

- [ ] **Step 3: room 장착형을 이중화 실효성 검사에 편입한다**

`dc_design_tool/engine/compliance.py` 의 `_check_redundancy_effectiveness` 에서
`cases` 리스트 정의 직후에 넣는다(265-270행 다음).

```python
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
```

- [ ] **Step 4: 랙 장착형 용량 판정을 새로 만든다**

같은 파일에서 `_check_pdu_capacity` 바로 위에 함수를 넣는다.

```python
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
```

- [ ] **Step 5: `check()` 에 등록한다**

같은 파일 `check()` 의 81행(`f += _check_pdu_capacity(result)`) 바로 위에 넣는다.

```python
    f += _check_air_cooling_rack_capacity(result)
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_compliance.py -v`
Expected: PASS (기존 + 신규 4개)

- [ ] **Step 7: 전량 회귀**

Run: `python -X utf8 -m pytest -q`
Expected: 353 passed

기존 규격검증 테스트 중 findings 개수를 세는 것이 있으면 새 판정 1건만큼 어긋난다.
그럴 때는 개수 단언을 코드 집합 단언으로 바꾼다(개수는 판정이 늘 때마다 깨진다).

- [ ] **Step 8: 커밋**

```bash
git add dc_design_tool/engine/compliance.py tests/test_compliance.py
git commit -m "공냉 규격검증 — 랙 장착형 용량 판정 + 실 장착형 이중화 실효성"
```

---

## Task 6: 공냉 표시 — 화면·계통도·설계기준서·CLI

계산은 이미 끝났다. 이 태스크는 **표시만** 바꾼다. 새 수치를 만들지 않는다.

**Files:**
- Modify: `app.py` (`COOLING_LABELS` 35-43행, `EQUIPMENT_GROUPS` 87-93행, caption 235-236행)
- Modify: `dc_design_tool/reports/diagram_mermaid.py` (`cooling_loop`, 51행)
- Modify: `dc_design_tool/reports/design_basis_docx.py` (냉각 `_kv_table`, 127-134행)
- Modify: `dc_design_tool/cli.py` (`build` 냉각 요약, 117-118행)
- Test: `tests/test_diagram.py`, `tests/test_app_equipment.py`

**Interfaces:**
- Consumes: Task 3 의 결과 키 `air_cooling_qty`/`air_cooling_unit_kw`/`air_cooling_method`/`rack_air_kw`, `result.candidates["air_cooling"]`.
- Produces: 없음(최종 표시 계층).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_diagram.py` 끝에:

```python
def test_cooling_loop_shows_selected_air_equipment():
    """공냉 노드가 하드코딩 문구가 아니라 실제 선택 장비를 보여준다."""
    from dc_design_tool.engine.models import Spec
    from dc_design_tool.engine.sizing import size
    from dc_design_tool.reports.diagram_mermaid import cooling_loop
    result = size(Spec(project="d", rack_id="nvidia_gb200_nvl72", it_power_mw=5.0))
    src = cooling_loop(result)
    assert "(CRAH/RDHx)" not in src          # 하드코딩 제거 확인
    assert str(result.cooling["air_cooling_qty"]) in src
    assert result.cooling["air_cooling_method"] in src
```

`tests/test_app_equipment.py` 끝에. 이 파일의 헬퍼는 `_after_design_run()`,
`_picker(at, label)`, `_cell(at, table_index, item)` 이고 `COOLING_TABLE = 0` 이다.

```python
def test_air_cooling_dropdown_is_present():
    """공냉장비도 화면에서 교체할 수 있어야 한다."""
    at = _after_design_run()
    assert _picker(at, "공냉장비") is not None


def test_cooling_table_shows_air_cooling_quantity():
    """냉각 표에 공냉장비 수량이 보인다(값은 엔진이 만든 것을 그대로)."""
    at = _after_design_run()
    assert _cell(at, COOLING_TABLE, "공냉장비 수량")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_diagram.py -k air tests/test_app_equipment.py -k air -v`
Expected: FAIL — `"(CRAH/RDHx)" not in src` 가 거짓, 드롭다운 라벨 없음.

- [ ] **Step 3: 계통도에서 하드코딩 문구를 없앤다**

`dc_design_tool/reports/diagram_mermaid.py` 의 `cooling_loop` 51행을 교체한다.

```python
        _node("AIR", f"공냉 잔열 {c['air_kw']}kW / "
                     f"{c['air_cooling_method']} {c['air_cooling_qty']}대"),
```

- [ ] **Step 4: 설계기준서에 공냉 구성을 넣는다**

`dc_design_tool/reports/design_basis_docx.py` 의 냉각 `_kv_table` 에서 `("공냉 열량", ...)`
바로 아래에 한 줄을 더한다.

```python
        ("공냉 열량", f"{c['air_kw']} kW"),
        ("공냉 구성", f"{c['air_cooling_qty']} 대 x {c['air_cooling_unit_kw']} kW "
                      f"({c['air_cooling_method']})"),
```

- [ ] **Step 5: CLI 요약에 공냉 수량을 더한다**

`dc_design_tool/cli.py` 의 `build` 117-118행을 교체한다.

```python
    typer.echo(f"CDU {c['cdu_qty']}대 / 칠러 {c['chiller_qty']}대 "
               f"/ 공냉 {c['air_cooling_qty']}대({c['air_cooling_method']}) "
               f"/ {c['total_rt']}RT / 유량 {c['coolant_flow_lpm']}L/min")
```

- [ ] **Step 6: 화면에 라벨과 드롭다운을 붙인다**

`app.py` 세 곳.

`COOLING_LABELS` 에 `"chiller_unit_kw"` 다음 줄로 넣는다.

```python
    "air_cooling_qty": "공냉장비 수량",
    "air_cooling_unit_kw": "공냉장비 단위용량 (kW)",
    "air_cooling_method": "공냉 방식", "air_cooling_mounting": "공냉 장착",
    "rack_air_kw": "랙당 공냉 잔열 (kW)",
```

`EQUIPMENT_GROUPS` 의 기계 행:

```python
    ("기계", [("cdu", "CDU"), ("chiller", "칠러"), ("air_cooling", "공냉장비")]),
```

장비 교체 expander 의 caption(235-236행) — Task 1 에서 기본값 판정 근거가 바뀌었다.

```python
        st.caption("바꾸면 수량·용량·면적·규격검증이 엔진에서 다시 계산된다. "
                   "`기본`은 카탈로그에 기본으로 지정된 블록이다.")
```

- [ ] **Step 7: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_diagram.py tests/test_app_equipment.py -v`
Expected: PASS

- [ ] **Step 8: 산출물을 실제로 만들어 본다**

Run: `python -X utf8 -m dc_design_tool.cli build --spec examples/spec_gb200_5mw_tier3.yaml --out out/`
Expected: 종료코드 0, 요약 줄에 `공냉 42대(rear_door_hx)` 가 보이고 BOM 엑셀에
`공냉장비` 행이 있다.

- [ ] **Step 9: 전량 회귀**

Run: `python -X utf8 -m pytest -q`
Expected: 355 passed

- [ ] **Step 10: 커밋**

```bash
git add app.py dc_design_tool/reports/diagram_mermaid.py \
        dc_design_tool/reports/design_basis_docx.py dc_design_tool/cli.py \
        tests/test_diagram.py tests/test_app_equipment.py
git commit -m "공냉 장비를 화면·계통도·설계기준서·CLI 에 표시"
```

---

## Task 7: 사이드바 기본 랙을 대표 모델(GB200)로

지금 기본 랙은 정렬상 첫 항목인 `aws_trainium3_ultraserver_rack` 이라 첫 화면 수치가
의외로 보인다.

**Files:**
- Modify: `app.py` (`_catalog()` 124-137행, 랙 selectbox 163-164행)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `_catalog()["default_rack"]` — 첫 화면 기본 랙 id.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_app.py` 끝에 붙인다.

```python
def test_sidebar_default_rack_is_representative_model():
    """첫 화면 기본 랙은 정렬 첫 항목이 아니라 대표 모델(GB200)이다."""
    at = _fresh()
    rack = next(s for s in at.sidebar.selectbox if s.label == "랙 모델")
    assert rack.value == "nvidia_gb200_nvl72"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_app.py -k default_rack -v`
Expected: FAIL — `assert 'aws_trainium3_ultraserver_rack' == 'nvidia_gb200_nvl72'`

- [ ] **Step 3: 기본 랙을 카탈로그 조회에 싣는다**

`app.py` 의 `EQUIPMENT_KEY` 정의 아래에 상수를 둔다.

```python
# 첫 화면 기본 랙(대표 모델). 카탈로그에 없으면 목록 첫 항목으로 폴백한다.
DEFAULT_RACK = "nvidia_gb200_nvl72"
```

`_catalog()` 의 반환 dict 에 한 줄을 더한다.

```python
    racks = {bid: b for bid, b in blocks.items() if b.type == "rack"}
    options = sorted(racks)
    return {
        "rack_options": options,
        "default_rack": DEFAULT_RACK if DEFAULT_RACK in racks else options[0],
        "rack_labels": {bid: f"{b.vendor} {b.model} · {b.interface.power_kw_typical}kW "
                             f"[{b.confidence}]" for bid, b in racks.items()},
        "tiers": list(load_rule("tiers.yaml")["tiers"]),
        "redundancy": list(load_rule("redundancy.yaml")),
        "regions": available_regions(),
        "region_names": {c: load_region(c).get("name", c) for c in available_regions()},
    }
```

- [ ] **Step 4: selectbox 가 그 값을 쓰게 한다**

`app.py` 163-164행을 교체한다.

```python
rack_id = st.sidebar.selectbox("랙 모델", cat["rack_options"],
                               index=cat["rack_options"].index(cat["default_rack"]),
                               format_func=lambda b: cat["rack_labels"][b])
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_app.py -v`
Expected: PASS (기존 12개 + 신규 1개)

- [ ] **Step 6: 전량 회귀**

Run: `python -X utf8 -m pytest -q`
Expected: 356 passed

- [ ] **Step 7: 커밋**

```bash
git add app.py tests/test_app.py
git commit -m "사이드바 기본 랙을 대표 모델(GB200)로"
```

---

## Task 8: Windows 콘솔 인코딩 방어

Windows 기본 콘솔(cp949)에서 CLI 출력이 `UnicodeEncodeError` 로 죽는다. 확인된 원인
문자는 두 개다 — em-dash `—`(U+2014, `cli.py`·`catalog.py`·`rules/ashrae.yaml`·
`rules/regions/KR.yaml` 등)와 `≈`(U+2248, `data/cooling.yaml`). 한글 자체는 cp949 로
정상 인코딩된다.

**Files:**
- Modify: `dc_design_tool/cli.py` (import 구역, `app` 정의 아래)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `cli._harden_console() -> None` — `sys.stdout`/`sys.stderr` 의 인코딩 오류 처리를 `replace` 로 바꾼다. typer 콜백이 매 실행마다 부른다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_cli.py` 끝에 붙인다. 파일 상단 import 에 `import io`, `import sys` 를 더한다.

```python
# ---------- 콘솔 인코딩 ----------

def test_harden_console_survives_cp949_unencodable_chars(tmp_path, monkeypatch):
    """cp949 콘솔에서 em-dash·≈ 가 섞여도 죽지 않는다(한글은 그대로 나온다)."""
    from dc_design_tool.cli import _harden_console

    path = tmp_path / "console.txt"
    stream = io.TextIOWrapper(path.open("wb"), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", stream)

    _harden_console()
    print("규격검증 — 위반 0건 / 1000RT ≈ 3517kW")   # 예외가 나면 실패다
    stream.flush()

    written = path.read_text(encoding="cp949")
    assert "규격검증" in written and "위반 0건" in written


def test_harden_console_tolerates_stream_without_reconfigure(monkeypatch):
    """reconfigure 가 없는 스트림(파이프·캡처)에서도 조용히 넘어간다."""
    from dc_design_tool.cli import _harden_console

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    _harden_console()      # 예외 없이 끝나야 한다
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -X utf8 -m pytest tests/test_cli.py -k harden_console -v`
Expected: FAIL — `ImportError: cannot import name '_harden_console'`

- [ ] **Step 3: 방어 함수를 만들고 콜백으로 건다**

`dc_design_tool/cli.py`. import 구역에 `import sys` 를 더하고(`import pathlib` 아래),
`SEVERITY_LABEL` 정의 아래에 넣는다.

```python
def _harden_console() -> None:
    """콘솔이 인코딩하지 못하는 문자로 CLI 가 죽지 않게 한다.

    Windows 기본 콘솔(cp949)은 em-dash(—)·≈ 를 인코딩하지 못해
    UnicodeEncodeError 를 낸다. 한글은 cp949 로 정상 인코딩되므로 **콘솔 인코딩은
    그대로 두고 오류 처리만 'replace' 로 바꾼다** — UTF-8 로 강제 전환하면 cp949
    콘솔에서 한글 전체가 깨지기 때문이다. 인코딩 불가 문자만 '?' 로 떨어진다.

    reconfigure 를 지원하지 않는 스트림(파이프·테스트 캡처)에서는 아무것도 하지 않는다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


@app.callback()
def _main() -> None:
    """모든 하위 명령 앞에 돈다."""
    _harden_console()
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -X utf8 -m pytest tests/test_cli.py -v`
Expected: PASS (기존 + 신규 2개)

`@app.callback()` 을 더하면 typer 가 하위 명령을 필수로 요구한다. 인자 없이
`dc-design` 을 부르면 도움말이 나오고 종료코드가 0 이 아닐 수 있다 — 기존 테스트가
이를 검사하고 있으면 그 단언을 도움말 출력 확인으로 바꾼다.

- [ ] **Step 5: 실제 cp949 콘솔에서 확인한다**

Run (PowerShell, `-X utf8` **없이**):
`python -m dc_design_tool.cli check --spec examples/spec_gb200_5mw_tier3.yaml --verbose`
Expected: `UnicodeEncodeError` 없이 끝난다. 한글은 정상, em-dash 자리에 `?`.

- [ ] **Step 6: 전량 회귀**

Run: `python -X utf8 -m pytest -q`
Expected: 358 passed

- [ ] **Step 7: 커밋**

```bash
git add dc_design_tool/cli.py tests/test_cli.py
git commit -m "Windows 콘솔 인코딩 방어 — cp949 에서 CLI 가 죽지 않게"
```

---

## Task 9: 문서 갱신

**Files:**
- Modify: `CLAUDE.md` (「장비 교체」 절 — Task 1 에서 이미 고쳤으므로 여기서는 역할 목록만)
- Modify: `status.md`

**Interfaces:**
- Consumes: Task 1~8 의 결과.
- Produces: 없음.

- [ ] **Step 1: `CLAUDE.md` 의 엔진 API 표를 확인한다**

`engine.sizing.size(Spec, blocks=None, selections=None)` 행은 시그니처가 안 바뀌었으니
그대로 둔다. 「장비 교체」 절 마지막 문단에 공냉 역할을 한 줄 덧붙인다.

```
공냉 잔열 처리 장비는 `air_cooling` 역할 하나로 묶여 있고, 랙 후면 장착(RDHx)과 실
단위 설치(CRAH)를 같은 드롭다운에서 바꾼다. 수량 산정식은 `interface.mounting`
(`rack` = 랙당 1대 · 이중화 없음, `room` = 용량 + 이중화 규칙)으로 갈린다.
```

- [ ] **Step 2: `status.md` 를 갱신한다**

- "최종 갱신" 날짜를 `2026-08-07` 로.
- 테스트 표에 행 추가: `| 공냉 역할 | test_cooling.py / test_selection.py / test_compliance.py | 2026-08-07 추가 |`
- "최근 작업" 에 이번 세션 절을 추가(공냉 역할 신설, default 플래그, 기본 랙, CLI 인코딩).
- "알려진 제약 · 남은 일" 에서 **해결된 항목을 지운다**:
  - `rdhx_60kw` 가 쓰이지 않는다 → 삭제
  - 사이드바 기본 랙이 Trainium3 → 삭제
  - cp949 `UnicodeEncodeError` → 삭제
  - "YAML 순서가 기본 설계를 결정한다" → `default` 플래그로 대체됐다는 서술로 교체
- "다음 후보" 를 남은 것으로 줄인다: Streamlit Cloud 배포(브라우저), `capex_usd` 확보.

- [ ] **Step 3: 최종 회귀와 산출물 확인**

```bash
python -X utf8 -m pytest -q
python -X utf8 -m dc_design_tool.cli build --spec examples/spec_gb200_5mw_tier3.yaml --out out/
python -X utf8 -m dc_design_tool.cli check --spec examples/spec_gb200_5mw_tier3.yaml --verbose
```
Expected: 358 passed / build 종료코드 0 / check 가 `AIR_COOLING_RACK_CAPACITY` 판정을
info 로 보여준다.

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md status.md
git commit -m "status.md·CLAUDE.md 갱신 — 공냉 역할과 default 플래그 반영"
```

---

## 완료 기준

- `python -X utf8 -m pytest -q` 전량 통과(기존 333 + 신규 25 = 358 전후).
- `dc-design build` 산출물 BOM 에 `공냉장비` 행이 있다.
- 화면 `장비 교체` 에 `공냉장비` 드롭다운이 있고, CRAH 로 바꾸면 수량·기계실 면적·
  규격검증이 함께 바뀐다.
- `data/*.yaml` 의 줄 순서를 바꿔도 설계 결과가 바뀌지 않는다.
- Windows 기본 콘솔에서 CLI 가 예외 없이 끝난다.

## 주의

- **테스트 개수는 참고값이다.** 위 Expected 숫자는 이 계획대로 테스트를 추가했을 때의
  값이다. 어긋나도 통과 여부가 기준이지 숫자가 기준이 아니다.
- **Task 4 에서 벤더 데이터를 못 찾으면 후보를 지어내지 말 것.** `mounting: room`
  후보를 하나도 확보하지 못하면 Task 4·5 의 room 관련 테스트를 작성할 수 없다.
  그때는 진행을 멈추고 사용자에게 보고한다 — 조용히 generic 블록으로 대체하지 않는다.
- **골든 테스트가 깨지면 멈춘다.** 기본 블록(`rdhx_60kw`, footprint 0)을 유지하는 한
  IT 부하·PUE·면적은 바뀌지 않아야 한다. 깨졌다면 어딘가에서 기본 선택이 바뀐 것이다.
