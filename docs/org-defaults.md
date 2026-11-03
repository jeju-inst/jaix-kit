# 전사 기본 설정 (claude.ai 관리자 콘솔)

> 11/10 전원 배포 전에 Owner가 관리자 콘솔에서 한 번 맞춰 두는 값이다. 붙여 넣을 JSON은 `admin/managed-settings.json`.
> 결정 근거: 2026-11-03 사용자 결정 — 비영리 플러그인 조직에서 끔 · 기본 커넥터 Slack·Google·monday·규정 MCP · 잠금 수준 "느슨"(기본만 깔아 주고 개인 추가는 허용).
> 출처는 각 절 끝에 적었다. **설정 메뉴와 키 동작은 2026-11-03에 공식 문서로 확인했고, 콘솔에서 실제로 해 본 것은 아니다** → 아래 "실측 체크"를 11/9 전에 채운다.

## 0. 표면별로 무엇이 닿는가 (먼저 알아 둘 것)

| 설정 | 터미널·IDE Claude Code | Desktop Code 탭 | Cowork | 웹·모바일 채팅 |
|---|---|---|---|---|
| ① Plugins & skills (조직 플러그인) | ○ (계정 동기화) | ○ | ○ | ○ (스킬) |
| ② Connectors (조직 커넥터) | ○ (claude.ai 로그인 시 자동) | ○ | 미확인 | ○ |
| ③ Managed settings (JSON) | ○ (시작 시 + 1시간마다) | 미확인 | **✕ (문서에 명시)** | ✕ |

- 그래서 **jaix 플러그인은 ①과 ③ 두 곳에 다 등록한다.** ③만 하면 Cowork에 안 간다.
- ③의 `model` 은 터미널·IDE에만 적용된다. Desktop·Cowork는 온보딩 안내에서 Sonnet을 고르게 한다(`design.md` 사용량 예산 절).

## 1. Plugins & skills — `Organization settings > Plugins & skills`

| 할 일 | 값 | 이유 |
|---|---|---|
| `claude-for-nonprofits` 의 **Default access** | **Not available** | 비영리 할인 조직에 Anthropic이 "기본 설치"로 내려보낸다(2026-10-28 갱신본, 미국 모금·지원금용 커넥터 20개·스킬 13개). 도구 정의만으로 상시 예산 3k를 몇 배 넘는다 |
| ⚠ "Remove from organization" 은 누르지 않는다 | — | Anthropic 카탈로그 출처 전체가 빠진다(플러그인 하나만 빠지지 않음) |
| jaix 마켓플레이스 추가 | GitHub `jeju-inst/jaix-kit` (main) | Cowork·Desktop 경로 |
| jaix 플러그인 6종 기본 접근 | **Installed by default** (Required 아님) | "느슨" 결정. 사용자가 끌 수 있다 |
| 그 밖의 Anthropic 카탈로그(`engineering` 등) | 기본값(Available to install) 유지 | 깔지 않으면 비용 없음 |

- 출처: https://claude.com/docs/plugins/admin

## 2. Connectors — `Organization settings > Connectors`

| 커넥터 | 켬 | 비고 |
|---|---|---|
| Slack | ○ | Slack 워크스페이스 쪽 앱 승인이 따로 필요한지 미확인 → 실측 |
| Google Drive · Gmail · Calendar | ○ | worklog가 캘린더를 씀 |
| monday | ○ | |
| 규정 Q&A (커스텀) | ○ (OAuth 준비 뒤) | URL·인증은 `docs/regs-mcp.md`. OAuth 전에는 등록 값만 확인(같은 문서 Q3) |

- 켜 두어도 연구원은 각자 처음 쓸 때 자기 계정으로 OAuth를 한 번 한다.
- 출처: https://claude.com/docs/plugins/admin, https://code.claude.com/docs/en/mcp.md ("Use MCP servers from claude.ai")

## 3. Managed settings — `Organization settings > Claude Code > Managed settings`

Primary Owner·Owner만 보이고 고칠 수 있다. `admin/managed-settings.json` 을 그대로 붙여 넣는다.

| 키 | 값 | 효과 |
|---|---|---|
| `extraKnownMarketplaces.jaix` | git URL + `autoUpdate: true` | jaix 자동 등록·자동 업데이트. `jaix setup` 이 사용자 설정에 넣던 것과 같은 값 |
| `enabledPlugins` (jaix 6종) | `true` | **managed의 `true` 는 강제 켬이다** — 사용자가 꺼도 로드된다(①의 "Installed by default"와 다름). 아래 주의 참조 |
| `enabledPlugins` 비영리 | `false` | ①과 이중 차단. 모든 스코프에서 막힌다. **키 이름은 미확인**: 메타의 마켓플레이스 이름은 `claude-for-nonprofits` 인데 CLI에는 `claude-for-nonprofits@synced` 로 보인다 → 실측 3에서 안 막히면 `@synced` 로 바꾼다 |
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
| 1 | managed settings가 CLI에 내려옴 | 시험 계정 `claude doctor` → "Managed settings (remote)" 줄 | |
| 2 | Desktop Code 탭에도 적용되는지 | Code 탭에서 `/status`·플러그인 목록 | |
| 3 | 비영리 플러그인이 사라짐 | `~/.claude/plugins/synced/` 에서 빠지는지, `/mcp` 에 `plugin:claude-for-nonprofits:*` 가 없는지 | |
| 4 | jaix 6종이 Cowork에 보임 | Desktop Cowork 플러그인 목록 | |
| 5 | 조직 커넥터 4종이 CLI `/mcp` 에 `claude.ai …` 로 보임 | `/mcp` | |
| 6 | Slack 커넥터 첫 연결이 Slack 관리자 승인 없이 되는지 | 일반 연구원 계정으로 연결 | |
| 7 | `model: sonnet` 이 CLI에서 기본으로 잡힘 | 새 세션 `/model` | |
