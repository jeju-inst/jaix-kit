# jaix-win — namun-ji 실기 측정 (Claude)

공통 규칙: [README.md](README.md). 태스크 #1.

## 목표
연구원 PC와 같은 Windows에서 **세 채널(데스크톱 앱 · CLI · Hermes 슬랙)** 이 jaix-kit 도구를 실제로 실행하는지 확인하고, 결과를 `docs/field-test-namun-ji.md`로 PR한다. 이 결과로 설치 프로그램(`jaix-setup`)과 안내문의 방향이 정해진다. **이 세션은 측정과 기록만 하고 도구 코드는 고치지 않는다.**

## 알려진 사실 (2026-10-27)
- namun-ji: **Windows 11 Home**. Windows Sandbox 불가(Pro 이상 기능). `Win32_Processor.VirtualizationFirmwareEnabled`가 False로 나옴(하이퍼바이저가 이미 떠 있어도 False로 나올 수 있으니 확인 필요).
- 접속: 맥에서 `ssh namun-ji`(Tailscale). 로그인 계정은 **`user` — 업무용이라 Claude/Codex 설정·로그인을 건드리지 않는다.**
- 시험 계정: **`jaix-test`**(표준 사용자, 이미 있음). 깨끗한 설치 시험은 여기서 한다. GUI 조작은 사용자가 화면에서 직접 해야 하므로, 사용자가 따라 할 **단계별 체크리스트**를 주고 스크린샷·로그를 받아 판정한다. 비밀번호는 사용자에게 묻는다.
- PowerShell 5.1, 콘솔 코드페이지가 CP949라 ssh로 받은 한글 출력이 깨진다. `[Console]::OutputEncoding=[Text.Encoding]::UTF8` 을 먼저 실행하거나 결과를 UTF-8 파일로 써서 `scp`로 받는다.
- 마켓플레이스 등록(관리자 콘솔 없이 흉내): `/plugin marketplace add jeju-inst/jaix-kit` 또는 `~/.claude/settings.json`의 `extraKnownMarketplaces`(+ `autoUpdate: true`)와 `enabledPlugins`. 관리자 콘솔은 11/1부터라 지금은 이 경로로 시험한다.
- 현재 잠금(main, 묶음 `v2026.10.27.1`): hwp-agent `v2026.10.26.4`, calendar-worklog `v2026.10.26.3`, ji-report-writing(main).
- hwp-agent MCP는 `uvx --from ${CLAUDE_PLUGIN_ROOT} ... hwp-agent mcp` 로 뜬다. 즉 **uv가 있어야** 한다. 깨끗한 계정에는 uv가 없다는 것 자체가 측정 대상이다.

## 답해야 할 질문
각 항목마다 ✅/⚠️(우회로 됨)/❌ 와 **근거(로그 경로·스크린샷·명령 출력)** 를 적는다.

1. **Cowork(Claude Desktop) on Windows Home**: 설치·실행되는가? VM/가상화 요구 사항이 있는가?
2. Cowork에서 jaix-kit 플러그인의 **스킬**이 로드되는가?
3. Cowork에서 플러그인의 **stdio MCP**(`uvx …`)가 실행되는가? Cowork가 로컬 PC가 아닌 격리 환경에서 도는지, 로컬 파일(`C:\Users\…\문서`)에 접근하는지.
4. Desktop **Code 탭**에서 2-3번이 되는가?
5. **Claude Code CLI**(`jaix-test`에 새로 설치)에서 2-3번이 되는가? 플러그인 훅의 Windows 셸이 무엇인가(PowerShell? Git Bash?)
6. **Codex**(데스크톱·CLI)가 같은 마켓플레이스를 받을 수 있는가? 형식 차이는?
7. `autoUpdate`: 잠금이 바뀌었을 때(이번 주 안에 갱신 봇 PR이 머지되면) 재시작만으로 새 버전이 오는가? — 인수 시험 0-4.
8. 한글·공백 경로(인수 시험 0-6)에서 hwp-agent `convert` 1건.
9. **Hermes**: namun-ji에 Hermes가 있다(`user` 계정, 과거 Hermes-zh 실기 검증 이력). `jaix-test`에서 Hermes 설치가 비개발자에게 몇 단계인지 세기만 한다(자동화는 나중 세션).

## 하지 말 것
- `user` 계정의 `~/.claude`, `~/.codex`, Hermes 설정 수정.
- 관리자 권한이 필요한 시스템 변경(기능 켜기, Hyper-V 활성화 등)은 **멈추고 보고**. 연구원 PC도 관리자 권한이 없다는 전제다.
- 측정하다 도구 버그를 찾으면 고치지 말고 해당 저장소에 이슈만 연다(`gh issue create`, 제목 `[jaix:jaix-win] …`).

## 산출물·완료 기준
- `docs/field-test-namun-ji.md`: 위 질문별 결과표 + 근거 + "그래서 jaix-setup이 해야 할 일" 목록.
- `docs/acceptance-tests.md`의 0번 절에 이미 확인된 칸이 있으면 채운다.
- 3번(Cowork 로컬 MCP)의 답이 나오면 **바로 사용자에게 먼저 알린다** — 설계의 최대 리스크다.
