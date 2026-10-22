# 연구직 AI 스킬 통합 배포 (jaix-kit) — 계획

> 작업 위치: 여러 저장소에 걸친 일이라 새 저장소 `~/dev/jaix-kit`(jeju-inst)에서 진행함. 각 도구 저장소 수정은 해당 저장소에서 브랜치 → PR로 함. STATUS.md에 한 줄 추가함.

## Context
- 2026-11-10부터 연구직 전원에게 Claude(비영리 할인) 또는 Codex 계정을 줌. 연구원 대부분 Windows, 비개발자.
- AI센터에서만 쓰던 원내 스킬을 "AI 설치 → 원내 도구 줄줄이 설치 → GitHub 버전업이 저절로 반영"되게 하고 싶음. 사용 경험은 일반 프로그램 설치·업데이트와 비슷해야 함.
- 스킬은 저장소가 제각각이고 서로 물려 있어서(gw → hwp-agent convert 등) **조합 단위 버전 관리**가 필요함. 지금은 semver 태그도 없고, 버전을 고정하는 장치도 없음.
- 기존 표준 `ji-deploy-standards/README.md`(로컬 stdio MCP + `<tool> setup --register`)가 있음. 이번 계획으로 이 표준을 갱신함.

## 조사로 정리된 것 (도구별 판정)
| 사용자 목록 | 판정 | 연구원 경로 |
|---|---|---|
| 1 hwp-agent | **번들 핵심** | 공개, Windows exe+Inno 설치본(JRE 동봉), stdio MCP·`setup --register` 있음 |
| 2 mail-skill | 번들(선택) | 공개 플러그인+`bootstrap.ps1`. 개인 앱비번+IMAP 1회 수작업. himalaya·age 필요 |
| 3 slack | **공식 커넥터로 대체** | 사내 쪽은 관리자 토큰이라 배포 불가 |
| 4 google | **공식 커넥터로 대체** | 사내 쪽은 Super Admin 위임 SA. `gdoc-push`(표 폭 보존)만 나중에 이식 후보 |
| 5 monday | **공식 커넥터로 대체** | ji-monday-admin 문서가 이미 공식 MCP를 권장함 |
| 6 웍스모바일 | **기성 `nworks` + 기관 User-OAuth 앱 1개** | 사내 `works`는 도메인 관리자급 키라 배포 금지. 설정 안내만 작성 |
| 7 ji-gw-ai | 번들(조건부) | private·라이선스상 재배포 불가·uv+playwright+pymssql·원내망 필요. 관리자 경로를 뺀 공유 빌드가 필요 |
| 8 worklog | 번들 | 이미 `jeju-inst/calendar-worklog` 공개 플러그인(v0.1.11) |
| 9 hermes-slackbot | **3번 채널의 기반**(아래 채널 원칙) | 그대로는 개인 Slack 앱 생성·토큰 처리가 필요해 비개발자에게 무리 → 관리자 사전 생성 + 설치 프로그램 자동화로 해결 |

추천 추가 후보: **ji-writing-standards**(보고서 톤·서식·인용 → 스킬화, 효과 큼), **ji-project-template**(새 과제 폴더 스킬), **korea-rio-mcp**(경제파급 분석 연구자용, Windows 온보딩 있음), **규정 Q&A**(ji-regulations, private 유지 필요), **card-puller**(경비 증빙). rec2md는 로컬 엔진이 Apple Silicon 전용이라 Windows는 클라우드 STT 검증 뒤에.

## 확정된 결정 (2026-10-22 사용자 답)
- 주 사용 화면은 **Claude Desktop 앱**(Cowork·Code 탭). 플랜은 **Team/Enterprise**라 관리자 콘솔로 일괄 배포함.
- gw는 **관리자 경로를 뺀 공유 빌드를 따로 공개**함(사내 한정 라이선스).
- 1차 번들에 추가: ji-writing-standards 스킬, ji-project-template, korea-rio-mcp, 규정 Q&A.
  - 규정 Q&A는 원문이 private임 → 플러그인으로 원문을 나눠주지 않고, **원내 호스팅 원격 MCP(HTTP+인증)를 조직 커스텀 커넥터로** 등록함. Desktop·웹 채팅 어디서든 닿음.
- **최대 리스크**: Cowork가 로컬 CLI·stdio MCP를 실행할 수 있는지는 문서로 확인되지 않음. 1단계에서 namun-ji로 실측함. 안 되면 로컬 도구(hwp·gw)는 Desktop **Code 탭**으로 안내하고, Cowork에서는 스킬·원격 커넥터만 씀.

## 채널 원칙: 세 채널을 모두 켜 둠 (2026-10-22 사용자 지시)
| 순위 | 채널 | 대상 | 도구가 닿는 방식 |
|---|---|---|---|
| 1 (베스트) | **데스크톱 앱** — Claude Desktop(Cowork·Code 탭), Codex/ChatGPT 데스크톱 | 전원 | 조직 플러그인(Claude) · 워크스페이스 플러그인(Codex) |
| 2 (불가 시) | **CLI** — Claude Code, Codex CLI | 데스크톱 앱에서 안 되는 기능이 있을 때 | 같은 플러그인 + 같은 로컬 런타임 |
| 3 | **Hermes Agent + 슬랙** — 개인 `Hermes-<id>` 봇 | CLI를 못 쓰는 일반 사용자 | Hermes 스킬 폴더에 같은 SKILL.md + 같은 로컬 런타임 |

- **핵심은 한 벌만 둠**: 도구마다 CLI + stdio MCP + 호스트 중립 SKILL.md 하나씩. 채널별로는 얇은 어댑터(Claude 플러그인 / Codex 플러그인 / Hermes 스킬 복사)만 둠.
- jaix-kit lockfile 하나가 세 채널의 버전을 같이 정함. `jaix update`가 Hermes 스킬 폴더도 같은 태그로 맞춤(Windows는 심링크 대신 복사).
- **Hermes 채널을 비개발자도 쓸 수 있게 하기**: 지금 hermes-slackbot은 개인이 Slack 앱을 만들고 토큰을 다뤄야 해서 무리임. → 관리자가 Slack App Manifest API(`apps.manifest.create`)로 사람마다 앱을 **미리 만들어** 두고, 토큰은 설치 프로그램이 받아 Hermes 설정에 넣음. 사용자는 설치 프로그램에서 "슬랙으로도 쓰기"만 체크함. 게이트웨이는 Windows 작업 스케줄러로 로그인 시 자동 시작함. Hermes 모델은 각자 받은 Claude/Codex 구독으로 돌림.
- CI 조합 테스트와 namun-ji 실측도 세 채널 각각에서 함.

## 설계 (추천안)
### 1. 배포 허브 = 기관 마켓플레이스 저장소 하나 (`jeju-inst/jaix-kit`, 신규)
- `.claude-plugin/marketplace.json`이 각 도구 저장소를 `{"source":"github","repo":…,"ref":"vX.Y.Z"}`로 **태그 고정**해서 가리킴. 이 파일이 곧 "검증된 조합" 잠금 파일(lockfile) 역할을 함.
- 도구 저장소는 각자 개발함. 릴리스 = semver 태그를 붙이고 → jaix-kit에서 ref를 올리는 PR → CI(조합 테스트)를 통과하면 머지 → 전원에게 자동 반영.
- 채널은 둘: `stable`(전원)과 `beta`(AI센터, ref=main). hwp-agent·gw처럼 수시로 버전이 오르는 도구는 beta에서 먼저 굴림.
- 도구 사이 의존은 각 플러그인의 `requires` 메타(예: gw ≥ x 는 hwp-agent ≥ y)로 적고, jaix-kit CI가 조합을 검사함.

### 2. 사용자에게 내려가는 경로
- **Claude**: claude.ai 관리자 콘솔 Organization 플러그인 설정 + server-managed settings(`extraKnownMarketplaces`에 `autoUpdate:true`, `enabledPlugins`)로 일괄 등록함. → Cowork·Desktop Code 탭·터미널 Claude Code에 자동으로 내려가고 자동 업데이트됨. 사용자는 아무것도 안 함.
- **Codex**: 워크스페이스 관리자가 같은 GitHub 마켓플레이스를 import함(Codex 플러그인 형식 차이는 1단계에서 확인).
- **로컬 실행파일**(hwp-agent·himalaya·gw 런타임)은 플러그인만으로 안 깔림 → **Windows 부트스트랩 설치본 1개** `jaix-setup.exe`(Inno, per-user, 관리자 권한 불필요):
  - uv·JRE(Temurin)·himalaya·age·Git을 winget으로 설치하고, 체크리스트 UI → `jaix setup`에 위임함(ji-deploy-standards 3.2 원칙 그대로).
  - 플러그인 `.mcp.json`은 `uvx --from git+https://github.com/z0nam/hwp-agent@vX.Y.Z hwp-agent mcp`처럼 **고정 태그로 실행** → 마켓플레이스 ref가 오르면 실행파일도 같이 오름. 조합이 어긋날 일이 없음.
  - 플러그인 SessionStart 훅(`"shell":"powershell"`)은 런타임이 빠졌는지만 점검하고, 빠졌으면 "설치 프로그램을 다시 실행하세요" 한 줄을 띄움. 무거운 설치는 훅에서 하지 않음.
- 공식 커넥터(Slack·Google·monday)는 관리자 콘솔에서 조직 커넥터로 켜고, 사용자는 첫 사용 때 OAuth만 함.

### 3. 비밀·권한 원칙
- jaix-kit과 플러그인 저장소에는 비밀을 두지 않음(공개 가능해야 함). 개인 자격증명은 Windows 자격 증명 관리자/DPAPI에 둠(맥 `security` 의존은 추상화함).
- 관리자 경로(gw admin, works SA, Slack admin token)는 공유 빌드에서 **코드 차원에서 빼냄**.

## 단계
0. **결정**: 아래 질문 답 → `ji-deploy-standards` README 갱신(이 설계를 v2로).
1. **골격**: `jeju-inst/jaix-kit` 생성 — marketplace.json, 채널 2개, 조합 CI(Windows runner에서 각 플러그인 설치 + `--version`·스모크).
   Claude/Codex 마켓플레이스 형식이 서로 호환되는지 확인함.
   **namun-ji 실측(최우선)**: Desktop Cowork/Code 탭에서 플러그인 stdio MCP(`uvx …`)·로컬 CLI가 실행되는지, Windows에서 훅 셸은 무엇인지 확인함.
2. **1차 편입(공개·Windows 준비된 것)**: hwp-agent(v0.2.0 태그, `.claude-plugin` 추가, SKILL.md의 낡은 jar/Maven 설명 정리), calendar-worklog(외부 ref로 편입), ji-writing-standards 스킬화, ji-project-template 스킬화, korea-rio-mcp 플러그인화(`ONBOARDING.md` Windows 절차 재사용).
3. **부트스트랩 설치본**: `jaix-setup.exe` + `jaix` CLI(setup·doctor·update). hwp-agent의 Inno/PyInstaller 워크플로를 재사용함.
4. **gw 공유 빌드**: `ji-gw-ai`에서 admin 경로·Slack/Anthropic 토큰 의존을 빼낸 패키지를 분리함(`gw directory-lite` 계열 재사용). `osascript` 알림은 OS별로 분기함. playwright chromium은 부트스트랩이 설치함.
   **규정 Q&A**: 원격 MCP 서버(원내 호스팅, 조직 커넥터).
   **mail-skill**: Windows auth.cmd 미검증 항목 해소. **웍스**: nworks 안내 + 기관 OAuth 앱 등록.
   **공식 커넥터**(Slack·Google·monday)를 조직 커넥터로 켬.
4b. **Hermes 채널**: hermes-slackbot에 관리자용 일괄 앱 생성 스크립트 추가(manifest API, 관리자 config token은 관리자 머신에만 둠). `jaix-setup.exe`에 Hermes 설치·게이트웨이 등록 단계 추가. namun-ji에는 Hermes-zh 실기 검증 이력이 있으니 그 절차를 재사용함.
5. **파일럿**: AI센터 2-3명이 beta → 11/10 전원 stable. 안내는 ji-manual-portal에 올림.

## 일정 (Team 관리자 권한은 11/1부터)
| 기간 | 할 일 |
|---|---|
| **~10/31** (관리자 권한 없음) | 1-4단계 중 관리자 콘솔이 필요 없는 것 전부: 저장소·태그·lockfile·플러그인·`jaix-setup.exe`·gw 공유 빌드·Hermes 자동화. 배포 경로는 관리자 콘솔 대신 **사용자 설정으로 흉내** 냄(`/plugin marketplace add jeju-inst/jaix-kit` 또는 시험 계정 `~/.claude/settings.json`의 `extraKnownMarketplaces`+`autoUpdate`). 세 채널을 namun-ji에서 실측함 |
| **11/1-11/9** (관리자 콘솔 실측) | 조직 플러그인·server-managed settings·조직 커넥터(Slack·Google·monday·규정 MCP)를 실제로 켜고 확인함: Cowork·Code 탭·CLI에 내려가는지, `autoUpdate`가 강제되는지, Codex 워크스페이스 import가 되는지. AI센터 파일럿(beta 채널) |
| **11/10** | 전원 stable 배포, ji-manual-portal 안내 공개 |

- **관리자 경로가 안 될 때의 대비**: `jaix setup`이 사용자 설정(`~/.claude/settings.json` 등)에 마켓플레이스 등록과 `autoUpdate`를 직접 넣는 경로를 처음부터 함께 만들어 둠. 11/1-9 실측 결과에 따라 둘 중 하나를 고름. 일정이 관리자 콘솔 하나에 걸리지 않게 함.

## 개발·테스트 플랫폼
- 개발은 맥에서 계속함. 다만 **Windows가 1급 타깃**이라 CI는 `windows-latest` runner로 돌림.
- 실기 검증은 namun-ji(ssh, PowerShell 5.1). 이미 claude·codex·uv·git·hermes가 다 깔려 있어 "처음 설치"를 재현하지 못함 → 깨끗한 설치를 시험할 공간을 따로 둠. **기존 `user` 계정(업무용)은 그대로 둠.**
  - 1순위 **Windows Sandbox**: 켤 때마다 빈 Windows가 뜨고, 닫으면 통째로 사라짐. 기존 계정·파일·설정에 흔적이 남지 않음. "처음 설치"를 몇 번이든 반복할 수 있음. Pro/Enterprise 에디션 + 가상화가 켜져 있어야 함 → 1단계에서 확인함.
  - 2순위 **로컬 표준 사용자 `jaix-test` 추가**: Windows 계정은 프로필이 서로 분리돼 있음. `user`의 Claude/Codex 로그인·설정·파일은 건드리지 않음. 시험 때만 사용자 전환으로 들어감. 계정 생성에는 관리자 권한이 필요함(회사 PC 정책 확인).
  - 둘 다 사용자 확인을 받은 뒤 진행함.

## Verification
- jaix-kit CI: Windows runner에서 플러그인 설치 → 각 MCP `initialize` 응답·CLI `--version`이 lockfile의 태그와 일치하는지 확인.
- namun-ji 새 계정에서: `jaix-setup.exe` → Claude Desktop 로그인 → hwp 서식 채우기 1건·worklog 1건·(mail 1건) 실행.
- 버전업 시험: hwp-agent에 태그를 하나 더 찍고 jaix-kit ref를 올림 → namun-ji에서 재시작만으로 새 버전이 실행되는지 확인.
