"""jaix connect. 진짜 gw·mailskill·hermes·nworks·새 창은 부르지 않는다 — 가짜 call·login·window·popen 으로 시험한다."""
import subprocess
from pathlib import Path

import pytest

from jaix import cli, connect, gw, hermesbot, lock, paths, plugbin, selftest, works

LOCK_FILE = Path(__file__).resolve().parents[1] / ".claude-plugin" / "marketplace.json"
FORBIDDEN = ("hermes", "hermes-acp", "gw", "mailskill", "nworks", "claude", "osascript")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    # 진짜 외부 명령을 부르지 못하게(#115 의 hermes 사고와 같은 보호). 시험은 모두 가짜를 넘긴다
    real_popen = subprocess.Popen

    class GuardedPopen(real_popen):
        def __init__(self, args, *a, **kw):
            exe = args[0] if isinstance(args, (list, tuple)) and args else str(args)
            if Path(str(exe)).stem.lower() in FORBIDDEN or "mailskill" in str(args):
                raise AssertionError(f"시험이 외부 명령을 부름: {args}")
            super().__init__(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: None)
    monkeypatch.setattr(hermesbot, "show_console", lambda: False)
    monkeypatch.setattr(connect, "_open_url", lambda url: (_ for _ in ()).throw(AssertionError("브라우저를 엶")))
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "JAIX_DATA", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("JAIX_LOCK", str(LOCK_FILE))
    monkeypatch.setenv("JI_GW_CONFIG_DIR", str(tmp_path / "gwconf"))
    monkeypatch.setenv("HIMALAYA_CONFIG", str(tmp_path / "himalaya" / "config.toml"))
    monkeypatch.setenv("MAIL_SKILL_SECRETS", str(tmp_path / "mail" / "secrets.age"))
    for name in ("GW_BASE_URL", "GW_USER", "GW_PW"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(gw.ENV, raising=False)


@pytest.fixture
def the_lock():
    return lock.load(str(LOCK_FILE))


def _log():
    lines = []
    return lines, lines.append


# --- 상태 -----------------------------------------------------------------------------------------
def test_status_gw(monkeypatch):
    monkeypatch.setattr(gw, "source", lambda: "x")
    monkeypatch.setattr(gw, "installed_version", lambda: "1.0")
    monkeypatch.setattr(gw, "base_url", lambda: "https://gw.example")
    assert connect.status_gw(lambda u: True, lambda: True).state == "ok"
    assert connect.status_gw(lambda u: True, lambda: False).state == "missing"
    assert connect.status_gw(lambda u: True, lambda: None).state == "unknown"
    st = connect.status_gw(lambda u: False, lambda: False)
    assert st.state == "unavailable" and "원내망" in st.detail
    assert connect.status_gw(lambda u: False, lambda: True).state == "ok"  # 저장돼 있으면 원외여도 됨
    monkeypatch.setattr(gw, "source", lambda: None)
    assert connect.status_gw(lambda u: True, lambda: False).state == "unavailable"


def test_status_gw_does_not_print_address(monkeypatch):
    monkeypatch.setattr(gw, "source", lambda: "x")
    monkeypatch.setattr(gw, "installed_version", lambda: "1.0")
    monkeypatch.setattr(gw, "base_url", lambda: "http://210.127.0.1")
    for saved in (True, False):
        for reach in (True, False):
            assert "210.127" not in connect.render([connect.status_gw(lambda u: reach, lambda: saved)])


def test_status_mail(the_lock, tmp_path):
    assert connect.status_mail(the_lock).state == "missing"
    conf, secrets = selftest.mail_config_paths()
    conf.parent.mkdir(parents=True)
    conf.write_text('[accounts.ji]\nemail = "a@b"\n', encoding="utf-8")
    secrets.parent.mkdir(parents=True)
    secrets.write_text("x", encoding="utf-8")
    assert connect.status_mail(the_lock).state == "ok"


def test_status_works(monkeypatch, the_lock):
    monkeypatch.setattr(works, "plugin", lambda lk: object())
    monkeypatch.setattr(works, "logged_in", lambda: False)
    monkeypatch.setattr(works, "exe", lambda: None)
    assert connect.status_works(the_lock).state == "unavailable"
    monkeypatch.setattr(works, "exe", lambda: "/x/nworks")
    monkeypatch.setattr(works, "saved_client", lambda: None)
    assert "원내망" in connect.status_works(the_lock).detail
    monkeypatch.setattr(works, "saved_client", lambda: {"client_id": "a", "client_secret": "b"})
    assert connect.status_works(the_lock).state == "missing"
    monkeypatch.setattr(works, "logged_in", lambda: True)
    assert connect.status_works(the_lock).state == "ok"
    monkeypatch.setattr(works, "plugin", lambda lk: None)
    assert connect.status_works(the_lock) is None


def test_status_hermes(monkeypatch):
    monkeypatch.setattr(hermesbot, "recorded", lambda: {})
    assert connect.status_hermes() is None
    monkeypatch.setattr(hermesbot, "recorded", lambda: {"status": "connected", "model": "claude"})
    assert connect.status_hermes().state == "unavailable"
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    seen = []
    assert connect.status_hermes(lambda h, p: seen.append(p) or []).state == "missing"
    assert seen == [hermesbot.PROVIDERS["claude"]["provider"]]
    assert connect.status_hermes(lambda h, p: [{"label": "a"}]).state == "ok"
    assert connect.status_hermes(lambda h, p: None).state == "unknown"


# --- 항목 하나 --------------------------------------------------------------------------------------
def test_connect_gw_needs_network(monkeypatch):
    monkeypatch.setattr(paths, "which", lambda n: "/x/gw" if n == "gw" else None)
    monkeypatch.setattr(gw, "base_url", lambda: "https://gw.example")
    lines, log = _log()
    called = []
    assert connect.connect_gw(log, reachable=lambda u: False, call=called.append) == 1
    assert not called and any("원내망" in ln for ln in lines)
    assert connect.connect_gw(log, reachable=lambda u: True, call=lambda c: called.append(c) or 0) == 0
    assert called == [["/x/gw", "login"]]


def test_connect_mail_opens_guide_then_setup(monkeypatch):
    monkeypatch.setattr(paths, "which", lambda n: "/x/mailskill" if n == "mailskill" else None)
    opened, called = [], []
    lines, log = _log()
    code = connect.connect_mail(log, opener=lambda u: opened.append(u) or True, call=lambda c: called.append(c) or 3)
    assert code == 3 and opened == [connect.MAIL_GUIDE] and called == [["/x/mailskill", "setup"]]
    # 비밀번호를 인자로 넘기지 않는다
    assert not any("--password" in a for a in called[0])


def test_connect_mail_missing_tool(monkeypatch):
    monkeypatch.setattr(paths, "which", lambda n: None)
    lines, log = _log()
    assert connect.connect_mail(log, opener=lambda u: True, call=lambda c: 0) == 1
    assert "jaix setup" in lines[-1]


def test_connect_mail_opens_guide_only_once(monkeypatch):
    monkeypatch.setattr(paths, "which", lambda n: "/x/mailskill" if n == "mailskill" else None)
    opened = []
    lines, log = _log()
    for _ in range(3):
        connect.connect_mail(log, opener=lambda u: opened.append(u) or True, call=lambda c: 2)
    assert opened == [connect.MAIL_GUIDE]  # 할 때마다 탭이 쌓이지 않음(실기 11/7)
    assert sum(connect.MAIL_GUIDE in line for line in lines) == 2  # 두 번째부터는 주소만 보인다


def test_connect_mail_guide_retried_when_browser_failed(monkeypatch):
    monkeypatch.setattr(paths, "which", lambda n: "/x/mailskill" if n == "mailskill" else None)
    opened = []
    lines, log = _log()
    connect.connect_mail(log, opener=lambda u: opened.append(u) and False, call=lambda c: 2)
    connect.connect_mail(log, opener=lambda u: opened.append(u) or True, call=lambda c: 2)
    assert len(opened) == 2


def test_mail_command_skips_cmd_batch_on_windows(monkeypatch, tmp_path):
    # jaix 심 → 플러그인 사본 mailskill.cmd → mailskill.ps1. .cmd 를 거치면 Ctrl+C 에 cmd 의 Y/N 질문이 끼어든다
    cli_dir = tmp_path / "plugin" / "cli"
    cli_dir.mkdir(parents=True)
    (cli_dir / "mailskill.cmd").write_text("@echo off\r\npowershell -File \"%~dp0mailskill.ps1\" %*\r\n")
    (cli_dir / "mailskill.ps1").write_text("# ps1\n")
    shim = tmp_path / "bin" / "mailskill.cmd"
    shim.parent.mkdir()
    shim.write_text(f'@rem {plugbin.SHIM_MARK}\r\n@call "{cli_dir / "mailskill.cmd"}" %*\r\n@exit /b %ERRORLEVEL%\r\n')
    monkeypatch.setattr(connect, "IS_WIN", True)
    cmd = connect.mail_command(str(shim))
    assert cmd[0] == "powershell" and cmd[-2:] == [str(cli_dir / "mailskill.ps1"), "setup"]
    assert connect.mail_command(str(cli_dir / "mailskill.cmd"))[-2] == str(cli_dir / "mailskill.ps1")
    (cli_dir / "mailskill.ps1").unlink()  # ps1 을 못 찾으면 예전대로 .cmd
    assert "mailskill.cmd" in str(connect.mail_command(str(shim)))
    monkeypatch.setattr(connect, "IS_WIN", False)
    assert connect.mail_command("/x/mailskill") == ["/x/mailskill", "setup"]


@pytest.mark.parametrize("code", [3221225786, -1073741510, hermesbot.CANCELLED])
def test_closed_window_code_is_explained(code):
    line = connect.result_line("mail", code)
    assert "창을 닫" in line and str(code) not in line


def test_result_line_says_again_once():
    for item, table in connect.RESULT.items():
        for code in [*table, 99, hermesbot.CANCELLED, None]:
            assert connect.result_line(item, code).count("다시") <= 1, (item, code)


def test_connect_hermes_uses_saved_model(monkeypatch):
    monkeypatch.setattr(hermesbot, "recorded", lambda: {"status": "connected", "model": "claude"})
    seen = []
    assert connect.connect_hermes(print, login=lambda a, log: seen.append(a) or 0) == 0
    assert seen[0].model == "claude" and seen[0].force is False and seen[0].no_wait is False


@pytest.mark.parametrize("item,code,word", [("mail", 0, "[완료]"), ("mail", 1, "jaix setup"), ("mail", 2, "[실패]"),
                                            ("mail", 3, "로그인 확인 실패"), ("gw", 2, "아이디·비밀번호"),
                                            ("gw", 3, "취소"), ("hermes", hermesbot.ALREADY, "[완료]"),
                                            ("works", None, "[미완료]")])
def test_result_line(item, code, word):
    assert word in connect.result_line(item, code)


def test_console_items_open_new_window_when_not_a_terminal(monkeypatch):
    monkeypatch.setattr(connect, "interactive", lambda: False)
    lines, log = _log()
    opened = []
    code = connect.connect_one("mail", log, window=lambda item, log: opened.append(item) or 0,
                               runner=lambda item, log: (_ for _ in ()).throw(AssertionError("이 창에서 돌림")))
    assert code == 0 and opened == ["mail"]
    assert lines[-1].startswith("[완료] 회사메일")


class _Tty:
    def __init__(self, tty=True):
        self.tty = tty

    def isatty(self):
        return self.tty

    def fileno(self):
        return 0


def _windows_stdin(monkeypatch, console):
    """Windows 에서 stdin 이 NUL(console=False — isatty 는 True)이거나 진짜 콘솔(True)인 상태(#180)."""
    monkeypatch.setattr(paths, "IS_WIN", True)
    monkeypatch.setattr(paths, "_win_console_mode", lambda fd: console)
    monkeypatch.setattr(paths.sys, "stdin", _Tty())
    monkeypatch.setattr(paths.sys, "stdout", _Tty())


@pytest.mark.parametrize("console,where", [(False, "window"), (True, "here")])
def test_console_items_with_nul_stdin_open_new_window(monkeypatch, console, where):
    """에이전트가 stdin 을 NUL 로 두고 부르면(isatty 는 True) 이 창에서 입력을 기다리지 않고 새 창을 연다.
    시작 메뉴 'JAIX 계정 연결'(jaix.exe 가 자기 콘솔을 가짐)은 지금처럼 이 창에서 받는다."""
    _windows_stdin(monkeypatch, console)
    got = []
    connect.connect_one("mail", lambda *a: None, window=lambda item, log: got.append("window") or 0,
                        runner=lambda item, log: got.append("here") or 0, pause=lambda: None)
    assert got == [where]


def test_connect_all_with_nul_stdin_does_not_ask(monkeypatch, the_lock):
    _windows_stdin(monkeypatch, False)
    lines, log = _log()
    code = connect.connect_all(the_lock, log, sts=STS, ask=lambda q: pytest.fail(f"NUL stdin 에서 물음: {q}"),
                               runner=lambda *a: pytest.fail("연결을 시도함"))
    assert code == 1 and any("jaix connect <항목>" in ln for ln in lines)


def test_gw_and_works_run_inline_even_for_agents(monkeypatch):
    monkeypatch.setattr(connect, "interactive", lambda: False)
    for item in ("gw", "works"):
        ran = []
        connect.connect_one(item, print, window=lambda *a: (_ for _ in ()).throw(AssertionError("새 창")),
                            runner=lambda it, log: ran.append(it) or 0)
        assert ran == [item]


def test_here_writes_result_file(monkeypatch, tmp_path):
    monkeypatch.setattr(connect, "IS_WIN", False)
    f = tmp_path / "r.txt"
    assert connect.connect_one("mail", print, here=True, result_file=str(f), runner=lambda it, log: 3) == 3
    assert f.read_text(encoding="utf-8") == "3"


def test_here_waits_for_enter_on_windows_except_hermes(monkeypatch):
    monkeypatch.setattr(connect, "IS_WIN", True)
    paused = []
    connect.connect_one("mail", print, here=True, runner=lambda it, log: 0, pause=lambda: paused.append(1))
    connect.connect_one("hermes", print, here=True, runner=lambda it, log: 0, pause=lambda: paused.append(2))
    assert paused == [1]


def test_child_command():
    cmd = connect.child_command("mail", "/tmp/r.txt")
    assert cmd[-5:] == ["connect", "mail", "--here", "--result-file", "/tmp/r.txt"]


def test_new_window_windows(monkeypatch):
    monkeypatch.setattr(connect, "IS_WIN", True)
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    seen = {}

    class P:
        def __init__(self, cmd, creationflags=0):
            seen["cmd"], seen["flags"] = cmd, creationflags
            Path(cmd[-1]).write_text("0", encoding="utf-8")

        def poll(self):
            return None  # 결과를 적고 Enter 를 기다리는 중(창이 열려 있음)
    assert connect.in_new_window("mail", print, popen=P, sleep=lambda s: None) == 0
    assert seen["flags"] == 0x10 and "--here" in seen["cmd"]
    assert not Path(seen["cmd"][-1]).exists()  # 결과 파일은 지운다


def test_new_window_windows_child_exits_without_result(monkeypatch):
    monkeypatch.setattr(connect, "IS_WIN", True)
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)

    class P:
        def __init__(self, cmd, creationflags=0):
            pass

        def poll(self):
            return 5
    assert connect.in_new_window("mail", print, popen=P, sleep=lambda s: None) == 5


def test_new_window_mac_polls_result(monkeypatch):
    monkeypatch.setattr(connect, "IS_WIN", False)
    monkeypatch.setattr(connect, "IS_MAC", True)
    seen = {}

    def osa(script):
        seen["script"] = script
        return 0
    ticks = []

    def sleep(s):
        ticks.append(s)
        if len(ticks) == 2:  # 몇 번 기다린 뒤 자식이 끝남
            path = seen["script"].split("--result-file ")[1].strip().strip("'")
            Path(path).write_text("2", encoding="utf-8")
    assert connect.in_new_window("hermes", print, osascript=osa, sleep=sleep) == 2
    assert "connect hermes --here" in seen["script"]


def test_new_window_mac_times_out(monkeypatch):
    monkeypatch.setattr(connect, "IS_WIN", False)
    monkeypatch.setattr(connect, "IS_MAC", True)
    assert connect.in_new_window("mail", print, osascript=lambda s: 0, sleep=lambda s: None, limit=3) is None


# --- 전체(jaix connect) -----------------------------------------------------------------------------
STS = [connect.Status("gw", "ok", "저장된 로그인 정보 있음"), connect.Status("mail", "missing", "앱 비밀번호 설정 안 됨"),
       connect.Status("works", "unavailable", "원내망에서 jaix setup")]


def test_connect_all_non_interactive_only_shows(monkeypatch, the_lock):
    monkeypatch.setattr(connect, "interactive", lambda: False)
    lines, log = _log()
    code = connect.connect_all(the_lock, log, sts=STS,
                               runner=lambda *a: (_ for _ in ()).throw(AssertionError("연결을 시도함")))
    text = "\n".join(lines)
    assert code == 1
    assert "[됨] 그룹웨어" in text and "[연결 필요] 회사메일: 앱 비밀번호 설정 안 됨 — jaix connect mail" in text
    assert "[지금은 못 함] 웍스" in text


def test_connect_all_asks_and_runs_missing(monkeypatch, the_lock):
    monkeypatch.setattr(connect, "interactive", lambda: True)
    monkeypatch.setattr(connect, "IS_WIN", False)
    ran = []
    code = connect.connect_all(the_lock, print, sts=STS, ask=lambda q: "", runner=lambda it, log: ran.append(it) or 0)
    assert ran == ["mail"] and code == 0
    ran.clear()
    code = connect.connect_all(the_lock, print, sts=STS, ask=lambda q: "n", runner=lambda it, log: ran.append(it) or 0)
    assert ran == [] and code == 1


def test_connect_all_nothing_missing(monkeypatch, the_lock):
    monkeypatch.setattr(connect, "interactive", lambda: False)
    lines, log = _log()
    assert connect.connect_all(the_lock, log, sts=STS[:1]) == 0
    assert "연결이 필요한 항목이 없습니다." in lines


def test_cli_parses_connect(monkeypatch):
    seen = {}
    monkeypatch.setattr(connect, "connect_one", lambda item, log, here, result_file: seen.update(
        item=item, here=here, rf=result_file) or 0)
    assert cli.main(["connect", "mail", "--here", "--result-file", "x"]) == 0
    assert seen == {"item": "mail", "here": True, "rf": "x"}
    with pytest.raises(SystemExit):
        cli.main(["connect", "nope"])


def test_cli_connect_all(monkeypatch):
    seen = []
    monkeypatch.setattr(connect, "connect_all", lambda lk, log: seen.append(lk.source) or 0)
    assert cli.main(["connect", "--offline"]) == 0 and seen


def test_selftest_hints_point_to_connect():
    for item in ("gw", "mail", "works", "hermes"):
        assert f"jaix connect {item}" in selftest.CONNECT_HINT.format(item=item)
    assert "JAIX 계정 연결" in selftest.CONNECT_HINT


def test_guide_mentions_connect():
    assert "jaix connect" in cli.guide(["claude"], {})


# --- slack: 연결 코드만 넣기(설치기를 다시 돌리지 않고, 11/26) ------------------------------------------
def _hermes_pc(monkeypatch, env_lines=""):
    monkeypatch.setattr(hermesbot, "IS_WIN", True)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "hermes")
    hermesbot._save_record({"status": "no-code", "model": "chatgpt"})
    home = paths.hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text(env_lines, encoding="utf-8")


def test_status_slack(monkeypatch):
    assert connect.status_slack() is None                     # JAIX 가 Hermes 를 깔지 않은 PC
    _hermes_pc(monkeypatch)
    assert connect.status_slack().state == "missing"
    hermesbot._save_record({"status": "connected", "slack": {"id": "demo"}})
    (paths.hermes_home() / ".env").write_text("SLACK_BOT_TOKEN=b\nSLACK_APP_TOKEN=a\n", encoding="utf-8")
    st = connect.status_slack()
    assert st.state == "ok" and "Hermes-demo" in st.detail


def test_connect_code_connects(monkeypatch):
    _hermes_pc(monkeypatch)
    got = {}
    monkeypatch.setattr(hermesbot, "claim", lambda code: got.setdefault("code", code) and
                        {"id": "demo", "user": "U0T", "bot_token": "b", "app_token": "a"})
    monkeypatch.setattr(hermesbot, "connect_slack", lambda bundle, log: True)
    monkeypatch.setattr(hermesbot, "bot_room", lambda *a, **k: True)
    lines = []
    code = "jx-" + "a" * 26
    assert hermesbot.cmd_connect_code(lines.append, ask=lambda q: f"  {code} ") == 0
    assert got["code"] == code.upper() and hermesbot.recorded()["status"] == "connected"
    assert code.upper() not in "\n".join(lines)               # 코드를 화면 기록에 다시 찍지 않는다


def test_connect_code_stops_before_claim_on_foreign_bot(monkeypatch):
    _hermes_pc(monkeypatch, "SLACK_BOT_TOKEN=xoxb-OLD\n")
    monkeypatch.setattr(hermesbot, "slack_call", lambda m, t, **k: {"ok": True, "user": "hermeszh"})
    monkeypatch.setattr(hermesbot, "claim", lambda code: pytest.fail("코드를 쓰면 안 됨"))
    lines = []
    assert hermesbot.cmd_connect_code(lines.append, ask=lambda q: pytest.fail("코드를 묻지 않아야 함")) == 1
    assert "hermeszh" in "\n".join(lines) and "jaix hermes remove" in "\n".join(lines)


def test_connect_code_needs_installed_hermes_and_valid_code(monkeypatch):
    monkeypatch.setattr(hermesbot, "IS_WIN", True)
    lines = []
    assert hermesbot.cmd_connect_code(lines.append, ask=lambda q: pytest.fail("묻지 않음")) == 1
    assert "슬랙으로도 쓰기" in lines[-1]
    _hermes_pc(monkeypatch)
    monkeypatch.setattr(hermesbot, "claim", lambda code: pytest.fail("형식이 틀리면 받지 않음"))
    assert hermesbot.cmd_connect_code(print, ask=lambda q: "") == hermesbot.CANCELLED
    assert hermesbot.cmd_connect_code(print, ask=lambda q: "JX-123") == 2


def test_slack_is_a_connect_item():
    assert "slack" in connect.ITEMS and "slack" in connect.NEEDS_CONSOLE
    assert connect.result_line("slack", 0).startswith("[완료]")
