# 작업 현황

최종 갱신: 2026-08-06

## 한 줄 요약
엔진·카탈로그·산출물은 동작하며 테스트 298개가 통과한다. Streamlit 웹 UI에 사번
로그인을 붙이고 Streamlit Community Cloud 배포 준비를 마쳤다. **실제 배포는 아직
수행되지 않았다**(GitHub 저장소 미생성).

## 테스트
```
pytest -q   → 298 passed
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

### 3. Streamlit Cloud 배포 준비
- `requirements.txt`(루트), `.streamlit/secrets.toml.example`, `.gitignore` 갱신.
- `dc_design_tool/ui_auth.py` — 사번+비밀번호 로그인. 자격증명은 `st.secrets`에서만
  읽고, **설정이 없으면 화면을 열지 않는다(fail closed)**.
- `scripts/hash_password.py` — bcrypt 해시 생성(입력 가림, 히스토리에 안 남음).
- README에 로그인 설정 + 배포 절차 5단계.
- 설치 없이 저장소 루트에서 `import dc_design_tool`이 잡히는지 검증 완료
  (Cloud가 `requirements.txt`만으로 동작하는 전제).

## 배포 상태

| 단계 | 상태 |
|---|---|
| git 저장소 초기화 | 완료 (`main`) |
| 최초 커밋 | 완료 |
| GitHub 저장소 생성·push | **미완** — 계정/조직 미정, `gh` CLI 미설치 |
| share.streamlit.io 앱 생성 | **미완** — 브라우저 로그인 필요 |
| Secrets 설정 | **미완** — 실제 사번·비밀번호 필요 |
| 뷰어 초대 | **미완** |

절차는 README의 "Streamlit Community Cloud 배포" 절 참고.

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
- **하드코딩 설계 계수 4건이 CLAUDE.md 절대규칙 6 위반 상태다.**
  `sizing.py:16` `COOLING_POWER_RATIO=0.35`, `power.py` `pf=0.95`·하우스부하 `0.10`·
  PUE 손실 `0.08`. `rules/*.yaml`로 옮겨야 한다(수치 변화 없음).
- `selections`는 `size()` 인자로만 받는다. `spec.yaml`·CLI·`scenario.run_sweep`에서는
  장비를 바꿀 수 없다(장비 축 스윕 비교 불가). 필요해지면 `Spec` 필드로 승격.
- `capex_usd`를 가진 블록이 0개라 `scenario`의 CAPEX 비교가 항상 "비용 미상"이다.
  공개 데이터시트에 단가가 없어 견적 등 별도 경로로만 채울 수 있다.
- `rdhx_60kw`(rear_door_hx)는 카탈로그에만 있고 어떤 엔진도 소비하지 않는다.
- Windows 기본 콘솔(cp949)에서 CLI 출력이 `UnicodeEncodeError`로 깨진다
  (규격검증 메시지의 em-dash). `python -X utf8` 로는 정상. 기존 이슈.

### 다음 후보
1. 하드코딩 계수 `rules/*.yaml` 이관 (작고 독립적, 절대규칙 위반 해소)
2. `app.py`에 장비 교체 드롭다운 연결 (`candidates` 데이터는 이미 나온다)
3. GitHub push → Cloud 배포 실행
