# JAIX 도구 편입 표준

원내 AI 도구를 JAIX(이 저장소의 잠금 목록)에 넣을 때 지켜야 할 규칙이다. 사람이 읽는 표준은 이 문서 한 벌이고, 기계 검사(잠금 CI)는 이 문서의 규칙 ID를 그대로 쓴다.

- **왜 따로 두나**: 2026-10-27 하루 동안 나온 문제 대부분이 같은 일을 도구마다 따로 정해서 생겼다. Python 버전 고정, 플러그인 경로 변수, 설치기 상수, cp949 출력 같은 것들이다. 한 도구에서 배운 것을 다음 도구가 처음부터 다시 배우지 않게, 여기 한 번만 적는다.
- **흡수한 문서**: `ji-deploy-standards` README(v1, 로컬 초안)의 목표·전달 경로·설치 UX를 이 문서 1-2절로 옮겼다. 그 뒤로는 이 문서가 원본이다.
- **고치는 법**: 규칙을 바꾸거나 새로 넣을 때는 이 저장소에 PR을 올린다. 규칙마다 **근거(이슈·PR)** 를 붙인다. 근거 없는 규칙은 넣지 않는다.

## 읽는 법

규칙마다 ID와 검사 방식을 붙였다.

| 표시 | 뜻 |
|---|---|
| ○ | 지금 jaix-kit CI(`lock-check`: `claude plugin validate`, `jaixlock.py check`, 새 머신 전체 설치)가 검사한다 |
| △ | 기계 검사로 옮길 예정이거나 일부만 검사한다. 잠금 CI 확장 PR이 이 ID를 그대로 쓴다 |
| 문서 | 기계로 판정하기 어렵다. 작업 세션이 확인하고 PR 본문 체크리스트(맨 끝)에 적는다 |

ID 형식은 `TS-<분야>-<번호>`이다. 번호는 지우지 않고, 폐기한 규칙은 "폐기"로 표시해 남긴다(CI·PR 본문의 옛 ID가 가리킬 곳이 있어야 한다).

## 1. 목표 (v1에서)

1. **플랫폼 프리** — AI 구독만 있으면 Claude(Desktop·Code)와 Codex에서 같은 도구를 쓴다. 특정 호스트에서만 되는 배선은 하지 않는다.
2. **"설치 한 번" 수준의 경험** — 연구원은 대부분 Windows를 쓰는 비개발자다. `jaix-setup.exe` 한 번이면 끝나야 하고, 터미널을 여는 일이 없는 것이 목표다.
3. **Windows가 1급 타깃** — 맥에서만 되는 것은 완료가 아니다.

## 2. 전달 경로

- 도구는 **Claude 플러그인**으로 포장하고, 잠금 목록(`.claude-plugin/marketplace.json`)에 태그·커밋으로 고정해 함께 배포한다. 설치·갱신·런타임 준비는 `jaix setup`·`jaix update`가 맡는다(README "jaix CLI").
- 도구의 실행 기능은 **로컬 stdio MCP** 또는 **스킬 + PATH의 CLI**로 낸다. 로컬 stdio MCP 하나면 Claude Desktop·Claude Code·Codex가 모두 붙는다.
- ChatGPT·Gemini 소비자 앱처럼 로컬 MCP를 못 쓰는 곳은 자체 호스팅 웹 링크(예: hwp-agent `serve`)로 우회한다. 보조 경로이며 이 표준의 필수 항목은 아니다.
- **등록 로직은 설치기에 넣지 않는다.** 도구 CLI의 `setup` 명령이나 `jaix setup`이 맡고, 설치기는 체크박스를 받아 그 명령에 넘기는 껍데기다. 맥·Windows·개발자 설치에서 같은 코드가 돌고 테스트할 수 있어야 하기 때문이다(v1 3.2).

---

## 3. 규칙

### FORMAT — 플러그인 형식

**플러그인 루트**는 잠금 entry가 가리키는 폴더다. `url` 소스면 저장소 루트이고, `git-subdir` 소스면 그 `path`다(예: calendar-worklog는 `plugin/`). 아래 FORMAT 규칙의 경로는 모두 플러그인 루트 기준이다. 저장소 단위 파일(`calver.yml` 등 `.github/` 아래)은 플러그인 루트와 상관없이 **저장소 루트**에 둔다(TS-VER-2).

| ID | 규칙 | 검사 |
|---|---|---|
| TS-FORMAT-1 | **플러그인 루트**에 `.claude-plugin/plugin.json`을 둔다. `name`(잠금 entry 이름과 같게), `displayName`(한국어), `description`(한 문장), `author`, `homepage`, `repository`, `license`, `keywords`를 넣는다 | △ (plugin_lint, 경고; 설치되는지는 ○ 새 머신 설치, 필드는 아직 검사 안 함) |
| TS-FORMAT-2 | `plugin.json`에 **`version`을 넣지 않는다.** Claude는 plugin.json의 version을 먼저 보므로, 고정값이 남아 있으면 새 버전을 못 알아챈다. 버전 표기는 잠금 entry의 `version` 하나뿐이다 | △ (plugin_lint, 경고) |
| TS-FORMAT-3 | 스킬은 플러그인 루트의 `skills/<name>/SKILL.md`에 둔다. frontmatter는 `name`·`description`만 쓴다 | △ (plugin_lint, 경고) |
| TS-FORMAT-4 | MCP 서버는 플러그인 루트의 `.mcp.json`에 둔다(형식은 MCP 절) | △ |

근거: README "버전", `docs/handoff/jaix-intake.md`(참고 구현 `z0nam/hwp-agent`). 하위 폴더 예: jeju-inst/calendar-worklog(`plugin/.claude-plugin/plugin.json`, `plugin/skills/calendar-worklog/SKILL.md`, 저장소 루트 `.github/workflows/calver.yml`).

### VER — 버전

| ID | 규칙 | 검사 |
|---|---|---|
| TS-VER-1 | 버전은 날짜 태그 `vYYYY.MM.DD.N`(KST, 같은 날 N번째) 하나뿐이다. 사람은 번호를 매기지 않는다. 소스 안의 버전은 `0.0.0+dev` 같은 고정값으로 두고, 배포 빌드가 태그 값을 찍는다 | △ |
| TS-VER-2 | 도구 **저장소 루트**에 `.github/workflows/calver.yml`을 두고(플러그인 루트가 하위 폴더여도 저장소 루트), main에 머지될 때마다 jaix-kit의 재사용 워크플로 `calver-tag.yml`을 부른다 | △ (plugin_lint, 경고) |
| TS-VER-3 | `calver-tag.yml`은 `@main`이 아니라 **jaix-kit 커밋 40자 SHA**로 고정한다. 다른 저장소의 코드가 이 저장소의 태그 권한을 쥐기 때문이다. SHA를 올릴 때는 PR로 한다 | △ (plugin_lint, 경고) |
| TS-VER-4 | 태그로 고정한 잠금 entry의 `version`은 태그에서 `v`를 뺀 값과 같아야 한다. 아직 태그가 없는 도구는 브랜치 head 커밋으로 고정하고 `version`을 비운다 | ○ `jaixlock.py check` (태그 entry만. 브랜치 entry는 △ 경고) |

`calver.yml` 예시:

```yaml
on: { push: { branches: [main] } }
concurrency: calver-tag
jobs:
  tag:
    uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@<jaix-kit 커밋 40자 SHA>
    permissions: { contents: write }
```

근거: README "버전"·"새 버전이 퍼지는 길", `.github/workflows/calver-tag.yml` 머리 주석.

### LOCK — 잠금 소스

| ID | 규칙 | 검사 |
|---|---|---|
| TS-LOCK-1 | 잠금 entry의 `source`는 `url`(또는 `git-subdir`)이고, URL은 `https://`로 시작한다. **`github` 소스, `owner/repo` 축약, `git@` URL은 금지한다.** SSH로 클론돼서, SSH 키가 없는 연구원 PC에서는 설치가 실패한다 | ○ `jaixlock.py check` |
| TS-LOCK-2 | 모든 entry는 40자 커밋 `sha`로 고정한다. `ref`만 있는 entry는 두지 않는다 | ○ `jaixlock.py check` |
| TS-LOCK-3 | 잠금 파일은 갱신 봇과 `scripts/jaixlock.py`만 고친다. 새 도구를 넣는 편입 PR만 예외로 entry를 추가한다 | 문서 |

근거: `docs/handoff/jaix-intake.md` C절, `scripts/jaixlock.py` `check()`.

### MCP — MCP 서버

| ID | 규칙 | 검사 |
|---|---|---|
| TS-MCP-1 | Python MCP는 `uvx --python 3.12 --from ${CLAUDE_PLUGIN_ROOT} [--with …] <진입점>`으로 띄운다. **`--python`을 반드시 고정한다.** 고정하지 않으면 uv가 최신 Python(깨끗한 Windows 계정에서 3.15)을 고르는데, 바이너리 휠이 없는 의존성(lxml)이 소스 빌드에 실패해 MCP가 오류 없이 안 뜬다. `jaix setup`은 이 값을 읽어 그 Python을 앱 밖에서 미리 설치한다 | △ (plugin_lint, 경고) |
| TS-MCP-2 | Codex는 `.mcp.json`의 `${CLAUDE_PLUGIN_ROOT}`를 치환하지 않는다. 그래서 Codex용 MCP 등록은 `jaix`가 `~/.codex/config.toml`에 **절대경로로** 쓴다. 도구 저장소는 `.mcp.json`을 위 형태 하나로만 두고, Codex 전용 설정을 따로 만들지 않는다 | 문서 (jaix 쪽 구현) |
| TS-MCP-3 | MCP 도구 스키마(이름·설명·입력 스키마) 크기를 재서 편입 PR에 적는다. 상시 분량 예산(TS-TOKEN-1)에 들어간다 | △ |
| TS-MCP-4 | stdio MCP는 stdout에 프로토콜 메시지 말고 아무것도 쓰지 않는다(로그는 stderr로). 확인할 때는 실제 `.mcp.json` 명령을 그대로 띄워 `initialize`와 `tools/list`에 응답하는지 본다 | △ |

근거: z0nam/hwp-agent#75(3.15·lxml 실패), z0nam/hwp-agent#76·z0nam/korea-rio-mcp#5(고정), jeju-inst/jaix-kit#15(Python 미리 설치), jeju-inst/jaix-kit#23(Codex 미치환).

### SKILL — 스킬 본문

| ID | 규칙 | 검사 |
|---|---|---|
| TS-SKILL-1 | **호스트 중립**으로 쓴다. "PATH의 셸 명령을 Bash로 부른다"처럼 쓰고, 특정 호스트의 슬래시 명령·도구 이름을 가정하지 않는다 | 문서 |
| TS-SKILL-2 | 스킬이 가리키는 저장소 파일은 **스킬 기준 디렉터리 상대 경로**로 적는다(예: `<skill_base_dir>/../../scripts/init_project.sh`). 플러그인으로 설치되면 파일이 플러그인 캐시에 있으므로, 저장소 루트 상대 경로나 **`path/to/...` 같은 자리표시 경로는 쓰지 않는다** | △ (`path/to` 문자열 검사, plugin_lint, 경고) |
| TS-SKILL-3 | 본문이 길면 워크플로별 `references/*.md`로 나누고, SKILL.md에는 공통 규칙과 "어느 경우에 어느 파일을 읽는지" 표만 남긴다(점진 공개). reference를 못 읽으면 추측하지 말고 알리게 한다 | 문서 |

근거: jeju-inst/ji-project-template#3(커밋 b3eb688: `path/to/ji-project-template/...` → 스킬 기준 상대 경로), jeju-inst/calendar-worklog#41(점진 공개).

### TOKEN — 사용량 예산

연구원 좌석은 Pro의 약 1.25배다. 한도에 걸리는 것도 실패로 본다.

| ID | 규칙 | 검사 |
|---|---|---|
| TS-TOKEN-1 | **상시 분량**(플러그인 설명 + 모든 스킬 frontmatter + MCP 도구 스키마)은 도구 하나당 합계 **3k 토큰 이하**로 한다 | △ |
| TS-TOKEN-2 | **호출 한 번에 싣는 분량**(SKILL.md + 그 워크플로가 읽는 reference)은 **10k 토큰 이하**로 한다 | △ (plugin_lint, 경고) |
| TS-TOKEN-3 | 편입 PR에 측정값을 적는다. 측정법은 다음과 같다. `claude -p --output-format json`으로 문서를 붙인 프롬프트와 빈 프롬프트를 번갈아 3회씩 보내고, `input + cache_creation + cache_read`의 차이를 낸 뒤 **중앙값**을 적는다(기준선이 회차마다 튀기 때문). 워크플로별 합계는 SKILL.md와 해당 reference를 한 번에 붙여 잰다 | 문서 |

근거: `docs/handoff/README.md` 공통 규칙 9, jeju-inst/calendar-worklog#41(측정법, 22k → 10k 이하).

### WIN — Windows

| ID | 규칙 | 검사 |
|---|---|---|
| TS-WIN-1 | 연구원이 부르는 스크립트는 bash 전용으로 두지 않는다. Python(표준 라이브러리) 하나로 쓰거나, bash와 같은 일을 하는 PowerShell 짝을 함께 둔다. bash만 있는 스크립트는 편입 PR에 목록으로 적는다 | △ (`.sh`만 있고 `.ps1`/`.py` 짝이 없는 파일 목록) |
| TS-WIN-2 | **한글·공백이 든 경로**에서 동작해야 한다(예: `C:\Users\홍길동\바탕 화면\2026 과제\서식.hwp`). 경로를 인용 없이 셸에 넘기지 않는다 | 문서 (인수 시험 0-6) |
| TS-WIN-3 | 다른 프로그램의 출력을 읽을 때 **UTF-8로 가정하지 않는다.** 한국어 Windows의 콘솔 프로그램은 cp949(ANSI 코드 페이지)로 출력하는 일이 많다(PyInstaller로 만든 exe는 `PYTHONIOENCODING`도 따르지 않았다). 바이트로 받아 UTF-8로 먼저 해석하고, 실패하면 로캘 인코딩으로 해석한다. 파일을 열 때는 `encoding="utf-8"`을 명시한다 | 문서 |
| TS-WIN-4 | Claude Desktop(MSIX)이 띄운 프로세스가 `%APPDATA%`·`%LOCALAPPDATA%`에 처음 쓰는 것은 가상화돼 앱 안에만 생긴다. 그래서 도구가 실행 중에 런타임(Python·jar 등)을 처음 내려받게 두지 않는다. 런타임은 TS-RUNTIME-1로 선언해 `jaix setup`이 앱 밖에서 미리 깔게 한다. 설치기 안에서 부른 `uv python install`은 결과물이 생겨도 os error 448로 실패를 보고할 수 있으니, 종료 코드가 아니라 결과물로 판정한다 | 문서 (jaix 쪽 구현) |
| TS-WIN-5 | Inno Setup 스크립트에서는 **Inno에 실제로 있는 상수만** 쓴다. 사용자 폴더는 `{%USERPROFILE}`(환경변수 상수)로 쓴다. 없는 상수(`{userprofile}` 등)도 ISCC 컴파일은 통과하지만, `[Code]`에서 쓰면 설치기가 첫 화면 전에 `Unknown constant`로 죽는다. 그래서 TS-INSTALLER-1 스모크로 잡는다 | △ (도구 저장소의 설치기 스모크가 잡는다. 잠금 CI는 아직 검사 안 함) |
| TS-WIN-6 | 한컴 COM 등 데스크톱 세션이 필요한 일은 **사용자가 로그온한 대화형 세션**에서만 돌린다. 세션 0(ssh·서비스·"로그온 여부와 관계없이" 예약 작업)에서는 한컴 COM 서버가 뜨지 않는다(약 2분 뒤 실패) | 문서 |

근거: jeju-inst/jaix-kit#14·#21(MSIX 가상화, os error 448), z0nam/hwp-agent#73(Inno `{userprofile}`), z0nam/hwp-agent#71(cp949 출력, 세션 0 COM 실패), `docs/acceptance-tests.md` 0-6.

### RUNTIME — 런타임 의존성

| ID | 규칙 | 검사 |
|---|---|---|
| TS-RUNTIME-1 | 도구가 실행에 필요로 하는 런타임(Python 버전, JRE, 외부 jar, 외부 CLI 예: `hwp2pdf-cli`)을 **선언한다.** `jaix setup`이 그것을 미리 설치한다. Python 버전은 `.mcp.json`의 `--python`이 선언이다. jar처럼 내려받는 파일은 주소와 sha256을 저장소 안 한 곳에 두고(예: hwp-agent `fetch_jar.py`), jaix가 잠금이 고정한 커밋의 그 파일을 읽는다 | △ |
| TS-RUNTIME-2 | 도구는 외부 런타임을 **스스로 설치하지 않는다.** 찾는 순서(예: 환경변수 → PATH)를 문서에 적고, 없으면 무엇을 깔아야 하는지 한 줄로 알린다. 설치는 `jaix setup` 몫이다 | 문서 |
| TS-RUNTIME-3 | 런타임이 없거나 바쁘면(예: 한글이 열려 있음) 다음 수단으로 넘어가고, **어느 수단으로 처리했는지 결과에 표시한다.** 사용자의 작업(열려 있는 한글 등)을 닫거나 방해하지 않는다 | 문서 |

근거: jeju-inst/jaix-kit#15·#19(Python·jar 미리 받기), `docs/handoff/README.md` "hwp2pdf 위치" 약속, z0nam/hwp-agent#71(엔진 순서·표시).

### SECRET — 비밀·공개 범위

| ID | 규칙 | 검사 |
|---|---|---|
| TS-SECRET-1 | 비밀·토큰·개인정보는 커밋하지 않는다. jaix-kit과 플러그인 저장소는 공개다. 서버 주소·토큰은 코드에 넣지 않고 설정 파일·환경변수에서 읽는다 | △ (비밀 패턴 검사) |
| TS-SECRET-2 | 연구원용 배포물에는 **관리자 경로를 넣지 않는다**(관리자 세션·백엔드 DB·운영 봇이 필요한 명령). 운영 기능은 별도 패키지로 나누고, 코어가 그 패키지를 import하지 않게 한다 | 문서 |
| TS-SECRET-3 | private 원본에서 공개·공유 배포물을 만들 때는 **allow-list**로 넣을 것만 적고(deny-list 금지), **누수 검사 CI**(금지 패턴·명령 목록 대조)를 둔다. 공개할 수 없는 도구는 원내 배포 위치에서 받게 한다(README "gw") | 문서 (원본 저장소 CI) |

근거: jeju-inst/ji-gw-ai#112(운영 명령 분리), jeju-inst/ji-gw-ai#113(allow-list 내보내기 + 누수 검사 CI), `docs/handoff/README.md` 공통 규칙 6.

### TEST — 테스트 격리

| ID | 규칙 | 검사 |
|---|---|---|
| TS-TEST-1 | 테스트는 **실제 데이터·설정 폴더에 쓰지 않고, 실제 자격증명을 읽지 않는다.** 설정·데이터 폴더를 환경변수로 바꿀 수 있게 하고(예: `JI_GW_CONFIG_DIR`), 테스트 conftest가 tmp로 돌린다. 환경에 이미 있는 토큰 변수는 지운다 | 문서 |
| TS-TEST-2 | 실제 폴더 쓰기는 **가드로 막는다**(테스트 중 보호 폴더에 쓰면 실패). 격리를 빠뜨린 테스트가 조용히 실제 데이터를 건드리지 않게 하기 위해서다 | 문서 |
| TS-TEST-3 | 테스트가 PATH의 실제 외부 프로그램(예: `hwp2pdf-cli`)이나 이 머신에 저장된 토큰(예: `%LOCALAPPDATA%`)을 집어 쓰지 않게 막는다. 외부 프로그램은 가짜 실행 파일로 바꾼다(POSIX는 shebang 스크립트, Windows는 `.cmd` 심) | 문서 |

근거: jeju-inst/ji-gw-ai#112(데이터 폴더 가드), jeju-inst/ji-gw-ai#121(설정 폴더·자격증명 격리), z0nam/hwp-agent#71(가짜 CLI, `LOCALAPPDATA` 격리).

### ACCEPT — 인수 시험

| ID | 규칙 | 검사 |
|---|---|---|
| TS-ACCEPT-1 | `docs/acceptance-tests.md`에 그 도구의 **실제 업무 시나리오를 1건 이상** 넣는다. 시나리오마다 통과 기준을 적고, 채널 칸(DC·DK·CC·CX·HS)을 둔다. 단위 테스트·CI가 통과해도 실제 서식·실제 계정으로 안 되면 실패다 | △ (도구 이름이 문서에 있는지) |

근거: `docs/acceptance-tests.md`.

### STEPS — 사용자 단계

| ID | 규칙 | 검사 |
|---|---|---|
| TS-STEPS-1 | 연구원이 **직접 해야 하는 단계**를 편입 PR에 목록으로 적는다(예: 앱 재시작, 로그인, SmartScreen "추가 정보 → 실행", 원내망 접속). 목록이 비어야 이상적이고, 남은 단계는 이유를 붙인다 | 문서 |
| TS-STEPS-2 | 사용자가 할 일이 생기면 화면에 **고치는 방법 한 줄**을 낸다(예: `jaix doctor`의 안내 줄). 오류 메시지만 남기지 않는다 | 문서 |

근거: `docs/acceptance-tests.md` 0-1·0-3, README SmartScreen 절.

### CHANNEL — 사용 채널

| ID | 규칙 | 검사 |
|---|---|---|
| TS-CHANNEL-1 | 편입 PR에 채널별 동작 여부를 표시한다: **DC** Desktop Cowork, **DK** Desktop Code 탭, **CC** Claude Code CLI, **CX** Codex, **HS** Hermes + 슬랙. 각 칸은 ✅ 확인 / ⚠️ 우회로 됨 / ❌ 안 됨 / 미확인 / — 해당 없음 | 문서 |
| TS-CHANNEL-2 | **Desktop·Cowork(DC)는 관리자 배포 대상이다.** 데스크톱 앱은 사용자 `settings.json`의 마켓플레이스를 읽지 않고 계정 단위 조직 플러그인에서 받는다. jaix는 DK·CC·CX(·HS)만 등록한다. DC에서의 동작은 관리자 콘솔 배포 뒤에 확인한다 | 문서 |

근거: jeju-inst/jaix-kit#19(Desktop은 settings.json 마켓플레이스를 안 읽음), `docs/acceptance-tests.md` 채널 약어.

### INSTALLER — 설치기

| ID | 규칙 | 검사 |
|---|---|---|
| TS-INSTALLER-1 | 도구 저장소에 설치기(Inno Setup 등)가 있으면, CI가 **설치기나 그 워크플로를 바꾸는 PR에서** 빌드한 설치기를 **무인 설치 → `<tool> --version` → 무인 제거**까지 돌린다. 버전 찍기·게시 단계는 태그에서만 돈다 | △ (워크플로에 스모크 단계·`pull_request` 트리거가 있는지) |
| TS-INSTALLER-2 | 설치기는 사용자 범위로 설치한다. 관리자 권한·시스템 PATH·재부팅을 쓰지 않는다 | 문서 |

근거: z0nam/hwp-agent#73(스모크가 `{userprofile}` 버그를 재현·검출), z0nam/hwp-agent#74(PR 트리거), jaix-kit `jaix-setup.yml`(무인 설치·doctor·제거).

---

## 4. 새 도구 편입 체크리스트

작업 세션은 아래를 **PR 본문 끝에 그대로 붙이고** 채운다. 해당 없는 항목은 `—`와 이유를 적는다. 확인하지 못한 항목은 체크하지 말고 "미확인"과 이유를 적는다.

```markdown
### JAIX 편입 체크리스트 (docs/tool-standard.md)
- [ ] TS-FORMAT-1-4 플러그인 루트(`/` 또는 `<subdir>/`): plugin.json(version 없음) · skills/<name>/SKILL.md · .mcp.json
- [ ] TS-VER-2·3 저장소 루트 calver.yml, calver-tag.yml @<40자 SHA>
- [ ] TS-LOCK-1·2 잠금 entry: https url + 40자 sha (jaixlock.py check 통과)
- [ ] TS-MCP-1 uvx --python 3.12 고정 / — (MCP 없음)
- [ ] TS-MCP-4 실제 .mcp.json 명령으로 initialize·tools/list 응답 (맥: _ / Windows: _)
- [ ] TS-SKILL-1·2 호스트 중립, 스킬 기준 상대 경로(path/to 없음)
- [ ] TS-TOKEN-1 상시 분량: ___ 토큰 (≤3k)
- [ ] TS-TOKEN-2 호출당 최대: ___ 토큰 (≤10k, 워크플로: ___)
- [ ] TS-WIN-1 bash 전용 스크립트: 없음 / 목록: ___
- [ ] TS-WIN-2·3 한글·공백 경로, cp949 출력 확인
- [ ] TS-RUNTIME-1 선언한 런타임: ___ (jaix setup이 미리 설치하는지 확인)
- [ ] TS-SECRET-1-3 비밀 없음 · 관리자 경로 없음 · (private 원본이면) allow-list + 누수 검사
- [ ] TS-TEST-1-3 테스트가 실제 데이터·설정·자격증명·외부 프로그램을 쓰지 않음
- [ ] TS-ACCEPT-1 docs/acceptance-tests.md 시나리오: #___
- [ ] TS-STEPS-1 사용자가 직접 할 단계: 없음 / ___
- [ ] TS-CHANNEL-1 DC _ · DK _ · CC _ · CX _ · HS _
- [ ] TS-INSTALLER-1 설치기 스모크(PR 트리거) / — (설치기 없음)
```
