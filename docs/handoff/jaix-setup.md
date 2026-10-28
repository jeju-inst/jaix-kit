# jaix-setup — `jaix` CLI와 `jaix-setup.exe` (Claude)

공통 규칙: [README.md](README.md). 태스크 #4.

## 목표
Windows 표준 사용자 계정에서 **관리자 권한 없이** 한 번 실행하면 JAIX 도구가 세 채널에 다 깔리는 설치 프로그램 `jaix-setup.exe`와, 그 뒤를 맡는 `jaix` CLI(`setup` · `doctor` · `update`)를 jaix-kit에 만든다. 명칭은 **jaix**로 통일(jiai·ji-ai 금지).

## 범위
1. **`jaix` CLI** (jaix-kit 저장소 안, 예: `src/jaix/`). Python + PyInstaller 단일 exe. 맥에서도 동작(개발·AI센터용).
   - `jaix setup [--channels claude,codex,hermes]`
     - 런타임 설치: uv · Git · Temurin JRE 21 · hwp2pdf(아래 약속) · (선택) himalaya · age. **winget 사용자 범위 설치**를 우선하고, 안 되면 포터블 zip을 `%LOCALAPPDATA%\Programs\jaix\` 아래에 풀고 사용자 PATH에 추가.
     - Claude 마켓플레이스 등록: 사용자 `~/.claude/settings.json`에 `extraKnownMarketplaces`(jeju-inst/jaix-kit, `autoUpdate: true`)와 잠금의 플러그인 전부를 `enabledPlugins`로 **병합**(기존 설정 보존, 쓰기 전 백업). 관리자 콘솔(11/1부터)이 같은 일을 하면 이 단계는 건너뛰도록 감지.
     - Codex: 같은 도구를 Codex에서 쓰는 방법을 확인해 등록(형식이 다르면 `jaix-win` 결과를 기다리고 그 사실을 PR에 적음).
     - Hermes: **자리만** 만든다(`--channels hermes`는 "다음 버전" 안내). 스킬 폴더 복사 함수(Windows는 심링크 대신 복사)까지만.
   - `jaix doctor`: 런타임 버전·PATH·마켓플레이스 등록·플러그인 버전이 잠금(`marketplace.json`)과 맞는지. 어긋나면 고치는 방법 한 줄. 인수 시험 0-3.
   - `jaix update`: 런타임 갱신 + Hermes 스킬 폴더를 잠금 태그에 맞춤.
2. **`jaix-setup.exe`**: Inno Setup, per-user(`PrivilegesRequired=lowest`), 관리자 권한·재부팅 없음. 체크리스트 UI(Claude / Codex / 슬랙으로도 쓰기[비활성, 다음 버전]) → `jaix setup`에 위임. 끝나면 채널별 "이렇게 쓰세요" 안내.
3. **빌드 워크플로**: `windows-latest`에서 exe와 설치본을 만들고, **jaix-kit 묶음 날짜 태그**(`bundle-tag.yml`이 다는 `vYYYY.MM.DD.N`)에서 릴리스로 올린다. 태그 값을 버전으로 찍는다.

## 참고 구현 (그대로 가져다 쓸 것)
- hwp-agent `.github/workflows/windows-exe.yml`: PyInstaller 단일 exe, JRE 동봉 Inno, 태그에서 버전 찍기(`Stamp version from tag`), 태그 실행일 때만 Publish, concurrency 분리. `installer/hwp-agent.iss`.
- 이 저장소의 `calver-tag.yml`·`bundle-tag.yml`: GITHUB_TOKEN으로 단 태그는 `push: tags` 워크플로를 깨우지 않는다 → 태그 단 워크플로에서 `gh workflow run <빌드>.yml --ref <tag>` 로 부른다.
- `~/dev/ji-deploy-standards/README.md` 3.2: 설치 프로그램은 얇게, 실제 일은 CLI에 위임.

## 약속 (다른 세션과)
- hwp2pdf: GitHub `z0nam/hwp2pdf` 릴리스에서 받아 설치하고 **`hwp2pdf-cli`를 사용자 PATH에** 올린다. hwp2pdf는 한컴오피스가 있는 Windows에서만 의미가 있으므로, 한컴이 없으면 설치는 하되 doctor에 "한컴 없음 → rhwp 근사 렌더로 대체" 표시. hwp-agent 쪽(`hwp-render` 세션)은 PATH만 본다.
- `jaix-win`의 `docs/field-test-namun-ji.md`가 머지되면 결과대로 조정한다. 그 전엔 Cowork에서 로컬 MCP가 안 되는 경우도 안내문에 대비한다.

## 하지 말 것
- 관리자 권한 요구, 시스템 PATH 수정, 재부팅.
- 사용자 설정 파일 **덮어쓰기**(반드시 병합 + 백업).
- `marketplace.json` 수정(봇 몫).
- 토큰·비밀을 설치본에 넣기. 개인 자격증명은 Windows 자격 증명 관리자/DPAPI에 둔다(이번 범위에서는 쓸 일 없음).

## 완료 기준
- CI(windows-latest)에서: 설치본 빌드 → 무인 설치(`/VERYSILENT /CURRENTUSER`) → `jaix doctor` 통과 → 제거까지.
- 맥에서 `jaix doctor` 동작.
- namun-ji `jaix-test` 실기는 `jaix-win` 세션 또는 사용자에게 체크리스트로 넘긴다(PR에 체크리스트 포함).
- 크면 PR을 나눈다: ① CLI ② 설치본·워크플로.
