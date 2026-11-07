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


def test_logon_offer_asks_then_opens_browser_never_downloads(su):
    st = selfupdate.logon_prepare(lambda m="": None, fetch=release)
    assert st and st["newer"]
    opened = []
    # [아니요] → 열지 않고 기록만
    assert not selfupdate.logon_offer(st, lambda m="": None, ask=lambda s: False, opener=opened.append)
    assert not opened and selfupdate.load_state()["declined"]
    lines = []
    assert selfupdate.logon_offer(st, lines.append, ask=lambda s: True, opener=lambda u: opened.append(u) or True)
    assert opened == ["https://x/v2026.11.05.1/jaix-setup.exe"]  # 릴리스 첨부를 브라우저가 받는다
    assert any("[추가 정보]" in line for line in lines) and any(selfupdate.RELEASES in line for line in lines)
    assert not list((su / "jaix_data" / "updates").glob("*.exe"))  # jaix 는 받지 않는다


def test_logon_prepare_never_breaks_update(su):
    def boom():
        raise RuntimeError("x")
    assert selfupdate.logon_prepare(lambda m="": None, fetch=boom) is None
    assert selfupdate.logon_offer(None, lambda m="": None, ask=lambda s: pytest.fail("묻지 않아야 함")) is False


def test_setup_choice_fallback_for_installs_before_choice_file(su, monkeypatch):
    (su / "claude_config_dir").mkdir()
    monkeypatch.setattr(hermesbot, "recorded", lambda: {"status": "connected", "model": "claude"})
    assert selfupdate.setup_choice() == (["claude", "hermes"], "claude")
    selfupdate.save_choice(["claude", "codex"], "chatgpt")  # 기록이 있으면 그것을 믿는다
    assert selfupdate.setup_choice() == (["claude", "codex"], "chatgpt")


def test_cmd_self(su):
    args = argparse.Namespace(yes=False)
    lines, opened = [], []
    assert selfupdate.cmd_self(args, lines.append, fetch=lambda: release("v2026.11.04.7")) == 0
    assert "최신" in lines[-1]
    assert selfupdate.cmd_self(args, lines.append, fetch=release, opener=opened.append, ask=lambda q: "n") == 0
    assert not opened
    args.yes = True
    assert selfupdate.cmd_self(args, lines.append, fetch=release, opener=lambda u: opened.append(u) or True) == 0
    assert opened == ["https://x/v2026.11.05.1/jaix-setup.exe"]
    assert selfupdate.cmd_self(args, lines.append, fetch=release, opener=lambda u: False) == 1  # 브라우저 못 엶
    assert selfupdate.RELEASES in "\n".join(lines)  # 그래도 주소는 보인다


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


def test_dry_run_never_opens_browser(su):
    opened = []
    args = argparse.Namespace(yes=True, dry_run=True)
    assert selfupdate.cmd_self(args, lambda m="": None, fetch=release, opener=opened.append) == 0
    assert not opened
    assert cli.build_parser().parse_args(["update", "--self", "--dry-run"]).dry_run


def test_other_jaix_finds_same_folder_only(su, monkeypatch):
    """jaix-win .8→.9: 'JAIX Hermes 로그인' 창이 열려 있어 설치기가 /SILENT 인데 Abort/Retry/Ignore 로 멈춤."""
    here = su / "app" / "jaix"
    import os
    procs = [(os.getpid(), str(here / "jaixw.exe")),           # 나 — 빼야 함
             (101, str(here / "jaix.exe")),                    # 로그인 창
             (102, str(su / "other" / "jaix.exe"))]            # 다른 폴더의 jaix — 상관없음
    assert selfupdate.other_jaix(lambda: procs) == [(101, "jaix.exe")]


def test_old_flow_installers_are_pruned(su):
    """예전 흐름이 updates 에 받아 둔 설치기(jaix-test 11/7: 깐 3초 뒤 Execution.A!ml)는 확인 때 모두 지운다."""
    upd = su / "jaix_data" / "updates"
    upd.mkdir(parents=True)
    for v in ("2026.11.04.7", "2026.11.05.1"):
        (upd / f"jaix-setup-{v}.exe").write_bytes(PAYLOAD)
    (upd / "install-2026.11.05.1.log").write_text("x")
    selfupdate.check(fetch=release)
    assert not list(upd.glob("*.exe"))
    assert (upd / "install-2026.11.05.1.log").exists() and selfupdate.state_file().exists()


def test_installer_closes_jaix_windows_itself():
    """#110: 열린 jaix 창이 파일을 잡으면 설치기가 멈췄다 — 사용자가 직접 연 설치기도 닫도록(전엔 jaix 가 닫고 /FORCE…)."""
    iss = (Path(__file__).resolve().parents[1] / "installer" / "jaix-setup.iss").read_text(encoding="utf-8-sig")
    assert "\nCloseApplications=force\n" in iss
    assert "procedure ApplyPreviousChoice" in iss  # 이전 선택은 설치기가 체크 기본값으로
