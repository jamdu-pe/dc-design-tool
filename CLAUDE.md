# CLAUDE.md — 데이터센터 M&E 설계 TOOL 운영 규칙

## 프로젝트
AI 가속기(GPU/TPU/Trainium) 랙 기반 데이터센터 M&E 개념설계 자동화 도구.
부품은 `dc_design_tool/data/*.yaml` "레고 블록", 계산은 `dc_design_tool/engine/*` 결정론적
파이썬, 규격은 `dc_design_tool/rules/*.yaml`, 산출은 `dc_design_tool/reports/*`.

## 절대 규칙
1. 모든 수치는 `engine.*` 함수 호출로 얻는다. LLM이 직접 계산/암산하지 않는다.
2. 카탈로그(사양)는 `data/*.yaml`에만 둔다. 각 항목 `as_of_date`, `confidence`, `source_url` 필수.
3. 카탈로그에 없는 장비를 지어내지 않는다 → "카탈로그 부재"로 표기하고 블록 추가를 제안.
   확인은 `dc-design catalog --type <chip|rack|cooling|electrical|network>`.
4. `confidence: projected`(미출시 추정) 값은 결과에 불확실성 범위와 함께 표기.
5. 산출물에는 "개념설계/타당성 수준, 실시설계·인허가는 면허기술자 검토 필요" 고지문 삽입.
6. 설계 계수는 코드가 아니라 `rules/*.yaml`에서 바꾼다(하드코딩 금지).
7. 커밋은 Phase 단위, `pytest` 통과 후에만.

## 오케스트레이션 절차 (대화형)

```
사용자 요구
  └─ intake      : 자연어 → spec.yaml 정규화(랙 id는 카탈로그에서만)
       └─ sizing : engine.sizing.size(spec) 1회 호출 → SizingResult
            ├─ mechanical : 냉각(액냉/공냉 분배·유량·CDU/칠러·PUE) 해설
            ├─ electrical : UPS/배터리/발전기/변압기/버스웨이·PDU·고조파 해설   (병렬)
            └─ ict        : 스케일아웃 포트→leaf/spine→트랜시버·케이블 해설
                 └─ compliance : engine.compliance.check 결과로 위반·가정 리포트
                      └─ reporter : xlsx/docx/mermaid 산출 + 경영진 요약
```

각 서브에이전트는 `engine`/`reports` 함수를 툴처럼 호출하고 **결과를 해설만** 한다.
에이전트 정의 원본은 `dc_design_tool/agents/*.md`, 설치본은 `.claude/agents/*.md`이며
`dc-design install-agents`로 동기화한다(`tests/test_agents.py`가 불일치를 잡는다).

## 엔진 API (에이전트가 호출할 지점)

| 목적 | 호출 |
|---|---|
| 전체 사이징 + 규격검증 | `engine.sizing.size(Spec, blocks=None, selections=None)` → `SizingResult` |
| 역할별 장비 후보 조회 | `engine.catalog.list_candidates(type, subtype)` → `list[Block]` |
| 역할에 쓸 블록 결정 | `engine.catalog.resolve(type, subtype, blocks, selections)` → `Block` |
| spec+인자 선택 병합·검증 | `engine.sizing.merge_selections(spec, override)` → `dict` |
| 칩→노드→랙 롤업·일관성 | `engine.compose.composed_power_kw / composed_accel_count / check_consistency` |
| IT 부하·랙 수량 | `engine.it_load.size_it_load(spec, blocks)` |
| 냉각 사이징 | `engine.cooling.size_cooling(...)` |
| 냉각 계산식 | `engine.calc.coolant_flow_lpm / rt_from_kw / pue` |
| 전기 상세 | `engine.power.size_electrical(...)` |
| 공간/구조 | `engine.space.size_space(...)` |
| 통신 패브릭 | `engine.network.size_network(...)` |
| 규격검증 | `engine.compliance.check(result, spec)` → `ComplianceReport` |
| 시나리오 비교 | `engine.scenario.run_sweep(base, sweep)` / `rank(rows, metric)` |
| 규격 팩 | `engine.catalog.load_rule(name, region)` / `load_region(code)` / `available_regions()` |
| 사용자 랙 등록 | `engine.catalog.append_user_block(raw)` → `data/user_racks.yaml` |
| 산출물 | `reports.bom_xlsx.write_bom` / `design_basis_docx.write_design_basis` / `diagram_mermaid.write_diagrams` |

## 장비 교체
역할(subtype)마다 카탈로그 후보가 여러 개일 수 있다. 역할별 블록은 두 곳에서 지정한다 —
`spec.yaml`의 `selections:`(설계안에 기록되는 선택, CLI·시나리오 스윕·MCP 공통)와
`size(spec, selections=...)` 인자(화면에서 지금 바꾼 선택). 역할 단위로 인자가 이긴다.
지정하지 않은 역할은 **카탈로그 등재 순서상 첫 후보**를 쓴다.
따라서 `data/*.yaml` 안의 순서가 곧 기본 설계다 — 기존 블록 앞에 새 블록을 끼워 넣지 말 것.
교체 가능한 역할은 `engine.sizing.SELECTABLE_ROLES` 에 정의한다. 장비를 바꿔도 수량·용량은
반드시 `calc.*` 로 재산정한다(절대규칙 1). 결과의 `selections`(쓰인 블록)와
`candidates`(선택 가능한 후보)로 UI 드롭다운을 구성한다.

## 웹 UI
`app.py`(Streamlit)는 **표시 전용**이다. 계산·판정·저장 로직을 화면 코드에 넣지 말고
`engine.*` / `reports.*` 함수를 호출한다. 새 지표를 화면에 띄워야 하면 엔진이 그 값을
내도록 먼저 고친다. 실행: `pip install -e ".[ui]"` 후 `streamlit run app.py`.

## MCP 서버
`dc_design_tool/mcp_server.py`는 엔진을 MCP 툴 7종으로 노출한다(`dc-design-mcp`, stdio).
툴 페이로드 함수는 순수 dict 반환이라 mcp 없이도 테스트된다. 엔진 예외는 `{"error": ...}`로
변환해 돌려준다. 새 툴을 붙일 때도 계산은 엔진에 두고 이 모듈은 검증·직렬화만 한다.

## 빌드/실행
- `pip install -e .` (웹 UI: `".[ui]"`, MCP: `".[mcp]"`)
- `pytest`
- `dc-design build --spec examples/spec_gb200_5mw_tier3.yaml --out out/`
- `dc-design check --spec examples/spec_gb200_5mw_tier3.yaml --verbose` (위반 시 종료코드 1)
- `dc-design compare --spec examples/sweep_chip_generation.yaml --out out/compare --sort pue`
- `dc-design catalog --type rack`
