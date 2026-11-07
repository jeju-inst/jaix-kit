"""jaix helper: 시작 메뉴 'JAIX 도우미'. 명령창에서 claude 를 JAIX 도우미 스킬 내용과 함께 띄우고 "jaix 점검해줘"로 시작한다.

플러그인 jaix-help(plugins/jaix-help)가 깔리지 않은 PC 의 안전망이다. 스킬 사본은 설치본(PyInstaller)·휠에 묶여 있어
플러그인 설치가 실패해도 있다. 깔린 플러그인 사본이 있으면 그것(더 새 판)을 먼저 쓴다.
`--append-system-prompt-file` 은 Claude Code 2.1.318 에서 확인했다. 데스크톱 앱 로그인은 명령창 claude 로 **이어지지 않는다**
(Windows 실기 2026-11-06, jaix v2026.11.06.2: 빈 설정에서 `claude -p` → "Not logged in"). 그래서 처음 한 번은 명령창 claude 가
로그인을 묻는다 — 안내문으로 무엇을 고를지 미리 알려 준다.
"""
import subprocess
import sys
from pathlib import Path

from jaix import claude, hermesbot, proc, selftest
from jaix.paths import IS_WIN

PLUGIN = "jaix-help"
SKILL_REL = Path("skills") / "jaix-help" / "SKILL.md"
FIRST_PROMPT = "jaix 점검해줘"
# 도우미가 묻지 않고 돌릴 명령: 읽기 위주의 자가시험과 입력 창을 여는 계정 연결. update·setup 은 Claude 가 묻는다
ALLOWED = "Bash(jaix selftest:*),Bash(jaix connect:*)"  # selftest.ALLOWED_TOOLS 와 같은 쉼표 형식


def bundled_candidates():
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller 묶음 자리
    if base:
        yield Path(base) / "jaix-help" / "SKILL.md"
    yield Path(__file__).resolve().parent / "jaix-help.md"  # 휠에 묶은 사본
    yield Path(__file__).resolve().parents[2] / "plugins" / PLUGIN / SKILL_REL  # 소스 체크아웃


def skill_file():
    root = selftest.plugin_root(PLUGIN)
    if root and (root / SKILL_REL).is_file():
        return root / SKILL_REL
    return next((p for p in bundled_candidates() if p.is_file()), None)


def command(cli, skill):
    # 첫 요청을 맨 앞에: --allowedTools 는 값을 여럿 받아 뒤의 낱말까지 삼킨다
    return proc.command(cli, [FIRST_PROMPT, "--append-system-prompt-file", str(skill), "--allowedTools", ALLOWED])


def run(log, call=None, pause=None):
    hermesbot.show_console()  # 시작 메뉴로 연 jaix.exe 는 콘솔을 혼자 가져 숨는다(hide-early)
    cli = claude.find_cli()
    skill = skill_file()
    if not cli:
        log("명령창용 claude 를 찾지 못했습니다 → jaix-setup 을 다시 실행해 'Claude' 를 고르세요.")
        code = 1
    elif not skill:
        log("JAIX 도우미 안내문을 찾지 못했습니다 → jaix-setup 을 다시 실행하세요.")
        code = 1
    else:
        log("JAIX 도우미를 엽니다.")
        log("처음 한 번은 Claude 로그인을 묻습니다(데스크톱 앱 로그인과 따로입니다):")
        log("  로그인 방법을 고르라고 하면 1번 'Claude account with subscription' → 브라우저에서 회사 계정(@ji.re.kr)으로 승인.")
        log("비밀번호는 이 창에 쓰지 마세요 — 계정 연결은 따로 뜨는 창에 직접 넣습니다. 끝내려면 /exit")
        log("")
        try:
            code = (call or subprocess.call)(command(cli, skill))
        except OSError as e:
            log(f"claude 를 실행하지 못함: {e}")
            code = 1
    if IS_WIN and code != 0:  # 실패면 창이 바로 닫히지 않게
        try:
            (pause or input)("창을 닫으려면 Enter 를 누르세요.")
        except (EOFError, KeyboardInterrupt):
            pass
    return code
