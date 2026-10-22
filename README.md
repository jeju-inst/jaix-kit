# jaix-kit — 제주연구원 JAIX 원내 AI 도구 배포 허브

연구원 PC에 원내 AI 도구(hwp-agent, 업무일지, 그룹웨어 등)를 **한 번에 깔고, 검증된 버전으로 함께 올리는** 저장소.
도구 코드는 각자의 저장소에 있다. 여기는 "어느 도구의 어느 버전을 같이 쓰는가"만 정한다.

## 무엇이 들어 있나
| 파일 | 역할 |
|---|---|
| `.claude-plugin/marketplace.json` | **잠금 목록(lockfile)**. 도구마다 저장소 + 태그 + 40자 커밋으로 고정. Claude 마켓플레이스 형식 그대로 |
| `scripts/jaixlock.py` | `check`(고정 상태 점검) · `bump NAME REF`(수동 고정) · `update`(새 날짜 태그·커밋으로 전부 올리기) |
| `.github/workflows/ci.yml` | Windows·Linux 새 머신에서 전 플러그인 설치 시험 + 매일 태그 감시 |
| `.github/workflows/calver-tag.yml` | 재사용 워크플로. 도구 저장소가 main 머지마다 불러 날짜 태그를 단다 |
| `.github/workflows/lock-update.yml` | 갱신 봇. 매일 새 버전을 찾아 beta 갱신 PR과 beta → main 승격 PR을 연다 |
| `.github/workflows/bundle-tag.yml` | main 잠금이 바뀔 때마다 묶음 날짜 태그 |

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
       uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@main
       permissions: { contents: write }
   ```
2. 매일 06:30 KST 갱신 봇이 새 태그를 찾아 **beta 갱신 PR**(`bot/lock-update` → `beta`)을 열고 CI를 돌린다.
   → AI센터가 머지하면 파일럿 반영.
3. beta 잠금이 main 과 다르면 봇이 **승격 PR**(`beta` → `main`)을 연다. 파일럿에서 문제없으면 머지
   → 전원 자동 반영(다음 앱 시작 때) + 묶음 태그.
- 급할 때: Actions 탭에서 `lock-update` 를 수동 실행하거나, `python scripts/jaixlock.py bump <plugin> <tag>` 로 PR.
- 되돌리기: 승격 PR 을 revert 하면 이전 잠금으로 돌아간다(도구 태그는 지우지 않는다).

## 수동 설치 (관리자 콘솔 배포 전·개발자용)
```
claude plugin marketplace add jeju-inst/jaix-kit
claude plugin install calendar-worklog-ji@jaix
```

설계 근거: `docs/design.md`, 상위 표준: `ji-deploy-standards`.
