# 작업 현황

최종 갱신: 2026-08-07

## 한 줄 요약
엔진·카탈로그·산출물은 동작하며 테스트 360개가 통과한다. 공냉 잔열 처리 장비가
`air_cooling` 역할로 BOM·규격검증에 들어왔고, 기본 장비 선택은 YAML 순서가 아니라
`default` 플래그가 정한다. Streamlit 웹 UI에 실명 로그인을 붙였고,
GitHub(`jamdu-pe/dc-design-tool`, private)에 올렸다.
**Streamlit Cloud 앱 생성은 아직 남았다.**

## 테스트
```
pytest -q   → 360 passed
```
| 영역 | 파일 | 비고 |
|---|---|---|
| 골든 회귀 | `test_golden_gb200.py` | GB200 NVL72 앵커값 |
| 엔진 | `test_it_load / cooling / power / space / network / compose / scenario` | |
| 규격검증 | `test_compliance*.py`, `test_region.py` | |
| 장비 교체 | `test_selection.py` (31) | 2026-08-06 신설, 2026-08-07 공냉 후보 검증 추가 |
| 공냉 역할 | `test_cooling.py` / `test_selection.py` / `test_compliance.py` | 2026-08-07 추가 |
| 산출물·CLI·MCP | `test_reports / diagram / cli / compare_cli / mcp_server` | |
| 웹 UI | `test_app.py` (12) | 로그인을 거쳐 검증 |
| 로그인 게이트 | `test_auth.py` (11) | 2026-08-06 추가 |
| 해시 생성기 | `test_hash_password.py` (6) | 2026-08-06 추가 |
| 설계 계수 출처 | `test_rule_factors.py` (11) | 2026-08-06 추가 |
| 화면 장비 교체 | `test_app_equipment.py` (11) | 2026-08-06 추가 |
| spec/CLI/스윕 장비 교체 | `test_spec_selections.py` (13) | 2026-08-06 추가 |

## 최근 작업 (2026-08-06)

### 1. 카탈로그 확장 — 22 → 37블록
역할(subtype)별 교체 후보를 실제 벤더 데이터시트 기준으로 추가했다.

| 역할 | 후보 |
|---|---|
| CDU | Generic 1300 · CoolIT CHx1000 · Vertiv XDU 1350 · CoolIT CHx750 |
| 칠러 | Generic 1000RT · Carrier 19DV 1150RT · Carrier 19DV 500RT |
| UPS | Generic 1250 · Vertiv EXL S1 800kVA · Schneider Galaxy VX 500kVA |
| 발전기 | Generic 2500 · Cat 3516C 2000kW · Cat C175-16 3000kW |
| 변압기 | Generic 2500 · LS Electric 몰드 1500kVA |
| 배터리 | Generic 200kWh · Vertiv HPL P1 51.2kWh |
| leaf/spine | Generic 64x800G · NVIDIA SN5600 · Arista 7060X6 128x400G |

용량·정격은 데이터시트 확인값, 확인 못 한 항목은 `confidence: projected`.
`footprint_m2`는 전부 미확인(동급 통상값) — YAML에 `# 미확인` 주석으로 표시.

### 2. 장비 교체 엔진 리팩터
- `catalog.list_candidates(type, subtype)` / `catalog.resolve(...)` 추가.
- `cooling.py`·`power.py`·`network.py`에 흩어져 있던 `_first()` 3벌 삭제.
- `size(spec, blocks, selections)` — 역할별 block_id 지정. 미지정은 첫 후보.
- `SizingResult.selections` / `.candidates` 추가(UI 드롭다운용).
- 교체해도 수량·용량은 기존 `calc.*` 로 재산정한다(절대규칙 1 유지).

### 3. 설계 계수를 rules/*.yaml 로 이관 (절대규칙 6)
코드에 박혀 있던 계수를 전부 규칙 파일로 옮겼다. **수치 변화 없음**(골든테스트 통과).

| 이전 위치 | 현재 |
|---|---|
| `sizing.COOLING_POWER_RATIO = 0.35` | `rules/cooling.yaml` `cooling_power_ratio` (신규 파일) |
| `power.py` `pf = 0.95` | `electrical.yaml` `distribution.power_factor` |
| `power.py` `it_kw * 0.10` | `electrical.yaml` `demand.house_load_ratio` |
| `power.py` `it_kw * 0.08` | `electrical.yaml` `demand.distribution_loss_ratio` |
| `calc.generator_kw` 기본인자 `0.15` | `electrical.yaml` `generator.start_margin` |

지역 규격 팩(`rules/regions/*.yaml`)의 `overrides` 로도 교체할 수 있다.
`electrical` 결과에 `power_factor`·`house_load_ratio`·`distribution_loss_ratio` 를
실어 어떤 계수가 쓰였는지 결과만 봐도 알 수 있게 했다.

### 4. 화면에서 장비 교체 (app.py)
결과 상단 `장비 교체` 확장 패널에 역할 11종 드롭다운을 붙였다. 후보 목록·기본값
판정은 `result.candidates` 를 그대로 쓰고, 고른 값은 `size(spec, selections=...)`
로 엔진에 넘긴다. **화면은 여전히 계산하지 않는다.**

- 흐름을 바꿨다: 버튼 클릭 시 결과가 아니라 **조건(spec)** 을 저장하고, 결과는 매
  실행마다 현재 선택으로 다시 만든다. 드롭다운을 바꾸면 표·BOM·규격검증이 함께 갱신된다.
- `기본 장비로 되돌리기` 버튼(on_click 콜백으로 위젯 키 삭제).
- 산출물 임시 폴더를 세션당 하나로 재사용한다(재실행마다 새로 만들면 조작 횟수만큼 쌓인다).

### 5. selections 를 Spec 필드로 승격
장비 교체가 화면에서만 되던 것을 `spec.yaml`·CLI·시나리오 스윕·MCP 로 넓혔다.

```yaml
# spec.yaml
selections:
  ups: ups_schneider_galaxy_vx_500kva
  cdu: cdu_coolit_chx1000
```
```yaml
# 스윕 파일 — 장비도 비교 축이 된다
sweep:
  selections:
    - {ups: ups_1250kva}
    - {ups: ups_vertiv_exl_s1_800kva}
```

- `sizing.merge_selections(spec, override)` — spec 위에 인자를 얹는다(역할 단위로
  인자 우선). 교체 불가 역할 키(오타)는 가능한 목록과 함께 ValueError.
- `dc-design build` 가 기본값과 다른 선택을 한 줄로 밝힌다(기본값뿐이면 침묵).
- 비교표 시나리오명은 dict 를 그대로 찍지 않고 `ups=<block_id>` 로 줄인다.
- MCP `size_design` 응답에 `selections`·`candidates` 를 실어, 호출한 에이전트가
  후보 밖의 장비를 지어내지 않도록 했다.

### 6. Streamlit Cloud 배포 준비
- `requirements.txt`(루트), `.streamlit/secrets.toml.example`, `.gitignore` 갱신.
- `dc_design_tool/ui_auth.py` — 실명+비밀번호 로그인. 자격증명은 `st.secrets`에서만
  읽고, **설정이 없으면 화면을 열지 않는다(fail closed)**.
- `scripts/hash_password.py` — bcrypt 해시 생성(입력 가림, 히스토리에 안 남음).
- README에 로그인 설정 + 배포 절차 5단계.
- 설치 없이 저장소 루트에서 `import dc_design_tool`이 잡히는지 검증 완료
  (Cloud가 `requirements.txt`만으로 동작하는 전제).

## 최근 작업 (2026-08-07)

### 1. 기본 장비 선택을 `default` 플래그로 — YAML 순서 의존 제거
`Block.default: bool`을 추가했다. `selections`로 지정하지 않은 역할은 이제 YAML의
첫 줄이 아니라 `default: true`가 붙은 후보를 쓴다. 줄 순서는 표시 순서일 뿐이다.
역할마다 플래그는 정확히 하나여야 하며 `tests/test_selection.py`가 강제한다.
`data/*.yaml`의 줄 순서를 바꿔도 설계 결과가 더 이상 바뀌지 않는다.

### 2. 공냉 역할 `air_cooling` 신설
`Interface`에 `mounting`(`rack`|`room`, 기본 `room`)과 `method`(표시용 라벨)를
추가하고, 새 교체 역할 `air_cooling`을 냉각 엔진에 연결했다. IT 발열 중 액냉이
못 받는 잔열(`air_kw`)을 처리할 장비가 이제 BOM에 실제로 잡힌다(`rdhx_60kw`가
카탈로그에만 있고 아무도 안 쓰던 문제 해결). 수량 산정은 `interface.mounting`으로
갈린다 — `rack`(랙 후면 장착, 예: RDHx)은 랙당 1대·이중화 배수 없음(여분 도어를
매달 수 없다), `room`(실 단위 설치, 예: CRAH)은 CDU·칠러와 같은 `calc.redundant_qty`
이중화 규칙을 쓴다. 랙당 공냉 부하(`rack_air_kw`)도 결과에 실린다.

### 3. 공냉 교체 후보 3종 추가
벤더 데이터시트 기준으로 `rdhx_motivair_chilleddoor_m16`(랙, 75kW, `confidence:
vendor`), `crah_vertiv_liebert_crv040`(실, 42.9kW, `confidence: vendor`),
`crah_stulz_cyberair3pro_cw2_1280`(실, 103.9kW, `confidence: projected` — 출처가
스캔 PDF라 재추출할 때마다 수치가 달라 용량·치수를 확정 못 함, 근거는 소스 주석에
명기)를 추가했다. 기본값은 그대로 `rdhx_60kw`.

### 4. 공냉 규격검증 2건 추가
`AIR_COOLING_RACK_CAPACITY`(랙 장착형 전용 — 부족하면 대수를 늘려도 랙당 용량이
그대로라 `violation`)와 `REDUNDANCY_EFFECTIVE_AIR_COOLING`(실 장착형 전용 — 기존
잔여용량 검증에 합류)을 추가했다. 두 판정은 `mounting`에 따라 상호 배타적이다.

### 5. 화면·계통도·설계기준서·CLI에 공냉 노출
Streamlit 화면 `장비 교체` 패널, mermaid 계통도, Word 설계기준서, CLI 요약 모두에
공냉 대수·방식을 띄웠다. 계통도에서 하드코딩돼 있던 `"(CRAH/RDHx)"` 추정 라벨을
지우고 실제 선택된 `air_cooling_method` 값을 쓰도록 고쳤다.

### 6. 사이드바 기본 랙을 대표 모델(GB200)로
정렬상 첫 항목(`aws_trainium3_ultraserver_rack`)이 아니라 대표 모델
`nvidia_gb200_nvl72`를 기본값으로 지정했다(카탈로그에 없으면 목록 첫 항목으로
안전하게 폴백).

### 7. Windows 콘솔 인코딩 방어
cp949 콘솔에서 CLI 출력 중 em-dash·`≈` 등을 만나면 `UnicodeEncodeError`로 죽던
문제를 CLI 진입점의 스트림 오류 처리기만 `errors="replace"`로 완화해 고쳤다.
인코딩 자체는 건드리지 않아 한글은 그대로 나오고, 깨지는 글자만 `?`로 바뀐다.
`-X utf8` 없이도 CLI가 예외 없이 끝난다.

## 배포 상태

원격: `https://github.com/jamdu-pe/dc-design-tool.git` (private)

| 단계 | 상태 |
|---|---|
| git 저장소 초기화 | 완료 (`main`) |
| 최초 커밋 | 완료 (`49b9dbd`, 90파일) |
| GitHub 저장소 생성·push | 완료 (2026-08-06) |
| share.streamlit.io 앱 생성 | **미완** — 브라우저 작업 |
| Secrets 설정 (로컬) | 완료 (2026-08-07) — `.streamlit/secrets.toml`, gitignore |
| Secrets 설정 (Cloud) | **미완** — 앱 Settings → Secrets 에 같은 내용 붙여넣기 |
| 뷰어 초대 (Sharing) | **미완** |

절차는 README의 "Streamlit Community Cloud 배포" 절 참고.

### 인증 관련 주의
- 이 PC의 Windows 자격 증명 관리자에 **다른 사람 계정(`Immersion-Ben`) 토큰이
  저장돼 있었고 제거했다.** git push 전에 어느 계정으로 인증되는지 확인할 것.
- 그 계정에 빈 private 저장소 `Immersion-Ben/dc-design-tool` 이 잘못 생성됐다.
  코드는 전송되지 않았으나(0 KB, 커밋 0건) 계정 소유자의 삭제가 필요하다.

## 알려진 제약 · 남은 일

### 배포 관련
- **Cloud 파일 시스템은 휘발성이다.** `랙 추가`로 등록한 랙(`data/user_racks.yaml`)은
  재시작 시 사라지고, 접속자 전원에게 공유된다(사용자별 격리 없음).
  영구 보관하려면 로컬에서 등록해 커밋해야 한다.
- Cloud 공유 설정(Sharing)과 앱 내부 로그인은 다른 층이다. 둘 다 켜야 한다.

### 코드 관련
- **기본 설계는 `default: true` 플래그가 정한다.** `selections` 미지정 시 해당
  subtype에서 `default: true`가 붙은 블록을 쓴다. `data/*.yaml`의 줄 순서는 표시
  순서일 뿐이며, 새 블록을 기존 블록 앞에 끼워 넣어도 설계 결과는 바뀌지 않는다.
  역할마다 플래그가 정확히 하나인지는 `tests/test_selection.py`가 강제한다.
- `capex_usd`를 가진 블록이 0개라 `scenario`의 CAPEX 비교가 항상 "비용 미상"이다.
  공개 데이터시트에 단가가 없어 견적 등 별도 경로로만 채울 수 있다.

### 다음 후보
1. Streamlit Cloud 앱 생성 → Secrets → 뷰어 초대 (브라우저 작업)
2. `capex_usd` 출처 확보 — 공개 데이터시트에 단가가 없어 견적 등 별도 경로가 필요하다.

## 다음 세션 시작점

코드 쪽은 일단락됐다. 공냉 역할(`air_cooling`) 신설과 `default` 플래그 전환을 마쳤고
`pytest -q` 는 360개 통과한다. 이번 작업분은 `worktree-air-cooling-role` 브랜치에
있으며, main 에 합치는 절차가 아직 남아 있다.

**남은 것은 사실상 배포뿐이며 대부분 브라우저 작업이다** (코드 쪽 잔여 항목은
`capex_usd` 출처 확보 하나뿐 — 아래 "다음 후보" 2번 참고). 배포 절차는 README
"Streamlit Community Cloud 배포" 절에 단계별로 있다. 요약:

1. 터미널에서 값 두 개를 만든다
   - 쿠키 키: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - 사용자별 해시: `python scripts/hash_password.py` (사람마다 1회, 로그인 ID는 실명)
2. <https://share.streamlit.io> → New app → `jamdu-pe/dc-design-tool` / `main` / `app.py`
3. Deploy 전에 Advanced settings → Secrets 에 `[auth.cookie]` + `[auth.credentials…]` 붙여넣기
4. Settings → Sharing → "Only specific people can view this app" → 사내 이메일 초대
5. 확인: 로그인 화면이 먼저 뜨는가 / 틀린 비밀번호가 막히는가 / 로그인 후 `설계 실행`
   과 `장비 교체` 드롭다운이 동작하는가

Secrets 를 빠뜨려도 설계 화면이 공개되지는 않는다(안내만 띄우고 멈춘다).

코드 작업을 다시 잡는다면 위 "다음 후보" 2번(`capex_usd` 출처 확보)이 남은 전부다 —
견적 등 별도 경로를 확보하기 전까지는 계속 "비용 미상"으로 보고하는 게 맞다.
