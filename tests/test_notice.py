"""새 판 알림(jaix notice): Claude 세션 시작 훅·Hermes 게이트웨이 훅. 설치는 하지 않는다."""
import ast
import json
import time
import types

import pytest

from jaix import cli, hermesbot, hermesnotice, paths, selfupdate


@pytest.fixture
def su(tmp_path, monkeypatch):
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "JAIX_DATA", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setattr(selfupdate, "IS_WIN", True)
    monkeypatch.setattr(selfupdate, "__version__", "2026.11.21.1")
    monkeypatch.setattr(paths, "exe_dir", lambda: tmp_path / "app" / "jaix")
    return tmp_path


def release(tag="v2026.11.24.1", body=""):
    return {"tag_name": tag, "body": body, "assets": [
        {"name": "jaix-setup.exe", "browser_download_url": f"https://x/{tag}/jaix-setup.exe", "digest": "sha256:00"}]}


def test_pending_notice_once_per_interval(su):
    st = selfupdate.pending_notice("claude", now=1000.0, fetch=release)
    assert st and "2026.11.24.1" in selfupdate.notice_text(st) and "JAIX 업데이트" in selfupdate.notice_text(st)
    selfupdate.mark_noticed("claude", st, now=1000.0)
    assert selfupdate.pending_notice("claude", now=1000.0 + 3600, fetch=release) is None  # 하루 안
    assert selfupdate.pending_notice("hermes", now=1000.0 + 3600, fetch=release)  # 채널마다 따로
    assert selfupdate.pending_notice("claude", now=1000.0 + 25 * 3600, fetch=release)


def test_new_version_is_noticed_again_right_away(su):
    st = selfupdate.pending_notice("hermes", now=1000.0, fetch=release)
    selfupdate.mark_noticed("hermes", st, now=1000.0)
    st = selfupdate.check(force=True, fetch=lambda: release("v2026.11.25.1"), now=2000.0)
    assert selfupdate.pending_notice("hermes", now=2000.0, fetch=release)["latest"] == "2026.11.25.1"


def test_critical_release_reminds_hourly(su):
    rel = lambda: release(body="jaix-priority: critical")  # noqa: E731
    st = selfupdate.pending_notice("hermes", now=1000.0, fetch=rel)
    assert selfupdate.notice_text(st).startswith("[중요]")
    selfupdate.mark_noticed("hermes", st, now=1000.0)
    assert selfupdate.pending_notice("hermes", now=1000.0 + 1800, fetch=rel) is None
    assert selfupdate.pending_notice("hermes", now=1000.0 + 3700, fetch=rel)


def test_no_notice_when_current_or_dev_or_offline(su, monkeypatch):
    assert selfupdate.pending_notice("claude", fetch=lambda: release("v2026.11.21.1")) is None

    def offline():
        raise OSError("offline")
    selfupdate.save_state({})
    assert selfupdate.pending_notice("claude", fetch=offline) is None
    monkeypatch.setattr(selfupdate, "__version__", "0.0.0+dev")
    assert selfupdate.pending_notice("claude", fetch=release) is None


def test_cmd_notice_claude_prints_ascii_hook_json(su, monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "_fetch", lambda timeout=15: release())
    assert cli.main(["notice", "--for", "claude"]) == 0
    out = capsys.readouterr().out
    assert out.isascii()
    data = json.loads(out)
    assert "2026.11.24.1" in data["systemMessage"]
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert cli.main(["notice", "--for", "claude"]) == 0 and capsys.readouterr().out == ""  # 같은 날 다시 안 함


def test_cmd_notice_is_silent_on_errors(su, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(selfupdate, "pending_notice", boom)
    assert cli.main(["notice", "--for", "claude"]) == 0 and capsys.readouterr().out == ""


def test_hermes_send_marks_only_on_success(su, monkeypatch):
    monkeypatch.setattr(selfupdate, "_fetch", lambda timeout=15: release())
    sent = []
    monkeypatch.setattr(hermesnotice, "send_owner", lambda text: sent.append(text) and False)
    assert cli.main(["notice", "--for", "hermes", "--send"]) == 0
    assert len(sent) == 1 and not (selfupdate.load_state().get("noticed") or {}).get("hermes")  # 실패 → 다음에 다시
    monkeypatch.setattr(hermesnotice, "send_owner", lambda text: sent.append(text) or True)
    assert cli.main(["notice", "--for", "hermes", "--send"]) == 0
    assert selfupdate.load_state()["noticed"]["hermes"]["version"] == "2026.11.24.1"
    assert cli.main(["notice", "--for", "hermes", "--send"]) == 0 and len(sent) == 2


def test_send_owner_posts_to_home_channel(su, monkeypatch):
    monkeypatch.setattr(hermesbot, "linked_id", lambda: "yjkang")
    env = {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_HOME_CHANNEL": "D123"}
    monkeypatch.setattr(hermesbot, "env_value", env.get)
    calls = []
    ok = hermesnotice.send_owner("hi", call=lambda m, t, **p: calls.append((m, p)) or {"ok": True})
    assert ok and calls == [("chat.postMessage", {"channel": "D123", "text": "hi"})]
    monkeypatch.setattr(hermesbot, "linked_id", lambda: None)
    assert not hermesnotice.send_owner("hi", call=lambda *a, **k: {"ok": True})


def test_install_hook_writes_valid_handler_once(su):
    logs = []
    assert hermesnotice.install(logs.append, cmd=[r"C:\jaix\jaix.exe"])
    d = hermesnotice.hook_dir()
    handler = (d / "handler.py").read_text(encoding="utf-8")
    ast.parse(handler)
    assert r"CMD = ['C:\\jaix\\jaix.exe']" in handler and "gateway:startup" in (d / "HOOK.yaml").read_text(encoding="utf-8")
    assert hermesnotice.install(logs.append, cmd=[r"C:\jaix\jaix.exe"]) and len(logs) == 1  # 같으면 그대로


def test_handler_throttles_and_runs_in_background(su, monkeypatch):
    hermesnotice.install(lambda m: None, cmd=["jaix"])
    ns = {}
    exec((hermesnotice.hook_dir() / "handler.py").read_text(encoding="utf-8"), ns)
    started = []

    class T:
        def __init__(self, target, args, daemon):
            started.append(args)

        def start(self):
            pass
    ns["threading"] = types.SimpleNamespace(Thread=T)  # 이 실행의 이름공간만 바꾼다
    ns["handle"]("gateway:startup", {})
    ns["handle"]("agent:end", {})  # 한 시간 안 → 건너뜀
    assert started == [(120,)]
    ns["_last"][0] = time.time() - 3700
    ns["handle"]("agent:end", {})
    assert started == [(120,), (0,)]


def test_plugin_hook_calls_notice_and_never_fails():
    from pathlib import Path
    hooks = json.loads((Path(__file__).parents[1] / "plugins/jaix-help/hooks/hooks.json").read_text(encoding="utf-8"))
    cmd = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "jaix notice --for claude" in cmd and cmd.endswith("|| true")
