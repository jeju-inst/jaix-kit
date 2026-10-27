# jaix-kit — 제주연구원 JAIX 원내 AI 도구 배포 허브

연구원 PC에 원내 AI 도구(hwp-agent, 업무일지, 그룹웨어 등)를 **한 번에 깔고, 검증된 버전으로 함께 올리는** 저장소.
도구 코드는 각자의 저장소에 있다. 여기는 "어느 도구의 어느 버전을 같이 쓰는가"만 정한다.

## 무엇이 들어 있나
| 파일 | 역할 |
|---|---|
| `.claude-plugin/marketplace.json` | **잠금 목록(lockfile)**. 도구마다 저장소 + 태그 + 40자 커밋으로 고정. Claude 마켓플레이스 형식 그대로 |
| `src/jaix/` | `jaix` CLI(setup · doctor · update). 아래 절 참고 |
| `scripts/jaixlock.py` | `check`(고정 상태 점검) · `bump NAME REF`(수동 고정) · `update`(새 날짜 태그·커밋으로 전부 올리기) |
| `.github/workflows/ci.yml` | Windows·Linux 새 머신에서 전 플러그인 설치 시험 + 매일 태그 감시 |
| `.github/workflows/calver-tag.yml` | 재사용 워크플로. 도구 저장소가 main 머지마다 불러 날짜 태그를 단다 |
| `.github/workflows/lock-update.yml` | 갱신 봇. 매일 새 버전을 찾아 beta 갱신 PR과 beta → main 승격 PR을 연다 |
| `.github/workflows/bundle-tag.yml` | main 잠금·설치본이 바뀔 때마다 묶음 날짜 태그 → `jaix-setup.yml` 빌드 호출 |
| `.github/workflows/jaix-setup.yml` | `jaix.exe`·`jaix-setup.exe` 빌드, 무인 설치·doctor·제거 시험, 태그 릴리스 |

## 채널
- `main` = **stable** (전원). 관리자 콘솔이 이 브랜치를 자동 업데이트로 배포한다.
- `beta` = AI센터 파일럿. 새 버전은 beta에서 먼저 굴린 뒤 main으로 PR.

## 사용 채널 3개 (모두 같은 잠금 목록을 따른다)
1. **데스크톱 앱** — Claude Desktop(Cowork·Code 탭), Codex/ChatGPT 데스크톱
2. **CLI** — Claude Code, Codex CLI
3. **Hermes Agent + 슬랙** — CLI를 못 쓰는 사용자용 개인 봇

## 버전: 전부 날짜 버전, 사람은 번호를 매기지 않는다
- 도구도 묶음도 `vYYYY.MM.DD.N`(KST, 같은 날 N번째). 숫자는 "언제 나온 것인가"만 뜻한다.
- 도구 간 호환은 번호로 약속하지 않는다. **잠금 목록 + CI 조합 시험**이 보장한다.
- 도구 `plugin.json` 에는 `version` 을 두지 않는다. 잠금 entry 의 `version` 이 유일한 표기다
  (Claude 는 plugin.json version 을 먼저 봐서, 거기 고정값이 남아 있으면 업데이트를 못 알아챈다).
- 아직 날짜 태그가 없는 도구는 브랜치 head 커밋으로 고정하고 version 을 비운다(Claude 가 sha 로 판단).

## 새 버전이 퍼지는 길 (사람은 PR 두 개 승인만)
1. 도구 저장소 main 에 머지 → `calver-tag` 가 태그를 단다. 도구 저장소에 넣을 것:
   ```yaml
   # .github/workflows/calver.yml
   on: { push: { branches: [main] } }
   concurrency: calver-tag
   jobs:
     tag:
       uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@<jaix-kit 커밋 40자 SHA>
       permissions: { contents: write }
   ```
   - `@main` 이 아니라 **커밋 SHA로 고정**한다. 다른 저장소 코드가 그 저장소의 태그 권한을 쥐기 때문이다. 올릴 때는 PR로.
2. 매일 06:30 KST 갱신 봇이 새 태그를 찾아 **beta 갱신 PR**(`bot/lock-update` → `beta`)을 열고 CI를 돌린다.
   → AI센터가 머지하면 파일럿 반영.
3. beta 잠금이 main 과 다르면 봇이 **승격 PR**(`beta` → `main`)을 연다. 파일럿에서 문제없으면 머지
   → 전원 자동 반영(다음 앱 시작 때) + 묶음 태그.
- 급할 때: Actions 탭에서 `lock-update` 를 수동 실행하거나, `python scripts/jaixlock.py bump <plugin> <tag>` 로 PR.
- 되돌리기: 승격 PR 을 revert 하면 이전 잠금으로 돌아간다(도구 태그는 지우지 않는다).

## `jaix` CLI — 설치·점검·갱신 (`src/jaix/`)
연구원 PC에서는 설치 프로그램 **`jaix-setup.exe`**(https://github.com/jeju-inst/jaix-kit/releases/latest/download/jaix-setup.exe, 관리자 권한 불필요)가 이것을 부른다.
### 처음 실행할 때 "Windows의 PC 보호" 창이 뜨면
설치 파일에 아직 코드 서명이 없어서 SmartScreen이 막을 수 있다. 창에서 **추가 정보** → **실행**을 누른다.

<!-- 스크린샷 자리: jaix-win 실기(namun-ji) 때 ① 첫 경고 창 ② "추가 정보"를 누른 뒤 "실행" 버튼이 보이는 창 두 장을 docs/img/ 에 넣고 여기 링크한다 -->
_(화면 예시는 실기 시험 뒤 추가)_

설치본은 채널 체크박스(Claude · Codex · 슬랙[다음 버전])만 받아 `jaix setup --channels …` 에 넘기는 껍데기다(`installer/jaix-setup.iss`).
묶음 태그가 새로 달리면 `jaix-setup.yml` 이 Windows 러너에서 빌드 → 무인 설치 → `jaix doctor` → 제거까지 시험하고 그 태그의 릴리스로 올린다. 개발자는 `uv tool install git+https://github.com/jeju-inst/jaix-kit` 로 같은 명령을 쓴다.

| 명령 | 하는 일 |
|---|---|
| `jaix setup [--channels claude,codex,hermes] [--runtimes …\|all\|none]` | 런타임(uv·Git·JRE 21·hwp2pdf-cli, 선택 himalaya·age)을 사용자 범위로 설치(winget → 포터블 `%LOCALAPPDATA%\Programs\jaix`) · Claude 사용자 설정에 마켓플레이스+`autoUpdate`+플러그인 **병합**(쓰기 전 백업) · Codex 마켓플레이스 등록·설치 |
| `jaix doctor [--json]` | 런타임 버전·사용자 PATH·마켓플레이스 등록·플러그인 버전이 잠금과 맞는지. 어긋나면 고치는 방법 한 줄. 실패가 있으면 종료 코드 1 |
| `jaix update` | 런타임 갱신 + Claude·Codex 플러그인과 Hermes 스킬 폴더를 잠금에 맞춤 |
| `jaix update --quiet` | 같은 일을 화면 없이. `jaix setup` 이 등록한 **로그온 자동 갱신**이 부르고, 결과는 `update.log`·`update-status.json` 에 남아 `jaix doctor` 가 보여 준다 |

- 잠금은 GitHub `main`(stable) 또는 `--channel beta` 에서 읽고, 못 받으면 실행파일에 묶은 사본을 쓴다. jaix 는 잠금을 고치지 않는다.
- **gw(그룹웨어)** 는 라이선스상 공개 저장소에 넣지 않고 원내 위치에서 받는다(ji-gw-ai#108 Q2). 위치가 정해지기 전이라 `jaix setup --gw-source <URL>` 자리만 있다 — 원내망이 아니면 gw만 건너뛰고 doctor가 안내한다.
- **uv 관리 Python 미리 설치**: Claude Desktop(Windows MSIX)이 띄운 `uvx` 가 Python을 처음 받으면 `%APPDATA%\uv\python` 쓰기가 MSIX 가상화로 앱 안에만 생기고 uv 정션이 깨져 플러그인 MCP(hwp-agent 등)가 오류 없이 안 뜬다(#14). 그래서 `jaix setup`·`update` 가 앱 밖에서 `uv python install` 을 해 둔다 — 버전은 잠금 플러그인 `.mcp.json` 의 `--python` 고정 + 기본 3.12. doctor가 있는지와 가상화 흔적(`Packages\Claude_*\LocalCache\Roaming\uv`)을 점검한다.
- **로그온 자동 갱신**: Claude는 마켓플레이스 `autoUpdate` 로 저절로 갱신되지만 Codex·Hermes는 그런 장치가 없다. 그래서 `jaix setup` 이 로그온마다 `jaix update --quiet` 를 도는 사용자 범위 예약 작업을 둔다 — Windows 작업 스케줄러 `jaix-update`(이 사용자 로그온 트리거, 일반 권한, 2분 지연), macOS LaunchAgent `kr.re.ji.jaix.update`. 실패하면 다음 로그온에 다시 하고 doctor가 [주의]로 보인다. 설치본을 제거하면(`jaix cleanup`) 함께 지운다. 끄려면 `jaix setup --no-autoupdate`.
- 관리자 콘솔(managed settings)이 jaix 마켓플레이스를 이미 내려주면 사용자 설정 등록은 건너뛴다.
- 관리자 권한·시스템 PATH·재부팅을 쓰지 않는다. 시험은 `CLAUDE_CONFIG_DIR`·`CODEX_HOME`·`JAIX_HOME`·`HERMES_HOME` 으로 격리한다.

## 수동 설치 (관리자 콘솔 배포 전·개발자용)
```
claude plugin marketplace add jeju-inst/jaix-kit
claude plugin install calendar-worklog-ji@jaix
```

설계 근거: `docs/design.md`, 상위 표준: `ji-deploy-standards`.
