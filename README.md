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
| `.github/workflows/jaix-setup.yml` | `jaix\`(onedir, `installer/jaix.spec`)·`jaix-setup.exe` 빌드, 무인 설치·doctor·제거 시험, 태그 릴리스 |

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
설치 파일에 코드 서명을 하지 않는다(비용 대비 효과가 낮아 하지 않기로 함). 그래서 SmartScreen이 막을 수 있다. 창에서 **추가 정보** → **실행**을 누른다. Windows 보안(Defender) 알림이 뜨면 허용하지 말고 AI센터로 연락한다.
연구원용 단계별 안내(그림 자리 포함)는 [`docs/install-guide.md`](docs/install-guide.md).

<!-- 스크린샷 자리: jaix-win 실기(namun-ji) 때 ① 첫 경고 창 ② "추가 정보"를 누른 뒤 "실행" 버튼이 보이는 창 두 장을 docs/img/ 에 넣고 여기 링크한다 -->
_(화면 예시는 실기 시험 뒤 추가)_

설치본은 채널 체크박스(Claude · Codex · 슬랙[다음 버전])만 받아 `jaix setup --channels …` 에 넘기는 껍데기다(`installer/jaix-setup.iss`).
묶음 태그가 새로 달리면 `jaix-setup.yml` 이 Windows 러너에서 빌드 → 무인 설치 → `jaix doctor` → 제거까지 시험하고 그 태그의 릴리스로 올린다. 개발자는 `uv tool install git+https://github.com/jeju-inst/jaix-kit` 로 같은 명령을 쓴다.

| 명령 | 하는 일 |
|---|---|
| `jaix setup [--channels claude,codex,hermes] [--runtimes …\|all\|none]` | 런타임(uv·Git·JRE 21·hwp2pdf-cli, 선택 himalaya·age)을 사용자 범위로 설치(winget → 포터블 `%LOCALAPPDATA%\Programs\jaix`) · Claude 사용자 설정에 마켓플레이스+`autoUpdate`+플러그인 **병합**(쓰기 전 백업) · Codex 마켓플레이스 등록·설치 |
| `jaix doctor [--json]` | 런타임 버전·사용자 PATH·마켓플레이스 등록·플러그인 버전이 잠금과 맞는지. 어긋나면 고치는 방법 한 줄. 실패가 있으면 종료 코드 1 |
| `jaix update` | 런타임 갱신 + Claude·Codex 플러그인과 Hermes 스킬 폴더를 잠금에 맞춤 |
| `jaix works login` | 웍스(NAVER WORKS) 브라우저 로그인, 처음 한 번. 잠금에 jaix-works 가 있으면 `jaix setup` 이 Node.js·nworks(버전·무결성 고정)를 깔고 기관 앱 정보를 원내 위치에서 받아 둔다(`docs/works.md`) |
| `jaix update --quiet` | 같은 일을 화면 없이. `jaix setup` 이 등록한 **로그온 자동 갱신**이 부르고, 결과는 `update.log`·`update-status.json` 에 남아 `jaix doctor` 가 보여 준다. Windows 에선 창 없는 `jaixw.exe` 로 돌아 콘솔 창이 뜨지 않는다 |

- 잠금은 GitHub `main`(stable) 또는 `--channel beta` 에서 읽고, 못 받으면 실행파일에 묶은 사본을 쓴다. jaix 는 잠금을 고치지 않는다.
- **gw(그룹웨어)** 는 라이선스상 공개 저장소에 넣지 않고 원내 위치에서 받는다(ji-gw-ai#108 Q2, 배포 형식 #122). `jaix setup`·`update` 가 `https://jaix.namun.net/gw/latest.json`(IP 게이트)을 읽어 wheel 을 받고 sha256 을 확인한 뒤 `uv tool install <wheel>` 한다. 설치된 버전이 배포 버전과 다르면(새 버전·롤백) 다시 깐다. 원내망이 아니면 gw만 건너뛰고 doctor가 안내하며, doctor는 설치된 `gw --version` 과 배포 버전을 비교한다. 주소는 `--gw-source <URL>`(설치본 `/GWSOURCE=`)로 바꾸고 `none` 이면 끈다. **jaix가 깔지 않은 gw**(개발용 `uv tool install -e` 한 ji-gw-ai, PATH 의 다른 gw)가 있으면 설치·갱신을 건너뛰고 "개발용 gw가 있어 건너뜀"으로 남긴다(status `foreign`, doctor 는 [생략]). 같은 패키지 이름이라 `uv tool install` 이 개발용 설치를 바꿔치기하기 때문이다. 덮어쓰기·`--force` 는 쓰지 않는다. jaix 것인지는 uv-receipt 의 요구 항목이 jaix가 받은 wheel(`<데이터 폴더>\gw\*.whl`)인지로 가린다.
- **이미 깔린 것과 겹침**(doctor, 읽기만): 있는 것을 쓸 수 있으면 그대로 쓰고, 같은 도구가 두 벌이면 알리기만 하고 지우지 않는다. ① jaix 플러그인이 깔린 호스트에 같은 도구가 또 있으면 [주의] — 다른 마켓플레이스의 같은 이름 플러그인, `~/.claude/skills`·`~/.codex/skills` 의 같은 이름 스킬(심링크 포함), `~/.claude.json`·Codex `config.toml` 에서 jaix가 쓰지 않은 같은 이름 MCP 서버. 같은 도구가 두 번 실려 토큰이 두 배로 든다. 이름은 대소문자·`_`·`-mcp` 꼬리를 맞춰 비교한다. ② PATH 에서 잡히는 `hwp-agent` 실행파일(단독 Inno 설치본 등)의 버전이 잠금과 다르면 [주의] — 스킬이 셸 명령으로 부를 때 그것이 잡힌다. ③ Claude·Codex 에 켜진 MCP 서버·스킬 수로 상시 분량을 어림해(MCP 하나 3k = TS-TOKEN-1 상한, 스킬 하나 150) 30k 를 넘으면 사용량 한도 위험을 한 줄로 알린다.
- **uv 관리 Python 미리 설치**: Claude Desktop(Windows MSIX)이 띄운 `uvx` 가 Python을 처음 받으면 `%APPDATA%\uv\python` 쓰기가 MSIX 가상화로 앱 안에만 생기고 uv 정션이 깨져 플러그인 MCP(hwp-agent 등)가 오류 없이 안 뜬다(#14). 그래서 `jaix setup`·`update` 가 앱 밖에서 `uv python install` 을 해 둔다 — 버전은 잠금 플러그인 `.mcp.json` 의 `--python` 고정 + 기본 3.12. doctor가 있는지와 가상화 흔적(`Packages\Claude_*\LocalCache\Roaming\uv`)을 점검한다.
- **로그온 자동 갱신**: Claude는 마켓플레이스 `autoUpdate` 로 저절로 갱신되지만 Codex·Hermes는 그런 장치가 없다. 그래서 `jaix setup` 이 로그온마다 `jaix update --quiet` 를 도는 사용자 범위 예약 작업을 둔다 — Windows 작업 스케줄러 `jaix-update`(이 사용자 로그온 트리거, 일반 권한, 2분 지연), macOS LaunchAgent `kr.re.ji.jaix.update`. 작업은 반드시 **사용자가 로그온할 때만 실행**(대화형 세션)이다 — 세션 0(무인)에서는 한컴 COM이 뜨지 않는다(hwp-render 실측). doctor가 이 실행 모드도 점검한다. 실패하면 다음 로그온에 다시 하고 doctor가 [주의]로 보인다. 설치본을 제거하면(`jaix cleanup`) 함께 지운다. 끄려면 `jaix setup --no-autoupdate`.
- **Claude 데스크톱·Cowork 는 관리자 배포 대상이다**(#19 실측): 데스크톱 앱(Cowork)은 `settings.json` 의 `extraKnownMarketplaces` 를 읽지 않고 계정 단위 조직 플러그인에서 도구를 받는다. jaix 는 Code 탭·Claude Code 쪽만 등록·설치하고, Code 탭 실행파일은 `%LOCALAPPDATA%\Claude-Data\claude_*\claude-code\<버전>\…\claude.exe`(가장 높은 버전)에서 찾는다. doctor 는 잠금 대비 빠진 플러그인이 있으면 [실패]로 보인다.
- **HWP 변환기 jar 미리 받기**: hwp-agent 가 `hwp-agent setup` 으로 받는 `hwp2hwpx.jar` 를 같은 자리(`%LOCALAPPDATA%\hwp-agent`, 맥 `~/.local/share/hwp-agent`)에 미리 받는다. 주소·sha256 은 잠금이 고정한 hwp-agent 커밋의 `fetch_jar.py` 에서 읽는다.
- **HWP 미리보기 엔진(rhwp) 미리 받기**: 한글이 열려 있으면 hwp-agent 의 첫 렌더 엔진(hwp2pdf-cli)이 건너뛰므로, 서버 없는 PC의 미리보기는 rhwp([edwardkim/rhwp](https://github.com/edwardkim/rhwp), MIT)가 맡는다. `hwp-agent setup` 이 받는 자리(`%LOCALAPPDATA%\hwp-agent\rhwp`)에 바이너리와 LICENSE 를 미리 받는다. 버전·sha256 은 잠금이 고정한 hwp-agent 커밋의 `render/fetch_rhwp.py` 에서 읽고, 그 파일이 없는 옛 커밋이면 건너뛴다. 실패는 doctor 주의(미리보기 폴백이라 실패 아님).
- **폴더**: 프로그램은 `%LOCALAPPDATA%\Programs\jaix` — 실행파일(`jaix.exe`·`jaixw.exe`·`_internal`, PyInstaller onedir)은 그 아래 `jaix\`, 포터블 런타임은 `bin`·`git`·`jre`. 예전 onefile 설치본(실행파일이 바로 아래)을 덮어 설치하면 옛 실행파일과 그 PATH 항목을 정리한다(#46). 기록·상태(`setup.log`·`update.log`·`update-status.json`·소유 기록·gw wheel)는 `%LOCALAPPDATA%\jaix`(맥은 둘 다 `~/.local/share/jaix`). 설치본을 제거하면 프로그램 폴더만 지우고 기록 폴더는 남긴다 — Claude·Codex 설정에 넣은 항목을 남기므로 재설치 때 jaix가 쓴 항목을 알아보게. 예전 설치본이 프로그램 폴더에 둔 기록은 jaix가 처음 돌 때 옮긴다.
- 관리자 콘솔(managed settings)이 jaix 마켓플레이스를 이미 내려주면 사용자 설정 등록은 건너뛴다.
- 관리자 권한·시스템 PATH·재부팅을 쓰지 않는다. 시험은 `CLAUDE_CONFIG_DIR`·`CODEX_HOME`·`JAIX_HOME`·`JAIX_DATA`·`HERMES_HOME` 으로 격리한다.

## 수동 설치 (관리자 콘솔 배포 전·개발자용)
```
claude plugin marketplace add jeju-inst/jaix-kit
claude plugin install calendar-worklog-ji@jaix
```

## 새 도구를 넣을 때
도구 편입 표준은 [`docs/tool-standard.md`](docs/tool-standard.md)다. 형식·버전·잠금·MCP·Windows·토큰 예산 같은 규칙에 ID(`TS-…`)가 붙어 있고, 잠금 CI가 같은 ID로 검사한다. 편입 PR 본문 끝에 이 문서의 체크리스트를 붙인다.

설계 근거: `docs/design.md`. 상위 표준이던 `ji-deploy-standards`(v1)는 `docs/tool-standard.md`에 흡수했다.
