# 전사 기본 설정 (claude.ai 관리자 콘솔)

> 11/10 전원 배포 전에 Owner가 관리자 콘솔에서 한 번 맞춰 두는 값이다. 붙여 넣을 JSON은 `admin/managed-settings.json`.
> 결정 근거: 2026-11-03 사용자 결정 — 비영리 플러그인 조직에서 끔 · 기본 커넥터 Slack·Google·monday·규정 MCP · 잠금 수준 "느슨"(기본만 깔아 주고 개인 추가는 허용).
> 출처는 각 절 끝에 적었다. **설정 메뉴와 키 동작은 2026-11-03에 공식 문서로 확인했고, 콘솔에서 실제로 해 본 것은 아니다** → 아래 "실측 체크"를 11/9 전에 채운다.

## 0. 표면별로 무엇이 닿는가 (먼저 알아 둘 것)

| 설정 | 터미널·IDE Claude Code | Desktop Code 탭 | Cowork | 웹·모바일 채팅 |
|---|---|---|---|---|
| ① Plugins & skills (조직 플러그인) | ○ (계정 동기화) | ○ | ○ | ○ (스킬) |
| ② Connectors (조직 커넥터) | ○ (claude.ai 로그인 시 자동) | ○ | 미확인 | ○ |
| ③ Managed settings (JSON) | ○ (시작 시 + 1시간마다) | **✕ (11-04 실측)** | **✕ (문서에 명시)** | ✕ |

- 그래서 **jaix 플러그인은 ①과 ③ 두 곳에 다 등록한다.** ③만 하면 Cowork에 안 간다.
- ③의 `model` 은 터미널·IDE에만 적용된다. Desktop·Cowork는 온보딩 안내에서 Sonnet을 고르게 한다(`design.md` 사용량 예산 절).

## 1. Plugins & skills — `Organization settings > Plugins & skills`

| 할 일 | 값 | 이유 |
|---|---|---|
| `claude-for-nonprofits` 의 **Default access** | **Not available** | 비영리 할인 조직에 Anthropic이 "기본 설치"로 내려보낸다(2026-10-28 갱신본, 미국 모금·지원금용 커넥터 20개·스킬 13개). 도구 정의만으로 상시 예산 3k를 몇 배 넘는다 |
| ⚠ "Remove from organization" 은 누르지 않는다 | — | Anthropic 카탈로그 출처 전체가 빠진다(플러그인 하나만 빠지지 않음) |
| jaix 마켓플레이스 추가 | **Sync from GitHub** → 비공개 저장소 `jeju-inst/jaix-kit-org` (아래 주) | Cowork·Desktop 경로 |
| jaix 플러그인 6종 기본 접근 | **Installed by default** (Required 아님) | "느슨" 결정. 사용자가 끌 수 있다 |
| 그 밖의 Anthropic 카탈로그(`engineering` 등) | 기본값(Available to install) 유지 | 깔지 않으면 비용 없음 |

- **주 — 조직 동기화는 공개 마켓플레이스 저장소를 받지 않는다.** Team·Enterprise 조직 동기화는 github.com 마켓플레이스 저장소가 private 또는 internal이어야 한다. `jeju-inst/jaix-kit` 은 공개라 그대로는 등록할 수 없다.
  - 대신 플러그인 소스는 공개 저장소여도 된다(자격 증명 없이 받는다). jaix 잠금의 6종은 모두 공개이고 소스 형식도 `url`·`git-subdir` 이라 받아들여진다(2026-11-03 확인).
  - 그래서 **`marketplace.json` 만 담은 비공개 저장소 `jeju-inst/jaix-kit-org` 를 두고**, jaix-kit main에 머지될 때마다 워크플로가 그 파일을 복사해 넣는다. 잠금의 정본은 계속 jaix-kit이다.
  - CLI 경로(③ managed settings·`jaix setup`)는 지금처럼 공개 `jaix-kit` 을 가리킨다. 조직 동기화 규칙이 적용되지 않는다.
  - 복사는 `.github/workflows/org-mirror.yml` 이 한다(main의 `marketplace.json` 이 바뀔 때 + 수동 실행). 인증은 사본 저장소의 **쓰기 deploy key** 이고, 비밀키는 이 저장소 시크릿 `ORG_MIRROR_DEPLOY_KEY` 에 둔다. 시크릿이 없으면 워크플로가 실패로 알린다.
  - 콘솔에서 "Sync from GitHub" 를 처음 할 때 Anthropic GitHub App을 `jaix-kit-org` 에 설치하라고 나온다. 그 저장소만 골라 허용한다.
- 출처: https://claude.com/docs/plugins/admin, https://claude.com/docs/plugins/org-sync ("Plugin sources that organization sync accepts")

## 2. Connectors — `Organization settings > Connectors`

| 커넥터 | 켬 | 비고 |
|---|---|---|
| Slack | ○ | Slack 워크스페이스 쪽 앱 승인이 따로 필요한지 미확인 → 실측 |
| Google Calendar · Drive | ○ | **`ji.re.kr` Google Workspace 계정**으로 연결. worklog가 캘린더를 씀 |
| Gmail | ○ | **`jri.re.kr`(옛 도메인) 계정**으로 연결 — `ji.re.kr` 메일이 포워딩되고 과거 메일이 있음. `ji.re.kr` 메일 본체는 웍스라 그 Google 계정의 Gmail은 비어 있음. 발신·답장은 jaix `mail`(웍스) |
| Google Docs · Sheets · Slides | ✕ (권장) | Drive로 충분, 도구 수만 늘어남. 연결한 사람에게만 도구가 붙음 |
| monday | ○ | 디렉터리의 monday **Plugin**(Cowork 플러그인·CRM)은 쓰지 않음 — 커넥터만 |
| 규정 Q&A (커스텀) | ○ (OAuth 준비 뒤) | URL·인증은 `docs/regs-mcp.md`. OAuth 전에는 등록 값만 확인(같은 문서 Q3) |

- 켜 두어도 연구원은 각자 처음 쓸 때 자기 계정으로 OAuth를 한 번 한다.
- 출처: https://claude.com/docs/plugins/admin, https://code.claude.com/docs/en/mcp.md ("Use MCP servers from claude.ai")

## 3. Managed settings — `Organization settings > Claude Code > Managed settings`

Primary Owner·Owner만 보이고 고칠 수 있다. `admin/managed-settings.json` 을 그대로 붙여 넣는다.

| 키 | 값 | 효과 |
|---|---|---|
| `extraKnownMarketplaces.jaix` | git URL + `autoUpdate: true` | jaix 자동 등록·자동 업데이트. `jaix setup` 이 사용자 설정에 넣던 것과 같은 값 |
| `enabledPlugins` (jaix 6종) | `true` | **managed의 `true` 는 강제 켬이다** — 사용자가 꺼도 로드된다(①의 "Installed by default"와 다름). 아래 주의 참조 |
| `enabledPlugins` `claude-for-nonprofits@synced` | `false` | ①과 이중 차단. 계정 동기화 플러그인 하나를 끄는 공식 형식이 `"<name>@synced": false` 다(settings-reference `syncClaudeAiPlugins` 절) |
| `model` | `sonnet` | 좌석이 대부분 Pro의 1.25배라 한도 방지. 사용자의 `/model` 선택보다 우선하지만 `--model` 은 이긴다 |
| `permissions.disableBypassPermissionsMode` | `disable` | 비개발자 PC에서 "전부 허용" 모드를 막는다. 잠금이 아니라 사고 방지 |
| `companyAnnouncements` | 안내 1줄 | 시작 화면에 표시 |

- **넣지 않은 것("느슨" 결정)**: `strictKnownMarketplaces`, `allowedMcpServers`/`deniedMcpServers`, `allowManagedPermissionRulesOnly`. 개인이 다른 마켓플레이스·MCP를 추가할 수 있다.
- **주의 — 강제 켬의 비용**: `korea-rio-mcp` 처럼 일부 연구자만 쓰는 플러그인도 CLI에서는 모두에게 강제로 켜진다. 인수 시험 7절에서 상시 비용이 3k를 넘으면 그 플러그인만 `enabledPlugins` 에서 빼고 ①의 "Available to install"로 내린다.
- 잠금(`.claude-plugin/marketplace.json`)에 플러그인이 늘면(예: #61 `jaix-works`) 이 JSON의 `enabledPlugins` 도 같이 고친다.
- 출처: https://code.claude.com/docs/en/server-managed-settings.md, https://code.claude.com/docs/en/plugins/org.md, https://code.claude.com/docs/en/settings-reference.md

## 4. 실측 체크 (11/9 전, 결과를 이 표에 적는다)

| # | 확인 | 방법 | 결과 |
|---|---|---|---|
| 1 | managed settings가 CLI에 내려옴 | 시험 계정 `claude doctor` → "Managed settings (remote)" 줄 | ✅ 11-04 `~/.claude/remote-settings.json` 동기화, 내용 일치. 시작 화면에 companyAnnouncements 표시 |
| 2 | Desktop Code 탭에도 적용되는지 | Code 탭에서 `/status`·플러그인 목록 | managed settings는 ✕ (jaix 안 보임). ①조직 동기화 후 ✅ 6종 "pre-installed by your organization" — **Desktop은 ①로만 간다** |
| 3 | 비영리 플러그인이 사라짐 | `~/.claude/plugins/synced/` 에서 빠지는지, `/mcp` 에 `plugin:claude-for-nonprofits:*` 가 없는지 | ✅ CLI: "synced copy ignored: locked by managed settings", MCP 사라짐. Desktop: ① Not available 후 재시작하니 사라짐 |
| 4 | jaix 6종이 Cowork에 보임 | `jaix-kit-org` 동기화 뒤 Desktop Cowork 플러그인 목록 | ⏳ 조직 플러그인 목록엔 들어옴. Cowork `/` 에서 스킬 호출 확인 남음 |
| 5 | 조직 커넥터 4종이 CLI `/mcp` 에 `claude.ai …` 로 보임 | `/mcp` | ✅ Gmail·Calendar·Drive·monday. Slack은 개인 설치 `plugin:slack:slack` 과 같은 URL이라 하나로 합쳐짐(일반 PC에선 `claude.ai Slack` 예상) |
| 6 | Slack 커넥터 첫 연결이 Slack 관리자 승인 없이 되는지 | 일반 연구원 계정으로 연결 | ⏳ 파일럿 |
| 7 | `model: sonnet` 이 CLI에서 기본으로 잡힘 | 새 세션 `/model` | ✅ 새 세션 Sonnet 5.5. 세션 안 `/model` 로 Opus 전환 가능, 다음 시작엔 다시 Sonnet("Managed settings pins Sonnet 5.5 — applies on restart"). 본인은 `claude --model opus` |
| 8 | CLI에서 jaix가 managed `@jaix` 와 조직 동기화 사본으로 두 벌 잡히지 않는지 | `claude plugin list` (동기화 반영 뒤) | ⏳ 11-04 시점 CLI 동기화 폴더 미갱신. 비영리 사례로 보아 managed와 같은 이름의 동기화 사본은 무시될 것으로 예상 |
