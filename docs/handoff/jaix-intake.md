# jaix-intake — 도구 두 개를 플러그인으로 편입 (agy)

공통 규칙: [README.md](README.md). 편입 표준: [../tool-standard.md](../tool-standard.md)(규칙 ID와 PR 본문 체크리스트). 태스크 #3의 나머지. 정해진 틀에 맞춰 옮기는 일이다. **틀에 안 맞는 상황이 나오면 추측해서 고치지 말고 멈추고 사용자에게 보고한다.**

## 할 일 (순서대로, 저장소마다 PR 하나)

### A. ji-project-template → 스킬 플러그인
- 저장소: `jeju-inst/ji-project-template`, 로컬 `~/dev/ji-project-template`. 새 연구과제 폴더 구조·연구계획서 표준.
- 만들 것:
  - `.claude-plugin/plugin.json` — `name: "ji-project-template"`, `displayName`(한국어), `description`(한 문장), `author`, `homepage`, `repository`, `license`, `keywords`. **`version` 넣지 않음.**
  - `skills/ji-project-template/SKILL.md` — "새 과제 폴더 만들어줘", "연구계획서 틀" 같은 요청에 저장소의 `templates/`·`scripts/`를 쓰는 방법. frontmatter는 `name`·`description`만. 본문은 셸 명령을 Bash로 부르는 식으로 **호스트 중립**하게(Claude 전용 표현 금지). 본문 10k 토큰 이하, 길면 `references/`로.
  - 스크립트가 맥 전용(bash·`security`·경로 `/Users/...`)이면 고치지 말고 **목록만 PR 본문에 적는다**(Windows 대응은 별도 판단).
- 참고 구현(그대로 따라 할 것): `z0nam/hwp-agent`의 `.claude-plugin/plugin.json`, `skills/hwp-agent/SKILL.md`.

### B. korea-rio-mcp → MCP 플러그인
- 저장소: `z0nam/korea-rio-mcp`, 로컬 `~/dev/korea-rio-mcp`. 산업연관 경제파급 분석 MCP(Python, `[project.scripts] korea-rio-mcp = "rio_mcp.server:main"`). `ONBOARDING.md`에 Windows 절차가 있다.
- 만들 것:
  - `.claude-plugin/plugin.json` (A와 같은 규칙).
  - `.mcp.json` — hwp-agent와 같은 방식:
    ```json
    {"mcpServers": {"korea-rio": {"command": "uvx", "args": ["--from", "${CLAUDE_PLUGIN_ROOT}", "korea-rio-mcp"]}}}
    ```
    `pyproject.toml`의 실행 진입점과 MCP 의존성을 확인해 맞춘다(필요하면 `--with`). 맥에서 `uvx --from . korea-rio-mcp`가 뜨고 MCP `initialize`에 응답하는지 확인.
  - `skills/korea-rio/SKILL.md` — 언제 이 도구를 쓰는지, 기본 흐름(기준표 불러오기 → 효과 계산 → 보고서). 짧게.
  - **MCP 도구 스키마 크기**를 재서 PR에 적는다(항상 싣는 분량 예산 3k 토큰). 넘으면 줄이지 말고 숫자만 보고.
- `data/`·`dist/`의 큰 파일이 플러그인 설치에 딸려 가는지 확인하고 크기를 PR에 적는다.

### C. jaix-kit 잠금에 두 도구 추가
- 저장소: `jeju-inst/jaix-kit`. A·B PR이 **머지된 뒤에** 한다(머지는 조율 세션이 함 — 기다린다).
- `.claude-plugin/marketplace.json`의 `plugins`에 entry 두 개 추가. 형식은 기존 `ji-report-writing` entry를 그대로 따른다:
  - `source`: `{"source": "url", "url": "https://github.com/<owner>/<repo>.git", "ref": "main", "sha": "<main 의 40자 sha>"}`
  - `metadata.jaix.refKind`: `"branch"`
  - **`github` 소스, `owner/repo` 축약, `git@` URL 금지** — SSH 키 없는 연구원 PC에서 설치가 실패한다.
- `python scripts/jaixlock.py check` 통과 확인. 그 뒤에는 갱신 봇이 알아서 따라간다.

## 하지 말 것
- 도구 기능 코드 수정(플러그인 포장만).
- plugin.json `version`, 날짜 태그 직접 달기.
- 다른 entry 수정, 워크플로 수정.
- Codex 리뷰 재요청 남발: **P1이 있을 때만** 재리뷰, 리뷰 총 3회 상한(`pr-watch`가 exit 7로 막으면 그대로 멈춤).

## 완료 기준
- PR 3개(A, B, C) 각각 pr-watch 결과와 함께 보고. C는 A·B 머지 뒤.
