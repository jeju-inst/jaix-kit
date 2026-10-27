# hwp-render — hwp-agent가 로컬 hwp2pdf를 먼저 쓰게 (Claude)

공통 규칙: [README.md](README.md). 태스크 #10. 기존 hwp-agent dev 세션이 맡아도 된다.

## 목표
연구원 PC(Windows + 한컴오피스)에서 hwp-agent의 PDF·미리보기 렌더가 **한컴 원본과 같은 품질**로 나오게 한다. 렌더 엔진 순서를 **로컬 `hwp2pdf-cli` → 원격 변환 서버 → rhwp(근사)** 로 정한다(2026-10-22 사용자 결정: hwp2pdf는 별도 플러그인이 아니라 런타임).

## 알려진 사실
- hwp-agent: `~/dev/hwp-agent`(공개, z0nam). 렌더 코드는 `src/hwp_agent/render/`, `verify/`. 지금 렌더는 rhwp 기반.
- hwp2pdf: `~/dev/hwp2pdf`(z0nam). Windows + 한컴 COM으로 HWP/HWPX → PDF/DOCX/HWPX. GUI + CLI(`hwp2pdf-cli`), `hwp2pdf-cli serve`(변환 서버 모드), 한컴 실패 시 rhwp 비상 변환 옵션, GitHub Releases 자동 업데이트.
- **주의(2026-05 메모)**: 예전 hwp2pdf는 변환 중 **한컴 보안경고창**이 떠서 무인 자동화에 부적합하다고 판정했었다. 지금 README는 "한컴 확인/오류 대화상자 자동 확인"을 말한다. **연구원 본인 PC에서 대화형으로 쓰는 경우와 무인 실행을 나눠 실제로 확인**하고, 경고창이 남으면 그 조건을 기록한다.
- 설치·PATH는 `jaix-setup` 세션 몫이다. 약속: `HWP2PDF_CLI` 환경변수 → PATH의 `hwp2pdf-cli` 순으로 찾는다.
- hwp-agent는 날짜 버전 자동 태그 중이다(main 머지 → `vYYYY.MM.DD.N` → Windows exe 빌드). 소스 버전은 `0.0.0+dev` 그대로 둔다.

## 범위
1. hwp-agent에 렌더 백엔드 선택 계층: `hwp2pdf`(로컬 CLI) / `remote`(설정된 변환 서버 URL) / `rhwp`. 기본은 자동(있는 것 중 앞 순서). 명시 옵션·환경변수로 강제 가능.
2. 실패 시 다음 백엔드로 넘어가되, 어느 엔진으로 렌더했는지 결과에 표시(verify 판정 신뢰도에 영향).
3. hwp2pdf 쪽 고칠 것이 있으면(예: 무인 모드 플래그, 종료 코드, stdout JSON) hwp2pdf 저장소에 **별도 PR**.
4. hwp-agent SKILL.md에 한 단락 갱신(사용량 예산 지킴).

## 실기
- namun-ji(`ssh namun-ji`, 한컴 설치 여부 먼저 확인)에서 hwp/hwpx 각 1건을 세 엔진으로 렌더해 비교. **`user` 계정 설정은 건드리지 않는다.** 한글 출력이 깨지면 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`.
- 맥에서는 hwp2pdf가 없으므로 자동으로 rhwp로 떨어지는지만 확인.

## 하지 말 것
- hwp-agent의 MCP 도구 스키마를 크게 늘리기(항상 싣는 분량 예산).
- hwp2pdf 설치 로직을 hwp-agent에 넣기(설치는 jaix-setup).
- 원격 변환 서버 주소·토큰을 코드에 박기.

## 완료 기준
- 테스트: 백엔드 선택·폴백 단위 테스트(hwp2pdf는 가짜 실행 파일로 대체).
- namun-ji 실측 결과(엔진별 성공 여부, 보안경고창 여부, 소요 시간)를 PR 본문에.
