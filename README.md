# dc-design-tool

AI 가속기(GPU/TPU/Trainium) 랙 기반 데이터센터 M&E 개념설계 자동화 도구.
레고형 카탈로그(`dc_design_tool/data/*.yaml`) + 결정론적 엔진(`engine/`) + 규격(`rules/`) + 산출물(`reports/`).

## 빠른 시작

### 웹 UI (Streamlit)
```bash
pip install -r requirements.txt          # 또는 pip install -e ".[ui]"
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 자격증명 설정(필수)
streamlit run app.py
```
**로그인이 설정되지 않으면 화면이 열리지 않는다.** 아래 [로그인 설정](#로그인-설정)을 먼저 보라.

로그인 후 랙 모델·규모·Tier·이중화·ΔT·목표 PUE를 고르고 **설계 실행**을 누르면
기계/전기/통신/공간/규격검증 5개 탭과 BOM이 나오고, xlsx·docx를 내려받을 수 있다.
`랙 추가` 탭에서 카탈로그에 없는 랙을 등록하면 `data/user_racks.yaml`에 저장되어
CLI에서도 즉시 보인다(출처 `source_url` 필수).

### CLI
```bash
pip install -e .
pytest -q
dc-design build --spec examples/spec_gb200_5mw_tier3.yaml --out out/gb200_5mw
```

### MCP 서버 (다른 에이전트에서 엔진 호출)
```bash
pip install -e ".[mcp]"
dc-design-mcp          # stdio 전송
```
Claude Desktop / Claude Code 등의 MCP 설정에 아래를 추가하면 툴 7종
(`size_design`, `check_compliance`, `list_catalog`, `list_regions`,
`compare_scenarios`, `build_reports`, `add_rack`)이 노출된다.
```json
{"mcpServers": {"dc-design": {"command": "dc-design-mcp"}}}
```

| 명령 | 용도 |
|---|---|
| `dc-design build --spec <file> --out <dir>` | 사이징 → 규격검증 → xlsx·docx·mermaid 산출 |
| `dc-design build ... --strict` | 규격 위반이 있으면 종료코드 1 (CI 게이트) |
| `dc-design check --spec <file> --verbose` | 산출물 없이 규격검증만, 위반 시 종료코드 1 |
| `dc-design compare --spec <sweep> --out <dir> --sort pue` | 칩세대·이중화·냉각 조건 스윕 비교표 |
| `dc-design catalog --type rack` | 카탈로그 블록 조회(없는 장비 지어내기 방지) |
| `dc-design regions` | 국가별 규격 팩 목록 |
| `dc-design install-agents` | 서브에이전트 정의를 `.claude/agents/`에 설치 |

예제 spec: `examples/spec_gb200_5mw_tier3.yaml`(5MW Tier III),
`examples/spec_gb300_8mw_tier4.yaml`(8MW Tier IV 2N/N+2, 부산),
`examples/sweep_chip_generation.yaml`(칩세대 × 이중화 비교).

## 로그인 설정

자격증명은 **코드·저장소에 두지 않는다.** `st.secrets`(로컬은 `.streamlit/secrets.toml`,
배포는 Streamlit Cloud의 Secrets)에서만 읽는다. `dc_design_tool/ui_auth.py`가 게이트를
담당하며, 설정이 없으면 안내만 띄우고 화면을 열지 않는다(fail closed).

1. **템플릿 복사** — `cp .streamlit/secrets.toml.example .streamlit/secrets.toml`
   (`.streamlit/secrets.toml`은 `.gitignore`에 걸려 있다. 커밋되지 않는다.)
2. **쿠키 키 생성** — `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   결과를 `[auth.cookie] key`에 붙여 넣는다.
3. **사용자별 비밀번호 해시 생성** — 사람마다 한 번씩:
   ```bash
   python scripts/hash_password.py
   ```
   비밀번호는 화면에 표시되지 않고 셸 히스토리에도 남지 않는다. 출력된 TOML 블록을
   `secrets.toml`에 그대로 붙여 넣는다. 평문 비밀번호를 넣으면 로그인이 되지 않고
   화면에 경고가 뜬다(`auto_hash=False`).
4. 사용자를 추가·삭제하려면 `[auth.credentials.usernames."<이름>"]` 블록을 넣거나 지운다.
   로그인 ID는 사용자의 실명이다. 동명이인이 있으면 ID에 소속을 덧붙이고
   (`"홍길동-설비"`) `name`에는 화면에 띄울 이름을 둔다.

## Streamlit Community Cloud 배포

### 0. Git 저장소 준비
이 폴더는 아직 git 저장소가 아니다. 먼저 초기화한다.
```bash
git init
git add .
git commit -m "데이터센터 M&E 개념설계 도구"
```
`git status`로 **`.streamlit/secrets.toml`이 목록에 없는지** 반드시 확인할 것.
있다면 커밋하지 말고 `.gitignore`를 먼저 점검하라.

### 1. GitHub에 push
```bash
gh repo create <조직>/dc-design-tool --private --source=. --push
# 또는
git remote add origin https://github.com/<조직>/dc-design-tool.git
git branch -M main && git push -u origin main
```
사내 공유용이라면 **저장소를 private으로 만든다.** 카탈로그는 공개 사양뿐이지만,
저장소가 공개되면 이후 누군가 사내 장비를 커밋했을 때 그대로 노출된다.

### 2. 앱 생성
1. <https://share.streamlit.io> 접속 → GitHub 계정으로 로그인.
2. **New app** → **Deploy a public app from a repository**가 아니라
   방금 만든 private 저장소를 선택한다(GitHub 권한 승인이 필요하면 승인).
3. 입력값:
   - **Repository**: `<조직>/dc-design-tool`
   - **Branch**: `main`
   - **Main file path**: `app.py`   ← 저장소 루트
4. **Deploy** 를 누르기 전에 3번(Secrets)을 먼저 채우면 첫 실행부터 로그인 화면이 뜬다.

### 3. Secrets 설정
앱 화면 우하단 **Manage app → Settings → Secrets** (배포 전이면 **Advanced settings → Secrets**).
로컬 `.streamlit/secrets.toml`의 **내용을 그대로** 붙여 넣는다. 파일을 업로드하는 것이
아니라 텍스트를 붙여 넣는 방식이며, 저장하면 앱이 자동으로 재시작된다.

```toml
[auth.cookie]
name = "dc_design_auth"
key = "…token_urlsafe(48) 결과…"
expiry_days = 1

[auth.credentials.usernames."20240101"]
name = "홍길동"
email = "hong@example.com"
password = "$2b$12$…"
```

Secrets를 빠뜨린 채 배포하면 앱이 "로그인 설정을 읽지 못했습니다" 안내를 띄우고 멈춘다.
설계 화면이 공개되는 일은 없다.

### 4. 접근 제한 (비공개 설정)
Streamlit Cloud 자체 접근 제어와 앱 내부 로그인은 **다른 층**이다. 둘 다 켜라.

1. **Manage app → Settings → Sharing** 에서 **"Only specific people can view this app"** 선택.
2. **Invite viewers** 에 사내 이메일을 추가한다. 초대받은 사람은 Google/GitHub 등으로
   Streamlit에 로그인해야 앱 URL에 접근할 수 있다.
3. 그 뒤 앱 안에서 다시 **이름+비밀번호**로 로그인한다.

Cloud 공유 설정만으로는 초대 목록 관리가 이메일 단위라 사용자 추적이 안 되고,
앱 내부 로그인만으로는 URL이 공개 인터넷에 노출된다. 두 층을 함께 쓰는 이유다.

### 5. 배포 후 확인
- 로그인 화면이 먼저 뜨는가 (설계 화면이 바로 보이면 Secrets 설정을 다시 볼 것)
- 잘못된 비밀번호로 막히는가
- 로그인 후 `설계 실행` → 5개 탭·BOM·다운로드가 동작하는가
- 사이드바에 접속자 이름과 `로그아웃` 버튼이 보이는가

### 배포 시 알아둘 제약
- **파일 저장은 영구적이지 않다.** `랙 추가`로 등록한 랙은 `data/user_racks.yaml`에
  저장되는데, Cloud는 재시작·재배포 때 파일 시스템을 초기화한다. 등록한 랙은 사라진다.
  영구 보관하려면 로컬에서 등록해 저장소에 커밋해야 한다.
- **사용자 카탈로그는 접속자 간에 공유된다.** 한 사람이 등록한 랙이 다른 사람 화면에도
  보인다. 사용자별 격리가 없으므로 사내 장비 사양은 올리지 말 것.
- **저장소는 데모 상태로 유지한다.** 배포본 카탈로그는 공개 데이터시트 기반이며
  대부분 `confidence: projected`(개략 추정)다. `data/user_racks.yaml`은 `.gitignore`에
  걸려 있어 실수로 커밋되지 않는다.
- **리소스 한도.** Community Cloud는 무료 티어 기준 메모리·CPU가 제한적이고
  일정 시간 미사용 시 앱이 잠든다(첫 접속이 느릴 수 있다).

## 대화형 사용 (Claude Code)
1. 이 폴더에서 `claude` 실행 → `dc-design install-agents`.
2. 프롬프트 예: "GB200 5MW Tier III 부산 조건으로 설계해줘".
3. 오케스트레이션: `intake` → `sizing` → `mechanical`/`electrical`/`ict` →
   `compliance` → `reporter`. 규칙은 `CLAUDE.md`, 개념·판단 근거는 `docs/블루프린트.md`.

## 지금 되는 것
- **카탈로그**: 칩·노드(트레이)·랙(GB200/GB300/Rubin/TPU v7/Trainium3)·냉각·전기·통신 블록
  로드·검증, `source_url` 누락 시 오류, `confidence: projected` 경고.
- **레고 그래프 솔버**(`engine/compose.py`): `composed_of`로 칩→노드→랙을 조립해 전력·가속기 수를
  롤업하고, **벤더 선언 정격과 구성 합의 불일치를 검출**한다(순환 참조·수량 오류도 검사).
  예: GB200 NVL72 = 컴퓨트 트레이 18 × (B200 4 + 오버헤드) + NVLink 스위치 트레이 9 = 120.0 kW.
- **사이징**: IT부하 → 냉각(유량/CDU/칠러/RT) → 전기 상세 → 통신 → 공간/구조.
  - 전기: UPS, 배터리 자립시간·필요에너지, 발전기(고조파·스텝부하 여유), 변압기,
    **수전 전류(부하 기준)**, **열(row) 단위 버스웨이 정격**, PDU, 이중화(N/N+1/N+2/2N).
  - 통신: 오버섭스크립션 기반 leaf/spine 대수, 패브릭 링크, 트랜시버·케이블(예비율 포함).
  - 공간: 화이트스페이스, 전기실/기계실/지원공간, 총 건축면적, 랙 열 배치, 바닥하중 검증.
- **규격 자동검증**(`engine/compliance.py`) — 14개 항목, 위반/경고/정보 3단계, 각 판정에 근거 규칙 명시:

  | 코드 | 내용 |
  |---|---|
  | `TIER_ELECTRICAL` / `TIER_MECHANICAL` / `TIER_CONCURRENT_MAINT` | Uptime Tier 이중화 최소요건 |
  | `REDUNDANCY_EFFECTIVE_*` | **표기가 아닌 실제 설치대수**로 단일 고장 후 잔여 용량 검증 |
  | `PDU_CAPACITY` | 급전 경로당 PDU 용량 ≥ 랙 부하 |
  | `BUSWAY_RATING` | 버스웨이 정격 ≥ 열(row) 전류, 표준 상한 초과 시 위반 |
  | `ME_ROOM_AREA` | 부속실 장비 점유율(옥외 장비 제외) ≤ 허용치 |
  | `FLOOR_LOAD` | 랙 바닥하중 ≤ 슬래브 허용하중 |
  | `ASHRAE_WATER_CLASS` / `ASHRAE_AIR_CLASS` / `FREE_COOLING` | 수온등급 분류, 외기+접근온도 기반 프리쿨링 가능성 |
  | `PUE_TARGET` | 추정 PUE ≤ 목표 |
  | `PORT_SPEED_MATCH` / `NETWORK_RACK_SPACE` | 랙·스위치 포트속도 정합, 스위치 전용 랙 수 |
  | `CATALOG_PROJECTED` / `CATALOG_FRESHNESS` | 추정 사양 워터마크, `as_of_date` 노후 경고 |

  BOM 각 줄은 `block_id`로 카탈로그 블록까지 추적된다.
- **국가별 규격 팩**(`rules/regions/*.yaml`): `spec.region`으로 선택하면 해당 지역의
  수전전압·저압전압 등이 기존 규칙 위에 **오버레이 병합**되고, 지역 검증(`REGION_PACK` /
  `REGION_VOLTAGE` / `REGION_THD`)이 추가된다. `KR` 팩은 KEC 기반(22.9kV 수전, 380V 급전,
  전류 왜형률 5%). 팩 추가는 yaml 한 개를 넣으면 끝이다.
- **시나리오 비교**(`engine/scenario.py`): `base` + `sweep` 곱집합을 사이징해 랙 수·PUE·
  총 면적·설비 수량·가속기당 면적/부하·규격 위반 건수를 한 표로 비교. 한 조합이 실패해도
  나머지는 계속 평가된다. **CAPEX는 카탈로그에 `capex_usd`가 있는 블록만 합산하고,
  없으면 임의 단가를 만들지 않고 '비용 미상 블록 수'로 보고한다.**
- **산출물**: Excel BOM/부하요약(+규격검증 시트), Word 설계기준서, **mermaid 계통도 3종**
  (전기 단선도·냉각 계통도·통신 패브릭), 시나리오 비교표 xlsx.
- **테스트**: 111개(골든 회귀, 전력·공간·통신·규격·산출물·CLI·에이전트 동기화).

## 확장 방법 (코드 수정 없음)
- 신규 장비: `dc_design_tool/data/*.yaml`에 블록 추가(`as_of_date`·`confidence`·`source_url` 필수).
- 장비 교체: `spec.yaml`에 `selections:`(역할 → block_id)를 적으면 CLI·시나리오 비교·MCP에
  모두 반영된다. 웹 UI는 `장비 교체` 패널에서 고른다. 안 적은 역할은 `default: true`가
  붙은 블록을 쓴다.
  후보 확인은 `dc-design catalog --type electrical --subtype ups`.
- 설계 계수: `dc_design_tool/rules/*.yaml` 수정
  (`redundancy` 이중화, `electrical` 역률·하우스부하·배전손실·고조파·자립시간·버스웨이 표준,
   `cooling` 냉각소비전력 계수, `ashrae` 수온·공기등급,
   `space` 통로계수·허용 바닥하중, `network` 오버섭스크립션·예비율, `tiers` Tier 요건).
  코드에는 설계 계수를 두지 않는다 — 엔진은 전부 `load_rule()` 로 읽는다.

## 남은 단계
카탈로그 단가(`capex_usd`) 확보 시 CAPEX 비교 활성화, 규격 팩 확장(지역 추가는 yaml 1개).

## 주의
산출물은 개념설계/타당성 수준이며, 실시설계·인허가는 면허기술자(정보통신·전기·기계) 검토가 필요하다.
`confidence: projected` 사양과 `generic-industry-typical` 장비는 개략치이므로 벤더 확정값으로 갱신할 것.
`rules/*.yaml`의 계수는 국내 적용 시 KEC·건축구조기준 등 관할 규정으로 교체해야 한다.
