"""jaix 본체 자기 업데이트(selfupdate). 네트워크·설치기 실행은 가짜로 바꾼다."""
import argparse
import hashlib
import json
from pathlib import Path

import pytest

from jaix import cli, doctor, hermesbot, paths, schedule, selfupdate

PAYLOAD = b"MZ fake jaix-setup"
DIGEST = "sha256:" + hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def su(tmp_path, monkeypatch):
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "JAIX_DATA", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setattr(selfupdate, "IS_WIN", True)
    monkeypatch.setattr(selfupdate, "__version__", "2026.11.04.7")
    monkeypatch.setattr(paths, "exe_dir", lambda: tmp_path / "app" / "jaix")
    monkeypatch.setattr(hermesbot, "recorded", lambda: {})
    return tmp_path


def release(tag="v2026.11.05.1", digest=DIGEST, body=""):
    return {"tag_name": tag, "body": body, "assets": [
        {"name": "jaix-windows.zip", "browser_download_url": "https://x/zip", "digest": "sha256:00"},
        {"name": "jaix-setup.exe", "browser_download_url": f"https://x/{tag}/jaix-setup.exe", "digest": digest}]}


def fake_download(data=PAYLOAD, calls=None):
    def dl(url, dest):
        if calls is not None:
            calls.append(url)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(data)
        return dest
    return dl


def test_parse_version_and_dev_build_is_not_compared(su, monkeypatch):
    assert selfupdate.parse_version("v2026.11.05.1") == (2026, 11, 5, 1)
    assert selfupdate.parse_version("2026.11.04.7") < selfupdate.parse_version("v2026.11.04.10")
    assert selfupdate.current() == (2026, 11, 4, 7) and selfupdate.applies()
    monkeypatch.setattr(selfupdate, "__version__", "0.0.0+dev")
    assert selfupdate.current() is None and not selfupdate.applies()


def test_check_finds_newer_and_respects_interval(su):
    calls = []
    fetch = lambda: calls.append(1) or release()  # noqa: E731
    st = selfupdate.check(fetch=fetch, now=1000.0)
    assert st["newer"] and st["latest"] == "2026.11.05.1" and st["digest"] == DIGEST and not st["critical"]
    assert st["url"].endswith("/jaix-setup.exe")
    selfupdate.check(fetch=fetch, now=1000.0 + 5 * 3600)  # 6시간 안 → 묻지 않음
    assert len(calls) == 1
    selfupdate.check(fetch=fetch, now=1000.0 + 6 * 3600)
    assert len(calls) == 2
    assert not selfupdate.check(force=True, fetch=lambda: release("v2026.11.04.7"))["newer"]  # 같은 판


def test_critical_release_checks_hourly(su):
    calls = []
    fetch = lambda: calls.append(1) or release(body="급함\njaix-priority: critical\n")  # noqa: E731
    assert selfupdate.check(fetch=fetch, now=0.0)["critical"]
    selfupdate.check(fetch=fetch, now=3601.0)
    assert len(calls) == 2


def test_check_failure_retries_next_time(su):
    def boom():
        raise OSError("offline")
    st = selfupdate.check(fetch=boom, now=5000.0)
    assert "offline" in st["error"] and not st.get("checked_at")
    calls = []
    selfupdate.check(fetch=lambda: calls.append(1) or release(), now=5001.0)
    assert calls == [1]


def test_fetch_installer_verifies_sha256(su):
    st = selfupdate.check(force=True, fetch=release)
    path = selfupdate.fetch_installer(st, lambda m="": None, download=fake_download())
    assert path and path.read_bytes() == PAYLOAD and path.parent == su / "jaix_data" / "updates"
    calls = []  # 이미 받아 둔 것이 맞으면 다시 받지 않는다
    assert selfupdate.fetch_installer(st, lambda m="": None, download=fake_download(calls=calls)) == path and not calls


def test_fetch_installer_rejects_mismatch_and_missing_digest(su):
    st = selfupdate.check(force=True, fetch=release)
    assert selfupdate.fetch_installer(st, lambda m="": None, download=fake_download(b"tampered")) is None
    assert "sha256 불일치" in st["error"] and not list((su / "jaix_data" / "updates").glob("*.exe"))
    st = selfupdate.check(force=True, fetch=lambda: release(digest=None))
    assert selfupdate.fetch_installer(st, lambda m="": None, download=fake_download()) is None
    assert "sha256" in st["error"]


def test_download_failure_is_recorded_not_raised(su):
    st = selfupdate.check(force=True, fetch=release)

    def dl(url, dest):
        raise PermissionError("Defender 격리")
    assert selfupdate.fetch_installer(st, lambda m="": None, download=dl) is None
    assert "Defender" in selfupdate.load_state()["error"]


def test_logon_offer_asks_and_launches_with_previous_choice(su):
    selfupdate.save_choice(["claude", "hermes"], "claude")
    st = selfupdate.logon_prepare(lambda m="": None, fetch=release, download=fake_download())
    assert st and st["newer"]
    launched = []
    # [아니요] → 띄우지 않고 기록만
    assert not selfupdate.logon_offer(st, lambda m="": None, ask=lambda s: False, popen=lambda *a, **k: launched.append(a))
    assert not launched and selfupdate.load_state()["declined"]
    assert selfupdate.logon_offer(st, lambda m="": None, ask=lambda s: True,
                                  popen=lambda cmd, **k: launched.append(cmd))
    cmd = launched[0]
    assert cmd[0].endswith("jaix-setup-2026.11.05.1.exe")
    assert {"/SILENT", "/CURRENTUSER", "/JAIXAUTOUPDATE=1", "/CHANNELS=claude,hermes", "/HERMESMODEL=claude"} <= set(cmd)
    assert any(a.startswith("/LOG=") and a.endswith("install-2026.11.05.1.log") for a in cmd)


def test_launch_refuses_when_installer_was_quarantined(su):
    st = selfupdate.logon_prepare(lambda m="": None, fetch=release, download=fake_download())
    selfupdate.installer_path(st).unlink()  # Defender 가 지움
    launched = []
    assert not selfupdate.logon_offer(st, lambda m="": None, ask=lambda s: True, popen=lambda *a, **k: launched.append(a))
    assert not launched and "격리" in selfupdate.load_state()["error"]


def test_logon_prepare_never_breaks_update(su):
    def boom(*a, **k):
        raise RuntimeError("x")
    assert selfupdate.logon_prepare(lambda m="": None, fetch=release, download=boom) is None
    assert selfupdate.logon_offer(None, lambda m="": None, ask=lambda s: pytest.fail("묻지 않아야 함")) is False


def test_setup_choice_fallback_for_installs_before_choice_file(su, monkeypatch):
    (su / "claude_config_dir").mkdir()
    monkeypatch.setattr(hermesbot, "recorded", lambda: {"status": "connected", "model": "claude"})
    assert selfupdate.setup_choice() == (["claude", "hermes"], "claude")
    selfupdate.save_choice(["claude", "codex"], "chatgpt")  # 기록이 있으면 그것을 믿는다
    assert selfupdate.setup_choice() == (["claude", "codex"], "chatgpt")


def test_cmd_self(su):
    args = argparse.Namespace(yes=False)
    lines, launched = [], []
    assert selfupdate.cmd_self(args, lines.append, fetch=lambda: release("v2026.11.04.7")) == 0
    assert "최신" in lines[-1]
    assert selfupdate.cmd_self(args, lines.append, fetch=release, download=fake_download(),
                               popen=lambda cmd, **k: launched.append(cmd), ask=lambda q: "n") == 0
    assert not launched
    args.yes = True
    assert selfupdate.cmd_self(args, lines.append, fetch=release, download=fake_download(),
                               popen=lambda cmd, **k: launched.append(cmd)) == 0
    assert launched and "/JAIXAUTOUPDATE=1" in launched[0]


def test_cmd_self_off_windows_or_dev(su, monkeypatch):
    monkeypatch.setattr(paths, "exe_dir", lambda: None)
    lines = []
    assert selfupdate.cmd_self(argparse.Namespace(yes=True), lines.append) == 1 and "Windows 설치본" in lines[-1]


def test_doctor_line(su):
    selfupdate.check(force=True, fetch=release)
    res = selfupdate.doctor_status(check_now=False)
    assert res[0] == "warn" and "2026.11.05.1" in res[1] and "jaix update --self" in res[2]
    selfupdate.check(force=True, fetch=lambda: release("v2026.11.04.7"))
    assert selfupdate.doctor_status(check_now=False)[0] == "ok"


def test_doctor_has_self_check(su, monkeypatch):
    monkeypatch.setattr(selfupdate, "doctor_status", lambda: ("warn", "새 판 X 있음", selfupdate.GUIDE))
    (c,) = doctor.check_self()
    assert c.area == "jaix 본체" and c.status == "warn"


def test_update_parser_self():
    args = cli.build_parser().parse_args(["update", "--self", "--yes"])
    assert args.self_update and args.yes and args.func is cli.cmd_update


def test_quiet_update_prepares_first_and_offers_last(su, monkeypatch):
    order = []
    monkeypatch.setattr(selfupdate, "logon_prepare", lambda log: order.append("prepare") or {"newer": True})
    monkeypatch.setattr(cli, "_update", lambda args, log: order.append("update") or [])
    monkeypatch.setattr(selfupdate, "logon_offer", lambda st, log: order.append(("offer", st["newer"])))
    monkeypatch.setattr(schedule, "open_log", lambda: su / "update.log")
    args = cli.build_parser().parse_args(["update", "--quiet"])
    assert cli.cmd_update(args, lambda m="": None) == 0
    assert order == ["prepare", "update", ("offer", True)]


def test_installer_auto_update_mode():
    iss = (Path(__file__).resolve().parents[1] / "installer" / "jaix-setup.iss").read_text(encoding="utf-8-sig")
    assert "ExpandConstant('{param:JAIXAUTOUPDATE|0}') = '1'" in iss
    skip = iss.split("function ShouldSkipPage", 1)[1].split("\nend;", 1)[0]
    assert "IsAutoUpdate()" in skip  # 로그인 페이지 건너뜀
    assert "updates\\history.log" in iss and "(CurStep = ssDone) and IsAutoUpdate()" in iss


def test_setup_records_choice(su, monkeypatch):
    monkeypatch.setattr(selfupdate, "IS_WIN", False)
    selfupdate.save_choice(["claude", "hermes"], "claude")
    assert json.loads(selfupdate.choice_file().read_text(encoding="utf-8")) == {
        "channels": ["claude", "hermes"], "hermes_model": "claude"}


def test_cached_state_is_rejudged_against_running_version(su, monkeypatch):
    """Codex #100: 자기 업데이트 뒤 6시간 안에 다시 로그온해도 이미 깐 판을 권하지 않는다."""
    calls = []
    selfupdate.check(fetch=lambda: calls.append(1) or release(), now=1000.0)
    monkeypatch.setattr(selfupdate, "__version__", "2026.11.05.1")  # 새 판으로 바뀜
    assert not selfupdate.check(fetch=lambda: calls.append(1) or release(), now=1001.0)["newer"]
    assert len(calls) == 2  # 판이 바뀌면 지난 판정을 버리고 다시 확인
    monkeypatch.setattr(selfupdate, "__version__", "2026.11.06.1")  # 손으로 더 새 판을 깔았으면 내리지 않는다
    assert not selfupdate.check(fetch=lambda: (_ for _ in ()).throw(OSError("offline")), now=1002.0)["newer"]
    assert selfupdate.doctor_status(check_now=False)[0] == "ok"


def test_dry_run_never_downloads_or_launches(su):
    dl, launched = [], []
    args = argparse.Namespace(yes=True, dry_run=True)
    assert selfupdate.cmd_self(args, lambda m="": None, fetch=release, download=fake_download(calls=dl),
                               popen=lambda cmd, **k: launched.append(cmd)) == 0
    assert not dl and not launched
    assert cli.build_parser().parse_args(["update", "--self", "--dry-run"]).dry_run


def test_other_jaix_finds_same_folder_only(su, monkeypatch):
    """jaix-win .8→.9: 'JAIX Hermes 로그인' 창이 열려 있어 설치기가 /SILENT 인데 Abort/Retry/Ignore 로 멈춤."""
    here = su / "app" / "jaix"
    import os
    procs = [(os.getpid(), str(here / "jaixw.exe")),           # 나 — 빼야 함
             (101, str(here / "jaix.exe")),                    # 로그인 창
             (102, str(su / "other" / "jaix.exe"))]            # 다른 폴더의 jaix — 상관없음
    assert selfupdate.other_jaix(lambda: procs) == [(101, "jaix.exe")]


def test_launch_closes_other_windows_first_and_forces_close(su):
    st = selfupdate.logon_prepare(lambda m="": None, fetch=release, download=fake_download())
    order, seen = [], []
    assert selfupdate.launch(st, seen.append, popen=lambda cmd, **k: order.append(("popen", cmd)),
                             close=lambda log: order.append(("close",)))
    assert order[0] == ("close",) and order[1][0] == "popen"
    assert "/FORCECLOSEAPPLICATIONS" in order[1][1] and "/SUPPRESSMSGBOXES" not in order[1][1]


def test_close_others_reports_each(su):
    seen = []
    others = selfupdate.close_others(seen.append, find=lambda: [(101, "jaix.exe"), (102, "jaixw.exe")],
                                     kill=lambda pid: pid == 101)
    assert len(others) == 2 and "닫음" in seen[0] and "닫지 못함" in seen[1]
