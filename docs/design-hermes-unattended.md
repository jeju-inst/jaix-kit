# 설계: jaix-setup의 Hermes 무인 설치와 슬랙 토큰 경로

상태: **설계안, 사용자 승인 전.** 비밀(슬랙 토큰)이 오가는 설계라 구현은 승인 뒤에 한다.
요청: jaix-kit-dev 2026-10-30. 사용자 결정은 "jaix가 무인 설치", 목표는 11/5-6이다.

## 1. 범위

jaix-setup에서 **슬랙으로도 쓰기(Hermes)** 를 고르면 다음을 마법사 없이 한다.

| 항목 | 정한 값 |
|---|---|
| Hermes 본체 | 공식 `install.ps1`을 비대화형으로 실행: `-NonInteractive -SkipBrowser -SkipComputerUse` |
| 모델 | 각자의 ChatGPT 구독(`openai-codex`, 기기 코드) 또는 Claude 구독(`anthropic`, OAuth). Nous Portal은 쓰지 않는다 |
| Computer Use·브라우저 조작 | 끈다: 설치 단계에서 받지 않고(`-SkipBrowser -SkipComputerUse`), `config.yaml`의 `platform_toolsets.cli` 목록에서 `browser`·`computer_use`를 뺀다. 슬랙은 프리셋 `hermes-slack`에 browser가 들어 있어 프리셋 대신 목록을 명시한다(아래 §3.4) |
| Nous 기본값 | 마법사에서 Nous가 기본값인 화면 셋(모델·이미지·검색, Q9)을 jaix가 설정으로 미리 정한다: 모델은 고른 구독, 이미지는 그 구독, 웹 검색은 끔. Nous Portal 인증은 붙이지 않는다 |
| MCP | `import-agent`를 쓰지 않는다. jaix가 Codex에 써 둔 jaix 항목만(`codex.owned_mcp()`) Hermes `config.yaml`의 `mcp_servers`에 병합한다(백업 후) |
| gateway | UAC 없이 시작프로그램 vbs로 둔다(`hermes gateway install --start-now --start-on-login`, 아래 §3.3) |
| 슬랙 앱 | 관리자 대리 생성(z0nam/hermes-slackbot#15 `provision_app.py`)이 만든 `Hermes-<id>` |

범위 밖: 맥 Hermes 무인 설치, 채널 대화 권한 확대, 슬랙 앱 생성 자동화(관리자 쪽은 #15 그대로).

## 2. 비밀은 세 종류다

| 비밀 | 만드는 곳 | 머무는 곳 | 연구원 PC에 오나 |
|---|---|---|---|
| ① 앱 설정 토큰(refresh `xoxe-…`, access 12시간) | 관리자가 api.slack.com에서 발급 | **관리자 맥 키체인**(#15 `token set`) | **안 온다** |
| ② 봇 토큰 `xoxb-…`(사람별) | 관리자가 `Install to Workspace` 할 때 슬랙이 발급 | 슬랙 앱 설정 화면(OAuth & Permissions) | 온다 |
| ③ 앱 수준 토큰 `xapp-…`(사람별, `connections:write`) | 관리자가 앱 설정 화면에서 발급 | 슬랙 앱 설정 화면(Basic Information) | 온다 |
| ④ 모델 로그인(ChatGPT·Claude OAuth) | 연구원 본인이 브라우저에서 승인 | Hermes `auth.json`(Hermes가 관리) | 본인 PC에서 생긴다 |

비밀이 아닌 값: 아이디(`<id>`, 앱 이름 `Hermes-<id>`), 연구원의 슬랙 멤버 ID(`U…`). 두 값은 관리자 레지스트리(`~/.config/hermes-slackbot/apps.json`, 관리자 맥, 저장소 밖)에 있다.

**관리자 자격(①)은 jaix·연구원 PC·공개 저장소 어디에도 들어가지 않는다.** jaix는 ①을 읽거나 쓰는 코드를 갖지 않는다.

## 3. 경로

### 3.1 ②③이 연구원 PC에 들어가는 길 — #15 원칙을 그대로 따른다

#15는 "토큰을 메시지·메일로 주고받지 않는다. 관리자가 연구원을 그 앱의 Collaborator로 추가하고, 연구원이 자기 브라우저에서 직접 복사한다"로 정했다. 이 설계도 이 원칙을 바꾸지 않는다.

```
관리자 맥                          슬랙                          연구원 PC
provision_app.py create ──▶ 앱 Hermes-<id> 생성·설치
  (① 키체인에서 회전)            ②③ 발급, 연구원=Collaborator
  출력: 연결 코드 "<id>:U…"   ─(비밀 아님, 방문 메모·DM 가능)─▶ jaix-setup 화면에 입력
                                  │
                         연구원 브라우저(본인 슬랙 로그인)
                                  └─ ②③ 복사 ─────────────▶ jaix-setup 화면의 숨김 칸 2개에 붙여넣기
```

- 관리자→연구원으로 가는 것은 **연결 코드(아이디 + 멤버 ID)뿐**이고, 비밀이 아니다. ②③은 관리자 손을 거쳐 전달되지 않는다.
- 연구원이 하는 일은 붙여넣기 두 번이다. 무인 설치는 "마법사 단계가 없다"는 뜻이다. 사람별 비밀을 받는 일은 남는다. 이것을 없애려면 관리자가 ②③을 PC에 놓아야 하는데, 그러면 #15 원칙과 부딪힌다(§6 판단 2).

### 3.2 설치기 → jaix → Hermes, PC 안에서 비밀이 거치는 곳

1. **설치기 화면**(Inno Setup 사용자 페이지): 연결 코드 칸 1개와 숨김(password) 칸 2개(`xoxb-`, `xapp-`)를 둔다. 접두사가 맞는지만 확인한다.
2. **설치기 → jaix**: 명령줄(argv)에 싣지 않는다. 프로세스 목록과 설치 로그(`SetupLogging`)에 남기 때문이다.
   - 설치기가 `%LOCALAPPDATA%\jaix\pending\slack.json`(사용자 프로필 아래, 상속 ACL = 본인·SYSTEM·Administrators)에 쓴다. 이어서 `jaix setup --hermes-secrets <그 경로>`를 부르고, jaix는 **읽자마자 파일을 지운다**. 실패해도 설치기 `ssPostInstall` 끝에서 한 번 더 지운다.
   - Inno 설치 로그에는 경로만 남고 값은 남지 않는다(`Log`에 값을 넘기지 않는다). jaix `--log`·진행 줄도 값을 찍지 않는다. 시험으로 막는다(§5).
3. **jaix가 확인**: `auth.test`(봇이 `Hermes-<id>`인지), `apps.connections.open`(Socket Mode가 열리는지). #15 `setup_pc.py`와 같은 검사다.
4. **저장**(§4): Hermes가 읽는 곳에 쓴다.
5. **gateway 등록·재시작**, 그리고 `gateway.log`에서 `slack connected`와 슬래시 핸들러가 뜨는지 기다린다(#15의 표지 그대로).

무인 설치(`/VERYSILENT`)에서는 `/HERMESSECRETS=<파일>`로 같은 파일을 넘긴다. CI는 가짜 토큰으로 "검증 실패 → 파일 지워짐 → 값이 로그에 없음"만 본다.

### 3.3 gateway: UAC 없이 시작프로그램

Hermes `gateway_windows.install()`(맥 소스 2026-10-13 확인. jaix-win Q9 실측 v0.22.5와 일치)의 동작은 다음과 같다.

- 관리자가 아니면 먼저 "UAC 창을 열까요?"(기본값 **아니오**)를 묻는다. 입력이 막힌 실행(비대화형)이면 기본값을 쓴다.
- 그다음 **시작프로그램 폴더 vbs**(`…\Startup\Hermes_Gateway*.vbs`)로 대체 등록한다. 예약 작업이 이미 있으면 vbs를 만들지 않는다(두 번 뜨는 것 방지).

jaix-win Q9(10-28·29, jaix-test): 마법사에서 UAC에 No를 고르자 "Falling back to Startup folder"가 나왔다. 그 결과 `%APPDATA%\…\Startup\Hermes_Gateway.vbs`가 생겼다. 이 vbs는 `%LOCALAPPDATA%\hermes\gateway-service\Hermes_Gateway.vbs`를 창 없이 실행한다. 재부팅 뒤 이 경로로 gateway가 뜨는 것까지 확인했다. 그 vbs가 `VIRTUAL_ENV=…\hermes\tools`를 넣기 때문에 `--python` 없는 uvx가 3.14를 고른다(#45). jaix가 넣는 MCP 항목에는 이미 `--python 3.12`가 있다(#47).

그래서 jaix는 표준 입력을 닫고 `hermes gateway install --start-now --start-on-login`을 부른다. UAC 창은 뜨지 않는다. doctor는 vbs 존재, gateway 프로세스, `gateway.log`의 `slack connected`를 본다.

### 3.4 Hermes 설정(무인 설치가 대신 정하는 값)

`hermes setup` 마법사(Q9 실측 15개 화면)를 돌리지 않는다. 대신 jaix가 `hermes config set`과 `config.yaml` 병합(백업 후)으로 다음을 정한다.
- 모델 공급자: 설치기에서 고른 구독(ChatGPT → `openai-codex`, Claude → `anthropic`). 로그인은 `hermes auth add openai-codex`(기기 코드: 브라우저에서 코드 입력) 또는 `hermes auth add anthropic --type oauth`를 띄운다. 브라우저 승인 한 번은 사람이 한다.
- 이미지: 같은 구독. 웹 검색: 끔. TTS: 기본(Edge). 원격 수집(telemetry): 끔.
- `platform_toolsets.cli`: Q9의 현재 목록에서 `browser`·`computer_use`를 뺀 것.
- `platform_toolsets.slack`: 프리셋 `hermes-slack` 대신 그 구성(terminal, file, web, vision, image, tts, skills, todo, cronjob, messaging)에서 `browser`를 뺀 목록. web은 검색을 끄면 의미가 없으므로 실측 뒤 정한다.
- MCP: `import-agent`는 항목을 고를 수 없고(Q9 ⑤) 기존 항목도 갱신하지 않는다. 그래서 jaix가 `mcp_servers`에 jaix 항목만 직접 쓴다. 이미 있는 같은 이름 항목은 jaix가 쓴 것(소유 기록)일 때만 바꾼다.

## 4. 저장 위치 — Hermes는 `.env` 평문만 읽는다

확인한 사실: Hermes는 슬랙 토큰을 `HERMES_HOME\.env`(Windows `%LOCALAPPDATA%\hermes\.env`)에서 읽는다. 자격 증명 관리자·DPAPI·keyring에서 슬랙 토큰을 읽는 코드는 없다. `.env` 값은 이미 있는 환경 변수보다 우선하고, `.env`에 없는 키는 물려받은 환경 변수를 쓴다. 모델 로그인(④)도 Hermes가 `auth.json`에 평문으로 둔다.

| 안 | 저장 | 장점 | 단점 |
|---|---|---|---|
| **A (권장)** | Hermes 표준대로 `.env`에 ②③과 `SLACK_ALLOWED_USERS=<U…>`를 쓴다. 기존 `.env`는 병합하고 백업한다 | Hermes 업데이트·`hermes gateway setup`·#15 문서와 같은 상태다. 유지 부담이 없다. ④와 보호 수준이 같다 | 같은 Windows 사용자로 도는 프로그램은 읽을 수 있다(사용자 프로필 ACL만 있음) |
| B | ②③을 **자격 증명 관리자**(DPAPI로 사용자 키 암호화, `CredWriteW`, 대상 `jaix/hermes-slack/<id>`)에 두고 `.env`에서는 뺀다. 시작프로그램 vbs 대신 jaix 실행기(`jaixw.exe hermes-gateway`)가 자격 증명을 읽어 환경 변수로 넘기고 gateway를 띄운다 | 디스크에 평문이 없다. 백업·동기화 폴더로 새지 않는다 | Hermes의 시작 경로를 jaix가 대신하므로 `hermes gateway restart`·`hermes update`가 vbs를 다시 만들면 토큰 없이 뜬다. Hermes 판마다 맞춰야 한다. 같은 사용자 권한의 프로그램은 `CredReadW`로 여전히 읽을 수 있어 실익이 작다 |

권장은 A다. 근거: 같은 사용자 권한의 악성 프로그램 앞에서는 A·B 모두 비밀을 지키지 못한다. B는 "디스크 평문 없음"만 더하고, Hermes 시작 경로를 가로채는 유지 부담을 진다. A를 쓰면서 보완하는 것:
- `.env` 상속 ACL을 확인하고, 다른 사용자에게 읽기 권한이 있으면 doctor가 [주의]로 알린다.
- doctor·로그·안내문에 토큰 값을 찍지 않는다(앞 4자 + 길이만).
- 폐기 경로: 관리자가 앱 설정에서 토큰을 재발급하면 PC의 값은 즉시 무효가 된다. 연구원이 퇴사하거나 PC를 바꾸면 관리자가 `Revoke`하면 된다(#15 문서 4번에 덧붙임).

## 5. 공개 저장소에 아무것도 남지 않는다는 근거

| 저장소 | 들어가는 것 | 비밀·식별자 |
|---|---|---|
| jeju-inst/jaix-kit(공개) | 설치기 화면, `jaix setup --hermes-secrets` 처리 코드, 이 문서 | 없음. 토큰·멤버 ID·채널 ID·아이디 목록을 넣지 않는다 |
| z0nam/hermes-slackbot(공개) | `setup_pc.py` 비대화형 입력(§7) | 없음(#15 이미 같은 규칙. 레지스트리는 관리자 맥 `~/.config`) |
| 릴리스 산출물(`jaix-setup.exe`) | 위 코드 | 없음. 사람별 값은 실행 때 화면에서 받는다 |

막는 장치:
1. 테스트에서 가짜 토큰(`xoxb-TEST…`)으로 setup을 돌린 뒤 setup.log·Inno 로그·stdout에 그 문자열이 없는지, pending 파일이 지워졌는지 확인한다.
2. CI에 `xox[abpe]-`·`xapp-` 패턴 grep 검사를 둔다. 테스트용 가짜 접두사(`xoxb-TEST`)만 허용한다.
3. 비밀은 argv·환경 변수(설치기→jaix 구간)·로그 어디에도 싣지 않는다.

## 6. 사용자가 판단할 것

1. **저장 위치 A(`.env`, 권장) / B(자격 증명 관리자 + jaix 실행기)**.
2. **②③ 전달: 연구원이 직접 붙여넣기(권장, #15 원칙 유지)** / 관리자가 PC에 놓기(완전 무인이지만 #15 원칙을 바꿔야 하고, 관리자→PC 전달 경로를 따로 설계해야 함).
3. **gateway 등록 실패 처리**: #15 `setup_pc.py`는 경고만 하고 넘어간다. 무인에서는 **실패로 처리하고 doctor에 보이기**를 권장한다(설치기는 나머지 채널을 그대로 둔다).

## 7. hermes-slackbot 쪽 수정(승인 뒤 그 저장소에서 PR)

hermes-slackbot-b2 확인(10-30): 진행·예정 작업 없음, 겹치지 않는다. #15는 아직 실제 Slack API·Windows에서 돌린 적이 없다(11월 초 첫 설치 때 확인 예정). 이 설계는 그 미검증 상태를 전제로 한다.

- `setup_pc.py`에 `--secrets-file <path>`(읽고 지움), `--replace`(기존 토큰 덮어쓰기), `--yes`(봇 이름 불일치 시 계속)를 넣는다. 대화형 입력 세 곳(`getpass` 2번, `input` y/N 2번)을 플래그로 넘긴다. 토큰은 argv로 받지 않는다.
- 안 B를 고르면 `CredReadW`를 ctypes로 읽는 경로를 넣는다(stdlib만 사용).
- jaix는 `setup_pc.py`를 잠금에 고정한 커밋으로 받아 부른다. 같은 로직을 jaix에 다시 쓰지 않는다.

## 8. 확인 못 한 것(구현 전 실기 항목)

- `install.ps1 -NonInteractive -SkipBrowser -SkipComputerUse`의 표준 사용자 실행: 시간(이전 실측 14분·2.9GB), Defender 반응.
- 표준 입력이 막힌 `hermes gateway install`이 실제로 UAC 없이 vbs로 가는지. 소스상 그렇지만 Windows 실측이 없다.
- `platform_toolsets`에서 `browser`·`computer_use`를 뺀 뒤 실제로 도구가 안 실리는지(Q9는 파일 확인만 함). Claude 구독 로그인(Q9 미시험).
- 모델 로그인은 브라우저 승인이 필요해 완전 무인이 안 된다. 설치기 마지막에 고른 구독의 `hermes auth add …` 창을 띄운다(ChatGPT는 기기 코드 화면, Q9에서 마법사 안 흐름으로 확인).

작성: 조남운 · claude/jaix-setup · 2026-10-30
