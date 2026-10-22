# jaix-kit — 제주연구원 JAIX 원내 AI 도구 배포 허브

연구원 PC에 원내 AI 도구(hwp-agent, 업무일지, 그룹웨어 등)를 **한 번에 깔고, 검증된 버전으로 함께 올리는** 저장소.
도구 코드는 각자의 저장소에 있다. 여기는 "어느 도구의 어느 버전을 같이 쓰는가"만 정한다.

## 무엇이 들어 있나
| 파일 | 역할 |
|---|---|
| `.claude-plugin/marketplace.json` | **잠금 목록(lockfile)**. 도구마다 저장소 + 태그 + 40자 커밋으로 고정. Claude 마켓플레이스 형식 그대로 |
| `scripts/jaixlock.py` | `check`(고정 상태 점검) · `bump NAME REF`(버전 올리기, sha 자동 갱신) |
| `.github/workflows/ci.yml` | Windows·Linux 새 머신에서 전 플러그인 설치 시험 + 매일 태그 감시 |

## 채널
- `main` = **stable** (전원). 관리자 콘솔이 이 브랜치를 자동 업데이트로 배포한다.
- `beta` = AI센터 파일럿. 새 버전은 beta에서 먼저 굴린 뒤 main으로 PR.

## 사용 채널 3개 (모두 같은 잠금 목록을 따른다)
1. **데스크톱 앱** — Claude Desktop(Cowork·Code 탭), Codex/ChatGPT 데스크톱
2. **CLI** — Claude Code, Codex CLI
3. **Hermes Agent + 슬랙** — CLI를 못 쓰는 사용자용 개인 봇

## 새 버전 배포 절차
1. 도구 저장소에서 semver 태그(`v0.3.0` 또는 `claude plugin tag`의 `<name>--v0.3.0`)를 단다.
2. 여기서 `python scripts/jaixlock.py bump <plugin> <tag>` → `beta` 브랜치에 PR.
3. CI 통과 + 파일럿 확인 → `main`으로 PR·머지 → 전원 자동 반영(다음 앱 시작 때).

## 수동 설치 (관리자 콘솔 배포 전·개발자용)
```
claude plugin marketplace add jeju-inst/jaix-kit
claude plugin install calendar-worklog-ji@jaix
```

설계 근거: `docs/design.md`, 상위 표준: `ji-deploy-standards`.
