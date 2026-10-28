# JAIX 작업 인계 (2026-10-27)

11/10 연구직 전원 배포까지 남은 일을 세션별로 나눠 맡긴다. 이 폴더의 문서 하나가 세션 하나의 일이다.
**조율 세션은 `jaix-kit-dev`(Claude)** 이고, 거기서는 인계·머지 판단만 한다. 각 세션은 PR까지만 만들고 **머지하지 않는다.**
운영 규칙(이름·직접 메시지·위임 머지·사용자 권한 사전 점검·정리·장부)은 전역 규칙 [`agent-rules/docs/orchestration.md`](https://github.com/z0nam/agent-rules/blob/main/docs/orchestration.md)를 따른다.

## 세션 배정

| 세션 이름 | 에이전트 | 문서 | 저장소 | 동시 시작 |
|---|---|---|---|---|
| `jaix-win` | Claude | [jaix-win.md](jaix-win.md) | jaix-kit (+ namun-ji 실기) | ✅ |
| `jaix-setup` | Claude | [jaix-setup.md](jaix-setup.md) | jaix-kit | ✅ |
| `hwp-render` | Claude (기존 hwp-agent dev 세션도 가능) | [hwp-render.md](hwp-render.md) | hwp-agent, hwp2pdf | ✅ |
| `worklog-slim` | Claude | [worklog-slim.md](worklog-slim.md) | calendar-worklog | ✅ |
| `gw-share` | Claude | [gw-share.md](gw-share.md) | ji-gw-ai (+ 새 공유 저장소) | ✅ |
| `jaix-intake` | agy | [jaix-intake.md](jaix-intake.md) | ji-project-template, korea-rio-mcp, jaix-kit | ✅ |

- 에이전트 배정 기준: 범위·완료 기준이 분명한 일은 agy, 판단이 들어가거나 민감한 일(비밀·관리자 경로·실사용자 동작 보존·실기 측정)은 Claude.
- 나중 차례(지금 시작하지 않음): 규정 Q&A 원격 MCP, mail-skill Windows 검증, 웍스 `nworks` 안내, Hermes 슬랙 채널 자동화. `jaix-win`·`jaix-setup` 결과를 보고 연다.

## 세션 사이의 약속 (인터페이스)

- **hwp2pdf 위치**: `jaix-setup`이 hwp2pdf를 설치하고 `hwp2pdf-cli`를 사용자 PATH에 올린다. `hwp-render`(hwp-agent)는 `HWP2PDF_CLI` 환경변수 → PATH의 `hwp2pdf-cli` 순으로 찾는다. 둘 다 이 약속만 믿고 상대 저장소를 고치지 않는다.
- **실측 결과**: `jaix-win`이 `docs/field-test-namun-ji.md`에 채널별 결과를 쓴다. `jaix-setup`은 그 결과가 머지되면 반영하고, 그 전에는 "Cowork에서 로컬 실행이 안 되는 경우"까지 대비해 만든다.
- **잠금 파일** `.claude-plugin/marketplace.json`은 갱신 봇과 `scripts/jaixlock.py`만 고친다. 새 도구를 넣는 `jaix-intake`만 예외로 entry를 추가한다.

## 모든 세션 공통 규칙

전역 규칙(`~/dev/agent-rules/GLOBAL.md`)이 우선이다. 이 작업에서 특히 지킬 것:

1. **PR로만 고친다.** 브랜치 → 커밋 → push → `gh pr create`. main 직접 push 금지. **머지는 하지 않는다**(조율 세션이 판단).
2. **원본 체크아웃 `~/dev/<repo>`에서 브랜치를 바꾸지 않는다.** launchd·스킬 심링크가 그 폴더를 직접 실행한다. 작업은 `git -C ~/dev/<repo> worktree add ~/.local/share/agent-worktrees/<repo>-<주제> -b <브랜치> origin/main` 에서 한다.
3. **PR 제목 앞에 `[jaix:<세션 이름>]`** 을 붙인다. 조율 세션이 `gh search prs "[jaix:" --state open` 으로 모은다.
4. PR 본문 끝 서명: `작성: 조남운 · <에이전트>/<세션 이름> · <날짜>`.
5. PR을 만들면 `pr-watch <PR URL>` 을 백그라운드로 띄우고, 지적 처리·재리뷰 규칙은 `GLOBAL.md` 그대로 따른다(P1만 재리뷰, 리뷰 총 3회 상한).
6. **비밀·토큰·개인정보를 커밋하지 않는다.** jaix-kit과 플러그인 저장소는 공개다.
7. **plugin.json에 `version`을 넣지 않는다.** 버전은 날짜 태그(`vYYYY.MM.DD.N`)가 자동으로 정한다. README "버전" 절 참고.
8. **Windows가 1급 타깃이다.** 연구원은 대부분 Windows 비개발자. 맥에서만 되는 것은 완료가 아니다.
9. **사용량 예산**: 플러그인이 항상 싣는 분량(설명·스킬 frontmatter·MCP 도구 스키마) 합계 3k 토큰 이하, 호출 한 번에 싣는 분량 10k 이하. 연구원 좌석은 Pro의 약 1.25배라 한도에 걸리는 것도 실패다.
10. 판단이 갈리는 지점(문서에 "멈추고 보고"라고 적힌 곳 포함)에서는 혼자 정하지 말고 사용자에게 묻는다.

## 끝낼 때 보고 형식

마지막 메시지를 아래 형식으로 **조율 세션에 직접 보낸다**(Claude Code: `SendMessage`, 받는 쪽 `jaix-kit-dev`). 세션 간 메시지가 닿지 않는 에이전트(agy)만 사용자가 전달한다.

```
[jaix 완료 보고] 세션=<이름> 에이전트=<claude|agy>
PR: <URL> (pr-watch 결과: CLEAN | FINDINGS 처리 n건, 리뷰 n/3회)
확인한 것: <실제로 돌려 본 명령·실기 결과>
확인 못 한 것: <안 돌린 것과 이유>
조율 세션이 판단할 것: <머지 순서·다른 세션과 겹치는 부분·사용자 결정 필요 사항>
사용자만 할 수 있는 단계: <저장소 생성·키·시크릿·조직 정책·재설치·브라우저 인증 등. 없으면 "없음">
```

"사용자만 할 수 있는 단계"는 작업을 **시작할 때** 먼저 뽑아 조율 세션에 알린다. 끝에서야 드러나면 일정이 밀린다.

## 배경 문서

- 설계: [`../design.md`](../design.md) · 실업무 인수 시험: [`../acceptance-tests.md`](../acceptance-tests.md) · 버전·배포 경로: [`../../README.md`](../../README.md)
- 전체 계획: `~/.claude/plans/11-10-dreamy-sonnet.md` (맥 로컬)
- 배포 표준(구판): `~/dev/ji-deploy-standards/README.md`
