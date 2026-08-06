# 작업 현황

최종 갱신: 2026-08-06

## 한 줄 요약
엔진·카탈로그·산출물은 동작하며 테스트 333개가 통과한다. Streamlit 웹 UI에 사번
로그인을 붙였고, GitHub(`jamdu-pe/dc-design-tool`, private)에 올렸다.
**Streamlit Cloud 앱 생성은 아직 남았다.**

## 테스트
```
pytest -q   → 333 passed
```
| 영역 | 파일 | 비고 |
|---|---|---|
| 골든 회귀 | `test_golden_gb200.py` | GB200 NVL72 앵커값 |
| 엔진 | `test_it_load / cooling / power / space / network / compose / scenario` | |
| 규격검증 | `test_compliance*.py`, `test_region.py` | |
| 장비 교체 | `test_selection.py` (22) | 2026-08-06 추가 |
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
- `dc_design_tool/ui_auth.py` — 사번+비밀번호 로그인. 자격증명은 `st.secrets`에서만
  읽고, **설정이 없으면 화면을 열지 않는다(fail closed)**.
- `scripts/hash_password.py` — bcrypt 해시 생성(입력 가림, 히스토리에 안 남음).
- README에 로그인 설정 + 배포 절차 5단계.
- 설치 없이 저장소 루트에서 `import dc_design_tool`이 잡히는지 검증 완료
  (Cloud가 `requirements.txt`만으로 동작하는 전제).

## 배포 상태

원격: `https://github.com/jamdu-pe/dc-design-tool.git` (private)

| 단계 | 상태 |
|---|---|
| git 저장소 초기화 | 완료 (`main`) |
| 최초 커밋 | 완료 (`49b9dbd`, 90파일) |
| GitHub 저장소 생성·push | 완료 (2026-08-06) |
| share.streamlit.io 앱 생성 | **미완** — 브라우저 작업 |
| Secrets 설정 | **미완** — 실제 사번·비밀번호 필요 |
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
- **YAML 순서가 기본 설계를 결정한다.** `selections` 미지정 시 해당 subtype의 첫 블록을
  쓴다. `data/*.yaml`에서 기존 블록 **앞에** 새 블록을 끼워 넣으면 모든 결과가 조용히
  바뀐다. 세 파일 상단에 경고 주석이 있으나 코드가 막지는 않는다.
- `capex_usd`를 가진 블록이 0개라 `scenario`의 CAPEX 비교가 항상 "비용 미상"이다.
  공개 데이터시트에 단가가 없어 견적 등 별도 경로로만 채울 수 있다.
- `rdhx_60kw`(rear_door_hx)는 카탈로그에만 있고 어떤 엔진도 소비하지 않는다.
- **사이드바 기본 랙은 목록 정렬상 첫 항목(`aws_trainium3_ultraserver_rack`)이다.**
  대표 모델(GB200)이 아니므로 첫 화면 수치가 의외로 보일 수 있다.
- Windows 기본 콘솔(cp949)에서 CLI 출력이 `UnicodeEncodeError`로 깨진다
  (규격검증 메시지의 em-dash). `python -X utf8` 로는 정상. 기존 이슈.

### 다음 후보
1. Streamlit Cloud 앱 생성 → Secrets → 뷰어 초대 (브라우저 작업)
2. `rdhx_60kw` 를 냉각 엔진에 연결하거나 카탈로그에서 제거
3. 사이드바 기본 랙을 대표 모델(GB200)로 지정
