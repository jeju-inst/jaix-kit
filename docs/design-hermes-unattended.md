# 설계: jaix-setup의 Hermes 무인 설치와 슬랙 토큰 경로

상태: **설계안 2판, 사용자 승인 전.** 비밀(슬랙 토큰)이 오가는 설계라 구현은 승인 뒤에 한다.
요청: jaix-kit-dev 2026-10-30. 사용자 결정은 "jaix가 무인 설치", 목표는 11/5-6이다.

1판에 대한 사용자 답(10-30): ① 토큰 전달은 **관리자가 PC에 놓는다**(1판 권장안이던 연구원 본인 복사와 다름). ② 저장은 **A `.env`**. ③ gateway 등록 실패는 **설치 실패로 보고 doctor에 표시**한다. 2판은 ①에 맞춰 §3.1·§3.2·§5-§7을 고쳤다.

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
| 슬랙 앱 | 관리자 대리 생성(z0nam/hermes-slackbot#15 `provision_app.py`)이 만든 `Hermes-<id>`. 토큰은 관리자가 1회용 연결 코드로 PC에 놓는다(§3.1) |

범위 밖: 맥 Hermes 무인 설치, 채널 대화 권한 확대, 슬랙 앱 생성 자동화(관리자 쪽은 #15 그대로).

## 2. 비밀은 세 종류다

| 비밀 | 만드는 곳 | 머무는 곳 | 연구원 PC에 오나 |
|---|---|---|---|
| ① 앱 설정 토큰(refresh `xoxe-…`, access 12시간) | 관리자가 api.slack.com에서 발급 | **관리자 맥 키체인**(#15 `token set`) | **안 온다** |
| ② 봇 토큰 `xoxb-…`(사람별) | 관리자가 `Install to Workspace` 할 때 슬랙이 발급 | 슬랙 앱 설정 화면(OAuth & Permissions) | 온다(§3.1 1회용 연결 코드) |
| ③ 앱 수준 토큰 `xapp-…`(사람별, `connections:write`) | 관리자가 앱 설정 화면에서 발급 | 슬랙 앱 설정 화면(Basic Information) | 온다(같은 길) |
| ④ 모델 로그인(ChatGPT·Claude OAuth) | 연구원 본인이 브라우저에서 승인 | Hermes `auth.json`(Hermes가 관리) | 본인 PC에서 생긴다 |

비밀이 아닌 값: 아이디(`<id>`, 앱 이름 `Hermes-<id>`), 연구원의 슬랙 멤버 ID(`U…`). 두 값은 관리자 레지스트리(`~/.config/hermes-slackbot/apps.json`, 관리자 맥, 저장소 밖)에 있다.

**관리자 자격(①)은 jaix·연구원 PC·공개 저장소 어디에도 들어가지 않는다.** jaix는 ①을 읽거나 쓰는 코드를 갖지 않는다.

## 3. 경로

### 3.1 ②③이 연구원 PC에 들어가는 길 — 관리자가 놓는다

#### #15 원칙을 바꾸는 근거

#15는 "토큰을 메시지·메일로 주고받지 않는다. 관리자가 연구원을 그 앱의 Collaborator로 추가하고, 연구원이 자기 브라우저에서 직접 복사한다"로 정했다. 사용자가 10-30에 "관리자가 PC에 놓기"로 바꿨고, 근거는 다음과 같다.
- **연구원이 할 일이 너무 많다.** 본인 복사 방식이면 연구원이 api.slack.com 앱 설정 화면 두 곳(OAuth & Permissions, Basic Information)을 찾아가 긴 토큰 두 개를 복사해야 한다. 슬랙 개발자 화면을 처음 보는 비개발자에게는 이것이 설치에서 가장 어려운 단계다. 무인 설치의 목적과 맞지 않는다.
- **Collaborator 권한이 과하다.** Collaborator는 앱 설정(명령·권한·토큰 재발급)을 바꿀 수 있다. #15 문서도 "끝나면 빼 두라"고 적었다. 관리자가 놓으면 연구원을 Collaborator로 넣을 필요가 없다.
- **#15 원칙의 목적은 유지한다.** 목적은 "토큰이 평문으로 메시지·메일에 실리지 않는다"였다. 아래 권장안도 토큰을 슬랙 DM·메일에 싣지 않는다.

#### 후보 비교

| | (가) 1회용 연결 코드 — 원내 배포처 | (나) 암호화 묶음 파일(age 등) | (다) 관리자 원격 쓰기 | (라) 관리자 방문 입력 |
|---|---|---|---|---|
| 방식 | 관리자가 ②③을 studio의 jaix 배포처(`jaix.namun.net`)에 사람별로 맡긴다. 연구원은 1회용 코드 하나를 설치기에 넣고, jaix가 받아 간다 | 관리자가 사람별로 암호를 걸어 묶음 파일을 만든다. 연구원은 파일과 암호를 설치기에 넣는다 | 관리자가 원격 지원 도구·ssh로 PC에 들어가 `.env`에 쓴다 | 관리자가 PC 앞에서 붙여넣는다(#15 방문 절차에서 연구원 대신 관리자가 입력) |
| 평문이 지나가는 곳 | 관리자 맥(입력) → studio 배포처 임시 폴더(받아 가면 즉시 지움) → HTTPS → 연구원 PC `.env`. 슬랙·메일에는 코드만 실린다 | 관리자 맥 → (암호문이 어떤 경로로든) → PC. 암호를 따로 전해야 하는데, DM으로 보내면 파일과 암호가 같은 경로를 탄다 | 원격 세션(암호화)과 관리자 클립보드 | 관리자 클립보드 |
| 1회용·만료 | **1회용**(처음 받으면 서버에서 지움), **72시간 만료**, **원내 IP만** 받을 수 있음 | 파일은 복사되면 계속 열 수 있다. 만료 없음 | 해당 없음 | 해당 없음 |
| 연구원이 할 일 | 코드 1개 붙여넣기 | 파일 받기, 경로 고르기, 암호 입력 | 원격 접속 허용 | 자리 비켜 주기 |
| 관리자 작업량(수십 명) | 1인당 명령 하나(아래 `handoff`)와 코드 보내기. 원격으로 됨 | 1인당 파일 만들기와 암호를 따로 전하기 | 1인당 원격 접속 일정 잡기. 연구원 PC에 원격 지원 도구가 없다 | 1인당 방문 |
| 유출 시 | 코드를 남이 먼저 쓰면 연구원 설치가 "이미 사용됨"으로 실패하므로 **바로 안다** → 아래 폐기 절차 | 유출을 알 방법이 없다 | 낮음 | 낮음 |
| 새로 필요한 것 | 배포처 서버에 경로 하나(ji-gw-ai `share_server.py`), jaix 명령 둘 | 암호화 라이브러리(jaix는 지금 외부 의존성이 0개) | 원격 접속 수단 | 없음 |

**권장: (가) 1회용 연결 코드.** 연구원이 할 일이 가장 적고, 관리자 작업이 원격으로 끝나고, 유출을 알아챌 수 있는 유일한 안이다. 배포처는 이미 gw 배포용으로 원내 IP 게이트·접근 기록·Cloudflare Access 두 겹을 갖추고 있다(ji-gw-ai `docs/share-deploy.md`). (나)는 만료·1회용이 없고 암호를 따로 전하는 문제가 남는다. (다)·(라)는 수십 명 규모에서 관리자 시간이 너무 든다.

#### (가)의 흐름

```
관리자(studio)                           jaix.namun.net (studio, 원내 IP만)        연구원 PC
provision_app.py create <id> --user U…
  → 앱 생성·설치, xapp 발급(화면에서)
jaix hermes handoff <id> --user U…
  ②③을 숨김 입력으로 받음
  auth.test·apps.connections.open 확인
  코드 C = 128비트 난수(base32, 26자)
  spool/hermes/sha256(C).json  ─────▶  보관(0600, 72시간)
  출력: "JX-…" 코드 ──(슬랙 DM 가능: 1회용·원내 전용)──────────────────────────▶ 설치기 칸에 붙여넣기
                                                                                    jaix setup
                                         POST /hermes/handoff (본문에 C) ◀────────── HTTPS
                                         sha256(C)로 찾아 돌려주고 **즉시 지움** ──▶ ②③·id·U… 수신
                                         두 번째 요청 → 410 "이미 사용됨"            .env에 쓰기(§4)
```

- 서버는 코드 원문을 저장하지 않는다. 파일 이름은 `sha256(C)`다. 접근 기록에는 요청 시각·IP·결과(200/410/404)만 남고, 코드와 본문은 남지 않는다. 코드는 URL에 넣지 않고 POST 본문으로 보낸다. URL에 넣으면 Cloudflare·서버 기록에 남기 때문이다.
- 만료(72시간, `--ttl`로 조정)가 지난 묶음은 서버가 요청을 받을 때와 주기적으로 지운다.
- **평문이 디스크에 머무는 곳은 studio 임시 폴더(최대 72시간)뿐이다.** studio에는 이미 더 강한 비밀인 앱 설정 토큰 ①이 있다. ①은 모든 앱을 만들고 바꿀 수 있다. 그래서 ②③을 잠시 더 두는 것은 위험을 크게 늘리지 않는다. 디스크 암호화까지 하려면 jaix에 암호화 라이브러리 의존성이 생긴다. 이것은 하지 않는다(§6 판단 2).
- 코드를 슬랙 DM으로 보내는 것은 허용한다. 근거는 세 가지다. 코드는 토큰이 아니다. 원내 IP에서 한 번만 쓸 수 있다. 남이 먼저 쓰면 연구원 설치가 실패해서 드러난다. 다만 DM 기록에 남은 코드는 사용 뒤나 만료 뒤에는 쓸모가 없다.
- 폐기 절차(유출을 의심하거나 퇴사·PC 교체 때): 관리자가 앱 설정에서 ② *OAuth & Permissions → Revoke Tokens*, ③ *Basic Information → App-Level Tokens → Revoke*를 누른 뒤 재설치하고 `handoff`를 다시 한다. 급하면 앱을 지운다(봇이 즉시 멈춘다). PC에 남은 옛 값은 그 순간 무효가 된다.

### 3.2 설치기 → jaix → Hermes, PC 안에서 비밀이 거치는 곳

1. **설치기 화면**(Inno Setup 사용자 페이지): "슬랙 연결 코드" 칸 하나를 둔다(형식 `JX-` + 26자). 코드 자체도 1회용 비밀로 다룬다.
2. **설치기 → jaix**: 코드를 명령줄(argv)에 싣지 않는다. 프로세스 목록과 설치 로그(`SetupLogging`)에 남기 때문이다.
   - 설치기가 `%LOCALAPPDATA%\jaix\pending\hermes-code`(사용자 프로필 아래, 상속 ACL = 본인·SYSTEM·Administrators)에 쓴다. 이어서 `jaix setup --hermes-code-file <그 경로>`를 부르고, jaix는 **읽자마자 파일을 지운다**. 실패해도 설치기 `ssPostInstall` 끝에서 한 번 더 지운다.
   - Inno 설치 로그에는 경로만 남고 값은 남지 않는다. jaix `--log`·진행 줄도 코드·토큰을 찍지 않는다. 시험으로 막는다(§5).
3. **jaix가 받기**: 배포처에서 ②③·아이디·멤버 ID를 받는다. 410이면 "이미 사용된 코드 — AI센터에 연락", 404·만료면 "코드가 만료됨 — AI센터에 새 코드 요청", 원내망이 아니면 "원내망에서 다시"로 실패한다.
4. **jaix가 확인**: `auth.test`(봇이 `Hermes-<id>`인지), `apps.connections.open`(Socket Mode가 열리는지). #15 `setup_pc.py`와 같은 검사다.
5. **저장**(§4): Hermes `.env`에 ②③과 `SLACK_ALLOWED_USERS=<U…>`를 쓴다.
6. **gateway 등록·재시작**, 그리고 `gateway.log`에서 `slack connected`와 슬래시 핸들러가 뜨는지 기다린다(#15의 표지 그대로). **뜨지 않으면 설치 실패**로 보고(종료 코드 10) doctor가 [실패]로 보인다(사용자 결정 ③). Claude·Codex 채널은 그대로 둔다.

무인 설치(`/VERYSILENT`)에서는 `/HERMESCODEFILE=<파일>`로 같은 파일을 넘긴다. CI는 가짜 배포처(로컬 서버)로 "한 번 받기 → 두 번째 410 → 코드 파일 지워짐 → 값이 로그에 없음"을 본다.

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

## 4. 저장 위치 — `.env`(사용자 결정 A)

확인한 사실: Hermes는 슬랙 토큰을 `HERMES_HOME\.env`(Windows `%LOCALAPPDATA%\hermes\.env`)에서 읽는다. 자격 증명 관리자·DPAPI·keyring에서 슬랙 토큰을 읽는 코드는 없다. `.env` 값은 이미 있는 환경 변수보다 우선하고, `.env`에 없는 키는 물려받은 환경 변수를 쓴다. 모델 로그인(④)도 Hermes가 `auth.json`에 평문으로 둔다.

**사용자 결정(10-30): A — Hermes 표준대로 `.env`에 쓴다.** jaix는 `.env`에 ②③과 `SLACK_ALLOWED_USERS=<U…>`를 병합하고, 바꾸기 전에 백업한다.

1판에서 비교한 B(자격 증명 관리자 + jaix 실행기)를 고르지 않은 까닭은 이렇다. 같은 사용자 권한의 프로그램은 `CredReadW`로 B의 값도 읽을 수 있어 실익이 작다. 그리고 Hermes의 gateway 시작 경로를 jaix가 가로채야 해서 Hermes 판마다 맞춰야 한다.

A를 쓰면서 보완하는 것:
- `.env` 상속 ACL을 확인하고, 다른 사용자에게 읽기 권한이 있으면 doctor가 [주의]로 알린다.
- doctor·로그·안내문에 토큰 값을 찍지 않는다(앞 4자 + 길이만).
- 폐기는 §3.1 절차대로 한다. 관리자가 토큰을 revoke하면 PC의 값은 그 즉시 무효가 된다.

## 5. 공개 저장소에 아무것도 남지 않는다는 근거

| 저장소 | 들어가는 것 | 비밀·식별자 |
|---|---|---|
| jeju-inst/jaix-kit(공개) | 설치기 코드 칸, `jaix setup --hermes-code-file`, 관리자 명령 `jaix hermes handoff`, 이 문서 | 없음. 토큰·코드·멤버 ID·채널 ID·아이디 목록을 넣지 않는다 |
| jeju-inst/ji-gw-ai | 배포처 `share_server.py`의 `POST /hermes/handoff`(1회 반환 후 삭제·만료·원내 IP) | 없음. 묶음은 studio 로컬 `~/.local/share/jaix-dist/hermes/`(저장소 밖)에만 있다 |
| z0nam/hermes-slackbot(공개) | `setup_pc.py` 비대화형 입력(§7), 관리자 문서의 jaix 경로 | 없음(#15와 같은 규칙. 레지스트리는 관리자 맥 `~/.config`) |
| 릴리스 산출물(`jaix-setup.exe`) | 위 코드 | 없음. 사람별 값은 실행 때 배포처에서 받는다 |

막는 장치:
1. 테스트에서 가짜 배포처와 가짜 토큰(`xoxb-TEST…`)으로 setup을 돌린다. 그 뒤 setup.log·Inno 로그·stdout에 토큰과 코드 문자열이 없는지, 코드 파일이 지워졌는지, 두 번째 요청이 410인지 확인한다.
2. CI에 `xox[abpe]-`·`xapp-`·`JX-` 패턴 grep 검사를 둔다. 테스트용 가짜 값만 허용한다.
3. 코드·토큰은 argv·URL·로그 어디에도 싣지 않는다.

## 6. 사용자가 판단할 것(2판)

1판의 세 질문은 결정됐다(맨 위). 2판에서 새로 정할 것은 다음과 같다.
1. **전달 방식: (가) 1회용 연결 코드(권장)** / (나) 암호화 묶음 / (다) 원격 쓰기 / (라) 방문 입력. 비교는 §3.1에 있다.
2. **배포처 임시 보관을 평문으로 할지**: 평문(0600, 받으면 즉시 삭제, 최대 72시간)을 권장한다. studio에는 이미 더 강한 앱 설정 토큰이 있어서 위험이 크게 늘지 않는다. 암호화하려면 jaix에 첫 외부 의존성(암호화 라이브러리)이 생긴다.
3. **연결 코드를 슬랙 DM으로 보내도 되는지**: 된다고 본다(1회용·원내 IP 전용·먼저 쓰이면 드러남). 안 된다면 방문 메모·전화로 전한다.
4. **유효 기간**: 72시간을 권장한다.

## 7. 다른 저장소 수정(승인 뒤 각 저장소에서 PR)

hermes-slackbot-b2 확인(10-30): 진행·예정 작업 없음, 겹치지 않는다. #15는 아직 실제 Slack API·Windows에서 돌린 적이 없다(11월 초 첫 설치 때 확인 예정). 이 설계는 그 미검증 상태를 전제로 한다.

- **hermes-slackbot**: `setup_pc.py`에 `--secrets-file <path>`(읽고 지움), `--replace`(기존 토큰 덮어쓰기), `--yes`(봇 이름 불일치 시 계속)를 넣는다. 대화형 입력 세 곳(`getpass` 2번, `input` y/N 2번)을 플래그로 넘긴다. jaix는 배포처에서 받은 값을 이 파일로 넘겨 `setup_pc.py`를 부른다(잠금에 고정한 커밋). 같은 로직을 jaix에 다시 쓰지 않는다.
- **hermes-slackbot 문서**: `docs/admin-provision.ko.md`에 "jaix-setup 경로"를 더한다. Collaborator 추가와 구성원 복사 단계 대신 `jaix hermes handoff` → 연결 코드 전달로 바꾸고, 폐기 절차를 적는다. 셀프·방문 경로는 그대로 둔다. 문서만 먼저 고치면 아직 없는 기능을 안내하게 되므로 구현 PR과 함께 올린다.
- **ji-gw-ai**: `share_server.py`에 `POST /hermes/handoff`를 넣는다. 원내 IP 게이트는 기존 것을 쓴다. 1회 반환 후 삭제, 만료 청소, 접근 기록에 본문을 남기지 않는다. 운영 서버라서 그 저장소의 리뷰를 받는다.

## 8. 확인 못 한 것(구현 전 실기 항목)

- `install.ps1 -NonInteractive -SkipBrowser -SkipComputerUse`의 표준 사용자 실행: 시간(이전 실측 14분·2.9GB), Defender 반응.
- 표준 입력이 막힌 `hermes gateway install`이 실제로 UAC 없이 vbs로 가는지. 소스상 그렇지만 Windows 실측이 없다.
- `platform_toolsets`에서 `browser`·`computer_use`를 뺀 뒤 실제로 도구가 안 실리는지(Q9는 파일 확인만 함). Claude 구독 로그인(Q9 미시험).
- 배포처 1회용 경로는 원내망에서만 된다. 원외에서 설치하면 Hermes 연결만 실패로 남고, 원내에서 `jaix setup`을 다시 하면 된다(코드가 만료되기 전이라면).
- 모델 로그인은 브라우저 승인이 필요해 완전 무인이 안 된다. 설치기 마지막에 고른 구독의 `hermes auth add …` 창을 띄운다(ChatGPT는 기기 코드 화면, Q9에서 마법사 안 흐름으로 확인).

작성: 조남운 · claude/jaix-setup · 2026-10-30
