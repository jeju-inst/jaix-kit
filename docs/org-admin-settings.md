# 관리자 콘솔 조직 설정 — 메뉴별 결정 기록

> 관리자 콘솔(claude.ai → Admin settings) 메뉴를 하나씩 보며 정한 값과 근거. 2026-11-09〜 진행 중.
> 플러그인·커넥터·Claude Code managed settings 는 `docs/org-defaults.md` 가 따로 다룬다.
> 상태: ✅ 적용 · ⏳ 결정 대기 · ⏸ 보류

## 1. Organization and access

| 항목 | 뜻 | 확인 당시 값 (11-09) | 결정 | 상태 |
|---|---|---|---|---|
| Team overview | 좌석·멤버 수 | 좌석 2(남은 0), 멤버 2 | 11/10 연구직 인원만큼 좌석 추가(Billing) | ⏳ |
| Organization instructions | 조직 모든 대화에 붙는 지시문(3000자, 개인 설정보다 우선, 반영 최대 1시간) | 비어 있음 | **초안 그대로 저장**(11-09, 160자). 나중에 정제 | ✅ |
| Internal help contact | 멤버 문의처. 비우면 primary owner 표시 | 비어 있음 | **AI데이터연구지원센터 / `ai@ji.re.kr`**(11-09 저장) | ✅ |
| Domains | 도메인 소유 DNS 인증 | `ji.re.kr` Unverified (허용 도메인은 ji.re.kr 하나) | **`ji.re.kr`·`jri.re.kr` 둘 다 Verified**(11-09, 기관 DNS 가비아에 `@` TXT `anthropic-domain-verification-…` 추가). `jri.re.kr` 은 이날 허용 도메인에 추가. TXT 레코드는 지우지 않는다(재검증에 쓰일 수 있음) | ✅ |
| Single sign-on | 기관 계정 로그인 | 도메인 미인증이라 불가 | 11/10 범위 밖. 도메인 인증 뒤 검토 | ⏸ |
| User provisioning | 멤버 추가 방식 | Invite only | 유지 | ✅ |
| Invite link | `@ji.re.kr` 이면 링크로 승인 없이 가입 | 켜짐(2027-01-30 만료) | **끔**(11-09). 승인 없는 가입 경로는 이것뿐이라 막음. 관리자 메일 초대만 사용 | ✅ |
| Member invites | 일반 멤버가 초대 가능 | 켜짐 | **끔**(11-09). 대상이 연구직뿐이라 관리자만 초대 | ✅ |
| New member approval | 초대·발견 가입자 승인 | Require admin approval | 유지 | ✅ |

조직 지시문(11-09 적용, 정제 예정):

```
사용자는 제주연구원(JRI) 연구원이다. 한국어로 답한다. 기관 보고서 본문을 쓸 때는 ji-report-writing 스킬(음슴체·문장형 bullet·제주연구원 인용표기)을 따른다. 주민등록번호·계좌번호 등 개인정보와 비공개 원문은 필요한 범위에서만 다루고 결과물에 옮겨 적지 않는다.
```

도메인 인증으로 되는 것: SSO 전제 조건(화면 문구), SSO 자동 가입(JIT) 전제, "Discoverable"(인증 도메인 사용자가 조직을 찾아 가입 요청 — 승인 필요). Team 요금제에서 기존 개인 계정 관리(domain capture)가 되는지는 미확인.

## 2. Billing · Usage · Data and privacy · Capabilities · Git providers · Notifications

### Billing

| 항목 | 확인 당시 값 (11-09) | 결정 | 상태 |
|---|---|---|---|
| 요금제 | Team, 좌석 2(남은 0). 11/1 청구 2명 $80, 12/1 예상 $88 | 11/10 좌석 추가(인원 미정) | ⏳ |
| 결제 수단 | 법인카드(사용자 확인) | 유지 | ✅ |
| API credits | 월 $200(좌석 2 × Premium $100, 풀링 상한 $500). 미연결이라 쓰이지 않던 상태 | **11-09 Console 조직 `제주연구원 (The Jeju Institute)` 새로 만들어 연결, $200 수령.** 카드 없이 진행 | ✅ |

API 크레딧 Console 조직 운영 규칙(어기면 추가 과금 경로가 열림):

- **Console 조직에 카드를 등록하지 않는다. 크레딧을 사지 않고 auto-reload 를 켜지 않는다.** 문서상 크레딧이 떨어지면 요청이 멈추고 "Usage is never charged to your Claude plan"(카드·구매 크레딧이 없을 때).
- 멤버는 관리자 초대로만. 생성 때 "@ji.re.kr 사용자가 찾아 가입 요청" 체크 해제.
- 연결은 1:1 이고 직접 바꿀 수 없다(지원팀 문의). 미사용 월 크레딧은 이월되지 않는다.
- Supplemental Credit Terms 적용(환불·양도 불가). 근거: platform.claude.com/docs/en/about-claude/api-credits-for-subscribers, support.claude.com/en/articles/17154008.
- 크레딧 대상: Claude API · Managed Agents · Agent SDK · Playground. Claude 앱·대화형 Claude Code 사용량에는 쓰이지 않는다.
- 11-09 확인: Console 결제 수단 없음, 청구서는 "API credit (Team) $200, 12/4 만료"만.

### Usage

| 항목 | 뜻 | 확인 당시 값 (11-09) | 결정 | 상태 |
|---|---|---|---|---|
| Turn on usage credits | 한도 초과 뒤 종량제로 계속 사용(조직 카드 청구) | 꺼짐 | **꺼 둠.** 켜면 좌석 외 추가 결제 | ✅ |
| Usage credit requests | 한도에 걸린 멤버가 관리자에게 크레딧 요청 | 켜짐 | **켜 둠** — 누가 한도에 걸리는지 알려는 신호용. **요청을 승인하지 않는다**(승인이 과금으로 이어질 수 있음, 동작 미확인). 요청은 좌석 요금제 적정성 판단 자료로만 쓴다 | ✅ |
| Services → Claude Code Review | GitHub PR 자동 리뷰(종량제) | 미설정, 한도 Unlimited | **설정하지 않음.** PR 리뷰는 Codex·로컬 `claude -p`(pr-watch) | ✅ |

### Data and privacy (11-10 확인)
| 항목 | 의미 | 값 | 결정·근거 | 상태 |
|---|---|---|---|---|
| Share chats | 조직 안 대화 공유 | 켜짐 | 유지 — 프롬프트·사례 공유 | ✅ |
| Share chats that use connectors | 커넥터 쓴 대화 공유 | 켜짐 | 유지 — 받는 사람은 Claude 답만 보고 커넥터 원본 데이터는 못 봄 | ✅ |
| Share chats with everyone in your organization | 조직 전체 공유 | 켜짐 | 유지 | ✅ |
| Share chats externally | 외부인 이메일 초대 공유 | **꺼짐** | 유지 — 기관 자료 외부 유출 경로 | ✅ |
| Share cloud sessions · Share projects · Public projects | 클라우드 세션·프로젝트 공유 | 켜짐 | 유지 | ✅ |
| Allow members to export their own data | 본인 대화 내려받기 | 꺼짐 | 유지 — 관리자는 전체 내보내기 가능, 퇴사 시 일괄 반출 방지 | ✅ |
| Rate chats | 👍👎 평가 시 대화가 Anthropic 에 피드백으로 전달 | **꺼짐(11-10 변경)** | 미공개 원고·내부 자료가 피드백 경로로 나가는 것을 막음. 품질 피드백은 베타 채널로 받음 | ✅ |
| Location metadata | 도시·지역 수준 위치 사용 | 켜짐 | 유지 — 거친 위치, 지역 맥락 답변용 | ✅ |
| Monitoring (OTel: Cowork·Office Agents) | 사용 기록을 지정 수집 서버로 전송 | 비움 | 수집 서버 없음. 필요해지면 **기관이 운영하는 서버로만** 연결(외부 SaaS 에 사용 기록 적재 금지). 사용량은 Usage·Analytics 화면으로 봄 | ✅ |

### Capabilities (11-10 확인)
| 항목 | 의미 | 값 | 결정·근거 | 상태 |
|---|---|---|---|---|
| Chat and Cowork unified | 대화창 통합 경험(코드 실행·파일·긴 작업) | 켜짐 | 유지 | ✅ |
| Web search · Interactive content · Ask jeju-inst | 웹 검색 · 외부 서비스 지도/이미지 · 조직 연결 자료원 통합 검색 | 켜짐 | 유지 | ✅ |
| Built-in browser | 내장 브라우저로 웹 읽기·폼 입력 | 켜짐 | 유지 | ✅ |
| └ Import cookies from other browsers | 다른 브라우저 로그인 상태를 내장 브라우저로 가져옴 | **꺼짐(11-10 변경)** | 그룹웨어·메일·웍스에 로그인된 채 에이전트가 움직이면 프롬프트 인젝션 피해가 커짐. 필요한 사이트는 내장 브라우저에서 직접 로그인 | ✅ |
| Artifact connectors · Inline visualizations | 외부 데이터 아티팩트 · 대화 안 차트 | 켜짐 | 유지 | ✅ |
| Allow "Automatically approve" mode | 사용자가 자동 승인을 고를 수 있음 | 켜짐 | 유지 | ✅ |
| └ Start new tasks in "Automatically approve" mode (Coming soon) | 새 작업 기본값을 자동 승인으로 | 켜짐 | **유지(사용자 결정)** — 수동 승인 기본값은 직접 써 보니 너무 불편해 초보자 반감 우려. 위험 동작은 Claude 가 멈춤 + 아래 두 안전장치는 꺼 둠 | ✅ |
| Allow "Skip all approvals" mode | 위험 동작에도 멈추지 않음 | 꺼짐 | 유지 | ✅ |
| Allow "Always allow" for connector tools | 쓰기 커넥터 도구 영구 허용 | 꺼짐 | 유지 — 메일 발송 등 쓰기 동작은 매번 승인 | ✅ |
| Cloud code execution and file creation | 서버 코드 실행·문서 생성(스킬 필수) | 켜짐 | 유지 | ✅ |
| Allow network egress | 코드 실행 환경 외부 접속 | 켜짐, Package managers only, 추가 도메인 없음 | 유지 | ✅ |
| Computer access | 폰·웹에서 본인 컴퓨터 원격 접속 | 켜짐 | 유지 | ✅ |
| Require trusted devices | 원격 접속(Computer access·Remote Control) 새 기기 인증 | **켜짐(11-10 변경)** | 계정 탈취 시 낯선 기기가 연구원 PC 에 붙는 것 방지. 새 기기 첫 연결 때 1회 등록. **켠 직후 이미 떠 있던 세션은 RC 가 403(`Remote Control server rejected the request`)으로 끊기고 `/login` 으로는 안 풀림** — 세션마다 `/exit` → `claude --resume` → `/rc` → enable → 약 10초 뒤 `/rc` 다시 하면 붙음(11-10 실측). 연결 유지 중인 세션은 끊기기 전까진 영향 없음 | ✅ |
| Scheduled tasks | 예약·웹훅 작업 | 켜짐 | 유지 | ✅ |
| Enable memory for your team | 본인 과거 대화 기억(본인만) | 켜짐 | 유지 | ✅ |
| Sensitive topics in memory | 건강·종교 등 민감 정보 기억 | 꺼짐 | 유지 | ✅ |

### Git providers (11-10 확인)
| 항목 | 값 | 결정·근거 | 상태 |
|---|---|---|---|
| GitHub → jeju-inst (Claude GitHub App) | Connected(11-04, Owner 가 연결), **Only select repositories**: `jeju-inst/jaix-kit`(공개), `jeju-inst/jaix-kit-org`(비공개) | 유지 — Plugin marketplaces 동기화가 이 연결을 씀. 끊으면 조직 플러그인 배포가 멈춤. **All repositories 로 바꾸지 않는다**(새 비공개 저장소 자동 노출 방지). 설정 위치: GitHub jeju-inst 조직 설정 → GitHub Apps → Claude | ✅ |
| GitHub Enterprise · GitLab | 미연결 | 해당 없음 | ✅ |

### Notifications (11-10 확인)
| 공지 | 우리 영향 | 조치 | 상태 |
|---|---|---|---|
| 독립 Claude Design(claude.ai/design) 12-14 종료 — 대화 안 Design 으로 통합 | 쓰는 사람이 있으면 Artifacts 설정의 Design·Design systems 가 켜져 있어야 함 | Artifacts 의 Design·Design systems 켜짐 확인(11-10) | ✅ |
| managed settings 의 `sshHostAllowlist` 를 Claude Desktop 이 적용(빈 목록이면 SSH 꺼짐) | `admin/managed-settings.json` 에 `sshHostAllowlist` 없음(11-10 확인) → 영향 없음 | 앞으로 넣을 때는 빈 목록 금지 | ✅ |

### 구독 계획 (11-10, 실무채널 확인 전)
| 대상 | 등급 | 석 | 비고 |
|---|---|---|---|
| 본원 연구직(AI센터 Premium 대상 제외) | Standard | **24** | GW 인사 명부(11-10 05:37) 기준. 예산 25석 안, 1석 여유 |
| AI센터 | Premium | 4 | 2명 적용 중, 2명 추가 |
| 기획 공용 계정 | Premium | 1 | 사람 계정 아님 |
| **합계** | | **29** (Premium 5 + Standard 24) | 11-10 명단 시트를 실무채널(#ai데이터연구지원센터-실무채널)에 공유, 확인 대기 |

경계 판단(11-10 사용자):
- 원장 직무대리(선임연구위원) → **포함**
- 연구년 중인 연구위원 → **당장은 제외**(복귀 시 추가)
- 제주학연구센터(@jst.re.kr) → **본원이 아니라 제외**
- 도청 파견 도정연구관 → **제외**
- 연구기획전략실 전문연구위원 3명 → **제외**(연구직 아님, 사용자 확인). 직급명 「전문연구위원」만 보고 연구직으로 간주한 것이 원인 — 연구직은 직급명으로 가르지 말고, 합계를 계획 석 수와 대조할 것(GW 고용구분 occupCtgryNm=전문직)
- 위탁센터 6곳·행정직·과제위촉 → 제외(위탁센터 구분은 11-06 경영지원실 기준)
- 명단 원본은 이 문서에 두지 않는다(GW 인사 명부에서 다시 뽑음).

### Claude ↔ Codex(OpenAI) 이동 시 좌석 처리 (11-10 논의)
- 우리 Team 결제는 **월간뿐**(연간 결제 없음, 사용자 확인 11-10)이라 좌석 축소는 **다음 달 결제부터** 반영됨. 일할 환불은 없는 것으로 알려짐(원문 미확인).
- 순서: 이동자 대화 보존이 필요하면 관리자 내보내기 → Members 에서 제거 → Billing 에서 좌석 수 축소.
- OpenAI 비영리(Goodstack 인증): Business **Standard** 좌석만 할인(연간 월 $8 / 월간 $10), Premium 은 할인 없음. **비영리 요금제의 Codex 포함·한도는 미확인** → 승인 때 확인.
- 좌석 추가 전에 Claude/Codex 선택을 먼저 받는 것이 낭비가 적음.

## 3. Members · 제품별(Claude Code〜Claude Academy)

### Members (11-10 확인)
| 항목 | 현재 | 결정·근거 | 상태 |
|---|---|---|---|
| Primary owner | AI센터 전문연구위원(비영리 할인 추진 담당) | 결제·계약 메일 수신자로 유지 | ✅ |
| Owner | AI센터 jaix 담당 | 유지 | ✅ |
| **Admin** | 없음 | **AI센터 센터장과 센터 연구원 1명에게 부여 예정** — Owner 가 아닌 Admin(구성원·설정 관리, 결제 불가) | ⏳ |
| Tier | 두 좌석 모두 **Nonprofit Premium**(석당 월 $40, 11/1 청구서) | 연구원 = Standard, AI센터·plan@ = Premium(아래 구독 계획) | ✅ |
| 연구원 좌석·초대 | 2석(빈 좌석 0) | **실무채널에 명단을 올려 확인받은 뒤** 좌석 추가(Billing → Manage) → Add member 로 이메일 초대 | ⏳ |


### Claude Code (11-10 확인)
| 항목 | 값 | 결정·근거 | 상태 |
|---|---|---|---|
| Managed settings | 콘솔본에 `jaix-works@jaix` 누락(PR #152 반영 전), 저장소에 없는 `channelsEnabled: true` 가 콘솔에만 있었음 | 저장소 `admin/managed-settings.json` 에 `channelsEnabled: true` 추가해 일치시킴 → 저장소본을 콘솔에 다시 붙여넣음(11-10 완료, jaix-works 포함). **원본은 저장소, 콘솔은 붙여넣기만** | ✅ |
| Desktop · Cloud sessions · Remote Control | 켜짐 | 유지(기기 인증은 Capabilities 에서 켬) | ✅ |
| Default environment | No default | 유지 | ✅ |
| Quick setup (Preview) | 켜짐 | 유지 | ✅ |
| Fast mode | 꺼짐 | **유지** — usage credits 로 별도 과금, credits 꺼 둠 | ✅ |
| Dynamic workflows | 켜짐 | 유지 — 좌석 한도 안에서만 동작 | ✅ |
| Channels (Preview) | 화면 토글은 꺼짐, managed settings `channelsEnabled: true` 로 켬 | 켬 — 텔레그램 등 `--channels` 연결용. 사용자가 직접 고른 서버만 연결돼 연구원 영향 없음 | ✅ |
| Allow code review | 꺼짐 | 유지(종량제) | ✅ |
| Claude Code analytics · GitHub analytics | 켜짐(jeju-inst) | 유지 | ✅ |

### 제품별 나머지 (11-10 확인)
| 메뉴 | 항목 | 값 | 결정·근거 | 상태 |
|---|---|---|---|---|
| Claude in Chrome | Enable for your team | 켜짐 | 유지 | ✅ |
| | Password managers | 꺼짐 | 유지 — 로그인은 사람이 직접(쿠키 가져오기 끈 것과 같은 취지) | ✅ |
| | Default for all sites | Allow all sites | 유지 — 허용 목록 방식은 불편 | ✅ |
| | Blocked sites | 인터넷뱅킹·홈택스·정부24 제안 | 사용자가 직접 적용(11-10). 그룹웨어는 막지 않음(`gw` 도구 경유) | ✅ |
| Claude Tag | 슬랙 @Claude | 미설정 | **설정 안 함** — 별도 usage credits 구매가 전제 | ✅ |
| Cloud environments | Allow self-hosted environments | 꺼짐 | **보류** — 원내 자원(그룹웨어 등)이 필요한 클라우드 예약 작업이 생기면 전용 runner 와 함께 검토. studio 에 얹는 것은 신중 | ✅ |
| | Anthropic-hosted environments | 없음 | 유지(기본 환경) | ✅ |
| Cowork | Enable · Cowork in the cloud | 켜짐 | 유지 | ✅ |
| | Enable Dispatch | 꺼짐 | 유지 — 감독 없이 PC 조작 | ✅ |
| Artifacts | Artifacts · 조직 내 공유 · presence · Slides/Design/Design systems/Docs/Data/Motion | 켜짐 | 유지 | ✅ |
| | External sharing | 꺼짐 | 유지 | ✅ |
| | Email invitations outside your organization | **꺼짐(11-10 변경)** | 외부 공개를 꺼 둔 것과 일관 | ✅ |
| Claude Design | Enable (standalone, 12-14 종료) | 켜짐 | 유지 — 종료 뒤엔 Artifacts 의 Design 으로 이어짐 | ✅ |
| | Allow public links | **꺼짐(11-10 변경)** | 공개 링크 = 외부 노출 | ✅ |
| Office Agents | Let Claude work across apps | 켜짐 | 유지 | ✅ |
| Claude Science (Beta) | Enable | **켜짐(11-10)** | 별도 데스크톱 앱이라 설치한 사람만 씀(켜도 PC 에 아무것도 안 깔림). 메타분석 수요 때문에 켬. 디렉터리 커넥터는 기관 구독이 없어 무료로 쓸 만한 IHME GBD·Elicit·Consensus 만 추천(Scite·Wiley 는 유료) | ✅ |
| | Allow custom connectors | **꺼짐(11-10 변경)** | 켤 때 기본값으로 켜졌던 것을 끔 — 조직의 커스텀 커넥터 기본 차단을 Science 에서만 풀어 주는 예외 | ✅ |
| | Custom skills · 이전 작업 가져오기 · memory · auto mode | 켜짐 | 유지 | ✅ |
| | SSH hosts · Modal · scientific model endpoints | 켜짐 | 유지(본인 계정·장비로 연산. 정책연구엔 거의 안 씀) | ✅ |
| | Manage network allowlist | 꺼짐(멤버가 각자 관리) | 유지 | ✅ |
| Claude Academy (Beta) | Claude in Academy | 꺼짐 | 유지(켜도 무방) | ✅ |

## 4. Plugins & skills · Connectors · Directory (11-10 확인)
| 메뉴 | 항목 | 값 | 결정·근거 | 상태 |
|---|---|---|---|---|
| Plugins & skills → Marketplaces | jeju-inst/jaix-kit-org(GitHub, 10개, Installed by default) · Knowledge Work · Anthropic Directory · Claude for Nonprofits | 동기화 정상 | 유지 | ✅ |
| Policy | Cloud code execution · Skills · User-created skills · Skill sharing | 켜짐 | 유지 | ✅ |
| Policy | **Publishing**(조직 전체에 스킬·플러그인 게시) | **Requires review(11-10 변경)** | Open 이면 누구나 검토 없이 전원에게 게시 가능 → 관리자 검토 거치게. 선택지: Requires review / Open / Off | ✅ |
| Connectors | GitHub · Gmail · Google Calendar/Docs/Drive/Sheets/Slides · monday · Slack (9) | 조직 커넥터, 각자 계정으로 연결 | 유지(GitHub·monday 는 연구원에겐 불필요하나 보안 문제 없음) | ⏳ |
| Connectors | Limit the desktop extensions | 꺼짐 | 유지(베타) — jaix 는 플러그인 경로라 무관 | ✅ |
| Directory | 제출 내역 | 0건 | 해당 없음 | ✅ |

### 결제 실측 (11-10)
- 11/1 청구: 2석 **$80**(Nonprofit Premium 석당 월 $40). 12/1 예정액 $88 — 차액은 부가세 10% 로 보임. 예산은 처음부터 부가세 포함으로 잡혀 있음(사용자 확인).
- 결제 카드는 법인카드. 결제 카드는 구독 갱신·usage credits·auto-reload 에 쓰이나 usage credits 는 꺼 둠.

## 도메인 인증 뒤 새로 나온 것 (11-09)

- **Domain memberships**: 인증 도메인(`ji.re.kr`·`jri.re.kr`) 주소로 된 Anthropic 계정 현황. 11-09 기준 Claude Free 17 · Pro 3 · Max/Ultra 2 · Teams 1(우리 조직, 2명) · 1인 Console 2. 개인별 명단은 CSV/JSON으로 받을 수 있음(개인정보라 내려받지 않음).
- **Security → Restrict organization creation**: 인증 도메인으로 새 조직(개인 계정 포함) 생성을 막음. ⏳ 결정 대기 — 11/10 전 베타는 개인 구독 계정을 쓰므로 지금 켜면 베타 참여자가 새로 가입하지 못할 수 있음.
- **구독 범위 밖 계정**: 인증 도메인에는 Team 편입 대상이 아닌 개인 유료 계정(센터 소속 등)도 있다. 현재 설정(도메인 인증·초대 경로 차단·조직 지시문·managed settings)은 우리 조직 멤버에게만 적용돼 이 계정들에 변동이 없다. **Restrict organization creation·SSO 를 켜기 전에는 이 계정들에 주는 영향을 먼저 확인하고 당사자와 상의한다.** 개인 Pro·Max 중 편입 예정자는 11/10 좌석 배정 뒤 개인 구독 해지를 안내한다(명단은 문서에 두지 않음).
- **Merge organizations**: 다른 조직을 상위 조직으로 합침(SSO·컴플라이언스 통합). 해당 없음.
- **Single sign-on**: 이제 "Setup SSO" 가능. **보류(11-10 결정)** — 지금 되는 "Google로 계속하기"는 SSO 가 아니라 소셜 로그인. SSO 를 켜면 IdP(Google Workspace) 경유 강제·구글 정지 시 즉시 차단·JIT 가 가능해지지만, 인증 도메인의 **모든** Claude 로그인(범위 밖 개인 계정 포함)에 적용됨. 사용자 입장에선 미설정이 더 편하고, 구글 로그인·이메일 코드 모두 Workspace 계정에 묶여 있어 보안 손실이 작음.
  - **대체 통제: 퇴사 절차에 "Claude Members 에서 제거"를 넣는다**(구글 정지만으로는 이미 로그인된 세션이 남음, 좌석 비용도 이때 정리). 2단계 인증 등은 Google Workspace 정책으로 건다.

## 가입 경로 정리 (11-09)

| 경로 | 승인 | 설정 |
|---|---|---|
| 관리자 메일 초대(Members) | 관리자가 직접 | 사용 |
| 초대 링크 | 자동 승인 | **끔** |
| 멤버 초대(Member invites) | New member approval 따름(관리자 승인) | **끔** |
| 도메인 검색(Discoverable) | 관리자 승인 | 꺼짐 |
