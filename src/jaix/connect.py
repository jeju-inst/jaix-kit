"""jaix connect: 본인 비밀이 필요한 첫 설정(그룹웨어·회사메일·웍스·Hermes AI 구독)을 여는 곳.

- `jaix connect` 는 항목별 상태(됨/안 됨)를 보이고, 명령창이면 안 된 것을 하나씩 물어 연결한다.
  시작 메뉴 'JAIX 계정 연결' 이 이것을 연다.
- `jaix connect <항목>` 은 그 항목의 입력 창을 연다. 비밀번호는 **사용자가 그 창에 직접** 넣는다. jaix 는 값을
  인자로 넘기거나 읽지 않는다(상태는 있음/없음만 본다 — selftest 와 같은 함수).
  - gw: `gw login` (에이전트가 부르면 gw 가 스스로 입력 창을 띄운다). 원내망일 때만.
  - mail: 앱 비밀번호 발급 안내를 브라우저로 열고 `mailskill setup` (숨김 입력이라 진짜 콘솔이 필요)
  - works: `jaix works login` (브라우저)
  - hermes: `jaix hermes login` (설치 때 고른 AI 구독)
- 에이전트(Claude·Codex)가 부르면 표준 입력이 콘솔이 아니다. 콘솔이 필요한 항목(mail·hermes)은 **새 창**을 열어
  거기서 입력받고, 끝날 때까지 기다려 결과를 한 줄로 알린다.
"""
import os
import shlex
import subprocess
import sys
import tempfile
import time
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from jaix import gw, hermesbot, paths, proc, selftest, works
from jaix.paths import IS_MAC, IS_WIN

ITEMS = ("gw", "mail", "works", "hermes")
LABEL = {"gw": "그룹웨어", "mail": "회사메일", "works": "웍스", "hermes": "Hermes AI 구독"}
NEEDS_CONSOLE = {"mail", "hermes"}  # 숨김 입력·기기 코드를 콘솔에서 받는다. gw 는 스스로 창을 띄우고 웍스는 브라우저
MAIL_GUIDE = "https://github.com/z0nam/mail-skill/blob/main/plugins/mail-skill/docs/naver-works-app-password.md"
WAIT_LIMIT = 30 * 60  # 새 창에서 입력을 기다리는 최대 시간
POLL = 1.0
HINT = selftest.CONNECT_HINT

# 종료 코드의 뜻. gw: jaix-gw skills/gw/SKILL.md · mail: mail-skill scripts/mail-setup(.ps1) 머리 주석
GW_RESULT = {0: "완료 — 로그인 정보를 이 PC 에 저장함",
             2: "로그인 실패 — 대개 아이디·비밀번호가 틀림. 확인한 뒤 다시",
             3: "취소했거나 5분 동안 입력하지 않음",
             4: "입력 창을 띄울 수 없음 — 명령창을 직접 열어 gw login"}
MAIL_RESULT = {0: "완료 — 앱 비밀번호를 저장하고 로그인까지 확인함",
               1: "메일 도구 런타임이 없음 — jaix setup 을 다시 실행한 뒤 다시",
               2: "입력을 받을 창(터미널)이 아니라 시작하지 못함 — 시작 메뉴 'JAIX 계정 연결' 에서 다시",
               3: "앱 비밀번호는 저장됐지만 로그인 확인 실패 — 웍스에서 앱 비밀번호를 새로 발급해 다시"}
WORKS_RESULT = {0: "완료 — 웍스에 로그인함"}
HERMES_RESULT = {0: "완료 — AI 구독에 로그인함", hermesbot.ALREADY: "이미 로그인돼 있어 그대로 둠",
                 hermesbot.CANCELLED: "취소함"}
RESULT = {"gw": GW_RESULT, "mail": MAIL_RESULT, "works": WORKS_RESULT, "hermes": HERMES_RESULT}
DONE = {"gw": {0}, "mail": {0}, "works": {0}, "hermes": {0, hermesbot.ALREADY}}


@dataclass
class Status:
    item: str
    state: str  # ok · missing(연결 필요) · unavailable(지금은 못 함) · unknown(확인 못 함)
    detail: str = ""


# --- 상태(값은 읽지 않고 있음/없음만) -----------------------------------------------------------------
def status_gw(reachable=None, saved=None):
    if not gw.source():
        return Status("gw", "unavailable", "끔 (--gw-source none)")
    if not (gw.installed_version() or paths.which(gw.EXE)):
        return Status("gw", "unavailable", "gw 가 설치되지 않음 — 원내망에서 jaix setup")
    have = (saved or selftest.gw_login_saved)()
    if have:
        return Status("gw", "ok", "저장된 로그인 정보 있음")
    url = gw.base_url()
    if not url or not (reachable or selftest.gw_reachable)(url):
        return Status("gw", "unavailable", "원내망(사무실·VPN)에서만 연결할 수 있음")
    if have is None:
        return Status("gw", "unknown", "저장 여부를 확인하지 못함")
    return Status("gw", "missing", "저장된 로그인 정보 없음")


def status_mail(lock):
    if not any(p.name == selftest.MAIL_PLUGIN for p in lock.plugins):
        return None
    res = selftest.check_mail(lock)
    if res and res[0].status == "ok":
        return Status("mail", "ok", "앱 비밀번호 설정 있음")
    return Status("mail", "missing", "앱 비밀번호 설정 안 됨")


def status_works(lock):
    if not works.plugin(lock):
        return None
    if works.logged_in():
        return Status("works", "ok", "로그인돼 있음")
    if not works.exe():
        return Status("works", "unavailable", "웍스 도구가 설치되지 않음 — jaix setup")
    if not works.saved_client():
        return Status("works", "unavailable", "기관 앱 정보가 없음 — 원내망(사무실·VPN)에서 jaix setup")
    return Status("works", "missing", "아직 로그인 안 함")


def hermes_model():
    return hermesbot.recorded().get("model") or "chatgpt"


def status_hermes(credentials=None):
    rec = hermesbot.recorded()
    if not rec.get("status"):
        return None
    hermes = hermesbot.find_hermes()
    if not hermes:
        return Status("hermes", "unavailable", "Hermes 가 설치되지 않음 — jaix setup --channels hermes")
    model = hermes_model()
    provider = hermesbot.PROVIDERS.get(model, hermesbot.PROVIDERS["chatgpt"])["provider"]
    rows = (credentials or hermesbot.credentials)(hermes, provider)  # `hermes auth list` — 이름만
    if rows is None:
        return Status("hermes", "unknown", "로그인 목록을 읽지 못함")
    if rows:
        return Status("hermes", "ok", f"{model} 로그인돼 있음")
    return Status("hermes", "missing", f"{model} 에 아직 로그인 안 함")


def statuses(lock):
    """적용되는 항목만, ITEMS 순서로."""
    out = []
    for fn in (status_gw, lambda: status_mail(lock), lambda: status_works(lock), status_hermes):
        try:
            st = fn()
        except Exception as e:  # noqa: BLE001 — 한 항목이 막혀도 나머지를 보인다
            st = Status("?", "unknown", f"확인 중 오류: {type(e).__name__}")
        if st:
            out.append(st)
    return out


MARK = {"ok": "[됨]", "missing": "[연결 필요]", "unavailable": "[지금은 못 함]", "unknown": "[모름]"}


def render(sts):
    lines = []
    for s in sts:
        line = f"{MARK[s.state]} {LABEL.get(s.item, s.item)}: {s.detail}"
        if s.state == "missing":
            line += f" — jaix connect {s.item}"
        lines.append(line)
    return "\n".join(lines)


# --- 항목 하나를 이 창에서 연결 -----------------------------------------------------------------------
def _open_url(url):
    try:
        if IS_WIN:
            os.startfile(url)  # noqa: S606 — 기본 브라우저
            return True
        import webbrowser
        return bool(webbrowser.open(url))
    except OSError:
        return False


def _call(cmd):
    """이 콘솔을 그대로 물려주고(입력을 사용자가 직접) 종료 코드만 받는다. Ctrl+C 는 취소(130)."""
    p = subprocess.Popen(cmd)
    try:
        return p.wait()
    except KeyboardInterrupt:
        try:
            return p.wait(timeout=10) or hermesbot.CANCELLED
        except subprocess.TimeoutExpired:
            p.kill()
            return hermesbot.CANCELLED


def connect_gw(log, reachable=None, call=None):
    exe = paths.which(gw.EXE)
    if not exe:
        log("gw 가 설치되지 않았습니다 → 원내망(사무실·VPN)에서 jaix setup 을 다시 실행하세요.")
        return 1
    url = gw.base_url()
    if not url or not (reachable or selftest.gw_reachable)(url):
        log("그룹웨어에 닿지 않습니다. 원내망(사무실·VPN)에서 다시 하세요.")
        return 1
    log("그룹웨어 로그인 창이 뜹니다. 본인 아이디·비밀번호를 그 창에 직접 넣으세요.")
    return (call or _call)(proc.command(exe, ["login"]))


def connect_mail(log, opener=None, call=None):
    exe = paths.which("mailskill")
    if not exe:
        log("메일 도구(mailskill)를 찾지 못했습니다 → jaix setup 을 다시 실행한 뒤 새 창에서 다시 하세요.")
        return 1
    log("1) 브라우저에 '웍스 앱 비밀번호 발급' 안내를 엽니다. 안내대로 앱 비밀번호를 발급하세요.")
    if not (opener or _open_url)(MAIL_GUIDE):
        log(f"   브라우저를 열지 못했습니다. 주소창에 붙여 넣으세요: {MAIL_GUIDE}")
    log("2) 아래에서 묻는 곳에 발급한 앱 비밀번호를 붙여 넣으세요. 입력한 글자는 화면에 보이지 않는 것이 정상입니다.")
    log("")
    return (call or _call)(proc.command(exe, ["setup"]))


def connect_works(log, login=None):
    return (login or works.login)(log)


def connect_hermes(log, login=None, wait=True):
    args = Namespace(model=hermes_model(), no_wait=not wait, force=False)
    return (login or hermesbot.cmd_login)(args, log)


def run_here(item, log, **kw):
    fn = {"gw": connect_gw, "mail": connect_mail, "works": connect_works, "hermes": connect_hermes}[item]
    return fn(log, **kw)


def meaning(item, code):
    if code is None:
        return "결과를 받지 못함(창을 닫았거나 시간이 지남)"
    return RESULT[item].get(code) or f"끝나지 않음(코드 {code}) — 창의 안내를 확인하고 다시"


def result_line(item, code):
    ok = code in DONE[item]
    return f"{'[완료]' if ok else '[미완료]'} {LABEL[item]}: {meaning(item, code)}" + \
        ("" if ok else f" — 다시: {HINT.format(item=item)}")


# --- 새 창에서 연결(에이전트가 부를 때) -----------------------------------------------------------------
def interactive():
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def child_command(item, result_file):
    return [*paths.self_command(), "connect", item, "--here", "--result-file", str(result_file)]


def _read_code(path):
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def in_new_window(item, log, popen=None, osascript=None, sleep=time.sleep, limit=WAIT_LIMIT):
    """새 콘솔 창에서 `jaix connect <item> --here` 를 돌리고 끝나길 기다린다. 종료 코드(모르면 None)."""
    fd, name = tempfile.mkstemp(prefix="jaix-connect-", suffix=".txt")
    os.close(fd)
    os.unlink(name)  # 자식이 끝날 때 만든다 — 있으면 끝난 것
    cmd = child_command(item, name)
    try:
        if IS_WIN:
            p = (popen or subprocess.Popen)(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            # 자식은 결과를 적은 뒤 Enter 를 기다린다 — 창을 닫지 않고 돌아와도 막히지 않게 결과 파일을 본다
            waited = 0.0
            while waited < limit:
                got = _read_code(name)
                if got is not None:
                    return got
                code = p.poll()
                if code is not None:
                    got = _read_code(name)
                    return got if got is not None else code
                sleep(POLL)
                waited += POLL
            return None
        if IS_MAC:
            script = " ".join(shlex.quote(c) for c in cmd)
            run = osascript or (lambda s: subprocess.run(
                ["osascript", "-e", f'tell application "Terminal" to do script "{s}"',
                 "-e", 'tell application "Terminal" to activate'], capture_output=True).returncode)
            if run(script.replace("\\", "\\\\").replace('"', '\\"')) != 0:
                log("터미널 창을 열지 못했습니다.")
                return None
            waited = 0.0
            while waited < limit:
                got = _read_code(name)
                if got is not None:
                    return got
                sleep(POLL)
                waited += POLL
            return None
        log("이 OS 에서는 새 창을 열 수 없습니다. 터미널을 열어 직접 실행하세요: jaix connect " + item)
        return None
    finally:
        Path(name).unlink(missing_ok=True)


def connect_one(item, log, here=False, result_file=None, window=None, runner=None, pause=None):
    """항목 하나. here 면 이 창에서, 아니면 콘솔이 필요한 항목은 새 창에서. 종료 코드를 돌려준다."""
    if here:
        hermesbot.show_console()  # jaix.exe 는 콘솔을 혼자 가지면 숨는다(hide-early) — 입력을 받으려면 보여야 한다
    code = None
    try:
        if item in NEEDS_CONSOLE and not here and not interactive():
            log(f"{LABEL[item]} 입력 창을 새로 엽니다. 그 창에서 직접 입력하세요(이 창은 끝날 때까지 기다립니다).")
            code = (window or in_new_window)(item, log)
        else:
            code = (runner or run_here)(item, log)
    finally:
        if result_file:
            try:
                Path(result_file).write_text(str(1 if code is None else code), encoding="utf-8")
            except OSError:
                pass
    log("")
    log(result_line(item, code))
    if here and IS_WIN and item != "hermes":  # hermes login 은 스스로 Enter 를 기다린다
        (pause or _pause)()
    return 1 if code is None else code


def _pause(ask=None):
    try:
        (ask or input)("창을 닫으려면 Enter 를 누르세요.")
    except (EOFError, KeyboardInterrupt):
        pass


def _yes(question, ask=None):
    try:
        answer = (ask or input)(question)
    except (EOFError, KeyboardInterrupt):
        return False
    return str(answer).strip().lower() in ("", "y", "yes", "예", "네", "ㅛ")


def connect_all(lock, log, ask=None, runner=None, sts=None):
    """`jaix connect`: 상태를 보이고, 명령창이면 연결 필요한 것을 하나씩 물어 연결한다."""
    hermesbot.show_console()
    sts = statuses(lock) if sts is None else sts
    log("JAIX 계정 연결 — 비밀번호는 뜨는 창에 본인이 직접 넣습니다(jaix·AI 는 값을 받지 않음).")
    log("")
    log(render(sts) or "연결할 항목이 없습니다.")
    todo = [s for s in sts if s.state == "missing"]
    if not todo:
        if sts:
            log("")
            log("연결이 필요한 항목이 없습니다.")
        code = 0
    elif not interactive():
        log("")
        log("항목마다 `jaix connect <항목>` 으로 연결하세요(새 창이 열립니다).")
        code = 1
    else:
        code = 0
        for s in todo:
            log("")
            if not _yes(f"{LABEL[s.item]} 을(를) 지금 연결할까요? [Y/n] ", ask):
                log("  건너뜀")
                code = 1
                continue
            got = (runner or run_here)(s.item, log)
            log(result_line(s.item, got))
            if got not in DONE[s.item]:
                code = 1
    if IS_WIN and interactive():
        _pause(ask)
    return code
