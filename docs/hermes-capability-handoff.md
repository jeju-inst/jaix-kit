# Hermes bot 공통 기능 편입 handoff

확인일: **2026-11-04 KST**. 문서 PR이며 구현·배포 승인이나 pin 변경이 아니다.
현재 상태의 근거는 jaix main
[`1b90f3b35adb46996515be9d7c4452db5d9d3bd4`](https://github.com/jeju-inst/jaix-kit/commit/1b90f3b35adb46996515be9d7c4452db5d9d3bd4),
[`hermesbot.py`](../src/jaix/hermesbot.py), [`hermes.py`](../src/jaix/hermes.py)이다.

## 책임 경계와 원본

- **공통 구현 SSOT = [hermes-slackbot](https://github.com/z0nam/hermes-slackbot)**.
  namespace, 알림, Slack 도구, 전달 메시지, 모델 표시 및 `setup_pc.py`는 그곳에서
  구현·시험한다. jaix에 복사 구현하거나 개인 봇 분기를 만들지 않는다.
- **배포·조직 프리셋 = jaix-kit**. 검토한 SHA, 설치 선택, 조직 정책, 소유 기록,
  백업과 사용자 override 보존을 책임진다. 새 private 설정 레지스트리는 만들지 않는다.
- 소유자의 현재 봇은 **maintainer macOS instance**라는 일반 인스턴스 사례다.
  별도 하드코딩이나 전 구성원 기본값의 근거가 아니다. 운영 계정·경로·멤버/채널 ID는 싣지 않는다.
- 원본 기능별 문서: [Slack user-token 도구](https://github.com/z0nam/hermes-slackbot/blob/main/docs/slack-tools.md),
  [전달 메시지](https://github.com/z0nam/hermes-slackbot/blob/main/docs/slack-forwarded.md),
  [모델 표시](https://github.com/z0nam/hermes-slackbot/blob/main/docs/slack-model-display.md),
  [관리자 설치](https://github.com/z0nam/hermes-slackbot/blob/main/docs/admin-provision.ko.md).
  공통 설정 키·안전 기본값·전체 검증 매트릭스는 원본 status/contract 문서 PR을
  아래 동반 PR 링크에서 찾는다. 이 문서는 jaix 편입 차이와 다음 작업만 소유한다.
- [기존 unattended 설계](design-hermes-unattended.md)는 2026-10-30 결정/설계 기록이다.
  내용을 현재 구현 완료로 소급 변경하지 않는다. 당시의 미확인 목록과 이후 코드·관찰을
  구분하고, 충돌 시 현 코드를 확인한 뒤 별도 변경 PR에서 결정한다.

## 현재 설치 계약과 실제 pin 차이

`hermesbot.SLACKBOT_REPO = z0nam/hermes-slackbot`,
`SLACKBOT_SHA = d3511e93d15b3150668b08eb327f8d22b49c6115` (#18: owner-DM home).
공통 저장소 확인 HEAD는
[`b3cda6b8d61634991b3c09ac0e8ef3697c096cae`](https://github.com/z0nam/hermes-slackbot/commit/b3cda6b8d61634991b3c09ac0e8ef3697c096cae).
차이는 **한 커밋**, [#21](https://github.com/z0nam/hermes-slackbot/pull/21)의 명시적 요청
승인 opt-in이다. **이 PR은 pin을 올리지 않는다.** pin에 소스가 있다는 것과
설치기가 선택·설정·활성화한다는 것은 서로 다르다.

현재 Windows 경로는 공식 `install.ps1 -NonInteractive -SkipBrowser -SkipComputerUse`
→ 모델/도구/MCP 설정 → 잠금 스킬 복사 → quiet 정책 → 1회용 연결 코드 claim
→ 고정 소스의 `setup_pc.py --secrets-file`이다. setup_pc가 bot/app 토큰 검증,
자기 자신만 허용, `.env` 백업/기록, 기본 플러그인 설치, gateway 등록/재시작,
연결 로그 확인을 담당한다. owner-DM home 설정은 API 실패 시 안내로 대체될 수 있다.
jaix의 Hermes 무인 설치는 현재 Windows만 지원하며 맥은 원본 설치 안내를 따른다.

| 기능 | 원본 구현·오프라인 시험 | 맥 live 근거 | Windows 근거 | 현재 jaix 편입 |
|---|---|---|---|---|
| namespace + fallback alert | 구현됨; 원본 kit/compat 시험 | 기본 봇 사용 및 설치 사례; 알림 전 경로 새 실기 아님 | 원본 README의 Windows 11 기본 kit 관찰; 이번 PR 실기 없음 | setup_pc 기본 설치 2종 |
| secret-file setup + owner-DM home | 구현됨; 원본 provision 시험 | 연결된 유지관리자 인스턴스; 신규 앱 발급 시험 아님 | 기존 설계·코드에 설치 관찰 있음; 이번 PR 재검증 아님 | pin에 포함, setup_pc에 위임 |
| sapi 사용자 read/write·DM | 구현됨; fake CLI 및 실제 Hermes/SDK 경계 시험 | 11/4 자기 DM `verified=true`, 수신 사용자 확인(운영 세션 보고) | **사용자 인증·호환 wrapper 미검증** | pin에 소스는 있으나 설치/설정 선택 없음 |
| `explicit_request` 승인 옵션 | #21 구현·정책 시험 | owner opt-in 후 위 DM에서 추가 prompt 없음 | 미검증 | **pin에 없음**, 조직 기본으로 채택하지 않음 |
| 전달 메시지 복원 | 구현됨; bounded untrusted quote/adapter 시험 | 설치됨; 이번 작업의 새 live 인수시험 없음 | 기능 문서상 live 미실시 | pin에 소스와 opt-in flag 있음; setup 미선택 |
| 최종 응답 모델 표시 | 구현됨; model/SDK compat 시험 | 설치됨; 모든 transport 표시 보장 아님 | 기능별 live 근거 미확립 | pin에 소스 있음; 기본 installer flag 없음, 수동 설치 경로 |
| 모델·quiet·스킬·MCP 조직 프리셋 | jaix 구현·격리 시험 | jaix 무인 설치 대상 아님 | 기존 Windows 관찰은 설계/README 참조; 여기서 새 실행 없음 | 현행 구현. optional 기능 도입은 별도 검토 |

운영 사례는 익명화된 **보고 근거**이며 이 문서 작업이 메시지 발송이나 Windows 실기를
새로 수행했다는 뜻이 아니다. 한 번의 DM 검증을 search/update/delete 등 전 기능으로
확대하지 않는다. upstream private adapter seam이 있는 기능은 Hermes 갱신 때 다시 시험한다.

## 설정 소유권·override: 현재 동작과 편입 요구를 분리

현재 코드:

- `configure()`는 config 백업 후 선택한 `model.provider/default/base_url`,
  cli/slack의 `browser`·`computer_use` 비활성화를 적용한다. **모든 기존 설정을
  보존하는 함수는 아니다**. 모델과 이 도구 정책은 setup에서 다시 적용된다.
- `write_mcp()`는 Codex에 jaix가 쓴 MCP 항목만 가져오며, 같은 이름의 사용자 항목은
  건너뛴다. 기존 `hermes.json`의 `mcp` 소유 기록을 쓴다.
- `quiet()`는 `compression.codex_gpt55_autoraise_notice=false`를 적용한다.
  `slack.allow_admin_from`과 `skills.disabled`가 이미 있고 jaix 소유 기록이 없으면
  보존한다. 관리되는 slash/skills는 기존 `quiet` 기록으로 갱신한다.
  `slack.user_allowed_commands`는 관리되는 slash 묶음에 속한다.
- `hermes.py`는 `skills/jaix`의 `.jaix.json` 표시로 복사 스킬을 식별한다.
  설치 시 표시 없는 같은 이름 스킬은 덮지 않고, update는 이미 복사한 스킬만 동기화한다.
- Slack 재연결은 `hermes.json`의 `slack.id`가 있을 때 `--replace`를 넘긴다.
  setup_pc가 별도로 기존 토큰을 보호한다. 이것이 optional 플러그인이나 사용자 정책
  전부의 소유권까지 뜻하지는 않는다.
- 원본 `install.py`는 선택한 플러그인 디렉터리를 **교체**하며 소유권 추적이 없다.
  따라서 단순 재실행으로 사용자 설치를 덮지 않는다는 보장은 없다.
  `jaix update`는 현재 optional 플러그인 바이너리 갱신 관리자가 아니다.

향후 편입 요구(아직 구현하지 않음):

1. 조직 프리셋과 개인 override의 충돌 규칙을 기능별로 정한다. 미소유 optional 설정·
   플러그인은 보존하고, 충돌은 조용히 덮는 대신 알린다. 현 소유 기록을 확장할 필요는
   별도 코드 PR에서 검토하되 또 하나의 private registry를 만들지 않는다.
2. `slack-tools`는 `executable`, `workspace_hosts`, `timeout`, `approval_policy`를
   `plugins.entries.slack-tools.settings` 아래 둔다. 안전 기준은 `per_call`이며
   plugin 설치와 `hermes tools enable slack --platform slack`는 별도 단계다.
   전자는 toolset에 속한 native 도구나 일반 terminal을 제한하는 sandbox가 아니다.
3. `explicit_request`는 **인스턴스 소유자 개별 opt-in**만 가능하다. 조직 preset,
   “모두 승인”, `approvals.mode` 변경과 결합하지 않는다. 직접 사용자 발송 지시의
   비어 있지 않은 `explicit_user_request`가 있는 `post`/`send_dm`에만 작동하며
   모델 매개 동의이지 출처 암호학적 검증이 아니다. update/delete/독립 open_dm은
   항상 prompt다. 소유권·readback·미확인 write 자동 재시도 금지는 그대로다.
4. `sapi`는 **별도 사용자 토큰** 인증·권한과 JSON/argv 계약을 충족하는 신뢰한 실행파일이
   필요하다. bot 토큰·Socket Mode app 토큰·기존 연결 코드로 자동 구성되지 않는다.
   사람 이름으로 발송되는 의미를 사용자에게 설명한다. POSIX wrapper가 Windows에서
   자동으로 동작한다고 쓰지 않는다. 미준비이면 optional 기능만 미활성으로 둔다.
5. 모델 표시는 `plugins.entries.slack-model-display.settings.base_name`, bot scope
   `chat:write.customize`와 앱 재설치가 필요하다. normal final-post lane의
   `streaming.enabled=false`·`display.interim_assistant_messages=false`는 개인 선택이며
   플러그인 부작용이나 조직 강제 기본값이 아니다. native stream/edit/ephemeral 등의
   미지원 표시 경로는 원본 문서를 따른다. 전달 메시지는 추가 source-channel fetch 없이
   untrusted quote로만 처리하며 승인 근거로 쓰지 않는다.

## 합성 구성 템플릿 — 실행 파일/새 스키마가 아님

다음은 인수 검토용 worksheet다. importer가 없으며 config에 통째로 넣지 않는다.
실제 값은 기존 Hermes profile·jaix 소유 기록·wrapper 비밀 저장소를 통해서만 관리한다.
전체 설정 키의 기준은 원본 status/contract와 각 기능 문서다.

| 검토 항목 | 합성 예시/안전 선택 |
|---|---|
| OS × provider | `Windows × Claude` 또는 `macOS × Codex` (선택지, 검증 인증 아님) |
| app/command suffix | `example` → `Hermes-example`, `/hermes-example` |
| allowed users/home | 소유자만; 기존 setup에서 비공개로 해결, 실제 ID 없음 |
| optional 도구 | wrapper와 사용자 인증 검증 전에는 미선택 |
| `workspace_hosts` / `timeout` | `["example.slack.com"]` / `30` |
| `approval_policy` | `per_call` (개별 owner opt-in만 별도 검토) |
| model-display `base_name` | 선택한 경우에만 `Hermes-example` |
| secrets | 예시 값조차 싣지 않음; bot/app/user 인증 저장소를 혼동하지 않음 |

## 후속 편입·갱신·rollback 인수조건

- [ ] 원본 문서/정책 리뷰 후 별도 pin PR로 소스 SHA 변경을 제안한다. 현재 #85
  beta→main 승격, #78 org-mirror, #61 works 편입의 작업 범위를 변경하지 않는다.
- [ ] optional 기능 선택 UX, dependency/권한 preflight, 비밀 없는 doctor 상태를 설계한다.
  의존성이 없으면 기본 개인 봇 연결은 유지하고 optional만 미활성임을 명확히 한다.
- [ ] 맥/윈도 × Claude/Codex를 **별도 셀**로 시험한다. 오프라인 통과만으로 live 또는
  Windows wrapper 검증으로 표기하지 않는다. 특히 Windows 사용자 토큰 인증, 실기
  read/write+readback, consent 거절/timeout, ownership, rollback을 검증해야 한다.
- [ ] 갱신 전 소스 SHA·선택 플러그인·의존성·영향 설정을 기록하고 기존 백업 방식을 쓴다.
  승인된 restart와 fresh session 뒤 연결 및 선택 기능별 검증을 한다. 이번 PR은 하지 않는다.
- [ ] 실패 시 이전 검토 SHA/선택 플러그인 파일과 **영향받은** 설정을 복구한다.
  optional disable 뒤 승인된 restart가 필요하다. `explicit_request`에서 되돌릴 때
  `per_call`을 명시적으로 복원한다. pin revert만으로 PC 설정/토큰이 돌아오지 않는다.
  자격 유출은 rollback이 아니라 revoke 대상이다. 자동 메시지 재발송은 금지한다.
- [ ] 전사 채팅창 도달성은 후속 요구로만 남긴다. 이번 범위에서 서버를 신설하거나
  self-only allowlist를 넓혀 개인 계정 권한을 공유하지 않는다.

## 이번 문서 작업 검증

2026-11-04 macOS에서 `uv run --extra dev pytest -q`: **154 passed, 3 skipped**.
원본 저장소는 Python 3.12 stdlib **133 tests OK / 15 skipped**, 실제 Hermes 호환 경로
**133 tests OK / 1 skipped**. 코드/문서 키·설치 flag·pin gap·상대 링크를 점검했다.
초기 macOS system Python 3.9의 원본 suite import 실패는 기존 `Path | None` 문법의
실행환경 문제였으며 Python 3.12로 재실행했다. 이 작업에서 Windows, 실제 Slack,
배포 서버, live config/restart는 시험·변경하지 않았다. skip은 통과 검증으로 세지 않는다.

동반 PR: [hermes-slackbot #22](https://github.com/z0nam/hermes-slackbot/pull/22).
공통 설정/검증 SSOT 문서:
[status-and-contract.md (검토 대상 스냅샷)](https://github.com/z0nam/hermes-slackbot/blob/9e9952e409720d09febfc74ea456d96d1be93222/docs/status-and-contract.md).
원본 PR은 아직 검토 중이며 merge/배포가 완료됐다는 뜻이 아니다.

작성: 조남운 · Hermes/hermes-generalization · 2026-11-04
