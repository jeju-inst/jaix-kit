# 웍스(NAVER WORKS) — nworks 설정 안내와 편입안

> 상태: **편입안. 아직 구현하지 않았다.** 관리자 작업(기관 OAuth 앱)과 아래 결정이 끝나면 구현 PR을 올린다.
> 배경: `docs/design.md` 도구별 판정 6번(기성 `nworks` + 기관 User-OAuth 앱 1개), 2026-10-30 사용자 결정(11/10 1차 배포에 포함).

## 먼저 정할 것 (사용자 결정)

| # | 질문 | 권고 |
|---|---|---|
| Q1 | 기관 OAuth 앱: 2026-08에 만든 공용 User OAuth 앱을 재사용할지, JAIX 전용 앱을 새로 만들지 | **기존 공용 앱 재사용 + Client Secret 재발급.** "사람마다 앱을 만들지 않는다"는 원칙대로 앱은 하나다. 그 앱의 Secret은 원래 재발급할 예정이었다(최초 전달 때 대화 기록에 남음). 지금 사용자는 1명이라 재로그인 1건이면 된다 |
| Q2 | 1차 스코프 | **`calendar` `calendar.read` `file` `file.read` `mail.read`** (5개). 메일 쓰기(`mail`)는 넣지 않는다. 게시판·할 일·연락처는 요청이 생기면 넓힌다 |
| Q3 | Client ID/Secret을 연구원 PC에 전달하는 경로 | **`jaix.namun.net`(기관 IP 게이트)에서 받는다.** gw 배포와 같은 경로다. 공개 저장소·설치본에는 넣지 않는다 |
| Q4 | MCP 서버로 붙일지, 스킬 + CLI로 붙일지 | **스킬 + CLI.** nworks MCP는 도구 36개라 상시 분량 예산(3k)을 혼자 넘는다(아래 3.1) |
| Q5 | 외부 개인 개발자의 npm 패키지를 쓰는 것 | **정확한 버전 + 무결성 해시로 고정**해서 쓴다. 버전 올리기는 PR로 한다(아래 3.4) |

## 1. 왜 nworks + 기관 User OAuth인가

사내 `works` CLI(`ji-worksmobile-admin`)는 **도메인 관리자급 키**(서비스 계정 권한 위임)로 동작한다. 그 키는 테넌트의 어느 구성원으로든 행동할 수 있으므로 연구원에게 배포하면 안 된다(TS-SECRET-2).

| | 사내 `works` (배포 금지) | `nworks` + 기관 User OAuth (배포안) |
|---|---|---|
| 토큰이 누구로 행동하나 | 전 구성원 누구로든 | **본인만** |
| 동의 | 없음(관리자가 부여) | 본인이 브라우저에서 로그인·허락 |
| 비밀이 새면 | 테넌트 전체 | 그 사람 계정(Client Secret만으로는 아무것도 못 함) |
| 관리자 콘솔 권한 | 필요 | 관리자 1명만 |

- `nworks`(github.com/yjcho9317/nworks, Apache-2.0, npm `nworks` 1.3.1, 2026-09-19)는 캘린더·드라이브·메일·할 일·게시판·연락처를 User OAuth로 다루는 CLI 겸 MCP 서버다. 모든 명령이 `--json`을 지원하고, 업로드·메일 발송은 `--dry-run`을 지원한다.
- 원내에서 이미 이 경로로 1명이 쓰고 있다(2026-08-24 로그인·드라이브·메일 조회 확인, ji-worksmobile-admin `docs/OPEN_ISSUES.md` B6).

## 2. 사용자 경험 (목표)

1. `jaix-setup.exe`에서 "웍스" 체크(기본 켬). 설치기가 Node.js와 nworks를 깔고 기관 앱 정보를 받아 둔다.
2. 처음 웍스를 쓸 때 AI가 `jaix works login`을 실행한다 → 브라우저에 웍스 로그인·허락 화면이 뜬다 → 한 번 허락.
3. 그 뒤로는 "웍스 공유드라이브에서 ○○ 서식 받아 줘", "이번 주 웍스 일정" 같은 요청이 바로 된다.

연구원이 직접 하는 단계(TS-STEPS-1): **첫 사용 때 브라우저 로그인·허락 1회.** 비밀번호나 Client ID를 손으로 넣는 일은 없다.

## 3. 편입안

### 3.1 MCP가 아니라 스킬 + CLI로 붙인다 (Q4)

- nworks MCP 도구 36개의 설명과 입력 스키마는 소스 기준으로 약 1만 6천 자(한글 약 2,900자)다. 토큰으로 대략 6-8k로 추정한다. **정적 추정이고 실행해서 잰 값은 아니다.** 상시 분량 예산 3k(TS-TOKEN-1)를 혼자 넘는다.
- 또 MCP로 붙이면 쓰지 않을 도구(봇 메시지·조직 구성원 조회 — 서비스 계정 전용, 메일 발송, 연락처 삭제 등)까지 모두 모델에 노출된다.
- 그래서 짧은 스킬 하나가 PATH의 `nworks ... --json`을 부르게 한다. 스킬은 쓰는 명령만 적고, 쓰기 명령은 확인 절차를 붙인다(3.3).
- 대가: 스킬은 로컬 셸 실행이 필요하다. Cowork(DC)에서 로컬 CLI가 실행되는지는 `jaix-win` 실측 결과를 따른다.

### 3.2 저장소와 플러그인 형태

- 새 공개 저장소 `jeju-inst/jaix-works`. 비밀은 두지 않는다.
- 플러그인 루트 = 저장소 루트:
  - `.claude-plugin/plugin.json` (version 없음, TS-FORMAT-1·2)
  - `skills/works/SKILL.md` (TS-FORMAT-3)
  - `runtime.json` — 런타임 선언(TS-RUNTIME-1): Node 최소 버전, nworks 정확한 버전과 npm 무결성 해시, 로그인 스코프 문자열
  - `.github/workflows/calver.yml` (TS-VER-2·3)
  - `.mcp.json` 없음
- 잠금 entry는 다른 도구와 같다(`url` 소스, 태그 + 40자 sha).

`runtime.json` 예:

```json
{
  "node": ">=18",
  "nworks": {
    "version": "1.3.1",
    "integrity": "sha512-sxlxy6Gv6/9ZCLtlAjGUapqDVb+h+A5/9ghrSKDfOGhQoMH3Bhz5BRrHcZPjx8vy8vAiwwaueVXq/p8Ko2Knag=="
  },
  "scope": "calendar calendar.read file file.read mail.read",
  "client_source": "https://jaix.namun.net/works/client.json"
}
```

### 3.3 스킬 내용 (요지)

- 읽기(일정 목록, 드라이브·공유드라이브 목록과 내려받기, 메일 목록·읽기)는 바로 실행한다.
- 쓰기(드라이브 업로드, 일정 만들기·고치기·지우기)는 **실행 전에 무엇을 할지 보여 주고 사용자 확인을 받는다.** 업로드는 `--dry-run`을 먼저 돌린다.
- 메일 발송·봇 메시지·조직 구성원 조회 명령은 스킬에 적지 않는다(스코프에도 없음).
- 로그인이 안 돼 있으면 `jaix works login`을 실행하라고 안내하고, 브라우저가 열린다는 것을 미리 알린다(TS-STEPS-2).
- 토큰·자격증명 파일(`~/.config/nworks/`)을 읽거나 출력하지 않는다.
- 호스트 중립으로 쓴다(TS-SKILL-1). 목표 분량은 SKILL.md 1.5k 토큰 이하.

### 3.4 jaix 쪽 구현

| 단계 | 내용 |
|---|---|
| `jaix setup` | Node.js LTS가 없으면 winget(`OpenJS.NodeJS.LTS`)으로 설치. `<데이터 폴더>\works`에 `runtime.json`의 nworks 버전을 깔고 **npm 무결성 해시를 대조**한다(다르면 설치 중단). `nworks` 실행 파일을 사용자 PATH에 올린다 |
| 기관 앱 정보 | `client_source`(IP 게이트)에서 Client ID/Secret을 받아 사용자 데이터 폴더에 둔다. 원외 망이면 건너뛰고 doctor가 "원내망에서 jaix setup 다시 실행"을 안내한다 |
| `jaix works login` | 받아 둔 값을 **환경변수**(`NWORKS_CLIENT_ID`·`NWORKS_CLIENT_SECRET`)로 넘겨 `nworks login --user --scope "<runtime.json scope>"`을 실행한다. 명령줄 인자로 넘기지 않는다(프로세스 목록에 남음). **스코프를 반드시 명시한다** — nworks 기본값은 전체 스코프이고, 앱에 없는 스코프를 하나라도 요청하면 웍스가 `invalid_scope`로 로그인 전체를 거절한다 |
| `jaix doctor` | `nworks --version`이 `runtime.json`과 같은지, `nworks whoami --json`이 로그인 상태인지 확인하고 고치는 방법 한 줄을 낸다 |
| `jaix update` | 잠금이 새 `runtime.json`을 가리키면 nworks를 그 버전으로 다시 깐다 |
| Codex·Hermes | 같은 CLI와 같은 SKILL.md를 쓴다. MCP 등록은 없다 |

- nworks는 자격증명과 토큰을 `%USERPROFILE%\.config\nworks\`에 평문 JSON으로 저장한다(맥·리눅스는 권한 600, **Windows는 권한 제한 없음**). `%APPDATA%`가 아니므로 Desktop(MSIX) 가상화(TS-WIN-4)와는 무관하다. 평문 저장은 nworks 쪽 한계로 기록하고, 필요하면 상류에 OS 자격 증명 저장소 지원을 제안한다.
- Windows에서 nworks의 브라우저 열기(`cmd /c start`)와 로그인 콜백(`localhost:9876`)은 아직 실기로 확인하지 않았다. 포트가 막혀 있으면 로그인이 실패하므로 `jaix-win` 실측 항목에 넣는다.
- 공급망: nworks는 외부 개인 개발자의 패키지다. 정확한 버전과 무결성 해시로 고정하고, 버전 올리기는 jaix-works PR에서 변경 내역을 읽은 뒤 한다. 자동 갱신 봇 대상에서 뺀다.

## 4. 웍스 관리자 체크리스트 (사용자 작업)

웍스 최고관리자 계정으로 한다. 값은 Q1-Q2 권고안 기준이다.

- [ ] **1. 콘솔 열기**: `https://dev.worksmobile.com` → API → Client App.
- [ ] **2. 앱 고르기 (Q1)**: 기존 공용 User OAuth 앱을 연다. 새로 만들기로 했다면 이름을 `JAIX 웍스 연동`으로 한다.
- [ ] **3. Redirect URL**: `http://localhost:9876/callback`이 목록에 있는지 확인한다. 없으면 입력하고 **추가 버튼까지 누른다**(입력만 하고 추가를 누르지 않아 로그인이 실패한 이력이 있음, 2026-08-24).
- [ ] **4. OAuth Scopes (Q2)**: `calendar` `calendar.read` `file` `file.read` `mail.read` 다섯 개를 켠다. **`mail`(메일 쓰기)은 켜지 않는다** — 발송과 함께 전달(forwarding) 규칙 변경 권한이 따라온다. 기존 앱에 있던 스코프는 그대로 둔다.
- [ ] **5. 서비스 계정 권한 위임**: 이 앱에서 **꺼져 있는지** 확인한다. 관리자 앱과 연구원 앱을 섞지 않는다.
- [ ] **6. 앱 접근(앱 관리 권한)**: "제한 — 관리자 본인만"으로 둔다. 이 설정은 앱을 *쓸* 사람이 아니라 앱 등록을 *보고·고치고·지울* 사람을 정한다. 열어 두면 콘솔에 들어온 누구나 Secret을 읽거나 스코프를 넓힐 수 있다.
- [ ] **7. Client Secret 재발급**: 새 값을 받는다. 이전 값은 폐기된다.
- [ ] **8. 값 기록**: Client ID와 새 Secret을 studio 로컬 배포 설정에만 기록한다(구현 PR이 파일 위치를 정한다. 저장소·메신저·메일에 붙이지 않는다). `https://jaix.namun.net/works/client.json`은 기관 IP에만 내준다.
- [ ] **9. 기존 사용자 재로그인 안내**: Secret이 바뀌었으므로 기존 사용자 1명에게 재로그인을 안내한다.
- [ ] **10. 관리자 PC에서 시험**: `nworks login --user --scope "calendar calendar.read file file.read mail.read"` → `nworks calendar list --json` → `nworks drive sharedrive-list --json`이 본인 권한 범위로 나오는지 본다.
- [ ] **11. 구성원 동의 정책 확인**: 일반 구성원이 이 앱에 OAuth 동의를 할 수 있는지(관리자 사전 승인이 필요한 설정이 있는지) 확인한다. 기존 사용자 1명은 동의가 됐으므로 막혀 있지는 않을 것으로 보지만, 전원 배포 전에 설정 화면에서 확인한다.

이후 운영 원칙:

- 연구원이 늘어도 **앱은 하나**다. 사람마다 앱을 만들지 않는다.
- 스코프를 넓힐 때는 먼저 이 문서와 `runtime.json`을 PR로 고치고, 그다음 콘솔을 바꾼다. 스코프는 앱 속성이라 넓히면 이후 동의하는 모든 사람에게 적용된다.
- Developer Console 권한을 연구원 개인에게 주지 않는다.

## 5. 인수 시험

`docs/acceptance-tests.md`의 5-5(웍스 드라이브: 공유드라이브 파일 목록·내려받기, 본인 권한 범위만)를 쓴다. 구현 PR에서 아래를 추가한다.

| # | 실제 업무 시나리오 | 통과 기준 |
|---|---|---|
| 5-7 | 웍스 공유드라이브의 과제 서식(hwp)을 받아 hwp-agent로 채운 뒤 내 드라이브에 올리기 | 업로드 전 확인 창. 한글·공백 파일명 그대로 유지 |
| 5-8 | "이번 주 웍스 일정 요약" | 본인 캘린더만, 시간대 KST |

## 6. 편입 체크리스트 (예정값)

```markdown
### JAIX 편입 체크리스트 (docs/tool-standard.md)
- [ ] TS-FORMAT-1-4 플러그인 루트(`/`): plugin.json(version 없음) · skills/works/SKILL.md · .mcp.json 없음(스킬 + CLI)
- [ ] TS-VER-2·3 저장소 루트 calver.yml, calver-tag.yml @<40자 SHA>
- [ ] TS-LOCK-1·2 잠금 entry: https url + 40자 sha
- [ ] TS-MCP-1 — (MCP 없음)
- [ ] TS-MCP-4 — (MCP 없음)
- [ ] TS-SKILL-1·2 호스트 중립, 스킬 기준 상대 경로
- [ ] TS-TOKEN-1 상시 분량: ___ 토큰 (스킬 frontmatter만, 목표 300 이하)
- [ ] TS-TOKEN-2 호출당 최대: ___ 토큰 (목표 1.5k 이하)
- [ ] TS-WIN-1 bash 전용 스크립트: 없음
- [ ] TS-WIN-2·3 한글·공백 파일명 업로드·내려받기, nworks 출력 인코딩
- [ ] TS-RUNTIME-1 선언한 런타임: Node ≥18, nworks 1.3.1(무결성 해시) — jaix setup이 설치
- [ ] TS-SECRET-1-3 비밀 없음(Client Secret은 IP 게이트에서 받음) · 관리자 경로 없음(서비스 계정 명령 미사용)
- [ ] TS-TEST-1-3 테스트가 실제 ~/.config/nworks·실제 nworks를 쓰지 않음
- [ ] TS-ACCEPT-1 docs/acceptance-tests.md 시나리오: 5-5, 5-7, 5-8
- [ ] TS-STEPS-1 사용자가 직접 할 단계: 첫 사용 때 브라우저 로그인·허락 1회
- [ ] TS-CHANNEL-1 DC 미확인(로컬 CLI 실측 결과 따름) · DK _ · CC _ · CX _ · HS _
- [ ] TS-INSTALLER-1 — (도구 저장소에 설치기 없음, jaix-setup이 설치)
```
