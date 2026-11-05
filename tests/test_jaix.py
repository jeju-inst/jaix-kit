import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from jaix import paths, proc
from jaix import claude, cli, clis, codex, doctor, gw, hancom, hermes, hermesbot, hwpjar, hwprhwp, lock, overlap, plugbin, runtimes, schedule, uvpython, winenv

REAL_HWPJAR = {}
REAL_CLIS = {}
REAL_RHWP_ENSURE = hwprhwp.ensure  # isolated 픽스처가 막기 전의 진짜 함수
REAL_UV_ENSURE = uvpython.ensure  # isolated 픽스처가 막기 전의 진짜 함수
REAL_GW_FOREIGN = gw.foreign  # isolated 픽스처가 막기 전의 진짜 함수
REAL_MANAGED = claude.managed_declaration  # isolated 픽스처가 막기 전의 진짜 함수
LOCK_FILE = Path(__file__).resolve().parents[1] / ".claude-plugin" / "marketplace.json"

REAL_HERMES_SETUP = hermesbot.setup
REAL_PLUGBIN_ENSURE = plugbin.ensure
REAL_REMOVE_USER_ENV_UNDER = winenv.remove_user_env_under

def _guard_real_hermes(tmp_path, monkeypatch):
    """시험이 이 PC의 진짜 hermes 를 부르지 못하게 한다. HERMES_HOME 만 tmp 로 돌린 채 진짜 hermes 가 돌면, Hermes 가
    자기 설치 폴더의 런처(~/.hermes/hermes-agent/.hermes/bin/hermes)를 tmp 의 파이썬으로 다시 써서 그 PC 의 hermes 가
    깨진다(studio 11/5: find_hermes 를 "hermes" 로 둔 doctor 시험이 `hermes auth list` 를 PATH 의 진짜 것으로 불렀다)."""
    real_popen = subprocess.Popen
    tmp = os.path.normcase(os.path.realpath(tmp_path))

    class GuardedPopen(real_popen):
        def __init__(self, args, *a, **kw):
            exe = args[0] if isinstance(args, (list, tuple)) and args else None
            if exe and Path(str(exe)).stem.lower() in ("hermes", "hermes-acp"):
                where = shutil.which(str(exe))
                if where and not os.path.normcase(os.path.realpath(where)).startswith(tmp):
                    raise AssertionError(f"시험이 진짜 hermes 를 부름: {where} {list(args)[1:3]}")
            super().__init__(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """실제 사용자 설정을 건드리지 않게 모든 경로를 tmp로."""
    _guard_real_hermes(tmp_path, monkeypatch)
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "JAIX_DATA", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("JAIX_LOCK", str(LOCK_FILE))
    monkeypatch.setattr(claude, "managed_declaration", lambda: None)
    # uv python install 은 진짜로 돌리지 않는다(내려받기)
    monkeypatch.setattr(uvpython, "ensure", lambda versions, log, dry_run=False: True)
    monkeypatch.setattr(uvpython, "needed", lambda lock, offline=False: [uvpython.DEFAULT])
    # hwp 변환기 jar 도 진짜로 받지 않는다. 받는 자리는 tmp
    REAL_HWPJAR["ensure"] = REAL_HWPJAR.get("ensure", hwpjar.ensure)
    monkeypatch.setattr(hwpjar, "ensure", lambda lock, log, dry_run=False, offline=False: True)
    monkeypatch.setattr(hwpjar, "dest", lambda: tmp_path / "hwp-agent" / "hwp2hwpx.jar")
    monkeypatch.setattr(hwprhwp, "ensure", lambda lock, log, dry_run=False, offline=False: True)
    # 사용자 환경변수(HKCU)는 진짜로 쓰지 않는다(Windows 러너)
    monkeypatch.setattr(winenv, "set_user_env", lambda name, value: False)
    monkeypatch.setattr(winenv, "remove_user_env_under", lambda name, prefix: False)
    # 플러그인 bin 명령: 소스를 진짜로 받지 않고, 링크는 tmp 에(시험은 REAL_PLUGBIN_ENSURE 를 부른다)
    monkeypatch.setattr(plugbin, "ensure", lambda lock, log, dry_run=False, offline=False:
                        {"status": "ok", "commands": [], "failed": []})
    monkeypatch.setenv("JAIX_LINK_DIR", str(tmp_path / "linkbin"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))  # 한컴 옵션 파일도 tmp 로
    monkeypatch.setattr(paths, "desktop_installed", lambda: False)
    # 새 창의 PATH(레지스트리)는 이 시험의 PATH 로 — Windows 러너의 진짜 uv·git 을 잡지 않게
    monkeypatch.setattr(winenv, "fresh_path", lambda: os.environ.get("PATH", ""))
    # 명령창 claude·codex 를 진짜로 받지 않는다(clis 시험은 test_clis.py)
    REAL_CLIS["ensure"] = REAL_CLIS.get("ensure", clis.ensure)
    monkeypatch.setattr(clis, "ensure", lambda name, log, dry_run=False, installer=None: {"status": "present", "path": name})
    # 예약 작업은 진짜로 등록하지 않는다(맥이면 launchctl이 시험 중에 update를 돌린다)
    monkeypatch.setenv("JAIX_LAUNCH_AGENTS", str(tmp_path / "LaunchAgents"))
    monkeypatch.setattr(schedule, "_run", lambda args: (True, ""))
    monkeypatch.setattr(schedule, "run_mode", lambda: None)
    monkeypatch.setenv(gw.ENV, "none")
    monkeypatch.setenv("JI_GW_CONFIG_DIR", str(tmp_path / "gwconf"))
    monkeypatch.delenv("GW_BASE_URL", raising=False)  # 기본 원내 주소로 나가지 않게(gw 시험이 저마다 바꾼다)
    monkeypatch.setattr(gw, "foreign", lambda uv=None: [])  # 개발 PC의 진짜 uv tool·gw 를 보지 않게
    monkeypatch.setattr(doctor, "PATH_TOOLS", {})
    # Hermes 무인 설치(Windows CI 에서 install.ps1 3GB 를 진짜로 받지 않게). 시험은 REAL_HERMES_SETUP 을 부른다
    monkeypatch.setattr(hermesbot, "setup", lambda lock, log, **kw: {"status": "unsupported"})  # 개발 PC의 진짜 hwp-agent 를 부르지 않게(시험이 저마다 켠다)
    return tmp_path


@pytest.fixture
def the_lock():
    return lock.load()


def test_lock_reads_repo_file(the_lock):
    names = [p.name for p in the_lock.plugins]
    assert "hwp-agent" in names
    for p in the_lock.plugins:
        assert len(p.sha) == 40 and p.id.endswith("@jaix")


def test_merge_adds_marketplace_and_keeps_existing(the_lock):
    before = {"theme": "dark", "enabledPlugins": {"foo@bar": True}}
    new, changes, warnings = claude.merge_settings(before, the_lock.plugins)
    assert before == {"theme": "dark", "enabledPlugins": {"foo@bar": True}}  # 원본 불변
    assert new["theme"] == "dark" and new["enabledPlugins"]["foo@bar"] is True
    assert new["extraKnownMarketplaces"]["jaix"] == claude.MARKET_ENTRY
    assert all(new["enabledPlugins"][p.id] is True for p in the_lock.plugins)
    assert changes and not warnings


def test_merge_restores_autoupdate_stripped_by_cli(the_lock):
    entry = {"source": {"source": "git", "url": lock.GIT_URL}}  # claude plugin marketplace add 가 남기는 모양
    new, changes, _ = claude.merge_settings({"extraKnownMarketplaces": {"jaix": entry}}, the_lock.plugins)
    assert new["extraKnownMarketplaces"]["jaix"]["autoUpdate"] is True
    assert any("autoUpdate" in c for c in changes)


def test_merge_respects_foreign_source_and_disabled_plugin(the_lock):
    dev = {"source": {"source": "directory", "path": "/Users/dev/jaix-kit-fork"}}
    pid = the_lock.plugins[0].id
    new, _, warnings = claude.merge_settings(
        {"extraKnownMarketplaces": {"jaix": dev}, "enabledPlugins": {pid: False}}, the_lock.plugins)
    assert new["extraKnownMarketplaces"]["jaix"] == dev
    assert new["enabledPlugins"][pid] is False
    assert len(warnings) == 2


def test_merge_is_idempotent(the_lock):
    once, _, _ = claude.merge_settings({}, the_lock.plugins)
    twice, changes, _ = claude.merge_settings(once, the_lock.plugins)
    assert once == twice and changes == []


def test_broken_settings_are_not_overwritten(isolated, monkeypatch):
    path = claude.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    rc = cli.main(["setup", "--runtimes", "none", "--channels", "claude"])
    assert rc == 2
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_setup_without_cli_writes_settings_and_backup(isolated, monkeypatch, the_lock):
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    path = claude.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"model": "sonnet"}', encoding="utf-8-sig")  # 메모장이 붙이는 BOM도 읽는다
    guide = isolated / "guide.txt"
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude,hermes", "--guide-out", str(guide)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "sonnet" and data["extraKnownMarketplaces"]["jaix"]["autoUpdate"] is True
    backups = list(path.parent.glob("settings.json.jaix-bak-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8-sig")) == {"model": "sonnet"}
    text = guide.read_bytes()
    assert text.startswith(b"\xef\xbb\xbf") and "Hermes" in text.decode("utf-8-sig")


def test_dry_run_changes_nothing(isolated, monkeypatch):
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--dry-run"]) == 0
    assert not claude.settings_path().exists()


def test_matches_by_version_or_sha(the_lock):
    tagged = next(p for p in the_lock.plugins if p.version)
    assert claude.matches(tagged, {"version": tagged.version})
    assert not claude.matches(tagged, {"version": "2000.01.01.1"})
    branch = lock.Plugin("x", None, "a" * 40, "main", "u")
    assert claude.matches(branch, {"gitCommitSha": "a" * 40})
    assert not claude.matches(branch, None)


def test_managed_declaration_detects_jaix(tmp_path, monkeypatch):
    f = tmp_path / "managed-settings.json"
    f.write_text(json.dumps({"extraKnownMarketplaces": {"jeju": {"source": {"source": "github", "repo": "jeju-inst/jaix-kit"}}}}))
    monkeypatch.setattr(claude.paths, "managed_settings_files", lambda: [tmp_path / "none.json", f])
    assert REAL_MANAGED() == f


def test_doctor_reports_install_state(isolated, monkeypatch, the_lock):
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    monkeypatch.setattr(codex, "find_cli", lambda: None)
    checks = doctor.check_claude(the_lock)
    assert any(c.status == "fail" and "마켓플레이스 없음" in c.message for c in checks)
    new, _, _ = claude.merge_settings({}, the_lock.plugins)
    claude.write_settings(new)
    rec_dir = claude.paths.claude_dir() / "plugins"
    rec_dir.mkdir(parents=True)
    first, rest = the_lock.plugins[0], the_lock.plugins[1:]
    recs = {first.id: [{"scope": "user", "version": "1999.01.01.1", "gitCommitSha": "0" * 40}]}
    recs.update({p.id: [{"scope": "user", "version": p.version, "gitCommitSha": p.sha}] for p in rest})
    (rec_dir / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": recs}))
    by_area = {c.area: c for c in doctor.check_claude(the_lock)}
    assert by_area["Claude 등록"].status == "ok"
    assert by_area[f"Claude {first.name}"].status == "fail" and by_area[f"Claude {first.name}"].fix
    assert all(by_area[f"Claude {p.name}"].status == "ok" for p in rest)
    assert doctor.check_codex(the_lock)[0].status == "skip"


def test_hermes_copy_replaces_old_files(tmp_path):
    src = tmp_path / "src" / "skill"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("new")
    dst = tmp_path / "dst" / "skill"
    dst.mkdir(parents=True)
    (dst / "OLD.txt").write_text("old")
    hermes.copy_skill(src, dst, {"plugin": "p", "sha": "s"})
    assert sorted(p.name for p in dst.iterdir()) == [".jaix.json", "SKILL.md"]
    assert json.loads((dst / ".jaix.json").read_text())["sha"] == "s"


def test_hermes_sync_noop_without_installed(the_lock):
    assert hermes.sync(the_lock, print) == []


@pytest.mark.skipif(sys.platform != "win32", reason="사용자 PATH 레지스트리는 Windows에만")
def test_user_path_add_and_remove(tmp_path):
    d = tmp_path / "jaix-path-test" / "bin"
    before = winenv.user_path_entries()
    try:
        assert winenv.add_to_path([d]) == [str(d)]
        assert winenv.in_user_path(d)
        assert winenv.add_to_path([d]) == []  # 두 번 넣지 않음
        assert winenv.remove_from_path(tmp_path / "jaix-path-test") == [str(d)]
        assert winenv.user_path_entries() == before
    finally:
        winenv.remove_from_path(tmp_path / "jaix-path-test")


def test_gw_off_is_skipped(monkeypatch):
    monkeypatch.setenv(gw.ENV, "none")
    assert gw.setup(print)["status"] == "off"
    assert doctor.check_gw()[0].status == "skip"


def test_gw_default_source(monkeypatch):
    monkeypatch.delenv(gw.ENV, raising=False)
    assert gw.source() == gw.DEFAULT_SOURCE


def test_gw_offsite_is_skipped_with_hint(monkeypatch):
    monkeypatch.setenv(gw.ENV, "http://127.0.0.1:9/gw/latest.json")  # 닿지 않는 곳 = 원외
    assert gw.setup(print)["status"] == "offsite"
    c = doctor.check_gw()[0]
    assert c.status == "warn" and "원내망" in c.fix


def _gw_share(isolated, monkeypatch, sha=None):
    """file:// 로 흉내 낸 원내 배포 폴더(latest.json + wheel)와 가짜 uv."""
    import hashlib
    share = isolated / "share" / "gw"
    (share / "2026.10.27.2").mkdir(parents=True)
    wheel = share / "2026.10.27.2" / "ji_gw_ai-2026.10.27.2-py3-none-any.whl"
    wheel.write_bytes(b"PK fake wheel")
    info = {"name": "ji-gw-ai", "version": "2026.10.27.2", "wheel": wheel.name, "url": wheel.as_uri(),
            "sha256": sha or hashlib.sha256(wheel.read_bytes()).hexdigest()}
    (share / "latest.json").write_text(json.dumps(info), encoding="utf-8")
    monkeypatch.setenv(gw.ENV, (share / "latest.json").as_uri())
    calls, state = [], {"installed": None}

    def run(args, timeout=60):
        calls.append(args)
        if args[1:3] == ["tool", "install"]:
            state["installed"] = "2026.10.27.2"
            return True, ""
        if args[1:3] == ["tool", "list"]:
            return True, f"ji_gw_ai v{state['installed']}\n- gw" if state["installed"] else "No tools installed"
        if args[1:3] == ["tool", "dir"]:
            return True, str(isolated / "uvbin")
        return False, ""  # gw --version: 가짜라 못 돎 → uv tool list 버전을 씀
    monkeypatch.setattr(gw, "_uv", lambda: "uv")
    monkeypatch.setattr(gw, "_run", run)
    monkeypatch.setattr(paths, "which", lambda name: None)  # 개발 PC PATH의 진짜 gw 를 보지 않게
    return calls, state


def test_gw_installs_wheel_after_sha256(isolated, monkeypatch):
    calls, state = _gw_share(isolated, monkeypatch)
    assert doctor.check_gw()[0].status == "fail"  # 닿는데 안 깔림
    assert gw.setup(print)["status"] == "installed"
    assert any(a[1:3] == ["tool", "install"] and a[3].endswith(".whl") for a in calls)
    assert gw.installed_version() == "2026.10.27.2"
    assert doctor.check_gw()[0].status == "ok"
    assert gw.setup(print)["status"] == "current"  # 다시 돌리면 그대로


def test_gw_refuses_wrong_sha256(isolated, monkeypatch):
    calls, state = _gw_share(isolated, monkeypatch, sha="0" * 64)
    assert gw.setup(print)["status"] == "failed"
    assert not any(a[1:3] == ["tool", "install"] for a in calls)
    assert not list((isolated / "jaix_home" / "gw").glob("*.whl"))


def test_gw_doctor_warns_on_older_install(isolated, monkeypatch):
    _gw_share(isolated, monkeypatch)
    monkeypatch.setattr(gw, "installed_version", lambda uv=None: "2026.10.27.1")
    c = doctor.check_gw()[0]
    assert c.status == "warn" and c.fix == "jaix update"


def test_gw_source_saved(isolated, monkeypatch):
    monkeypatch.delenv(gw.ENV, raising=False)
    url = "https://example.invalid/gw/latest.json"
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--gw-source", url]) == 0
    assert gw.source() == url


def test_uv_python_pins_from_mcp_json():
    cfg = {"mcpServers": {
        "a": {"command": "uvx", "args": ["--python", "3.13", "--from", "x", "a"]},
        "b": {"command": "C:\\tools\\uv.exe", "args": ["run", "--python=3.11", "b"]},
        "c": {"command": "node", "args": ["--python", "9"]},
        "d": {"command": "uvx", "args": ["--from", "${CLAUDE_PLUGIN_ROOT}", "hwp-agent", "mcp"]},
    }}
    assert uvpython.pins(cfg) == {"3.13", "3.11"}


def test_uv_python_raw_url(the_lock):
    by = {p.name: p for p in the_lock.plugins}
    url = uvpython._raw_url(by["hwp-agent"], ".mcp.json")
    assert url == f"https://raw.githubusercontent.com/z0nam/hwp-agent/{by['hwp-agent'].sha}/.mcp.json"
    sub = by["calendar-worklog-ji"]
    assert uvpython._raw_url(sub, ".mcp.json").endswith(f"/{sub.sha}/plugin/.mcp.json")


def test_doctor_uv_python(monkeypatch):
    monkeypatch.setattr(runtimes, "find", lambda rt: runtimes.Found("uv", "0.9"))
    monkeypatch.setattr(uvpython, "find", lambda v, uv=None: None)
    c = doctor.check_uv_python()[0]
    assert c.status == ("fail" if sys.platform == "win32" else "warn") and "3.12" in c.message
    monkeypatch.setattr(uvpython, "find", lambda v, uv=None: "/x/python")
    assert doctor.check_uv_python()[0].status == "ok"
    monkeypatch.setattr(runtimes, "find", lambda rt: runtimes.Found(None, None))
    assert doctor.check_uv_python()[0].status == "skip"
def test_task_xml_pins_logon_to_this_user():
    xml = schedule.task_xml([r"C:\Users\a b\jaix.exe", "update", "--quiet"], r"JI\홍길동")
    assert "<UserId>JI\\홍길동</UserId>" in xml and "<LogonTrigger>" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert '<Command>"C:\\Users\\a b\\jaix.exe"</Command>' in xml
    assert "<Arguments>update --quiet</Arguments>" in xml


def test_setup_registers_autoupdate_and_cleanup_removes(isolated, monkeypatch):
    guide = isolated / "guide.txt"
    assert cli.main(["setup", "--runtimes", "none", "--channels", "codex", "--guide-out", str(guide)]) == 0
    if schedule.IS_MAC:
        text = schedule.plist_path().read_text(encoding="utf-8")
        assert "<string>update</string>" in text and "<key>PATH</key>" in text
    if schedule.supported():
        assert cli.main(["cleanup"]) == 0
        assert not schedule.plist_path().exists()


def test_no_autoupdate_flag(isolated):
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--no-autoupdate"]) == 0
    assert not schedule.plist_path().exists()


def test_quiet_update_records_status_for_doctor(isolated, monkeypatch, capsys):
    monkeypatch.setattr(schedule, "supported", lambda: True)
    monkeypatch.setattr(schedule, "registered", lambda: True)
    assert doctor.check_autoupdate()[0].status == "ok"  # 아직 돈 적 없음
    monkeypatch.setattr(cli, "_update", lambda args, log: (log("하는 중"), [])[1])
    assert cli.main(["update", "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    assert "하는 중" in schedule.log_file().read_text(encoding="utf-8")
    assert doctor.check_autoupdate()[0].message.startswith("마지막 갱신")

    def offline(args, log):
        raise FileNotFoundError("잠금을 받지 못함")
    monkeypatch.setattr(cli, "_update", offline)
    assert cli.main(["update", "--quiet"]) == 1
    c = doctor.check_autoupdate()[0]
    assert c.status == "warn" and "잠금을 받지 못함" in c.message and c.fix == "jaix update"


def test_setup_or_direct_update_success_clears_old_logon_failure(isolated, monkeypatch):
    """지난 로그온 갱신 실패 뒤 setup·직접 update 가 성공하면 doctor 가 더는 실패를 보이지 않는다(jaix-win v.28.1 실측)."""
    monkeypatch.setattr(schedule, "supported", lambda: True)
    monkeypatch.setattr(schedule, "registered", lambda: True)
    monkeypatch.setattr(schedule, "run_mode", lambda: None)
    schedule.write_status(["Codex 플러그인 설치 실패: MCP 경로"])
    assert doctor.check_autoupdate()[0].status == "warn"
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--no-autoupdate"]) == 0
    c = doctor.check_autoupdate()[0]
    assert c.status == "ok" and c.message.endswith("(jaix setup)")

    schedule.write_status(["Codex 플러그인 설치 실패: MCP 경로"])
    monkeypatch.setattr(cli, "_update", lambda args, log: [])
    assert cli.main(["update"]) == 0
    c = doctor.check_autoupdate()[0]
    assert c.status == "ok" and "jaix setup" not in c.message

    monkeypatch.setattr(cli, "_update", lambda args, log: ["gw 설치 실패"])
    assert cli.main(["update"]) == 1
    assert doctor.check_autoupdate()[0].status == "warn"


def test_setup_keeps_old_failure_when_setup_has_problems():
    assert cli._setup_problems({"codex": {"failed": ["hwp-agent"]}})
    assert cli._setup_problems({"codex": {"error": "MCP 등록"}})
    assert cli._setup_problems({"gw": {"status": "failed"}})
    assert cli._setup_problems({"uvpython": False}) and cli._setup_problems({"hwpjar": False})
    assert not cli._setup_problems({"codex": {"failed": []}, "gw": {"status": "offsite"}})


def test_guide_gw_login_covers_agent_window_and_terminal():
    text = cli.guide(["claude"], {"gw": {"status": "installed"}})
    assert "gw 로그인해 줘" in text and "입력 창" in text and "그 자리에서 묻습니다" in text


def test_doctor_warns_when_autoupdate_missing(monkeypatch):
    monkeypatch.setattr(schedule, "supported", lambda: True)
    monkeypatch.setattr(schedule, "registered", lambda: False)
    assert doctor.check_autoupdate()[0].status == "warn"


def test_task_mode_must_be_interactive_least_privilege():
    import xml.etree.ElementTree as ET
    good = schedule.task_xml(["jaix.exe", "update", "--quiet"], "u").split("\n", 1)[1]
    assert schedule.mode_problem(ET.fromstring(good)) is None
    s4u = good.replace("InteractiveToken", "S4U")
    assert "로그온할 때만" in schedule.mode_problem(ET.fromstring(s4u))
    admin = good.replace("LeastPrivilege", "HighestAvailable")
    assert "관리자" in schedule.mode_problem(ET.fromstring(admin))


def test_update_exit_code_is_int(monkeypatch):
    monkeypatch.setattr(cli, "_update", lambda args, log: [])
    assert cli.main(["update"]) == 0
    monkeypatch.setattr(cli, "_update", lambda args, log: ["x"])
    assert cli.main(["update"]) == 1


def test_no_autoupdate_removes_existing(isolated, monkeypatch):
    if not schedule.IS_MAC:
        pytest.skip("LaunchAgent 파일로 확인")
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude"]) == 0
    assert schedule.plist_path().exists()
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--no-autoupdate"]) == 0
    assert not schedule.plist_path().exists()


def test_codex_setup_reports_failed_plugins(isolated, monkeypatch, the_lock):
    monkeypatch.setattr(codex, "find_cli", lambda: "codex")
    monkeypatch.setattr(codex, "marketplace_configured", lambda: True)
    monkeypatch.setattr(codex, "_run", lambda cli, args, log: args[:2] != ["plugin", "add"])
    res = codex.setup(the_lock, print)
    assert res["failed"] == [p.name for p in the_lock.plugins]


def test_hwpjar_spec_parsed_from_fetch_jar_source():
    src = '''_RELEASE_TAG = "converter-jar"
_ASSET = "hwp2hwpx.jar"
JAR_URL = os.environ.get(
    "HWP2HWPX_JAR_URL",
    f"https://github.com/z0nam/hwp-agent/releases/download/{_RELEASE_TAG}/{_ASSET}",
)
JAR_SHA256 = "578a7f8397342dca1d52845330462d5038a4706967a9c43c0e04faf5f6f3d0ce"
'''
    assert hwpjar.parse_spec(src) == hwpjar.FALLBACK
    assert hwpjar.parse_spec("nothing") is None


def test_hwpjar_download_checks_sha256(isolated, monkeypatch, the_lock):
    import hashlib
    ensure = REAL_HWPJAR["ensure"]
    src = isolated / "rel" / "hwp2hwpx.jar"
    src.parent.mkdir()
    src.write_bytes(b"PK jar")
    good = {"url": src.as_uri(), "sha256": hashlib.sha256(b"PK jar").hexdigest()}
    monkeypatch.setattr(hwpjar, "spec", lambda lock, offline=False: {**good, "sha256": "0" * 64})
    assert ensure(the_lock, print) is False and not hwpjar.dest().exists()
    assert doctor.check_hwp_jar(the_lock)[0].status == "fail"
    monkeypatch.setattr(hwpjar, "spec", lambda lock, offline=False: good)
    assert ensure(the_lock, print) is True and hwpjar.dest().read_bytes() == b"PK jar"
    assert doctor.check_hwp_jar(the_lock)[0].status == "ok"


def test_find_cli_in_desktop_msix_location(isolated, monkeypatch):
    local = isolated / "local"
    old = local / "Claude-Data" / "claude_pzs8" / "claude-code" / "2.1.9" / "abc"
    new = local / "Claude-Data" / "claude_pzs8" / "claude-code" / "2.1.10" / "def"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "claude.exe").write_bytes(b"MZ")
    monkeypatch.setattr(paths, "which", lambda name: None)
    monkeypatch.setattr(claude, "IS_WIN", True)
    monkeypatch.setattr(paths, "IS_WIN", True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(isolated / "roaming"))
    assert claude.find_cli() == str(new / "claude.exe")  # 2.1.10 > 2.1.9 (문자열 비교가 아님)


def test_doctor_fails_when_plugins_missing(isolated, monkeypatch, the_lock):
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    checks = {c.area: c for c in doctor.check_claude(the_lock)}
    c = checks["Claude 플러그인"]
    assert c.status == "fail" and f"{len(the_lock.plugins)}/{len(the_lock.plugins)}" in c.message
    assert "Code 탭" in c.fix
    monkeypatch.setattr(paths, "desktop_installed", lambda: True)
    assert {c.area: c for c in doctor.check_claude(the_lock)}["Claude 데스크톱·Cowork"].status == "skip"


def test_guide_says_how_to_really_quit(the_lock):
    text = cli.guide(["claude"], {"claude": {"cli": False, "managed": None}})
    assert ("Exit" if sys.platform == "win32" else "Quit") in text and "한 번 더 여세요" in text
    assert "작업 표시줄 아이콘 → 종료" not in text


def test_uv_python_judged_by_result_not_exit_code(isolated, monkeypatch):
    """#21: 설치본 안에서 uv 가 os error 448 을 보고해도 결과물이 있으면 성공."""
    pydir = isolated / "uvpy"
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(pydir))
    monkeypatch.setattr(uvpython, "_uv", lambda: "uv")
    exe = "python.exe" if sys.platform == "win32" else "bin/python3"

    class R:
        returncode, stdout, stderr = 2, "", "error: 신뢰할 수 없는 탑재 지점 (os error 448)"

    def fake_run(args, **kw):
        if args[1:3] == ["python", "install"]:
            target = pydir / f"cpython-{args[3]}.16-windows-x86_64-none" / exe
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")
        r = R()
        r.returncode = 2 if args[1:3] == ["python", "install"] else 1  # find 도 실패(가드 상속)
        return r
    monkeypatch.setattr(uvpython.subprocess, "run", fake_run)
    lines = []
    assert REAL_UV_ENSURE(["3.12"], lines.append) is True
    assert "결과물 확인" in lines[-1]
    assert uvpython.on_disk("3.12")
    assert uvpython.on_disk("3.1") is None  # 3.1 이 3.12 를 잡지 않음


def test_uv_python_missing_result_is_failure(isolated, monkeypatch):
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(isolated / "uvpy"))
    monkeypatch.setattr(uvpython, "_uv", lambda: "uv")

    class R:
        returncode, stdout, stderr = 2, "", "os error 448"
    monkeypatch.setattr(uvpython.subprocess, "run", lambda args, **kw: R())
    lines = []
    assert REAL_UV_ENSURE(["3.12"], lines.append) is False
    assert "다시 시도" in lines[-1]


def test_codex_found_in_npm_global_dir(isolated, monkeypatch):
    npm = isolated / "npm"
    npm.mkdir()
    name = "codex.cmd" if sys.platform == "win32" else "codex"
    (npm / name).write_text("@echo off\n")
    (npm / name).chmod(0o755)
    monkeypatch.setattr(paths, "npm_global_bin", lambda: npm)
    monkeypatch.setattr(paths.shutil, "which", lambda n, path=None: str(npm / name) if path == str(npm) else None)
    assert codex.find_cli() == str(npm / name)


def test_steps_continue_and_log_traceback(isolated, monkeypatch):
    """#27: 한 단계가 예외를 내도 traceback 을 남기고 다음 단계로 간다."""
    logf = isolated / "setup.log"

    def boom(*a, **kw):
        raise OSError(448, "신뢰할 수 없는 탑재 지점")
    monkeypatch.setattr(uvpython, "ensure", boom)
    guide = isolated / "guide.txt"
    rc = cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--log", str(logf), "--guide-out", str(guide)])
    text = logf.read_text(encoding="utf-8")
    assert rc == 1 and "Traceback" in text and "uv 관리 Python" in text
    assert "[2/3] Claude" in text and guide.exists()  # 뒤 단계도 돌았다
    assert "일부 단계가 실패했습니다: uv 관리 Python" in text


def test_main_logs_unexpected_exception_and_status(isolated, monkeypatch):
    logf, status = isolated / "setup.log", isolated / "status.json"

    def boom(*a, **kw):
        raise RuntimeError("뜻밖")
    monkeypatch.setattr(cli.lockmod, "load", boom)
    rc = cli.main(["setup", "--runtimes", "none", "--log", str(logf), "--status-out", str(status)])
    assert rc == 1 and "RuntimeError: 뜻밖" in logf.read_text(encoding="utf-8")
    assert json.loads(status.read_text(encoding="utf-8")) == {"code": 1}


def test_run_via_task_streams_log_and_returns_code(isolated, monkeypatch):
    import threading
    logf, status = isolated / "setup.log", isolated / "st.json"
    seen, calls = [], []

    def fake_run(args):
        calls.append(args)
        if args[:2] == ["schtasks", "/Run"]:  # 작업이 돈 것처럼: 로그를 쓰고 종료 코드를 남긴다
            def work():
                logf.write_text("[1/3] 런타임\n  uv: 있음\n", encoding="utf-8")
                status.write_text('{"code": 0}', encoding="utf-8")
            threading.Timer(0.2, work).start()
        return True, ""
    monkeypatch.setattr(schedule, "_run", fake_run)
    monkeypatch.setattr(schedule, "_user_id", lambda: "u")
    assert schedule.run_via_task(["jaix.exe", "setup"], logf, status, seen.append) == 0
    assert "  uv: 있음" in seen
    assert any(a[:2] == ["schtasks", "/Delete"] for a in calls)  # 끝나면 지운다


def test_run_via_task_falls_back_when_cannot_register(isolated, monkeypatch):
    monkeypatch.setattr(schedule, "_run", lambda args: (False, "액세스 거부"))
    monkeypatch.setattr(schedule, "_user_id", lambda: "u")
    seen = []
    assert schedule.run_via_task(["jaix.exe"], isolated / "l", isolated / "s", seen.append) is None
    assert "직접 실행" in seen[0]


def test_once_task_xml_has_no_trigger():
    xml = schedule.task_xml(["C:\\jaix.exe", "setup", "--log", "C:\\a b\\setup.log"], "u", logon=False)
    assert "<Triggers>" not in xml and "<LogonType>InteractiveToken</LogonType>" in xml
    assert '"C:\\a b\\setup.log"' in xml


def test_on_disk_survives_untrusted_mount(isolated, monkeypatch):
    pydir = isolated / "uvpy"
    (pydir / "cpython-3.12-windows-x86_64-none").mkdir(parents=True)
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(pydir))
    real = Path.is_file

    def guarded(self):
        if "none" in str(self):
            raise OSError(448, "untrusted mount point")
        return real(self)
    monkeypatch.setattr(Path, "is_file", guarded)
    assert uvpython.on_disk("3.12") is None  # 예외 없이


def test_via_task_replays_setup_command(isolated, monkeypatch):
    """작업으로 넘기는 명령이 그대로 다시 파싱되는지(setup 하위 명령 포함, --via-task 제외)."""
    seen = {}

    def fake(cmd, log_path, status, echo):
        seen["cmd"] = cmd
        return 0
    monkeypatch.setattr(cli.paths, "IS_WIN", True)
    monkeypatch.setattr(schedule, "run_via_task", fake)
    assert cli.main(["setup", "--via-task", "--channels", "claude", "--log", str(isolated / "s.log")]) == 0
    cmd = seen["cmd"]
    i = cmd.index("setup")
    replay = cli.build_parser().parse_args(cmd[i:])
    assert replay.cmd == "setup" and replay.channels == "claude" and not replay.via_task
    assert replay.status_out and replay.log == str(isolated / "s.log")


def _codex_home_with_plugin(isolated, monkeypatch, the_lock):
    """Codex가 hwp-agent 를 깐 상태를 흉내: 설치 폴더의 .mcp.json 은 ${CLAUDE_PLUGIN_ROOT} 를 쓴다."""
    home = isolated / "codex_home"
    root = home / "plugins" / "cache" / "jaix" / "hwp-agent" / "local"
    root.mkdir(parents=True)
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"hwp-agent": {
        "command": "uvx", "args": ["--from", "${CLAUDE_PLUGIN_ROOT}", "hwp-agent", "mcp"]}}}), encoding="utf-8")
    (home / "config.toml").write_text('[plugins."hwp-agent@jaix"]\nenabled = true\n', encoding="utf-8")
    calls = []

    def fake_run(cli, args, log):  # codex mcp add/remove 를 config.toml 에 흉내 내 쓴다
        calls.append(args)
        cfg = home / "config.toml"
        if args[:2] == ["mcp", "add"]:
            name, rest = args[2], args[args.index("--") + 1:]
            body = f'\n[mcp_servers."{name}"]\ncommand = {json.dumps(rest[0])}\nargs = {json.dumps(rest[1:])}\n'
            cfg.write_text(cfg.read_text(encoding="utf-8") + body, encoding="utf-8")
        return True
    monkeypatch.setattr(codex, "_run", fake_run)
    return home, root, calls


def test_codex_mcp_written_with_absolute_root(isolated, monkeypatch, the_lock):
    home, root, calls = _codex_home_with_plugin(isolated, monkeypatch, the_lock)
    assert codex.mcp_servers(the_lock) == {"hwp-agent": {"command": "uvx", "args": ["--python", "3.12", "--from", str(root),
                                                                                  "hwp-agent", "mcp"], "env": {}}}
    assert codex.write_mcp(the_lock, print, cli="codex")
    assert calls[-1][:3] == ["mcp", "add", "hwp-agent"] and str(root) in calls[-1]
    n = len(calls)
    codex.write_mcp(the_lock, print, cli="codex")
    assert len(calls) == n  # 이미 맞으면 다시 쓰지 않음


def test_codex_mcp_pins_python_only_when_missing():
    """Hermes가 Codex 항목을 가져가 자기 VIRTUAL_ENV(3.14)로 띄워도 같은 Python을 쓰게(jaix-kit#45)."""
    assert codex._pin_python({"command": "uvx", "args": ["--from", "x", "y"]})[:2] == ["--python", "3.12"]
    assert codex._pin_python({"command": r"C:\\u\\uvx.exe", "args": ["y"]})[:2] == ["--python", "3.12"]
    for args in (["--python", "3.11", "y"], ["-p", "3.13", "y"], ["--python=3.11", "y"]):
        assert codex._pin_python({"command": "uvx", "args": args}) == args
    assert codex._pin_python({"command": "node", "args": ["s.js"]}) == ["s.js"]


def test_codex_mcp_keeps_user_definition(isolated, monkeypatch, the_lock):
    home, root, calls = _codex_home_with_plugin(isolated, monkeypatch, the_lock)
    cfg = home / "config.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + '\n[mcp_servers."hwp-agent"]\ncommand = "my-hwp"\n', encoding="utf-8")
    lines = []
    codex.write_mcp(the_lock, lines.append, cli="codex")
    assert not calls and "사용자 정의" in lines[0]


def test_codex_sandbox_default_only_when_unset(isolated, monkeypatch):
    monkeypatch.setattr(codex, "IS_WIN", True)
    home = isolated / "codex_home"
    home.mkdir()
    cfg = home / "config.toml"
    cfg.write_text('model = "x"\n', encoding="utf-8")
    assert codex.ensure_sandbox(print) is True
    import tomllib
    assert tomllib.loads(cfg.read_text(encoding="utf-8"))["windows"]["sandbox"] == "unelevated"
    cfg.write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
    assert codex.ensure_sandbox(print) is False  # 있는 값은 건드리지 않음
    cfg.write_text('[windows]\nother = 1\n', encoding="utf-8")
    codex.ensure_sandbox(print)
    assert tomllib.loads(cfg.read_text(encoding="utf-8"))["windows"] == {"sandbox": "unelevated", "other": 1}


def test_gw_unpublished_when_dns_missing(monkeypatch):
    monkeypatch.setenv(gw.ENV, "https://not-yet.invalid/gw/latest.json")
    assert gw.unpublished()
    assert gw.setup(print)["status"] == "unpublished"
    assert doctor.check_gw()[0].status == "skip" and "배포 전" in doctor.check_gw()[0].message


def test_enabled_plugins_refilled_after_uninstall_but_off_respected(the_lock):
    """claude plugin uninstall 은 enabledPlugins 항목을 지운다 → setup/update 의 병합이 다시 채운다.
    사용자가 끈 것(false)은 그대로 둔다."""
    ids = [p.id for p in the_lock.plugins]
    settings = {"enabledPlugins": {ids[0]: False}}  # ids[1:] 는 uninstall 로 지워진 상태
    new, changes, warnings = claude.merge_settings(settings, the_lock.plugins)
    assert new["enabledPlugins"][ids[0]] is False
    assert all(new["enabledPlugins"][i] is True for i in ids[1:])


def test_same_commit_prefix(the_lock):
    from jaix.lock import same_commit
    full = "07040e21d448" + "0" * 28
    assert same_commit("07040e21d448", full) and same_commit(full, "07040e2")
    assert not same_commit("07040e", full)  # 7자 미만은 판단 안 함
    assert not same_commit("17040e21d448", full) and not same_commit(None, full)
    # 잠금이 전부 태그 고정이 돼도 시험하도록 branch 고정 플러그인을 만들어 쓴다
    branch = dataclasses.replace(the_lock.plugins[0], version=None)
    # Claude Code 기록: branch 고정이면 version 칸에 12자리 해시
    assert claude.matches(branch, {"version": branch.sha[:12]})
    assert not claude.matches(branch, {"version": "0" * 12})
    tagged = next(p for p in the_lock.plugins if p.version)
    assert claude.matches(tagged, {"version": tagged.version}) and not claude.matches(tagged, {"version": tagged.sha[:12]})


def test_codex_mcp_user_edit_after_jaix_is_kept(isolated, monkeypatch, the_lock):
    home, root, calls = _codex_home_with_plugin(isolated, monkeypatch, the_lock)
    codex.write_mcp(the_lock, print, cli="codex")
    cfg = home / "config.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('command = "uvx"', 'command = "my-uvx"'), encoding="utf-8")
    n = len(calls)
    codex.write_mcp(the_lock, print, cli="codex")
    assert len(calls) == n and "hwp-agent" not in codex.owned_mcp()


def test_codex_sandbox_header_variants(isolated, monkeypatch):
    import tomllib
    monkeypatch.setattr(codex, "IS_WIN", True)
    home = isolated / "codex_home"
    home.mkdir()
    cfg = home / "config.toml"
    for text in ('[windows] # 설정\nother = 1\n', '["windows"]\nother = 1\n'):
        cfg.write_text(text, encoding="utf-8")
        assert codex.ensure_sandbox(print) is True
        assert tomllib.loads(cfg.read_text(encoding="utf-8"))["windows"] == {"sandbox": "unelevated", "other": 1}
    cfg.write_text('windows = { other = 1 }\n', encoding="utf-8")
    assert codex.ensure_sandbox(print) is False  # 인라인 표는 그대로


def test_gw_base_url_written_preserving_other_keys(isolated):
    import tomllib
    f = gw.share_toml()
    f.parent.mkdir(parents=True)
    f.write_text('# 내 설정\n[gw]\nother = 1\n\n[ui]\ntheme = "dark"\n', encoding="utf-8")
    assert gw.save_base_url("https://gw.example.internal/", print)
    d = tomllib.loads(f.read_text(encoding="utf-8"))
    assert d == {"gw": {"base_url": "https://gw.example.internal/", "other": 1}, "ui": {"theme": "dark"}}
    assert "# 내 설정" in f.read_text(encoding="utf-8")
    assert gw.save_base_url("https://gw2.example.internal/", print)  # 있으면 그 줄만 바꿈
    assert tomllib.loads(f.read_text(encoding="utf-8"))["gw"]["base_url"] == "https://gw2.example.internal/"
    assert gw.base_url() == "https://gw2.example.internal/"


def test_gw_base_url_new_file_and_broken_file(isolated):
    assert gw.base_url() is None
    assert gw.save_base_url("https://gw.example.internal/", print)
    assert gw.base_url() == "https://gw.example.internal/"
    gw.share_toml().write_text("[gw\nbroken", encoding="utf-8")
    lines = []
    assert gw.save_base_url("https://x/", lines.append) is False and "건드리지 않음" in lines[0]


def test_gw_setup_records_base_url_only_when_present(isolated, monkeypatch):
    calls, state = _gw_share(isolated, monkeypatch)
    gw.setup(print)
    assert gw.base_url() is None  # 필드 없음(원외 응답) → 파일 안 만듦
    latest = json.loads((isolated / "share" / "gw" / "latest.json").read_text(encoding="utf-8"))
    latest["gw_base_url"] = "https://gw.example.internal/"
    (isolated / "share" / "gw" / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    gw.setup(print)
    assert gw.base_url() == "https://gw.example.internal/"
    assert {c.area: c for c in doctor.check_gw()}["gw 그룹웨어 주소"].status == "ok"


def test_gw_base_url_unreadable_file_does_not_raise(isolated):
    f = gw.share_toml()
    f.parent.mkdir(parents=True)
    f.write_bytes(b"[gw]\nother = \"\xff\xfe\"\n")  # UTF-8 아님
    lines = []
    assert gw.save_base_url("https://x/", lines.append) is False and "UnicodeDecodeError" in lines[0]


def test_migrate_data_moves_old_records_out_of_program_dir(isolated):
    """jaix-win 실측: 기록·상태가 프로그램 폴더(제거하면 통째로 지워짐)에 있었다 → 데이터 폴더로 옮긴다."""
    old, new = paths.jaix_home(), paths.data_dir()
    (old / "gw").mkdir(parents=True)
    (old / "update-status.json").write_text('{"ok": false}', encoding="utf-8")
    (old / "codex-mcp.json").write_text("{}", encoding="utf-8")
    (old / "gw" / "x.whl").write_text("w", encoding="utf-8")
    new.mkdir(parents=True)
    (new / "codex-mcp.json").write_text('{"keep": 1}', encoding="utf-8")  # 새 자리에 있으면 그쪽을 믿는다
    (old / "bin").mkdir()  # 런타임은 프로그램 폴더에 그대로
    assert sorted(paths.migrate_data()) == ["gw", "update-status.json"]
    assert (new / "gw" / "x.whl").exists() and not (old / "update-status.json").exists()
    assert json.loads((new / "codex-mcp.json").read_text(encoding="utf-8")) == {"keep": 1}
    assert (old / "bin").is_dir()
    assert schedule.status_file().parent == new


def test_self_command_prefers_windowless_exe(tmp_path, monkeypatch):
    exe = tmp_path / "jaix.exe"
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(paths, "IS_WIN", True)
    assert paths.self_command(windowless=True) == [str(exe)]  # jaixw.exe 가 없으면(옛 설치본) jaix.exe
    (tmp_path / "jaixw.exe").write_text("")
    assert paths.self_command(windowless=True) == [str(tmp_path / "jaixw.exe")]
    assert paths.self_command() == [str(exe)]
    assert schedule.command() == [str(tmp_path / "jaixw.exe"), "update", "--quiet"]


def test_task_pointing_at_missing_exe_is_a_problem(tmp_path):
    """onedir 로 옮긴 뒤 setup 을 다시 안 돌리면 작업이 예전 자리의 jaixw.exe 를 부른다(jaix-kit#46)."""
    import xml.etree.ElementTree as ET
    gone, here = tmp_path / "jaixw.exe", tmp_path / "jaix" / "jaixw.exe"
    here.parent.mkdir()
    here.write_text("")
    for exe, bad in ((gone, True), (here, False)):
        xml = schedule.task_xml([str(exe), "update", "--quiet"], "u").split("\n", 1)[1]
        assert (schedule.missing_command(ET.fromstring(xml)) is not None) == bad
    xml = schedule.task_xml(["jaixw.exe", "update"], "u").split("\n", 1)[1]
    assert schedule.missing_command(ET.fromstring(xml)) is None  # 경로 없는 이름은 판단하지 않음


@pytest.mark.skipif(sys.platform != "win32", reason="사용자 PATH(레지스트리)는 Windows")
def test_old_onefile_path_entry_is_dropped(tmp_path, monkeypatch):
    home = tmp_path / "Programs" / "jaix"
    (home / "jaix").mkdir(parents=True)
    monkeypatch.setenv("JAIX_HOME", str(home))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(home / "jaix" / "jaix.exe"))
    try:
        winenv.add_to_path([home, home / "jaix"])
        (home / "jaix.exe").write_text("")
        assert winenv.drop_old_exe_dir() == []  # 예전 jaix.exe 가 아직 있으면 둔다
        (home / "jaix.exe").unlink()
        assert winenv.drop_old_exe_dir() == [str(home)]
        assert not winenv.in_user_path(home) and winenv.in_user_path(home / "jaix")
    finally:
        winenv.remove_from_path(home)


def test_doctor_wants_exe_dir_on_path_only_when_frozen(tmp_path, monkeypatch):
    assert paths.exe_dir() is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "jaix" / "jaix.exe"))
    assert paths.exe_dir() == tmp_path / "jaix"
    monkeypatch.setattr(doctor, "IS_WIN", True)
    monkeypatch.setattr(doctor.winenv, "in_user_path", lambda d: False)
    (tmp_path / "jaix").mkdir()
    monkeypatch.setenv("JAIX_HOME", str(tmp_path / "elsewhere"))  # 풀어서 쓰는 zip: PATH 를 묻지 않음
    assert not any(str(tmp_path / "jaix") in c.message for c in doctor.check_path())
    monkeypatch.setenv("JAIX_HOME", str(tmp_path))  # 설치본({app}\\jaix)
    assert any(c.status == "fail" and str(tmp_path / "jaix") in c.message for c in doctor.check_path())


def test_log_and_guide_create_data_dir(isolated):
    logf = isolated / "fresh" / "setup.log"
    guide = isolated / "fresh2" / "guide.txt"
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--log", str(logf),
                     "--guide-out", str(guide)]) == 0
    assert logf.exists() and guide.exists()


def test_batch_wrapper_args_not_parsed_by_cmd(tmp_path, monkeypatch):
    """#36: codex.CMD 를 거칠 때 `mcp>=1.2,<2` 의 < > 가 cmd 리다이렉션이 되지 않게 감싼다."""
    monkeypatch.setattr(proc, "IS_WIN", True)
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\system32\\cmd.exe")
    cli = tmp_path / "codex.CMD"
    cli.write_text("@echo off\r\nsomething-else %*\r\n", encoding="utf-8")  # npm 래퍼가 아님 → 인용한 cmd 명령줄
    args = ["mcp", "add", "hwp-agent", "--", "uvx", "--from", "C:\\a b\\local", "--with", "mcp>=1.2,<2", "hwp-agent", "mcp"]
    line = proc.command(str(cli), args)
    assert line.startswith('"C:\\Windows\\system32\\cmd.exe" /d /s /c "')
    assert ' "mcp>=1.2,<2" ' in line and ' "C:\\a b\\local" ' in line and " mcp add hwp-agent -- uvx " in line
    inner = line.split(" /c ", 1)[1][1:-1]
    # 따옴표 밖에 < > 가 남지 않는다
    assert not re.search(r"[<>]", re.sub(r'"[^"]*"', "", inner))


def test_npm_shim_runs_node_directly(tmp_path, monkeypatch):
    monkeypatch.setattr(proc, "IS_WIN", True)
    script = tmp_path / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    (tmp_path / "node.exe").write_text("", encoding="utf-8")
    cli = tmp_path / "codex.cmd"
    cli.write_text('@ECHO off\r\nGOTO start\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n'
                   'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
                   '"%dp0%\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n', encoding="utf-8")
    assert proc.command(str(cli), ["mcp", "add", "x", "--", "mcp>=1.2,<2"]) == [
        str(tmp_path / "node.exe"), str(script), "mcp", "add", "x", "--", "mcp>=1.2,<2"]


def test_quote_roundtrips_msvcrt_rules():
    assert proc._quote("plain") == "plain"
    assert proc._quote("mcp<2") == '"mcp<2"'
    assert proc._quote("") == '""'
    assert proc._quote('C:\\dir\\') == 'C:\\dir\\'  # 특수문자 없으면 그대로
    assert proc._quote('C:\\a b\\') == '"C:\\a b\\\\"'  # 끝 역슬래시가 닫는 따옴표를 먹지 않게
    assert proc._quote('a"b') == '"a\\"b"'


def test_decode_falls_back_to_oem_codepage(monkeypatch):
    assert proc.decode("한글".encode("utf-8")) == "한글"
    monkeypatch.setattr(proc, "IS_WIN", True)

    class K:
        @staticmethod
        def GetOEMCP():
            return 949
    monkeypatch.setattr(proc.ctypes, "windll", type("W", (), {"kernel32": K}), raising=False)
    assert proc.decode("액세스가 거부되었습니다.".encode("cp949")) == "액세스가 거부되었습니다."


def test_setup_log_banner_records_path(isolated):
    logf = isolated / "setup.log"
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--log", str(logf)]) == 0
    assert re.search(r"^== \d{4}-\d\d-\d\d \d\d:\d\d:\d\d setup \(direct\) · ", logf.read_text(encoding="utf-8"), re.M)
    st = isolated / "st.json"
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--log", str(logf), "--status-out", str(st)]) == 0
    assert "setup (via task)" in logf.read_text(encoding="utf-8")
    assert cli.main(["update", "--quiet", "--offline"]) in (0, 1)
    assert "update (logon task)" in schedule.log_file().read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="진짜 cmd.exe 로 배치 래퍼를 돌려 본다")
def test_batch_wrapper_real_cmd_passes_args_verbatim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shim = tmp_path / "fake.cmd"
    shim.write_text(f'@echo off\r\n"{sys.executable}" -c "import sys, json; print(json.dumps(sys.argv[1:]))" %*\r\n',
                    encoding="utf-8")
    args = ["--with", "mcp>=1.2,<2", "--from", "C:\\a b\\local", "x&y", "100%"]
    code, out = proc.run(str(shim), args, timeout=60)
    assert code == 0, out
    assert json.loads(out.strip().splitlines()[-1])[:5] == args[:5]
    assert not (tmp_path / "2").exists() and not (tmp_path / "=1.2,").exists()  # 리다이렉션이 안 일어났다


RHWP_SRC = '''RHWP_REPO = "edwardkim/rhwp"
RHWP_VERSION = "v0.8.7"
RHWP_ASSETS = {
    "windows-x86_64": (
        f"rhwp-{RHWP_VERSION}-windows-x86_64.zip",
        "f7ac326e98f595ae8fecd8da7a614ee9a37db77bdf938782a8e07c9da473ec6f",
    ),
    "macos-aarch64": (
        f"rhwp-{RHWP_VERSION}-macos-aarch64.tar.gz",
        "6ed46aa63f6d10c447842999f73abc59cf9586c5645fefc5e763bd6a6d43662d",
    ),
}
'''


def test_rhwp_spec_parsed_from_fetch_rhwp_source():
    got = hwprhwp.parse_spec(RHWP_SRC, "windows-x86_64")
    assert got == {"version": "v0.8.7", "asset": "rhwp-v0.8.7-windows-x86_64.zip",
                   "sha256": "f7ac326e98f595ae8fecd8da7a614ee9a37db77bdf938782a8e07c9da473ec6f",
                   "url": "https://github.com/edwardkim/rhwp/releases/download/v0.8.7/rhwp-v0.8.7-windows-x86_64.zip"}
    assert hwprhwp.parse_spec(RHWP_SRC, "linux-x86_64") is None
    assert hwprhwp.parse_spec("nothing") is None


def _rhwp_release(tmp, name):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"rhwp/{name}", b"fake rhwp")
        zf.writestr("rhwp/LICENSE", b"MIT License")
        zf.writestr("rhwp/README.md", b"skip")
    src = tmp / "rel" / "rhwp-v0.8.7-x.zip"
    src.parent.mkdir()
    src.write_bytes(buf.getvalue())
    return src


def test_rhwp_download_checks_sha256_and_keeps_license(isolated, monkeypatch, the_lock):
    import hashlib
    src = _rhwp_release(isolated, hwprhwp.exe().name)
    good = {"version": "v0.8.7", "asset": src.name, "url": src.as_uri(),
            "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}
    monkeypatch.setattr(hwprhwp, "spec", lambda lock, offline=False: {**good, "sha256": "0" * 64})
    assert REAL_RHWP_ENSURE(the_lock, print) is False and not hwprhwp.exe().exists()
    assert doctor.check_rhwp(the_lock)[0].status == "warn"  # 폴백이라 fail 아님
    monkeypatch.setattr(hwprhwp, "spec", lambda lock, offline=False: good)
    assert REAL_RHWP_ENSURE(the_lock, print) is True
    assert hwprhwp.exe().read_bytes() == b"fake rhwp"
    assert (hwprhwp.dest_dir() / "LICENSE").read_bytes() == b"MIT License"
    assert not (hwprhwp.dest_dir() / "README.md").exists()
    assert hwprhwp.installed_version() == "v0.8.7"
    assert doctor.check_rhwp(the_lock)[0].status == "ok"
    src.unlink()  # 같은 버전이면 다시 받지 않는다
    assert REAL_RHWP_ENSURE(the_lock, print) is True


def test_rhwp_skipped_when_locked_hwp_agent_has_no_pin(isolated, monkeypatch, the_lock):
    monkeypatch.setattr(hwprhwp, "spec", lambda lock, offline=False: None)
    logs = []
    assert REAL_RHWP_ENSURE(the_lock, logs.append) is True and "건너뜀" in logs[0]


def test_gw_dev_install_is_never_replaced(isolated, monkeypatch):
    monkeypatch.setattr(gw, "foreign", REAL_GW_FOREIGN)
    """개발용(editable) ji-gw-ai 가 있으면 설치를 건너뛰고 doctor 는 실패가 아닌 안내로 보인다."""
    calls, state = _gw_share(isolated, monkeypatch)
    tools = isolated / "uvtools"
    (tools / "ji-gw-ai").mkdir(parents=True)
    (tools / "ji-gw-ai" / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "ji-gw-ai", editable = "/Users/x/dev/ji-gw-ai" }]\n'
        'entrypoints = [{ name = "gw", install-path = "/Users/x/.local/bin/gw", from = "ji-gw-ai" }]\n', encoding="utf-8")
    base_run = gw._run
    monkeypatch.setattr(gw, "_run", lambda args, timeout=60: (True, str(tools)) if args[1:] == ["tool", "dir"]
                        else base_run(args, timeout))
    res = gw.setup(print)
    assert res["status"] == "foreign" and "editable" in res["paths"][0]
    assert not any(a[1:3] == ["tool", "install"] for a in calls)
    c = doctor.check_gw()[0]
    assert c.status == "skip" and "개발용 gw" in c.message
    assert not cli._setup_problems({"gw": res})


def test_gw_own_wheel_install_is_not_foreign(isolated, monkeypatch):
    monkeypatch.setattr(gw, "foreign", REAL_GW_FOREIGN)
    calls, state = _gw_share(isolated, monkeypatch)
    tools = isolated / "uvtools"
    (tools / "ji-gw-ai").mkdir(parents=True)
    whl = paths.data_dir() / "gw" / "ji_gw_ai-2026.10.27.1-py3-none-any.whl"
    (tools / "ji-gw-ai" / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "ji-gw-ai", path = {json.dumps(str(whl))} }}]\n'
        'entrypoints = [{ name = "gw", install-path = "x", from = "ji-gw-ai" }]\n', encoding="utf-8")
    base_run = gw._run
    monkeypatch.setattr(gw, "_run", lambda args, timeout=60: (True, str(tools)) if args[1:] == ["tool", "dir"]
                        else base_run(args, timeout))
    assert gw.foreign() == []
    assert gw.setup(print)["status"] == "installed"
    # 예전 프로그램 폴더(jaix_home/gw)에서 깐 receipt 도 jaix 것(migrate_data 가 wheel 만 옮김)
    old = paths.jaix_home() / "gw" / whl.name
    (tools / "ji-gw-ai" / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "ji-gw-ai", path = {json.dumps(str(old))} }}]\n'
        'entrypoints = [{ name = "gw", install-path = "x", from = "ji-gw-ai" }]\n', encoding="utf-8")
    assert gw.foreign() == []


def test_gw_other_on_path_is_foreign(isolated, monkeypatch):
    monkeypatch.setattr(gw, "foreign", REAL_GW_FOREIGN)
    _gw_share(isolated, monkeypatch)
    other = isolated / "elsewhere" / "gw"
    monkeypatch.setattr(paths, "which", lambda name: str(other) if name == "gw" else None)
    assert gw.foreign() == [f"PATH의 {other}"]
    assert gw.setup(print)["status"] == "foreign"


def test_doctor_path_tool_version(isolated, monkeypatch, the_lock):
    monkeypatch.setattr(doctor, "PATH_TOOLS", {"hwp-agent": "hwp-agent"})
    monkeypatch.setattr(paths, "which", lambda name: "/opt/hwp-agent" if name == "hwp-agent" else None)
    want = next(p.version for p in the_lock.plugins if p.name == "hwp-agent")
    for out, status, word in ((f"hwp-agent {want}\n", "ok", "같음"), ("hwp-agent 0.0.0+dev\n", "warn", "개발판"),
                              ("hwp-agent 2026.9.1.1\n", "warn", "2026.9.1.1")):
        monkeypatch.setattr(proc, "run", lambda exe, args, timeout=600, out=out: (0, out))
        [c] = doctor.check_path_tools(the_lock)
        assert c.status == status and word in c.message
    monkeypatch.setattr(paths, "which", lambda name: None)
    assert doctor.check_path_tools(the_lock) == []


def _plugin_dir(root, mcp=(), skills=()):
    root.mkdir(parents=True, exist_ok=True)
    if mcp:
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": {n: {"command": "uvx"} for n in mcp}}), encoding="utf-8")
    for s in skills:
        (root / "skills" / s).mkdir(parents=True, exist_ok=True)
        (root / "skills" / s / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    return root


def test_doctor_reports_overlaps_without_removing(isolated, monkeypatch, the_lock):
    cdir = paths.claude_dir()
    mine = _plugin_dir(isolated / "c-cache" / "jaix" / "hwp-agent", mcp=["hwp-agent"], skills=["hwp-agent"])
    other = _plugin_dir(isolated / "c-cache" / "z0nam" / "hwp-agent", mcp=["hwp-agent"], skills=["hwp-agent"])
    (cdir / "plugins").mkdir(parents=True)
    (cdir / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {
        "hwp-agent@jaix": [{"scope": "user", "installPath": str(mine)}],
        "hwp-agent@hwp-agent": [{"scope": "user", "installPath": str(other)}],
        "slack@claude-plugins-official": [{"scope": "user", "installPath": str(isolated / "none")}]}}), encoding="utf-8")
    (cdir / "settings.json").write_text(json.dumps({"enabledPlugins": {
        "hwp-agent@jaix": True, "hwp-agent@hwp-agent": True, "slack@claude-plugins-official": True}}), encoding="utf-8")
    dev = _plugin_dir(isolated / "dev" / "hwp-agent", skills=[])
    (dev / "SKILL.md").write_text("---\nname: hwp-agent\n---\n", encoding="utf-8")
    (cdir / "skills").mkdir()
    try:
        (cdir / "skills" / "hwp-agent").symlink_to(dev, target_is_directory=True)
        linked = True
    except OSError:  # Windows 표준 사용자는 심링크를 못 만든다 → 폴더 그대로
        dev.rename(cdir / "skills" / "hwp-agent")
        linked = False
    (cdir / ".claude.json").write_text(json.dumps({"mcpServers": {"hwp_agent": {}, "dayone": {}}}), encoding="utf-8")
    # Codex: jaix가 쓴 hwp-agent MCP 는 겹침이 아니고, 사용자가 따로 넣은 korea_rio 는 겹침
    xdir = paths.codex_home()
    _plugin_dir(xdir / "plugins" / "cache" / "jaix" / "korea-rio-mcp" / "local", mcp=["korea-rio"])
    _plugin_dir(xdir / "plugins" / "cache" / "jaix" / "hwp-agent" / "local", mcp=["hwp-agent"])
    xdir.mkdir(exist_ok=True)
    (xdir / "config.toml").write_text('[plugins."korea-rio-mcp@jaix"]\nenabled = true\n[plugins."hwp-agent@jaix"]\n'
                                      'enabled = true\n[mcp_servers.korea_rio]\ncommand = "uv"\n'
                                      '[mcp_servers.hwp-agent]\ncommand = "uvx"\n'
                                      '[mcp_servers.korea-rio]\ncommand = "uvx"\n', encoding="utf-8")
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    (paths.data_dir() / "codex-mcp.json").write_text(json.dumps({"hwp-agent": {}}), encoding="utf-8")
    before = sorted(str(p) for p in isolated.rglob("*"))
    checks = {c.area: c for c in doctor.check_overlaps(the_lock)}
    c = checks["Claude 중복 hwp-agent"]
    assert c.status == "warn" and "토큰이 두 배" in c.message
    assert "hwp-agent@hwp-agent" in c.message and ("skills/hwp-agent →" if linked else "skills/hwp-agent") in c.message.replace("\\", "/")
    assert "'hwp_agent'" in c.message and "dayone" not in c.message and "slack" not in c.message
    x = checks["Codex 중복 korea-rio-mcp"]
    assert "korea_rio" in x.message
    assert "'korea-rio'" not in x.message  # 플러그인 서버와 같은 이름 = Codex가 플러그인 쪽을 건너뜀(덮어쓰기)
    assert "Codex 중복 hwp-agent" not in checks
    assert sorted(str(p) for p in isolated.rglob("*")) == before  # 아무것도 지우거나 쓰지 않는다


def test_doctor_load_warns_over_budget(isolated, monkeypatch):
    monkeypatch.setattr(overlap, "claude_load", lambda: (2, 10))
    monkeypatch.setattr(overlap, "codex_load", lambda: (12, 40))
    c, x = doctor.check_load()
    assert c.status == "ok" and "MCP 서버 2개" in c.message
    assert x.status == "warn" and "사용량 한도" in x.message
    monkeypatch.setattr(overlap, "codex_load", lambda: (0, 0))
    assert len(doctor.check_load()) == 1


def test_overlap_name_normalization():
    assert overlap.norm("korea_rio") == overlap.norm("korea-rio-mcp") == "korea-rio"
    assert overlap.norm("HWP_Agent") == "hwp-agent"


def _codex_installed(isolated, the_lock, heads):
    """Codex에 잠금 플러그인이 모두 켜진 상태. heads: {이름: 사본 .git HEAD 내용(없으면 .git 없음)}."""
    home = paths.codex_home()
    body = "[marketplaces.jaix]\nsource = \"x\"\n"
    for p in the_lock.plugins:
        root = home / "plugins" / "cache" / "jaix" / p.name / "local"
        root.mkdir(parents=True)
        if p.name in heads:
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text(heads[p.name] + "\n", encoding="utf-8")
        body += f'[plugins."{p.id}"]\nenabled = true\n'
    (home / "config.toml").write_text(body, encoding="utf-8")
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    (paths.data_dir() / "codex-installed.json").write_text(  # 처음 설치 때의 옛 커밋(#48)
        json.dumps({p.id: "0" * 40 for p in the_lock.plugins}), encoding="utf-8")


def test_codex_setup_aligns_stale_record_when_copy_is_current(isolated, monkeypatch, the_lock):
    """#48: 덮어 설치(setup) 뒤 사본은 최신인데 기록이 옛 커밋이라 doctor 가 '옛 버전' 실패를 냈다."""
    first, *rest = the_lock.plugins
    _codex_installed(isolated, the_lock, {p.name: p.sha for p in rest})  # first 는 .git 없음(git-subdir 사본)
    git = paths.codex_home() / "plugins" / "cache" / "jaix" / rest[0].name / "local" / ".git"
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")  # 브랜치 HEAD + packed-refs 꼴도
    (git / "packed-refs").write_text(f"# pack-refs\n{rest[0].sha} refs/heads/main\n", encoding="utf-8")
    monkeypatch.setattr(codex, "find_cli", lambda: "codex")
    monkeypatch.setattr(codex, "write_mcp", lambda lock, log, cli=None, dry_run=False: True)
    added = []
    monkeypatch.setattr(codex, "_run", lambda cli, args, log: added.append(args) or True)
    snap = paths.codex_home() / ".tmp" / "marketplaces" / "jaix" / ".claude-plugin"
    snap.mkdir(parents=True)
    snap.joinpath("marketplace.json").write_text(json.dumps(the_lock.data), encoding="utf-8")
    bad = [c for c in doctor.check_codex(the_lock) if c.status == "fail"]
    assert [c.area for c in bad] == [f"Codex {first.name}"]  # 사본으로 확인되는 것은 기록이 낡아도 통과
    res = codex.setup(the_lock, print)  # update=False(setup)
    assert res["failed"] == []
    assert [a for a in added if a[:2] == ["plugin", "add"]] == [["plugin", "add", first.id]]  # 실물 모르는 것만 다시 깜
    rec = codex.recorded()
    assert all(lock.same_commit(rec[p.id], p.sha) for p in the_lock.plugins)
    assert not [c for c in doctor.check_codex(the_lock) if c.status == "fail"]



def test_doctor_warns_outdated_hwp2pdf(monkeypatch):
    """HWP2PDF_LOCAL을 모르는 옛 hwp2pdf-cli는 동작은 하므로 실패가 아니라 주의 + 업데이트 안내."""
    rt = runtimes.BY_KEY["hwp2pdf"]
    monkeypatch.setattr(runtimes, "RUNTIMES", [dataclasses.replace(rt, windows_only=False)])
    monkeypatch.setattr(runtimes, "hancom_installed", lambda: True)
    for version, status in (("2026.09.28.1", "warn"), (rt.min_version, "ok"), ("2026.11.2.1", "ok"), (None, "ok")):
        monkeypatch.setattr(runtimes, "find", lambda r, v=version: runtimes.Found("C:/bin/hwp2pdf-cli.exe", v))
        [c] = doctor.check_runtimes()
        assert c.status == status, version
        if status == "warn":
            assert "업데이트 필요" in c.message and rt.min_version in c.message and "jaix update" in c.fix


# --- Hermes 무인 설치 · 슬랙 토큰 1회 전달 (hermesbot) ---------------------------------------------


def test_handoff_code_and_bundle_0600(tmp_path):
    codes = {hermesbot.new_code() for _ in range(50)}
    assert len(codes) == 50 and all(hermesbot.CODE_RE.match(c) for c in codes)
    code, _ = hermesbot.write_bundle(tmp_path / "spool", "demo", "U0TEST", "xoxb-TEST-1", "xapp-TEST-1")
    f = tmp_path / "spool" / f"{hermesbot.code_key(code)}.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["bot_token"] == "xoxb-TEST-1" and "expires_at" in data and code not in f.read_text(encoding="utf-8")
    if not paths.IS_WIN:
        assert oct(f.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(FileExistsError):  # 같은 코드로 덮어쓰지 않는다
        hermesbot.write_bundle(tmp_path / "spool", "demo", "U0TEST", "xoxb-TEST-2", "xapp-TEST-2", code=code)


def test_cmd_handoff_checks_tokens_before_writing(tmp_path, monkeypatch, capsys):
    tokens = iter(["xoxb-TEST-1" + "x" * 40, "xapp-TEST-1" + "x" * 40])
    monkeypatch.setattr(hermesbot.secret, "masked_input", lambda prompt, out=None: next(tokens))
    monkeypatch.setattr(hermesbot, "slack_call", lambda m, t: {"ok": True, "user": "hermes-bob", "team": "T"})
    args = type("A", (), {"id": "demo", "user": "U0TEST", "ttl": 72, "spool": str(tmp_path / "spool")})()
    assert hermesbot.cmd_handoff(args, print) == 1          # 다른 사람 봇 → 멈춤, 묶음 없음
    assert not (tmp_path / "spool").exists()
    tokens = iter(["xoxb-TEST-1" + "x" * 40, "xapp-TEST-1" + "x" * 40])
    monkeypatch.setattr(hermesbot, "slack_call", lambda m, t: {"ok": True, "user": "hermes-demo", "team": "T"})
    assert hermesbot.cmd_handoff(args, print) == 0
    out = capsys.readouterr().out
    assert len(list((tmp_path / "spool").glob("*.json"))) == 1
    assert "xoxb-TEST" not in out and "xapp-TEST" not in out and re.search(r"JX-[A-Z2-7]{26}", out)


def test_read_code_file_deletes_even_bad(tmp_path):
    f = tmp_path / "code"
    f.write_text("jx-" + "a" * 26 + "\n", encoding="utf-8")
    assert hermesbot.read_code_file(f) == "JX-" + "A" * 26 and not f.exists()
    f.write_text("nope", encoding="utf-8")
    with pytest.raises(hermesbot.HandoffError):
        hermesbot.read_code_file(f)
    assert not f.exists()


@pytest.fixture
def handoff_server(monkeypatch):
    """배포처 흉내: 코드 하나를 한 번만 준다(본문으로 받는지도 본다)."""
    import http.server
    import threading
    state = {"code": "JX-" + "A" * 26, "used": False, "paths": []}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            state["paths"].append(self.path)
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            if body != state["code"]:
                status, data = 404, {"error": "unknown"}
            elif state["used"]:
                status, data = 410, {"error": "used"}
            else:
                state["used"] = True
                status, data = 200, {"id": "demo", "user": "U0TEST", "bot_token": "xoxb-TEST-1", "app_token": "xapp-TEST-1"}
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("JAIX_HANDOFF_URL", f"http://127.0.0.1:{srv.server_address[1]}/hermes/handoff")
    yield state
    srv.shutdown()
    srv.server_close()


def test_claim_once_then_used(handoff_server):
    code = handoff_server["code"]
    assert hermesbot.claim(code)["bot_token"] == "xoxb-TEST-1"
    with pytest.raises(hermesbot.HandoffError, match="이미 사용"):
        hermesbot.claim(code)
    with pytest.raises(hermesbot.HandoffError, match="만료"):
        hermesbot.claim("JX-" + "B" * 26)
    assert all(code not in p for p in handoff_server["paths"])  # 코드는 URL에 싣지 않는다


def _fake_windows(monkeypatch, isolated, calls):
    monkeypatch.setattr(hermesbot, "IS_WIN", True)
    monkeypatch.setattr(hermesbot, "install_hermes", lambda log, dry_run=False: True)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "hermes")
    # 자격 목록(hermes auth list)은 _run 을 거치지 않는다 — 가짜로 막지 않으면 PATH 의 진짜 hermes 가 돈다
    monkeypatch.setattr(hermesbot, "_auth", lambda hermes, args, timeout=60: (0, ""))
    monkeypatch.setattr(hermesbot, "_run", lambda cmd, log, timeout=600: (calls.append(cmd), (True, ""))[1])
    monkeypatch.setattr(hermes, "install", lambda lock, log, dry_run=False: [])


def test_hermes_setup_connects_and_never_logs_secrets(isolated, monkeypatch, handoff_server, the_lock):
    calls, lines = [], []
    _fake_windows(monkeypatch, isolated, calls)
    seen = {}
    monkeypatch.setattr(hermesbot, "connect_slack", lambda bundle, log: seen.update(bundle) or True)
    code_file = isolated / "pending" / "hermes-code"
    code_file.parent.mkdir()
    code_file.write_text(handoff_server["code"], encoding="utf-8")
    res = REAL_HERMES_SETUP(the_lock, lines.append, code_file=str(code_file), model="claude")
    assert res["status"] == "connected" and res["id"] == "demo" and seen["app_token"] == "xapp-TEST-1"
    assert not code_file.exists()
    assert ["hermes", "config", "set", "model.provider", "anthropic"] in calls
    assert ["hermes", "tools", "disable", "browser", "computer_use", "--platform", "slack"] in calls
    text = "\n".join(lines)
    assert "xoxb-TEST" not in text and "xapp-TEST" not in text and handoff_server["code"] not in text
    assert hermesbot.recorded()["status"] == "connected"


def test_hermes_setup_bad_code_fails_and_doctor_shows_it(isolated, monkeypatch, the_lock):
    _fake_windows(monkeypatch, isolated, [])
    code_file = isolated / "code"
    code_file.write_text("wrong", encoding="utf-8")
    res = REAL_HERMES_SETUP(the_lock, print, code_file=str(code_file))
    assert res["status"] == "failed" and not code_file.exists()
    checks = doctor.check_hermes(the_lock)
    assert checks[0].status == "fail" and checks[0].area == "Hermes 슬랙"


def test_hermes_setup_without_code_installs_but_warns(isolated, monkeypatch, the_lock):
    _fake_windows(monkeypatch, isolated, [])
    assert REAL_HERMES_SETUP(the_lock, print)["status"] == "no-code"
    assert doctor.check_hermes(the_lock)[0].status == "warn"


def test_hermes_setup_failure_makes_setup_fail(isolated, monkeypatch, the_lock):
    monkeypatch.setattr(hermesbot, "setup", lambda lock, log, **kw: {"status": "failed", "error": "x"})
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    assert cli._setup_problems({"hermes": {"status": "failed"}})
    assert cli.main(["setup", "--runtimes", "none", "--channels", "hermes", "--no-autoupdate"]) != 0


def test_hermes_config_failure_stops_before_claim(isolated, monkeypatch, the_lock):
    _fake_windows(monkeypatch, isolated, [])
    monkeypatch.setattr(hermesbot, "configure", lambda *a, **kw: False)
    monkeypatch.setattr(hermesbot, "claim", lambda code: pytest.fail("코드를 쓰면 안 됨"))
    code_file = isolated / "code"
    code_file.write_text("JX-" + "A" * 26, encoding="utf-8")
    assert REAL_HERMES_SETUP(the_lock, print, code_file=str(code_file))["status"] == "failed"


def test_hermes_dry_run_keeps_code_file(isolated, monkeypatch, the_lock):
    _fake_windows(monkeypatch, isolated, [])
    code_file = isolated / "code"
    code_file.write_text("JX-" + "A" * 26, encoding="utf-8")
    assert REAL_HERMES_SETUP(the_lock, print, code_file=str(code_file), dry_run=True)["status"] == "dry-run"
    assert code_file.exists()


def test_hermes_mcp_only_jaix_entries(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", lambda cmd, log, timeout=600: (calls.append(cmd), (True, ""))[1])
    rec = codex._mcp_record()
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"hwp-agent": {"command": "uvx", "args": ["--python", "3.12", "x"], "env": {}},
                               "korea-rio": {"command": "uvx", "args": ["y"], "env": {}}}), encoding="utf-8")
    cfg = hermesbot.config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("model:\n  provider: x\nmcp_servers:\n  korea-rio:\n    command: mine\n", encoding="utf-8")
    assert hermesbot.write_mcp("hermes", print)
    names = [c[3] for c in calls]
    assert names == ["mcp_servers.hwp-agent"]           # 사용자 것(korea-rio)은 그대로
    assert json.loads(calls[0][4])["args"][:2] == ["--python", "3.12"]
    assert hermesbot._yaml_has_key(cfg.read_text(encoding="utf-8"), "mcp_servers", "korea-rio")
    assert not hermesbot._yaml_has_key("model:\n  korea-rio: 1\n", "mcp_servers", "korea-rio")
    for text in ("mcp_servers: # custom\n  hwp-agent:\n", "mcp_servers:\n    hwp-agent:\n",
                 "mcp_servers:\n  'hwp-agent':\n", "mcp_servers:\n  \"hwp-agent\": {}\n"):
        assert hermesbot._yaml_has_key(text, "mcp_servers", "hwp-agent"), text


def test_no_slack_secrets_in_repo():
    """공개 저장소에 진짜 슬랙 토큰·연결 코드가 들어가지 않게(시험용 TEST 값만 허용, 설계 §5)."""
    root = Path(__file__).resolve().parent.parent
    pat = re.compile(r"(xox[abpe]-|xapp-)(?!TEST|OLD|…)[0-9A-Za-z-]{8,}|JX-(?![A]{26}|[B]{26})[A-Z2-7]{26}")
    hits = []
    for f in root.rglob("*"):
        if f.is_file() and ".git" not in f.parts and ".venv" not in f.parts and f.suffix in {".py", ".md", ".iss", ".yml", ".json", ".toml"}:
            for m in pat.finditer(f.read_text(encoding="utf-8", errors="replace")):
                hits.append(f"{f.relative_to(root)}: {m.group(0)[:12]}…")
    assert not hits, hits
# --- mail 플러그인이 잠금에 들어가면: himalaya·age 필수, uv 관리 Python 3.12 점검 -----------------------
def _with_mail(the_lock):
    data = json.loads(json.dumps(the_lock.data))
    if not any(p["name"] == "mail-skill" for p in data["plugins"]):
        data["plugins"].append({**data["plugins"][0], "name": "mail-skill"})
    return lock.Lock(data, the_lock.source)


def _without_mail(the_lock):
    data = json.loads(json.dumps(the_lock.data))
    data["plugins"] = [p for p in data["plugins"] if p["name"] != "mail-skill"]
    return lock.Lock(data, the_lock.source)


def test_mail_runtime_name_matches_lock_entry(the_lock):
    """needed_by·MAIL_PLUGIN 은 잠금 entry 이름(plugin.json name)과 같아야 한다 — 'mail' 로 두면 영영 필수가 안 된다."""
    names = {p.name for p in the_lock.plugins}
    assert runtimes.BY_KEY["himalaya"].needed_by in names and runtimes.BY_KEY["age"].needed_by in names
    assert doctor.MAIL_PLUGIN in names


def test_mail_runtimes_required_only_when_mail_in_lock(the_lock):
    keys = lambda lk: {rt.key for rt in runtimes.select([], lk)}
    assert not {"himalaya", "age"} & keys(_without_mail(the_lock))
    assert {"himalaya", "age"} <= keys(_with_mail(the_lock))
    assert not runtimes.required(runtimes.BY_KEY["age"], None)


def test_doctor_mail_runtime_missing_fails_only_with_mail(the_lock, monkeypatch):
    monkeypatch.setattr(runtimes, "find", lambda rt: runtimes.Found(None, None))
    by = lambda lk: {c.area: c.status for c in doctor.check_runtimes(lk)}
    assert by(_without_mail(the_lock))["himalaya"] == "skip"
    assert by(_with_mail(the_lock))["himalaya"] == "fail"


def test_doctor_mail_python(the_lock, monkeypatch):
    assert doctor.check_mail_python(_without_mail(the_lock)) == []
    lk = _with_mail(the_lock)
    monkeypatch.setattr(runtimes, "find", lambda rt: runtimes.Found("/x/uv", "0.9"))
    monkeypatch.setattr(uvpython, "find", lambda v, uv=None: None)
    monkeypatch.setattr(doctor, "IS_WIN", True)
    [c] = doctor.check_mail_python(lk)
    assert c.status == "fail" and "3.12" in c.message
    monkeypatch.setattr(doctor, "IS_WIN", False)
    assert doctor.check_mail_python(lk)[0].status == "warn"   # 맥·리눅스는 uv 가 처음 실행 때 받음
    monkeypatch.setattr(uvpython, "find", lambda v, uv=None: "/py/3.12/python")
    assert doctor.check_mail_python(lk)[0].status == "ok"


def test_doctor_codex_mcp_taken_by_standalone_installer(isolated, monkeypatch, the_lock):
    """hwp-agent 단독 설치본(Inno)이 jaix가 쓴 [mcp_servers.hwp-agent] 를 자기 exe 로 덮어쓴 경우(jaix-win v30.2 3-(a))."""
    home, root, calls = _codex_home_with_plugin(isolated, monkeypatch, the_lock)
    codex.write_mcp(the_lock, print, cli="codex")
    monkeypatch.setattr(codex, "find_cli", lambda: "codex")
    monkeypatch.setattr(codex, "marketplace_configured", lambda: True)
    cfg = home / "config.toml"
    exe = r"C:\\Users\\u\\AppData\\Local\\Programs\\hwp-agent\\hwp-agent.exe"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('command = "uvx"', f'command = {json.dumps(exe)}'),
                   encoding="utf-8")
    mcp = [c for c in doctor.check_codex(the_lock) if c.area == "Codex MCP"]
    assert len(mcp) == 1 and mcp[0].status == "fail" and "다른 설치본" in mcp[0].message and "hwp-agent.exe" in mcp[0].message
    assert "0 tools" not in mcp[0].message and "단독 설치본의 MCP 등록을 끈 뒤" in mcp[0].fix
    codex.write_mcp(the_lock, print, cli="codex")          # update 가 돌면 손을 떼지만
    mcp = [c for c in doctor.check_codex(the_lock) if c.area == "Codex MCP"]
    assert [c.status for c in mcp] == ["warn"] and "hwp-agent.exe" in mcp[0].message   # 계속 알린다
    assert "무시해도 됨" in mcp[0].fix


def test_doctor_codex_mcp_user_definition_from_start_stays_quiet(isolated, monkeypatch, the_lock):
    """처음부터 사용자가 정의한 항목(jaix가 쓴 적 없음)은 예전처럼 경고하지 않는다."""
    home, root, calls = _codex_home_with_plugin(isolated, monkeypatch, the_lock)
    monkeypatch.setattr(codex, "find_cli", lambda: "codex")
    monkeypatch.setattr(codex, "marketplace_configured", lambda: True)
    cfg = home / "config.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + '\n[mcp_servers."hwp-agent"]\ncommand = "python"\n', encoding="utf-8")
    codex.write_mcp(the_lock, print, cli="codex")
    assert [c.status for c in doctor.check_codex(the_lock) if c.area == "Codex MCP"] == ["ok"]


def test_doctor_codex_mcp_missing_has_no_unmeasured_claim(isolated, monkeypatch, the_lock):
    home, root, calls = _codex_home_with_plugin(isolated, monkeypatch, the_lock)
    monkeypatch.setattr(codex, "find_cli", lambda: "codex")
    monkeypatch.setattr(codex, "marketplace_configured", lambda: True)
    [c] = [c for c in doctor.check_codex(the_lock) if c.area == "Codex MCP"]
    assert c.status == "fail" and "없음/옛것" in c.message and "0 tools" not in c.message


# 한컴 첫 실행 동의 창 — 실측(jaix-win, 2026-10-30)에서 창을 막은 바이트 그대로(UTF-8 BOM·CRLF·209바이트)
MEASURED_OPTION_INFO = b"\xef\xbb\xbf" + b"\r\n".join([
    b'<?xml version="1.0" encoding="utf-8"?>', b"<root>", b"  <Common>", b"    <OptionInfo>",
    b'      <EnableUsabilityLog value="0" />', b'      <EnableUsabilityLogSending value="0" />',
    b"    </OptionInfo>", b"  </Common>", b"</root>",
]) + b"\r\n"


def test_hancom_consent_written_only_when_missing(monkeypatch):
    monkeypatch.setattr(hancom, "applies", lambda: True)
    path = hancom.option_info()
    logs = []
    assert hancom.ensure(logs.append, dry_run=True) and not path.exists()
    assert hancom.ensure(logs.append) and path.read_bytes() == MEASURED_OPTION_INFO
    assert len(MEASURED_OPTION_INFO) == 209
    # 있으면(동의함·한글이 만든 기본값·깨진 파일) 무엇이 들었든 그대로
    for body in ('\ufeff<root><Common><OptionInfo><EnableUsabilityLog value="1" />'
                 '<EnableUsabilityLogSending value="1" /></OptionInfo></Common></root>'.encode(),
                 b"\xef\xbb\xbf<root><Common><OptionInfo><Activation value=\"1\" /></OptionInfo></Common></root>",
                 b"not xml"):
        path.write_bytes(body)
        assert hancom.ensure(logs.append) and path.read_bytes() == body
    assert not list(path.parent.glob("optionInfo.xml.*"))


def test_hancom_consent_skipped_without_hancom(monkeypatch):
    monkeypatch.setattr(hancom, "present", lambda: False)
    assert hancom.ensure(print) and not hancom.option_info().exists()
    assert doctor.check_hancom_consent() == []


def test_hancom_consent_only_for_measured_2022(monkeypatch):
    # 다른 버전(예: 2024=HOffice130)은 키·창이 같은지 모른다 — 120 폴더에 효과 없는 파일을 쓰지 않는다
    monkeypatch.setattr(hancom, "present", lambda: True)
    monkeypatch.setattr(hancom, "installed_version", lambda: "130")
    assert hancom.ensure(print) and not hancom.option_info().exists()
    [c] = doctor.check_hancom_consent()
    assert c.status == "skip" and "한컴 130" in c.message


def test_hancom_consent_never_replaces_a_file_made_meanwhile(monkeypatch):
    # 존재 확인 뒤에 한글이 파일을 만들었으면(경합) 그 파일을 그대로 둔다
    monkeypatch.setattr(hancom, "applies", lambda: True)
    path = hancom.option_info()
    real_link = hancom.os.link

    def link_after_hangul(src, dst):
        Path(dst).write_bytes(b"hangul wrote this")
        return real_link(src, dst)

    monkeypatch.setattr(hancom.os, "link", link_after_hangul)
    assert hancom.ensure(print) and path.read_bytes() == b"hangul wrote this"
    assert not path.with_name("optionInfo.xml.tmp").exists()


def test_doctor_hancom_consent_line(monkeypatch):
    monkeypatch.setattr(hancom, "present", lambda: True)
    monkeypatch.setattr(hancom, "applies", lambda: True)
    path = hancom.option_info()
    [c] = doctor.check_hancom_consent()
    assert c.status == "warn" and c.fix == "jaix setup"
    hancom.ensure(print)
    [c] = doctor.check_hancom_consent()
    assert c.status == "ok" and "동의 안 함" in c.message
    path.write_text('<root><Common><OptionInfo><EnableUsabilityLog value="1" />'
                    '<EnableUsabilityLogSending value="1" /></OptionInfo></Common></root>', encoding="utf-8-sig")
    [c] = doctor.check_hancom_consent()
    assert c.status == "ok" and c.message == "답해 둠"
    path.write_text('<root><Common><OptionInfo><Activation value="1" /></OptionInfo></Common></root>',
                    encoding="utf-8-sig")
    [c] = doctor.check_hancom_consent()
    assert c.status == "warn" and "한글을 한 번 직접 열어" in c.fix


def test_hancom_version_from_com_server_path():
    # namun-ji 실측(HKCR\\WOW6432Node\\CLSID\\{2291CF00-…}\\LocalServer32)
    assert hancom.version_from_server(r"C:\Program Files (x86)\Hnc\Office 2022\HOffice120\bin\hwp.exe -Automation") == "120"
    assert hancom.version_from_server(r"C:\Program Files (x86)\Hnc\Office 2024\HOffice130\Bin\Hwp.exe") == "130"
    assert hancom.version_from_server(r"C:\Hwp\hwp.exe") is None


def test_cli_hermes_handoff_runs_without_log_option(tmp_path, monkeypatch, capsys):
    """jaix-kit#67: hermes 하위 명령은 공통 옵션(--log)이 없어 main 이 AttributeError 로 죽었다."""
    tokens = iter(["xoxb-TEST-1" + "x" * 40, "xapp-TEST-1" + "x" * 40])
    monkeypatch.setattr(hermesbot.secret, "masked_input", lambda prompt, out=None: next(tokens))
    monkeypatch.setattr(hermesbot, "slack_call", lambda m, t: {"ok": True, "user": "hermes-demo", "team": "T"})
    assert cli.main(["hermes", "handoff", "demo", "--user", "U0TEST", "--spool", str(tmp_path / "spool")]) == 0
    assert re.search(r"JX-[A-Z2-7]{26}", capsys.readouterr().out)
    with pytest.raises(SystemExit):  # 연결 코드가 기록 파일에 남지 않게 --log 는 받지 않는다
        cli.build_parser().parse_args(["hermes", "handoff", "demo", "--user", "U0TEST", "--log", "x"])


def test_bot_name_matches_ignores_separators():
    """jaix-kit#69: 슬랙이 Hermes-jitest 봇의 user 를 'hermesjitest' 로 돌려준다."""
    for user in ("hermesjitest", "hermes-jitest", "Hermes_jitest", "hermes.jitest"):
        assert hermesbot.bot_name_matches({"user": user}, "jitest"), user
    assert not hermesbot.bot_name_matches({"user": "hermesbob"}, "jitest")
    assert not hermesbot.bot_name_matches({}, "jitest")



# --- 숨김 입력(*) — 사용자 피드백 2026-10-30 -------------------------------------------------------
from jaix import secret  # noqa: E402


class _Out:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s

    def flush(self):
        pass


def test_masked_feed_stars_backspace_and_paste():
    out = _Out()
    assert secret._feed(iter("abc\x7fd\r"), out) == "abd"
    assert out.text == "***\b \b*"                      # 글자마다 *, 백스페이스는 지움
    out = _Out()
    pasted = "xoxb-" + "1" * 52
    assert secret._feed(iter(pasted + "\n"), out) == pasted and out.text == "*" * len(pasted)
    assert secret._feed(iter("\xe0Ka\r"), _Out()) == "a"  # Windows 기능키(화살표)는 버림
    with pytest.raises(secret.Cancelled):
        secret._feed(iter("ab\x03"), _Out())
    with pytest.raises(EOFError):                          # 빈 상태의 Ctrl+D 는 취소
        secret._feed(iter("\x04"), _Out())
    assert secret._feed(iter("a\x04\x1bb\r"), _Out()) == "ab"
    out = _Out()
    assert secret._feed(iter("typo\x15ok\r"), out) == "ok"  # Ctrl+U 는 줄 전체를 지움(getpass 와 같게)
    assert out.text == "****" + "\b \b" * 4 + "**"  # 입력 중 Ctrl+D·그 밖의 제어문자는 무시


def test_ask_secret_retries_and_shows_only_length():
    good = "xoxb-" + "9" * 52
    answers, lines = iter(["oops", "xoxb-short", good]), []
    got = secret.ask_secret("Bot", secret.slack_token("xoxb-"), "xoxb-로 시작", reader=lambda p: next(answers),
                            log=lines.append)
    assert got == good
    assert lines[:2] == ["  형식이 맞지 않음 — 다시 붙여 넣으세요 (xoxb-로 시작)"] * 2 and lines[2] == f"  받음 ({len(good)}자)"
    assert all("oops" not in l and "9999" not in l for l in lines)
    assert secret.ask_secret("Bot", secret.slack_token("xoxb-"), "h", reader=lambda p: "bad", log=lines.append) is None


def test_masked_input_falls_back_to_getpass_without_tty(monkeypatch):
    monkeypatch.setattr(secret.getpass, "getpass", lambda prompt: "from-getpass")
    assert secret.masked_input("x: ") == "from-getpass"   # pytest 의 stdin 은 터미널이 아니다


def _connected_before(isolated, monkeypatch):
    _fake_windows(monkeypatch, isolated, [])
    hermesbot._save_record({"status": "connected", "slack": {"id": "jitest", "connected": "t0"}})
    hermes_home = hermesbot.paths.hermes_home()
    hermes_home.mkdir(parents=True, exist_ok=True)
    (hermes_home / ".env").write_text("SLACK_BOT_TOKEN=x\nSLACK_APP_TOKEN=y\n", encoding="utf-8")
    monkeypatch.setattr(hermesbot, "startup_entries", lambda: ["vbs"])


def test_hermes_rerun_without_code_keeps_connection(isolated, monkeypatch, the_lock):
    """jaix-win 2차: 연결된 PC 에서 새 판을 덮어 설치(코드 칸 비움)해도 '연결 안 됨'으로 바뀌지 않는다."""
    _connected_before(isolated, monkeypatch)
    res = REAL_HERMES_SETUP(the_lock, print)
    assert res["status"] == "connected" and res["id"] == "jitest"
    assert [c.status for c in doctor.check_hermes_bot()] == ["ok"]


def test_hermes_rerun_with_used_code_fails_but_keeps_connection(isolated, monkeypatch, the_lock, handoff_server):
    _connected_before(isolated, monkeypatch)
    handoff_server["used"] = True
    code_file = isolated / "code"
    code_file.write_text(handoff_server["code"], encoding="utf-8")
    res = REAL_HERMES_SETUP(the_lock, print, code_file=str(code_file))
    assert res["status"] == "failed" and "이미 사용" in res["error"]          # 이번 실행은 실패(종료 코드 10)
    assert "그대로 동작" in "\n".join(cli._hermes_guide(res))
    rec = hermesbot.recorded()
    assert rec["status"] == "connected" and rec["slack"]["id"] == "jitest" and "이미 사용" in rec["last_error"]
    assert [c.status for c in doctor.check_hermes_bot()] == ["ok", "warn"]   # 봇은 그대로, 주의만


# --- Hermes 소음 정리(jaix-win 2차 관찰, jaix-kit-dev 10-30) --------------------------------------
def _hermes_skills(names_builtin, names_jaix):
    root = hermesbot.paths.hermes_home() / "skills"
    for n in names_builtin:
        d = root / "creative" / n
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {n}\n---\n", encoding="utf-8")
    for n in names_jaix:
        d = hermes.skills_dir() / n
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {n}\n---\n", encoding="utf-8")
        (d / hermes.MARKER).write_text('{"plugin": "p"}', encoding="utf-8")


def test_hermes_quiet_sets_notice_slash_and_skills(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", lambda cmd, log, timeout=600: (calls.append(cmd), (True, ""))[1])
    _hermes_skills(["p5js", "humanizer", "hwp-agent"], ["hwp-agent", "gw"])
    assert hermesbot.quiet("hermes", print)
    sets = {c[3]: c[4] for c in calls if c[1:3] == ["config", "set"]}
    assert sets["compression.codex_gpt55_autoraise_notice"] == "false"
    allowed = json.loads(sets["slack.user_allowed_commands"])
    assert json.loads(sets["slack.allow_admin_from"]) == [hermesbot.SLASH_NOBODY]
    assert not {"login", "topup", "yolo"} & set(allowed) and {"new", "help", "approvals", "gw", "hwp-agent"} <= set(allowed)
    assert json.loads(sets["skills.disabled"]) == ["humanizer", "p5js"]   # jaix 와 같은 이름(hwp-agent)은 끄지 않음
    assert hermesbot.recorded()["quiet"]["slash"] is True


def test_hermes_quiet_keeps_user_settings(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", lambda cmd, log, timeout=600: (calls.append(cmd), (True, ""))[1])
    cfg = hermesbot.config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("slack:\n  allow_admin_from:\n    - U0ADMIN\nskills:\n  disabled: [x]\n", encoding="utf-8")
    lines = []
    assert hermesbot.quiet("hermes", lines.append)
    keys = [c[3] for c in calls if c[1:3] == ["config", "set"]]
    assert keys == ["compression.codex_gpt55_autoraise_notice"]
    assert any("사용자 설정" in l for l in lines)


def test_hermes_setup_runs_quiet_after_skills(isolated, monkeypatch, the_lock):
    order = []
    _fake_windows(monkeypatch, isolated, [])
    monkeypatch.setattr(hermes, "install", lambda lock, log, dry_run=False: order.append("skills") or [])
    monkeypatch.setattr(hermesbot, "quiet", lambda h, log: order.append("quiet") or True)
    REAL_HERMES_SETUP(the_lock, print)
    assert order == ["skills", "quiet"]



def test_hermes_quiet_refreshes_empty_managed_skill_list(isolated, monkeypatch):
    """처음에 기본 스킬이 없어 jaix가 skills.disabled: [] 를 썼어도, 다음 실행에서 새 기본 스킬을 끈다."""
    calls = []
    monkeypatch.setattr(hermesbot, "_run", lambda cmd, log, timeout=600: (calls.append(cmd), (True, ""))[1])
    hermesbot._save_record({"quiet": {"slash": True, "skills": []}})
    cfg = hermesbot.config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("skills:\n  disabled: []\n", encoding="utf-8")
    _hermes_skills(["new-default"], [])
    hermesbot.quiet("hermes", print)
    sets = {c[3]: c[4] for c in calls if c[1:3] == ["config", "set"]}
    assert json.loads(sets["skills.disabled"]) == ["new-default"]


# --- 위험 명령 승인 방식(사용자 결정 10-30: 연구원은 smart·manual, off 는 관리자만) ---------------------
def test_hermes_approvals_cli_only_smart_manual(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "hermes")
    monkeypatch.setattr(hermesbot, "_run", lambda cmd, log, timeout=600: (calls.append(cmd), (True, ""))[1])
    assert cli.main(["hermes", "approvals", "manual"]) == 0
    assert calls[-1] == ["hermes", "config", "set", "approvals.mode", "manual"]
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["hermes", "approvals", "off"])


def test_hermes_approval_mode_read_and_doctor_warns_off(isolated, monkeypatch):
    cfg = hermesbot.config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("model:\n  mode: x\napprovals:\n  timeout: 60\n  mode: off\nother: 1\n", encoding="utf-8")
    assert hermesbot.approval_mode() == "off"
    hermesbot._save_record({"status": "connected", "slack": {"id": "a", "connected": "t"}})
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")  # 진짜 hermes 를 부르지 않게
    monkeypatch.setattr(hermesbot, "env_has", lambda k: True)
    monkeypatch.setattr(hermesbot, "startup_entries", lambda: ["vbs"])
    assert [c.status for c in doctor.check_hermes_bot()] == ["ok", "warn"]
    cfg.write_text("approvals:\n  mode: 'smart'\n", encoding="utf-8")
    assert hermesbot.approval_mode() == "smart" and [c.status for c in doctor.check_hermes_bot()] == ["ok"]


# --- GitHub 익명 한도(원내 여러 PC 가 한 공인 IP 로 동시 설치, jaix-kit-dev 11-03) --------------------
import email.message  # noqa: E402
import urllib.error  # noqa: E402

from jaix import net  # noqa: E402


def _http_error(code, remaining=None):
    h = email.message.Message()
    if remaining is not None:
        h["X-RateLimit-Remaining"] = remaining
    return urllib.error.HTTPError("https://api.github.com/x", code, "rate limit exceeded", h, None)


def test_release_asset_falls_back_to_web_when_api_rate_limited(monkeypatch):
    monkeypatch.setattr(net, "_api_release", lambda repo: (_ for _ in ()).throw(_http_error(403, "0")))
    monkeypatch.setattr(net, "_web_release", lambda repo: {"tag_name": "v1", "assets": [
        {"name": "tool-1.exe", "browser_download_url": "https://github.com/o/r/releases/download/v1/tool-1.exe"}]})
    assert net.latest_release_asset("o/r", r"^tool-[\d.]+\.exe$")[0] == "tool-1.exe"


def test_release_asset_rate_limited_everywhere_gives_hint(monkeypatch):
    monkeypatch.setattr(net, "WEB_RETRY_SECONDS", 0)
    monkeypatch.setattr(net, "rate_limit_hit", False)
    monkeypatch.setattr(net, "_api_release", lambda repo: (_ for _ in ()).throw(_http_error(403, "0")))
    tries = []
    monkeypatch.setattr(net, "_web_release", lambda repo: tries.append(1) or (_ for _ in ()).throw(_http_error(429)))
    with pytest.raises(net.RateLimited, match="다시 실행"):
        net.latest_release_asset("o/r", "x")
    assert len(tries) == 2 and net.rate_limit_hit          # 한 번 쉬었다가 다시 해 본다
    assert any(net.RATE_LIMIT_HINT in line for line in cli.guide(["claude"], {}).splitlines())


def test_release_asset_other_http_errors_are_not_masked(monkeypatch):
    monkeypatch.setattr(net, "_api_release", lambda repo: (_ for _ in ()).throw(_http_error(404)))
    with pytest.raises(urllib.error.HTTPError):
        net.latest_release_asset("o/r", "x")



def test_release_asset_web_non_limit_error_is_not_called_rate_limit(monkeypatch):
    monkeypatch.setattr(net, "rate_limit_hit", False)
    monkeypatch.setattr(net, "_api_release", lambda repo: (_ for _ in ()).throw(_http_error(403, "0")))
    monkeypatch.setattr(net, "_web_release", lambda repo: (_ for _ in ()).throw(_http_error(404)))
    with pytest.raises(urllib.error.HTTPError) as e:
        net.latest_release_asset("o/r", "x")
    assert e.value.code == 404 and not net.rate_limit_hit


# --- jaix-win 11/4 실측 4건 ---------------------------------------------------------------------------------
def test_installer_does_not_spawn_cmd_from_run_section():
    """① 설치기 → cmd /K 에 Defender 행동 탐지가 걸렸다. [Run] 은 jaix.exe 가 띄운다."""
    iss = (Path(__file__).resolve().parents[1] / "installer" / "jaix-setup.iss").read_text(encoding="utf-8-sig")
    # [마침] 뒤 nowait 로 로그인 창을 남기던 [Run] 도 없앴다 — 설치기가 끝날 때 남는 자식 0개(jaix-win 11/4 (다))
    assert "\n[Run]" not in iss.replace("\r", "")


def test_installer_login_page_waits_for_login_and_start_menu_shortcut():
    iss = (Path(__file__).resolve().parents[1] / "installer" / "jaix-setup.iss").read_text(encoding="utf-8-sig")
    code = iss.split("[Code]", 1)[1]
    assert "LoginPage := CreateCustomPage(\n    GuidePage.ID," in code.replace("\r", "")  # 완료 화면 바로 앞
    click = code.split("procedure LoginButtonClick", 1)[1].split("\nend;", 1)[0]
    assert "ewWaitUntilTerminated" in click and "--no-wait" in click and "{app}\\jaix\\jaix.exe" in click
    assert "WizardSilent()" in code.split("function ShouldSkipPage", 1)[1].split("\nend;", 1)[0]
    icons = iss.split("[Icons]", 1)[1].split("\n[", 1)[0]
    assert ('Name: "{autoprograms}\\JAIX Hermes 로그인"; Filename: "{app}\\jaix\\jaix.exe"; '
            'Parameters: "hermes login --model {code:HermesModelArg}"') in icons


def test_hermes_login_runs_provider_login_and_waits(monkeypatch):
    shown = []
    monkeypatch.setattr(hermesbot, "show_console", lambda: shown.append(1))  # hide-early 로 숨은 창을 먼저 보인다
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    calls, waited = [], []
    args = argparse.Namespace(model="claude", no_wait=False)
    rc = hermesbot.cmd_login(args, lambda m="": None, run=lambda cmd: calls.append(cmd) or 0,
                             wait=waited.append)
    assert rc == 0 and calls == [["/x/hermes", "auth", "add", "anthropic", "--type", "oauth"]]
    assert bool(waited) == hermesbot.IS_WIN
    assert shown == [1]
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: None)
    assert hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=True), lambda m="": None) == 1


def test_show_console_is_noop_off_windows():
    if not hermesbot.IS_WIN:
        assert hermesbot.show_console() is False


def test_hermes_login_parser():
    args = cli.build_parser().parse_args(["hermes", "login", "--model", "claude"])
    assert args.func is hermesbot.cmd_login and args.model == "claude"


def test_setup_updates_stale_claude_plugins(isolated, monkeypatch):
    """③ 다시 설치할 때 옛 판 Claude 플러그인도 잠금에 맞춘다(update=True)."""
    seen = {}
    monkeypatch.setattr(claude, "setup", lambda lock, log, **kw: seen.update(kw) or {"managed": None, "cli": False})
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--no-autoupdate"]) == 0
    assert seen.get("update") is True
# --- 로그온 작업 진단 (jaix-win 11/4 ④) ----------------------------------------------------------------------
def test_logon_task_has_no_network_condition():
    """'네트워크 연결 시만'은 로그온 트리거를 조용히 건너뛰게 할 수 있다. 오프라인은 jaix update 가 스스로 다룬다."""
    xml = schedule.task_xml(["C:\\jaixw.exe", "update", "--quiet"], "u")
    assert "<RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>" in xml
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml


def test_parse_last_run_reads_by_position():
    line = '"PC","\\jaix-update","N/A","준비","대화형만","2026-11-03 오후 6:05:12","2147942402","PC\\u"'
    assert schedule.parse_last_run(line) == ("2026-11-03 오후 6:05:12", 0x80070002)
    assert schedule.run_failed(0x80070002)
    assert schedule.parse_last_run('"PC","\\jaix-update","N/A","준비","대화형만","1999-11-30","267011","u"')[1] == 0x41303
    assert schedule.parse_last_run('"PC","\\t","N/A","x","y","when","-2147024894","u"')[1] == 0x80070002
    assert not schedule.run_failed(0x41303) and not schedule.run_failed(0) and not schedule.run_failed(None)
    assert schedule.parse_last_run("") is None


# jaix-win 11/4 실측 원문(한국어 Windows, chcp 949, jaix-test 대화형 세션). '실행할 작업' 열은 따옴표가 이스케이프되지
# 않아 CSV 로 깨지지만 그 뒤라 5·6 열은 영향이 없다
KO_SCHTASKS_ROW = (
    '"NAMUN-JI","\\jaix-update","N/A","준비","대화형만","2026-11-04 오후 2:21:55","0","N/A",'
    '""C:\\Users\\jaix-test\\AppData\\Local\\Programs\\jaix\\jaix\\jaixw.exe" update --quiet","N/A",'
    '"JAIX 도구를 잠금 버전에 맞춤(로그온 때 jaix update). jaix-setup 제거 시 함께 지워짐","사용","사용 안 함","",'
    '"jaix-test","사용 안 함","01:00:00","이 형식으로 데이터를 예약할 수 없습니다.","로그온 시","N/A","N/A","N/A",'
    '"N/A","N/A","N/A","N/A","N/A","N/A"')


def test_parse_last_run_real_korean_windows_row():
    raw = (KO_SCHTASKS_ROW + "\r\n").encode("cp949")  # schtasks 가 내는 바이트 그대로
    assert schedule.parse_last_run(raw.decode("cp949", errors="replace")) == ("2026-11-04 오후 2:21:55", 0)
    # 코드페이지를 잘못 짚어도 판정(결과 코드)은 그대로다 — 날짜 속 한글만 깨진다
    assert schedule.parse_last_run(raw.decode("utf-8", errors="replace"))[1] == 0


def test_doctor_warns_when_logon_task_failed(monkeypatch):
    monkeypatch.setattr(schedule, "supported", lambda: True)
    monkeypatch.setattr(schedule, "registered", lambda: True)
    monkeypatch.setattr(schedule, "run_mode", lambda: None)
    monkeypatch.setattr(schedule, "last_status", lambda: {"ok": True, "time": "t", "by": "setup"})
    monkeypatch.setattr(schedule, "last_run", lambda: ("2026-11-03 18:05", 0x80070002))
    c = doctor.check_autoupdate()[0]
    assert c.status == "warn" and "0x80070002" in c.message
    monkeypatch.setattr(schedule, "last_run", lambda: ("2026-11-03 18:05", 0))
    c = doctor.check_autoupdate()[0]
    assert c.status == "ok" and "작업 마지막 실행 2026-11-03 18:05" in c.message
    monkeypatch.setattr(schedule, "last_run", lambda: ("1999-11-30 0:00:00", 0x41303))
    c = doctor.check_autoupdate()[0]
    assert c.status == "ok" and "작업은 아직 안 돎" in c.message and "1999" not in c.message


def test_hermes_login_ctrl_c_keeps_window_and_records(isolated, monkeypatch):
    """Ctrl+C 가 jaix 까지 올라와 창이 바로 닫히던 것(jaix-win 11/4). 취소로 받고, 안내 뒤 Enter 를 기다린다."""
    monkeypatch.setattr(hermesbot, "show_console", lambda: None)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    monkeypatch.setattr(hermesbot, "IS_WIN", True)

    class Child:
        waits = 0

        def __init__(self, cmd, env=None):
            pass

        def wait(self, timeout=None):
            Child.waits += 1
            if Child.waits == 1:
                raise KeyboardInterrupt
            return 1

        def kill(self):
            raise AssertionError("자식이 스스로 끝났으면 죽이지 않는다")

    monkeypatch.setattr(hermesbot, "credentials", lambda *a, **k: [])  # 자격 목록(hermes auth list)은 이 시험 밖
    monkeypatch.setattr(hermesbot.subprocess, "Popen", Child)
    seen, waited = [], []
    rc = hermesbot.cmd_login(argparse.Namespace(model="claude", no_wait=False), seen.append, wait=waited.append)
    assert rc == hermesbot.CANCELLED and Child.waits == 2 and waited
    assert any("취소" in m and "jaix hermes login --model claude" in m for m in seen)
    rec = (paths.data_dir() / "hermes-login.log").read_text(encoding="utf-8")
    assert "model=claude code=130" in rec


def test_hermes_login_tee_ctrl_c_is_cancel(monkeypatch):
    """chatgpt(기기 코드)는 출력을 파이프로 읽는다 — 읽는 중 Ctrl+C 도 '취소'(130)."""
    class Out:
        def read1(self, n):
            raise KeyboardInterrupt

    class Child:
        def __init__(self, cmd, env=None, stdout=None, stderr=None):
            self.stdout = Out()
            assert env.get("PYTHONUNBUFFERED") == "1"

        def wait(self, timeout=None):
            return 1

        def kill(self):
            raise AssertionError("스스로 끝났으면 죽이지 않는다")
    monkeypatch.setattr(hermesbot.subprocess, "Popen", Child)
    assert hermesbot._call_login_tee(["/x/hermes"], lambda t: None) == hermesbot.CANCELLED


def test_hermes_login_opens_device_page_and_shows_result_before_closing(isolated, monkeypatch):
    """jaix-win 11/5: ① device code 방식이라 브라우저가 안 열림 → jaix 가 연다 ② 승인하자 창이 바로 닫힘 → 몇 초 보임."""
    monkeypatch.setattr(hermesbot, "show_console", lambda: None)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    monkeypatch.setattr(hermesbot, "IS_WIN", True)
    monkeypatch.setattr(hermesbot, "OPEN_DELAY", 0)
    import threading
    import time as _t
    opened, paused, seen = [], [], []
    done = threading.Event()

    def run(cmd):  # 로그인이 도는 동안 타이머가 브라우저를 연다
        done.wait(2)
        _t.sleep(0.05)  # 타이머가 안내 줄을 다 쓸 틈
        return 0
    rc = hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=True), seen.append, run=run,
                             opener=lambda url: opened.append(url) or done.set() or True,
                             pause=lambda sec, log: paused.append(sec),
                             wait=lambda q: pytest.fail("--no-wait 는 Enter 를 기다리지 않는다"))
    assert rc == 0 and opened == ["https://auth.openai.com/codex/device"] and paused == [5]
    assert any("로그인 완료" in m for m in seen) and any("코드" in m for m in seen)
    # 브라우저를 못 열면 주소를 붙여 넣으라고 안내
    seen.clear()
    done.clear()
    hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=True), seen.append, run=run,
                        opener=lambda url: done.set() or False, pause=lambda sec, log: paused.append(sec))
    assert any("https://auth.openai.com/codex/device" in m and "붙여 넣" in m for m in seen)
    # 실패는 더 오래 보인다. claude 는 hermes 가 브라우저를 직접 연다 — jaix 는 열지 않는다
    opened.clear()
    hermesbot.cmd_login(argparse.Namespace(model="claude", no_wait=True), seen.append, run=lambda cmd: 1,
                        opener=opened.append, pause=lambda sec, log: paused.append(sec))
    _t.sleep(0.05)
    assert not opened and paused[-1] == hermesbot.CLOSE_AFTER_OTHER


def test_hermes_login_quick_failure_does_not_open_browser(isolated, monkeypatch):
    monkeypatch.setattr(hermesbot, "show_console", lambda: None)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    monkeypatch.setattr(hermesbot, "OPEN_DELAY", 0.3)
    opened = []
    hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=True), lambda m="": None, run=lambda cmd: 2,
                        opener=opened.append, pause=lambda sec, log: None)
    import time as _t
    _t.sleep(0.5)
    assert not opened


# --- 설치본 로그온 자동 갱신 = 설치기가 둔 시작프로그램 바로가기 (Defender Persistence.A!ml, jaix-win 11/4) ----------
@pytest.fixture
def managed(isolated, monkeypatch, tmp_path):
    monkeypatch.setattr(schedule, "IS_WIN", True)
    monkeypatch.setattr(schedule.paths, "exe_dir", lambda: tmp_path / "app" / "jaix")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    state = argparse.Namespace(calls=[], task=False)

    def fake_run(args):
        state.calls.append(args)
        if args[:2] == ["schtasks", "/Query"]:
            return (state.task, "")
        return (True, "")
    monkeypatch.setattr(schedule, "_run", fake_run)
    return state


def test_installer_declares_startup_link_with_same_name():
    iss = (Path(__file__).resolve().parents[1] / "installer" / "jaix-setup.iss").read_text(encoding="utf-8-sig")
    name = schedule.STARTUP_LINK.removesuffix(".lnk")
    line = next(ln for ln in iss.splitlines() if ln.startswith('Name: "{userstartup}'))
    assert f'{{userstartup}}\\{name}"' in line and 'jaixw.exe"' in line
    assert f"update --quiet --delay {schedule.LOGON_DELAY}" in line


def test_managed_register_does_not_create_task_and_drops_legacy(managed):
    assert schedule.installer_managed()
    managed.task = True  # 예전 판이 만든 jaix-update
    seen = []
    assert schedule.register(seen.append) is False  # 바로가기가 아직 없음
    assert not any(c[:2] == ["schtasks", "/Create"] for c in managed.calls)
    assert ["schtasks", "/Delete", "/TN", schedule.TASK_NAME, "/F"] in managed.calls
    assert any("바로가기가 없음" in m for m in seen)
    schedule.startup_link().parent.mkdir(parents=True)
    schedule.startup_link().write_bytes(b"lnk")
    managed.task = False
    seen.clear()
    assert schedule.register(seen.append) is True and schedule.registered()
    assert any("시작프로그램 바로가기" in m for m in seen)
    assert schedule.run_mode() is None and schedule.last_run() is None


def test_managed_unregister_removes_link(managed):
    schedule.startup_link().parent.mkdir(parents=True)
    schedule.startup_link().write_bytes(b"lnk")
    assert schedule.unregister() is True and not schedule.startup_link().exists()


def test_doctor_managed_missing_link_points_to_installer(managed, monkeypatch):
    c = doctor.check_autoupdate()[0]
    assert c.status == "warn" and schedule.STARTUP_LINK in c.message and "jaix-setup" in c.fix
    schedule.startup_link().parent.mkdir(parents=True)
    schedule.startup_link().write_bytes(b"lnk")
    monkeypatch.setattr(schedule, "last_status", lambda: {"ok": True, "time": "t"})
    c = doctor.check_autoupdate()[0]
    assert c.status == "ok" and "시작프로그램 바로가기" in c.message


def test_update_quiet_delay_sleeps(isolated, monkeypatch):
    slept = []
    monkeypatch.setattr(cli.time, "sleep", slept.append)
    monkeypatch.setattr(cli, "_update", lambda args, log: [])
    assert cli.main(["update", "--quiet", "--delay", "120"]) == 0
    assert slept == [120]


# --- Hermes 설정: 바뀐 것만 부르기 (재설치·로그온 갱신에서 hermes.exe 반복 줄이기, jaix-win 11/4) ------------------
def _hermes_fake_run(calls):
    def run(cmd, log, timeout=600):
        calls.append(cmd)
        f = hermesbot.config_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as out:  # hermes config set 이 파일을 고치는 것 흉내
            out.write(f"# {' '.join(cmd[1:4])}\n")
        return True, ""
    return run


def test_hermes_quiet_skips_unchanged_on_rerun(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", _hermes_fake_run(calls))
    monkeypatch.setattr(hermesbot, "builtin_skills", lambda: ["a", "b"])
    assert hermesbot.quiet("hermes", print)
    first = len(calls)
    assert first >= 4
    calls.clear()
    seen = []
    assert hermesbot.quiet("hermes", seen.append)  # 로그온 update·재설치
    assert calls == [] and any("건너뜀" in m for m in seen)
    monkeypatch.setattr(hermesbot, "builtin_skills", lambda: ["a", "b", "c"])  # Hermes 업데이트로 새 기본 스킬
    assert hermesbot.quiet("hermes", print)
    assert [c[3] for c in calls] == ["skills.disabled"]


def test_hermes_settings_reapplied_when_config_changed_elsewhere(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", _hermes_fake_run(calls))
    monkeypatch.setattr(hermesbot, "builtin_skills", lambda: [])
    monkeypatch.setattr(hermesbot.codex, "owned_mcp", lambda: {})
    assert hermesbot.configure("hermes", "chatgpt", print) and hermesbot.quiet("hermes", print)
    n = len(calls)
    calls.clear()
    assert hermesbot.configure("hermes", "chatgpt", print) and hermesbot.quiet("hermes", print)
    assert calls == []
    with open(hermesbot.config_path(), "a", encoding="utf-8") as f:  # 사용자·Hermes 가 파일을 고침
        f.write("model:\n  provider: other\n")
    assert hermesbot.configure("hermes", "chatgpt", print) and hermesbot.quiet("hermes", print)
    assert len(calls) == n  # 지문이 달라져 전부 다시
    calls.clear()
    assert hermesbot.configure("hermes", "claude", print)  # 모델을 바꾸면 바뀐 키만
    assert calls and all(c[1] == "config" and c[3].startswith("model.") for c in calls)


def test_hermes_config_backup_only_when_writing(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", _hermes_fake_run(calls))
    monkeypatch.setattr(hermesbot.codex, "owned_mcp", lambda: {})
    hermesbot.configure("hermes", "chatgpt", print)
    backups = lambda: list(hermesbot.config_path().parent.glob("config.yaml.jaix-bak-*"))
    before = len(backups())
    hermesbot.configure("hermes", "chatgpt", print)
    assert len(backups()) == before  # 아무것도 쓰지 않았으면 백업도 만들지 않음




# --- 플러그인 bin/ 명령을 PATH 에 (plugbin, TS-RUNTIME-4) -------------------------------------------
def _fake_plugin_source(monkeypatch, with_bin=("mailskill", "mailskill.cmd", "mailskill.ps1", "mail-secret.cmd")):
    """잠금 커밋 소스 대신 가짜 플러그인 루트를 돌려준다. 받은 (이름, 커밋)을 센다."""
    fetched = []

    def fake_fetch(plugin, workdir):
        fetched.append((plugin.name, plugin.sha))
        root = Path(workdir) / plugin.name / "root"
        (root / "skills" / plugin.name).mkdir(parents=True, exist_ok=True)
        (root / "skills" / plugin.name / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        if plugin.name == "mail-skill":
            (root / "bin").mkdir(exist_ok=True)
            (root / "scripts").mkdir(exist_ok=True)
            for f in with_bin:
                (root / "bin" / f).write_text("@echo off\n" if "." in f else "#!/bin/sh\necho hi\n", encoding="utf-8")
        return root

    monkeypatch.setattr(plugbin, "fetch_root", fake_fetch)
    return fetched


def _lock_with_mail_skill(the_lock, sha="a" * 40, include=True):
    data = json.loads(json.dumps(the_lock.data))
    data["plugins"] = [p for p in data["plugins"] if p["name"] != "mail-skill"]
    if include:
        data["plugins"].append({"name": "mail-skill", "version": "2026.11.3.1", "source": {
            "source": "git-subdir", "url": "https://github.com/z0nam/mail-skill.git", "path": "plugins/mail-skill",
            "ref": "v2026.11.03.1", "sha": sha}})
    return lock.Lock(data, the_lock.source)


def test_plugbin_puts_plugin_bin_commands_on_path(isolated, monkeypatch, the_lock):
    fetched = _fake_plugin_source(monkeypatch)
    the = _lock_with_mail_skill(the_lock)
    res = REAL_PLUGBIN_ENSURE(the, print)
    assert res["status"] == "ok"
    link = plugbin.link_dir()
    copy_bin = plugbin.plugins_dir() / "mail-skill" / "bin"
    assert (plugbin.plugins_dir() / "mail-skill" / "scripts").is_dir()  # bin 스크립트가 ../scripts 를 찾는다
    if paths.IS_WIN:
        shim = (link / "mailskill.cmd").read_text(encoding="utf-8")
        assert str(copy_bin / "mailskill.cmd") in shim and "%*" in shim
        assert (link / "mail-secret.cmd").is_file()
        assert str(copy_bin / "mailskill").replace("\\", "/") in (link / "mailskill").read_text(encoding="utf-8")
        assert not (link / "mailskill.ps1").exists()
    else:
        assert (link / "mailskill").resolve() == (copy_bin / "mailskill").resolve()
        assert os.access(copy_bin / "mailskill", os.X_OK)
        assert not (link / "mailskill.cmd").exists() and not (link / "mail-secret.cmd").exists()
    assert "mailskill" in res["commands"]
    # bin 이 없는 플러그인도 기록돼 다음엔 받지 않는다
    assert set(plugbin.recorded()) == {p.name for p in the.plugins}
    n = len(fetched)
    REAL_PLUGBIN_ENSURE(the, print)
    assert len(fetched) == n  # 커밋이 같으면 다시 받지 않음
    REAL_PLUGBIN_ENSURE(_lock_with_mail_skill(the_lock, sha="b" * 40), print)
    assert fetched[-1] == ("mail-skill", "b" * 40) and len(fetched) == n + 1
    # 잠금에서 빠지면 명령과 사본을 지운다
    REAL_PLUGBIN_ENSURE(_lock_with_mail_skill(the_lock, include=False), print)
    assert not (link / "mailskill").exists() and not (link / "mailskill").is_symlink()
    assert not (plugbin.plugins_dir() / "mail-skill").exists()
    assert "mail-skill" not in plugbin.recorded()


def test_plugbin_does_not_overwrite_foreign_command(isolated, monkeypatch, the_lock):
    _fake_plugin_source(monkeypatch)
    link = plugbin.link_dir()
    link.mkdir(parents=True)
    name = "mailskill.cmd" if paths.IS_WIN else "mailskill"
    (link / name).write_text("user's own\n", encoding="utf-8")
    msgs = []
    REAL_PLUGBIN_ENSURE(_lock_with_mail_skill(the_lock), msgs.append)
    assert (link / name).read_text(encoding="utf-8") == "user's own\n"
    assert any("jaix 가 만들지 않은 파일" in m for m in msgs)
    REAL_PLUGBIN_ENSURE(_lock_with_mail_skill(the_lock, include=False), print)
    assert (link / name).exists()  # 지울 때도 남의 것은 둔다


def test_plugbin_refetches_when_command_deleted_and_reports_failure(isolated, monkeypatch, the_lock):
    fetched = _fake_plugin_source(monkeypatch)
    the = _lock_with_mail_skill(the_lock)
    REAL_PLUGBIN_ENSURE(the, print)
    for c in plugbin.recorded()["mail-skill"]["commands"]:
        Path(c).unlink()
    n = len(fetched)
    REAL_PLUGBIN_ENSURE(the, print)
    assert len(fetched) == n + 1 and all(Path(c).exists() for c in plugbin.recorded()["mail-skill"]["commands"])

    def boom(plugin, workdir):
        raise OSError("offline")
    monkeypatch.setattr(plugbin, "fetch_root", boom)
    res = REAL_PLUGBIN_ENSURE(_lock_with_mail_skill(the_lock, sha="c" * 40), print)
    assert res["status"] == "failed" and "mail-skill" in res["failed"]
    assert plugbin.recorded()["mail-skill"]["sha"] == "a" * 40  # 실패하면 기록을 바꾸지 않아 다음에 다시 한다


def test_doctor_plugin_bin(isolated, monkeypatch, the_lock):
    _fake_plugin_source(monkeypatch)
    the = _lock_with_mail_skill(the_lock)
    assert [c.status for c in doctor.check_plugin_bin(the)] == ["warn"]  # 아직 확인 안 함
    REAL_PLUGBIN_ENSURE(the, print)
    monkeypatch.setenv("PATH", str(plugbin.link_dir()) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(winenv, "in_user_path", lambda d: True)
    checks = doctor.check_plugin_bin(the)
    assert [c.status for c in checks] == ["ok"] and "mailskill" in checks[0].message
    checks = doctor.check_plugin_bin(_lock_with_mail_skill(the_lock, sha="d" * 40))
    assert [c.status for c in checks] == ["warn"] and checks[0].fix == "jaix update"


def test_setup_counts_plugbin_failure():
    assert cli._setup_problems({"plugbin": {"status": "failed"}})
    assert not cli._setup_problems({"plugbin": {"status": "ok"}})


def test_hermes_skills_use_shared_fetch(isolated, monkeypatch, the_lock):
    _fake_plugin_source(monkeypatch)
    p = _lock_with_mail_skill(the_lock).plugins[-1]
    assert [d.name for d in hermes.plugin_skills(p, isolated / "w")] == ["mail-skill"]


# --- own_copy 런타임(hwp2pdf-cli 두 벌) -----------------------------------------------------------------
def _fake_cli(folder, version):
    """--version 에 version 을 찍는 가짜 hwp2pdf-cli. Windows 는 .cmd 심(TS-TEST-3)."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        f = folder / "hwp2pdf-cli.cmd"
        f.write_text(f"@echo hwp2pdf {version}\r\n", encoding="utf-8")
    else:
        f = folder / "hwp2pdf-cli"
        f.write_text(f"#!/bin/sh\necho hwp2pdf {version}\n", encoding="utf-8")
        f.chmod(0o755)
    return f


def test_own_copy_installs_jaix_copy_beside_foreign_and_exports_env(isolated, monkeypatch):
    rt = runtimes.BY_KEY["hwp2pdf"]
    foreign = isolated / "ProgramFiles" / "hwp2pdf"
    _fake_cli(foreign, "2026.9.28.1")
    monkeypatch.setenv("PATH", str(foreign))  # 러너의 실제 PATH 는 섞지 않는다
    monkeypatch.setattr(runtimes, "IS_WIN", True)
    installed, env = [], {}
    monkeypatch.setattr(runtimes, "install_portable",
                        lambda r, log: (installed.append(r.key), _fake_cli(r.path_dir(), "2026.11.5.1"))[1].parent)
    monkeypatch.setattr(winenv, "set_user_env", lambda name, value: env.update({name: value}) or True)
    msgs = []
    found = runtimes.ensure(rt, msgs.append)
    assert installed == ["hwp2pdf"]  # 밖의 사본이 쓸 만해도 jaix 사본을 깐다
    assert found.managed and found.version == "2026.11.5.1"
    assert env == {"HWP2PDF_CLI": found.path}
    assert any("jaix 밖의 사본" in m for m in msgs)
    assert [f.name for f in foreign.iterdir()] == ["hwp2pdf-cli.cmd" if os.name == "nt" else "hwp2pdf-cli"]  # 밖의 사본은 그대로
    # 다음 번: jaix 사본이 있으면 다시 깔지 않고 env 만 맞춘다
    installed.clear()
    runtimes.ensure(rt, msgs.append)
    assert installed == []


def test_doctor_warns_two_copies_and_env(isolated, monkeypatch):
    rt = runtimes.BY_KEY["hwp2pdf"]
    foreign = isolated / "ProgramFiles" / "hwp2pdf"
    _fake_cli(foreign, "2026.9.28.1")
    mine = _fake_cli(rt.path_dir(), "2026.11.5.1")
    monkeypatch.setenv("PATH", str(foreign))  # 러너의 실제 PATH 는 섞지 않는다
    monkeypatch.setattr(doctor, "IS_WIN", True)
    found = runtimes.copies(rt)
    assert [f.managed for f in found] == [False, True]  # 시스템 PATH 쪽이 먼저 잡힘
    monkeypatch.setattr(winenv, "get_user_env", lambda name: str(found[1].path))
    checks = doctor.check_runtime_copies()
    assert [c.area for c in checks] == ["hwp2pdf-cli 두 벌"]
    assert "PATH에서 먼저 잡힘" in checks[0].message and "jaix 사본" in checks[0].message
    assert "2026.9.28.1" in checks[0].message and "지우지 않음" in checks[0].fix
    monkeypatch.setattr(winenv, "get_user_env", lambda name: None)
    areas = [c.area for c in doctor.check_runtime_copies()]
    assert "hwp2pdf-cli 경로(HWP2PDF_CLI)" in areas
    # 한 벌이면 조용
    monkeypatch.setenv("PATH", str(isolated / "empty"))
    monkeypatch.setattr(winenv, "get_user_env", lambda name: str(mine))
    assert [c for c in doctor.check_runtime_copies() if c.area.endswith("두 벌")] == []


def test_cleanup_removes_env_only_when_it_points_into_jaix(isolated, monkeypatch):
    removed = []
    monkeypatch.setattr(winenv, "remove_user_env_under", lambda name, prefix: removed.append((name, prefix)) or True)
    msgs = []
    assert cli.cmd_cleanup(None, msgs.append) == 0
    assert sorted(removed) == [("CLAUDE_CODE_GIT_BASH_PATH", paths.jaix_home()), ("HWP2PDF_CLI", paths.jaix_home())]
    assert "환경변수 뺌: HWP2PDF_CLI" in msgs and "환경변수 뺌: CLAUDE_CODE_GIT_BASH_PATH" in msgs


def test_remove_user_env_under_keeps_user_value(monkeypatch, tmp_path):
    store = {"HWP2PDF_CLI": r"C:\\Program Files\\hwp2pdf\\hwp2pdf-cli.exe"}
    monkeypatch.setattr(winenv, "get_user_env", lambda name: store.get(name))
    assert not REAL_REMOVE_USER_ENV_UNDER("HWP2PDF_CLI", tmp_path)  # 사용자가 바꾼 값은 둔다


# --- Hermes 자격 누적(jaix-win v11.05.8: 설치기 2회+시작 메뉴 1회로 openai-codex 자격 #4) ----------------------------
CRED_LIST = """openai-codex (2 credentials):
  #1  a@ex.com             oauth   id=aaa111 priority=0 device_code ←
  #2  a@ex.com             oauth   id=bbb222 priority=1 manual:device_code
"""


class FakeAuth:
    def __init__(self, listing):
        self.listing, self.calls = listing, []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "list":
            return 0, self.listing
        if args[0] == "remove":
            return 0, f"Removed {args[1]} credential"
        return 1, ""


def _login_env(monkeypatch):
    monkeypatch.setattr(hermesbot, "show_console", lambda: None)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    monkeypatch.setattr(hermesbot, "IS_WIN", True)
    monkeypatch.setattr(hermesbot, "OPEN_DELAY", 60)


def test_credentials_parse_hermes_auth_list():
    rows = hermesbot.credentials("/x/hermes", "openai-codex", FakeAuth(CRED_LIST))
    assert [(r["index"], r["label"], r["id"]) for r in rows] == [(1, "a@ex.com", "aaa111"), (2, "a@ex.com", "bbb222")]
    assert hermesbot.credentials("/x/hermes", "openai-codex", lambda a: (1, "boom")) is None
    assert hermesbot.credentials("/x/hermes", "anthropic", FakeAuth("")) == []


def test_login_when_already_logged_in(isolated, monkeypatch):
    _login_env(monkeypatch)
    auth = FakeAuth(CRED_LIST)
    seen, runs = [], []
    # 설치기 페이지(--no-wait): 묻지 않고 건너뜀
    rc = hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=True, force=False), seen.append,
                             run=lambda cmd: runs.append(cmd) or 0, auth=auth, pause=lambda s, log: None)
    assert rc == hermesbot.ALREADY and not runs and any("이미 로그인" in m for m in seen)
    # 시작 메뉴: 묻고, N 이면 그대로
    rc = hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=False, force=False), seen.append,
                             run=lambda cmd: runs.append(cmd) or 0, auth=auth, ask=lambda q: "", wait=lambda q: None)
    assert rc == hermesbot.ALREADY and not runs
    assert not [c for c in auth.calls if c[0] == "remove"]


def test_relogin_prunes_old_credentials_keeps_new(isolated, monkeypatch):
    _login_env(monkeypatch)
    auth = FakeAuth(CRED_LIST)

    def run(cmd):  # 로그인하면 새 자격 #3 이 생긴다
        auth.listing = CRED_LIST.replace("(2 credentials)", "(3 credentials)") + \
            "  #3  a@ex.com             oauth   id=ccc333 priority=2 manual:device_code\n"
        return 0
    seen = []
    rc = hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=False, force=False), seen.append,
                             run=run, auth=auth, ask=lambda q: "y", wait=lambda q: None)
    assert rc == 0
    removed = [c for c in auth.calls if c[0] == "remove"]
    assert removed == [["remove", "openai-codex", "aaa111"], ["remove", "openai-codex", "bbb222"]]
    assert any("2개를 정리" in m for m in seen)


def test_prune_skipped_when_new_credential_not_seen(isolated, monkeypatch):
    _login_env(monkeypatch)
    auth = FakeAuth(CRED_LIST)  # 로그인 '성공'인데 새 자격이 안 보임 → 아무것도 지우지 않는다
    rc = hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=False, force=True), lambda m="": None,
                             run=lambda cmd: 0, auth=auth, wait=lambda q: None)
    assert rc == 0 and not [c for c in auth.calls if c[0] == "remove"]


def test_prune_failure_keeps_going(isolated, monkeypatch):
    seen = []

    class Failing(FakeAuth):
        def __call__(self, args):
            if args[0] == "remove":
                self.calls.append(args)
                return 1, "error: locked"
            return super().__call__(args)
    auth = Failing(CRED_LIST + "  #3  a@ex.com             oauth   id=ccc333 priority=2 manual:device_code\n")
    assert hermesbot.prune_credentials("/x/hermes", "openai-codex", {"aaa111", "bbb222"}, seen.append, auth) == 0
    assert any("정리 실패(새 자격은 그대로)" in m for m in seen)


def test_device_code_copied_to_clipboard(isolated, monkeypatch):
    _login_env(monkeypatch)
    copied = []

    def tee(cmd, on_text):  # hermes 출력이 조각나 와도 코드를 찾는다
        for part in ["To continue, follow these steps:\n\n  1. Open this URL in your browser:\n",
                     "     https://auth.openai.com/codex/device\n\n  2. Enter this ", "code:\n     0AR3-3DC",
                     "KV\n\nWaiting for sign-in..."]:
            on_text(part)
        return 0
    monkeypatch.setattr(hermesbot, "_call_login_tee", tee)
    seen = []
    hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=True, force=True), seen.append,
                        auth=FakeAuth(""), copy=lambda code: copied.append(code) or True, pause=lambda s, log: None)
    assert copied == ["0AR3-3DCKV"] and any("Ctrl+V" in m for m in seen)
    # 코드 둘째 마디가 4자 넘게 온 뒤 끊겨도 끝(줄바꿈)을 기다린다(Codex #109)
    copied.clear()

    def tee2(cmd, on_text):
        for part in ["  2. Enter this code:\n     0AR3-3DCK", "V\n"]:
            on_text(part)
        return 0
    monkeypatch.setattr(hermesbot, "_call_login_tee", tee2)
    hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=True, force=True), seen.append,
                        auth=FakeAuth(""), copy=lambda code: copied.append(code) or True, pause=lambda s, log: None)
    assert copied == ["0AR3-3DCKV"]


def test_claude_login_keeps_console_tty(isolated, monkeypatch):
    """anthropic 은 붙여넣기 입력을 받는다 — 파이프(tee)로 바꾸지 않는다."""
    _login_env(monkeypatch)
    used = []
    monkeypatch.setattr(hermesbot, "_call_login_tee", lambda cmd, on_text: used.append("tee") or 0)
    monkeypatch.setattr(hermesbot, "_call_login", lambda cmd: used.append("tty") or 0)
    hermesbot.cmd_login(argparse.Namespace(model="claude", no_wait=True, force=True), lambda m="": None,
                        auth=FakeAuth(""), pause=lambda s, log: None)
    assert used == ["tty"]


def test_doctor_warns_duplicate_credentials(isolated, monkeypatch):
    monkeypatch.setattr(hermesbot, "duplicate_credentials", lambda: ("openai-codex", 4, "chatgpt"))
    monkeypatch.setattr(hermesbot, "recorded", lambda: {"status": "connected", "slack": {"id": "x"}})
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    monkeypatch.setattr(hermesbot, "env_has", lambda k: True)
    monkeypatch.setattr(hermesbot, "startup_entries", lambda: ["x"])
    monkeypatch.setattr(hermesbot, "approval_mode", lambda: "smart")
    rows = [c for c in doctor.check_hermes_bot() if c.area == "Hermes 자격"]
    assert rows and rows[0].status == "warn" and "4개" in rows[0].message and "--force" in rows[0].fix


def test_installer_handles_already_logged_in():
    iss = (Path(__file__).resolve().parents[1] / "installer" / "jaix-setup.iss").read_text(encoding="utf-8-sig")
    click = iss.split("procedure LoginButtonClick", 1)[1].split("\nend;", 1)[0]
    assert "ResultCode = 3" in click and "이미 로그인돼 있습니다" in click and "' --force'" in click


# --- 슬랙 홈 채널(jaix-win 11/5: 첫 DM 답 앞 "No home channel is set for Slack … /hermes sethome") ----------------
def _hermes_env(text):
    f = paths.hermes_home() / ".env"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def test_quiet_sets_slack_home_to_owner_dm_when_missing(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", _hermes_fake_run(calls))
    monkeypatch.setattr(hermesbot, "builtin_skills", lambda: [])
    _hermes_env("SLACK_BOT_TOKEN=xoxb-x\nSLACK_APP_TOKEN=xapp-x\nSLACK_ALLOWED_USERS=U123\n")
    seen = []
    monkeypatch.setattr(hermesbot, "slack_call",
                        lambda method, token, **kw: seen.append((method, kw)) or {"ok": True, "channel": {"id": "D999"}})
    assert hermesbot.quiet("hermes", print)
    assert ["hermes", "config", "set", "SLACK_HOME_CHANNEL", "D999"] in calls
    assert seen == [("conversations.open", {"users": "U123"})]
    # .env 가 다시 만들어져 홈 채널이 빠지면(config.yaml 은 그대로) 다시 넣는다(Codex #111)
    calls.clear()
    _hermes_env("SLACK_BOT_TOKEN=xoxb-x\nSLACK_APP_TOKEN=xapp-x\nSLACK_ALLOWED_USERS=U123\n")
    assert hermesbot.quiet("hermes", print)
    assert ["hermes", "config", "set", "SLACK_HOME_CHANNEL", "D999"] in calls


def test_slack_home_falls_back_to_user_id_and_respects_existing(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(hermesbot, "_run", _hermes_fake_run(calls))
    monkeypatch.setattr(hermesbot, "builtin_skills", lambda: [])
    _hermes_env("SLACK_BOT_TOKEN=xoxb-x\nSLACK_ALLOWED_USERS=U123\n")
    monkeypatch.setattr(hermesbot, "slack_call", lambda *a, **k: {"ok": False, "error": "missing_scope"})
    assert hermesbot.quiet("hermes", print)
    assert ["hermes", "config", "set", "SLACK_HOME_CHANNEL", "U123"] in calls
    calls.clear()
    _hermes_env("SLACK_ALLOWED_USERS=U123\nSLACK_HOME_CHANNEL=C777\n")  # 사용자가 /sethome 으로 고른 것
    monkeypatch.setattr(hermesbot, "slack_call", lambda *a, **k: pytest.fail("이미 있으면 묻지 않는다"))
    assert hermesbot.quiet("hermes", print)
    assert not [c for c in calls if "SLACK_HOME_CHANNEL" in c]


def test_prune_points_at_hermes_english_warning(isolated, monkeypatch):
    monkeypatch.setattr(hermesbot, "show_console", lambda: None)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    monkeypatch.setattr(hermesbot, "IS_WIN", True)
    monkeypatch.setattr(hermesbot, "OPEN_DELAY", 60)
    auth = FakeAuth(CRED_LIST)

    def tee(cmd, on_text):
        auth.listing = CRED_LIST + "  #3  a@ex.com             oauth   id=ccc333 priority=2 manual:device_code\n"
        on_text("Added openai-codex OAuth credential #3\nwarning: this login is the same OpenAI account as "
                "openai-codex credential #1 (...). Log into a different account instead, or keep just one "
                "(`hermes auth remove openai-codex 1`).\n")
        return 0
    monkeypatch.setattr(hermesbot, "_call_login_tee", tee)
    seen = []
    hermesbot.cmd_login(argparse.Namespace(model="chatgpt", no_wait=False, force=True), seen.append,
                        auth=auth, copy=lambda c: True, wait=lambda q: None)
    assert any("위 영문 경고" in m and "신경 쓰지 마세요" in m and "2개" in m for m in seen)


# --- 설치 전에 연 창·앱(옛 PATH) · 런타임 조용한 실패 (소모임 11/5) -------------------------------------------
def test_find_sees_fresh_path_and_marks_stale(isolated, monkeypatch):
    """winget 이 사용자 PATH 에만 넣은 것(Git Programs 폴더 등): 이 프로세스 PATH 엔 없어도 찾고, stale 로 표시."""
    rt = runtimes.BY_KEY["hwp2pdf"]
    winget_dir = isolated / "Programs" / "hwp2pdf"
    _fake_cli(winget_dir, "2026.11.5.1")
    monkeypatch.setenv("PATH", str(isolated / "empty"))  # 설치 전에 연 창의 옛 PATH
    monkeypatch.setattr(runtimes, "IS_WIN", True)
    monkeypatch.setenv("LOCALAPPDATA", str(isolated / "la"))
    monkeypatch.setattr(winenv, "fresh_path", lambda: str(winget_dir))
    found = runtimes.find(rt)
    assert found.path and found.version == "2026.11.5.1" and found.stale
    # 이 창 PATH 에도 있으면 stale 아님
    monkeypatch.setenv("PATH", str(winget_dir))
    assert not runtimes.find(rt).stale


def test_doctor_warns_stale_runtime_instead_of_missing(isolated, monkeypatch, the_lock):
    rt = runtimes.BY_KEY["uv"]
    real = runtimes.find
    monkeypatch.setattr(runtimes, "find", lambda r: runtimes.Found("C:/x/uv.exe", "0.9.1", 0, stale=True)
                        if r is rt else real(r))
    check = next(c for c in doctor.check_runtimes(the_lock) if c.area == rt.label)
    assert check.status == "warn" and "새 창에서는 보이지만" in check.message
    assert "Exit" in check.fix and "새로 열어" in check.fix


def test_setup_counts_missing_required_runtime_as_failure(isolated, monkeypatch):
    monkeypatch.setattr(cli.paths, "IS_WIN", True)
    monkeypatch.setattr(runtimes, "ensure", lambda rt, log, dry_run=False, upgrade=False:
                        runtimes.Found(None, None) if rt.key == "git" else runtimes.Found("x", "1.0", 99))
    guide = isolated / "guide.txt"
    code = cli.main(["setup", "--channels", "claude", "--no-autoupdate", "--guide-out", str(guide),
                     "--log", str(isolated / "s.log")])
    assert code != 0
    text = guide.read_text(encoding="utf-8-sig")
    assert text.startswith("※ [실패]") and "Git" in text and "Code 탭" in text and "setup.log" in text
    assert cli._setup_problems({"runtimes_missing": ["Git"]})


def test_desktop_started_before_setup(isolated, monkeypatch):
    msix = r"C:\Program Files\WindowsApps\Claude_1.0.0.0_x64__abc\app\claude.exe"
    cli_exe = r"C:\Users\u\.local\bin\claude.exe"
    assert not claude.desktop_started_before_setup([(1, msix, 100.0)])  # setup 기록 없음 → 모름
    claude.mark_setup()
    at = claude.setup_stamp().stat().st_mtime
    assert claude.desktop_started_before_setup([(1, msix, at - 60), (2, msix, at + 5)])
    assert not claude.desktop_started_before_setup([(1, msix, at + 60)])  # setup 뒤에 다시 켬
    assert not claude.desktop_started_before_setup([(1, cli_exe, at - 60)])  # Claude Code CLI 는 앱이 아님
    assert claude._is_desktop(r"C:\Users\u\AppData\Local\AnthropicClaude\app-0.9\claude.exe")


def test_claude_setup_stamps_only_when_something_changed(isolated, monkeypatch, the_lock):
    """로그온 자동 갱신이 아무것도 안 바꾸면 시각을 그대로 둔다(매일 '앱이 setup 전에 켜짐' 오탐 방지)."""
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    claude.setup(the_lock, print)  # 처음: 설정에 마켓플레이스·플러그인을 넣음 → 찍음
    stamp = claude.setup_stamp()
    assert stamp.is_file()
    os.utime(stamp, (1000, 1000))
    claude.setup(the_lock, print)  # 바뀐 것 없음
    assert stamp.stat().st_mtime == 1000
    claude.setup(the_lock, print, dry_run=True)
    assert stamp.stat().st_mtime == 1000


def test_ensure_stale_runtime_reaches_child_processes(isolated, monkeypatch):
    """설치 전에 연 창에서 setup: 찾은 런타임 폴더를 이 프로세스 PATH 에 붙여 뒤의 claude·uvx 가 찾게(사용자 PATH 는 그대로)."""
    rt = runtimes.BY_KEY["hwp2pdf"]
    winget_dir = isolated / "Programs" / "hwp2pdf"
    _fake_cli(winget_dir, "2026.11.5.1")
    monkeypatch.setenv("PATH", str(isolated / "empty"))
    monkeypatch.setattr(runtimes, "IS_WIN", True)
    monkeypatch.setattr(rt, "own_copy", False)
    monkeypatch.setenv("LOCALAPPDATA", str(isolated / "la"))
    monkeypatch.setattr(winenv, "fresh_path", lambda: str(winget_dir))
    monkeypatch.setattr(winenv, "refresh_process_path", lambda: None)
    found = runtimes.ensure(rt, print)
    assert found.stale and str(winget_dir) in os.environ["PATH"].split(os.pathsep)
    assert not runtimes.find(rt).stale


# --- 다시 설치할 때 지난 선택을 체크 기본값으로(jaix-win 11/5) --------------------------------------------------
def _record_says(rec, key, value, span=16):
    """설치기 RecordSays 와 같은 판정(파스칼 Pos·Copy 를 그대로 옮김)."""
    p = rec.find(f'"{key}"')
    return p >= 0 and f'"{value}"' in rec[p + len(key) + 2:p + len(key) + 2 + span]


def test_installer_reads_previous_choice_written_by_setup(isolated):
    from jaix import selfupdate
    iss = (Path(__file__).resolve().parents[1] / "installer" / "jaix-setup.iss").read_text(encoding="utf-8-sig")
    code = iss.split("[Code]", 1)[1].replace("\r", "")
    wizard = code.split("procedure InitializeWizard", 1)[1].split("\nend;", 1)[0]
    # 페이지·기본값을 다 만든 뒤에 지난 선택으로 덮는다
    apply = code.split("procedure ApplyPreviousChoice", 1)[1].split("\nend;", 1)[0]
    assert wizard.index("ApplyPreviousChoice();") > wizard.index("ModelPage.Add('회사 Claude 계정(Team)")
    # 처음 설치는 Hermes 모델을 미리 고르지 않는다(사용자 결정 11/5) — 고르지 않고 [다음]이면 묻는다
    assert "ModelPage.Values[" not in wizard
    nxt = code.split("function NextButtonClick", 1)[1].split("\nend;", 1)[0]
    assert "CurPageID = ModelPage.ID" in nxt and "not WizardSilent()" in nxt and "골라 주세요" in nxt
    # 지난 선택은 Hermes 를 골랐을 때만 모델까지 채운다(chatgpt 도 채움)
    assert "if ChannelPage.Values[2] then\n          SetModelChoice(" in apply
    # 개인 Pro 로는 Hermes 가 안 된다(providers.md Subscription plans, studio 실측 11/5) — 화면에 밝힌다
    assert "개인 Claude Pro로는 동작하지 않습니다" in wizard and "개인 Pro 구독은 안 됨" in wizard
    assert "개인 Claude Pro 구독은 Hermes 에서 동작하지 않습니다" in hermesbot.PROVIDERS["claude"]["how"][0]
    apply = code.split("procedure ApplyPreviousChoice", 1)[1].split("\nend;", 1)[0]
    assert "'setup-choice.json'" in apply and "'hermes.json'" in apply
    assert "RecordSays(Rec, 'hermes_model', 'claude', 16)" in apply and "RecordSays(Rec, 'model', 'claude', 16)" in apply
    # jaix setup 이 쓰는 꼴을 설치기 판정이 알아본다
    selfupdate.save_choice(["claude", "hermes"], "claude")
    rec = selfupdate.choice_file().read_text(encoding="utf-8")
    chans = rec[rec.index('"channels"'):]
    chans = chans[chans.index("["):chans.index("]") + 1]
    assert '"hermes"' in chans and '"codex"' not in chans
    assert _record_says(rec, "hermes_model", "claude")
    selfupdate.save_choice(["codex"], "chatgpt")
    assert not _record_says(selfupdate.choice_file().read_text(encoding="utf-8"), "hermes_model", "claude")
    # 예전 판: hermes.json(indent=2) 의 model
    hermesbot._save_record({"model": "claude", "status": "linked"})
    assert _record_says(hermesbot._record_file().read_text(encoding="utf-8"), "model", "claude")

def test_guard_blocks_real_hermes_outside_tmp(isolated, monkeypatch, tmp_path_factory):
    """isolated 가 깐 가드: tmp 밖의 hermes 를 부르면 실행 전에 멈춘다(tmp 안의 가짜는 허용)."""
    outside = tmp_path_factory.mktemp("realbin")
    for d in (outside, isolated / "fakebin"):
        d.mkdir(exist_ok=True)
        f = d / ("hermes.cmd" if os.name == "nt" else "hermes")
        f.write_text("@echo ok\r\n" if os.name == "nt" else "#!/bin/sh\necho ok\n", encoding="utf-8")
        f.chmod(0o755)
    monkeypatch.setenv("PATH", str(outside))
    with pytest.raises(AssertionError, match="진짜 hermes"):
        subprocess.run(["hermes", "auth", "list"], capture_output=True)
    if os.name != "nt":  # Windows 는 .cmd 를 셸 없이 못 띄운다 — tmp 안의 가짜 허용은 맥·리눅스에서만 본다
        monkeypatch.setenv("PATH", str(isolated / "fakebin"))
        assert subprocess.run(["hermes"], capture_output=True).returncode == 0


# --- jaix hermes rename (사용자 결정 11/5: 베타 아이디를 나중에 바꿀 수 있게) -------------------------------------
def _connected(monkeypatch, ident="namun"):
    hermesbot._save_record({"status": "connected", "model": "chatgpt", "slack": {"id": ident, "connected": "t"}})
    env = paths.hermes_home() / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text(f"SLACK_BOT_TOKEN=xoxb-x\nSLACK_APP_TOKEN=xapp-x\nHERMES_SLACK_SLASH=hermes-{ident}\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, log, timeout=600):
        calls.append(cmd[1:])
        if cmd[1:3] == ["config", "set"]:  # hermes 는 UPPER_SNAKE 를 .env 에 쓴다
            env.write_text(env.read_text(encoding="utf-8").replace(f"HERMES_SLACK_SLASH=hermes-{ident}",
                                                                   f"HERMES_SLACK_SLASH={cmd[4]}"), encoding="utf-8")
        return True, ""
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    monkeypatch.setattr(hermesbot, "_run", fake_run)
    return calls


def test_hermes_rename_sets_slash_restarts_and_records(isolated, monkeypatch):
    calls = _connected(monkeypatch)
    lines = []
    assert cli.main(["hermes", "rename", "Hermes-NCho", "--dry-run"]) == 0
    assert calls == []
    assert hermesbot.cmd_rename(argparse.Namespace(id="Hermes-NCho", dry_run=False), lines.append) == 0
    assert calls == [["config", "set", "HERMES_SLACK_SLASH", "hermes-ncho"], ["gateway", "restart"]]
    slack = hermesbot.recorded()["slack"]
    assert slack["id"] == "ncho" and slack["renamed_from"] == "namun" and slack["connected"] == "t"
    assert any("/hermes-ncho" in line for line in lines)
    # 다시 하면 바꿀 것 없음
    calls.clear()
    assert hermesbot.cmd_rename(argparse.Namespace(id="ncho", dry_run=False), print) == 0 and calls == []
    # doctor: 기록과 슬래시가 맞으면 조용, 이름 바꾼 이력은 보임
    monkeypatch.setattr(hermesbot, "startup_entries", lambda: ["vbs"])
    monkeypatch.setattr(hermesbot, "duplicate_credentials", lambda: [])
    checks = doctor.check_hermes_bot()
    assert [c.status for c in checks] == ["ok"] and "Hermes-namun 에서 이름 바꿈" in checks[0].message


def test_hermes_rename_refuses_bad_id_and_unlinked(isolated, monkeypatch):
    assert hermesbot.cmd_rename(argparse.Namespace(id="Bad Name!", dry_run=False), print) == 2
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: "/x/hermes")
    assert hermesbot.cmd_rename(argparse.Namespace(id="ncho", dry_run=False), print) == 1  # 연결 기록 없음


def test_doctor_warns_slash_differs_from_record(isolated, monkeypatch):
    _connected(monkeypatch)
    env = paths.hermes_home() / ".env"
    env.write_text("SLACK_BOT_TOKEN=x\nSLACK_APP_TOKEN=y\nHERMES_SLACK_SLASH=hermes-old\n", encoding="utf-8")
    monkeypatch.setattr(hermesbot, "startup_entries", lambda: ["vbs"])
    monkeypatch.setattr(hermesbot, "duplicate_credentials", lambda: [])
    warn = [c for c in doctor.check_hermes_bot() if c.status == "warn"]
    assert len(warn) == 1 and "/hermes-old" in warn[0].message and warn[0].fix == "jaix hermes rename namun"


def test_guide_cowork_line_depends_on_managed_deployment():
    """관리자 배포가 없는 PC(개인 구독 계정)는 Cowork 마켓을 직접 추가하라고 안내한다(jaix-win .16)."""
    personal = cli.guide(["claude"], {"claude": {"cli": True, "managed": None}})
    assert "기관 관리자 배포로 내려옵니다" not in personal
    assert "Customize → Plugins → Add marketplace" in personal and "jeju-inst/jaix-kit" in personal
    assert "메일 도구는 Cowork 에서 쓸 수 없습니다" in personal
    org = cli.guide(["claude"], {"claude": {"cli": True, "managed": "remote-settings.json"}})
    assert "기관 관리자 배포로 내려옵니다" in org and "Add marketplace" not in org

# --- Git·uv·age: winget 없이 고정 판을 직접(소모임 11/5: winget 경유 셋만 전부 실패) ----------------------------
import hashlib  # noqa: E402
import zipfile  # noqa: E402


def _zip_bytes(files):
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _serve_pinned(monkeypatch, key, files, sha=None):
    data = _zip_bytes(files)
    pin = dict(runtimes.PINNED[key], sha256=sha or hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(runtimes.PINNED, key, pin)
    got = []

    def fake_download(url, dest, timeout=120):
        got.append(url)
        Path(dest).write_bytes(data)
        return Path(dest)
    monkeypatch.setattr(runtimes.net, "download", fake_download)
    return got


def test_git_uv_age_pinned_without_winget():
    for key in ("git", "uv", "age"):
        rt = runtimes.BY_KEY[key]
        assert rt.winget is None
        name, url = rt.resolve()  # 네트워크 없이(API 를 부르지 않음 — 원내 한 IP 익명 한도와 무관)
        pin = runtimes.PINNED[key]
        assert (name, url) == (pin["name"], pin["url"]) and url.startswith("https://github.com/")
        assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    assert runtimes.BY_KEY["git"].tree == "git" and runtimes.BY_KEY["git"].path_subdir == "cmd"


def _fake_sfx(fail=False):
    """PortableGit 자동 풀기 exe 흉내: -o<폴더> 에 cmd\\git.exe · bin\\bash.exe 를 만든다."""
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        assert cmd[2] == "-y" and cmd[1].startswith("-o")
        out = Path(cmd[1][2:])
        if not fail:
            (out / "cmd").mkdir(parents=True)
            (out / "cmd" / "git.exe").write_bytes(b"g")
            (out / "bin").mkdir()
            (out / "bin" / "bash.exe").write_bytes(b"b")
        return subprocess.CompletedProcess(cmd, 1 if fail else 0, b"", b"")
    return run, seen


def test_portablegit_unpacks_into_jaix_git_and_exports_bash(isolated, monkeypatch):
    rt = runtimes.BY_KEY["git"]
    assert runtimes.PINNED["git"]["name"].startswith("PortableGit-") and runtimes.PINNED["git"]["name"].endswith(".7z.exe")
    data = b"sfx"
    monkeypatch.setitem(runtimes.PINNED, "git", dict(runtimes.PINNED["git"], sha256=hashlib.sha256(data).hexdigest()))
    monkeypatch.setattr(runtimes.net, "download", lambda url, dest, timeout=120: (Path(dest).write_bytes(data), Path(dest))[1])
    run, seen = _fake_sfx()
    monkeypatch.setattr(runtimes.subprocess, "run", run)
    old = paths.jaix_home() / "git" / "cmd"
    old.mkdir(parents=True)
    (old / "git.exe").write_bytes(b"mingit")  # 예전 MinGit 사본 → 바뀐다
    where = runtimes.install_portable(rt, print)
    assert where == paths.jaix_home() / "git" / "cmd" and (where / "git.exe").read_bytes() == b"g"
    assert seen[0][1] == f"-o{paths.jaix_home() / 'git'}" and not (paths.jaix_home() / "git.old").exists()
    # jaix 사본이면 Git Bash 위치를 알린다. 사용자가 다른 bash 를 가리켜 두었으면 그대로
    env = {}
    monkeypatch.setattr(runtimes, "IS_WIN", True)
    monkeypatch.setattr(winenv, "get_user_env", lambda name: env.get(name))
    monkeypatch.setattr(winenv, "set_user_env", lambda name, value: env.update({name: value}) or True)
    found = runtimes.Found(str(where / "git.exe"), "2.56.0", 2, managed=True)
    runtimes._export(rt, found, print)
    assert env["CLAUDE_CODE_GIT_BASH_PATH"] == str(paths.jaix_home() / "git" / "bin" / "bash.exe")
    mine = isolated / "MyGit" / "bin" / "bash.exe"
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"x")
    env["CLAUDE_CODE_GIT_BASH_PATH"] = str(mine)
    runtimes._export(rt, found, print)
    assert env["CLAUDE_CODE_GIT_BASH_PATH"] == str(mine)
    # 시스템 Git(jaix 사본 아님)이면 손대지 않는다
    env.clear()
    runtimes._export(rt, runtimes.Found(r"C:\Program Files\Git\cmd\git.exe", "2.50", 2), print)
    assert env == {}


def test_portablegit_failed_unpack_restores_previous_copy(isolated, monkeypatch):
    rt = runtimes.BY_KEY["git"]
    prev = paths.jaix_home() / "git" / "cmd"
    prev.mkdir(parents=True)
    (prev / "git.exe").write_bytes(b"prev")
    run, _ = _fake_sfx(fail=True)
    with pytest.raises(RuntimeError, match="풀기 실패"):
        runtimes._run_sfx(isolated / "PortableGit.7z.exe", rt, run=run)
    assert (prev / "git.exe").read_bytes() == b"prev" and not (paths.jaix_home() / "git.old").exists()


def test_pinned_sha_mismatch_refuses_to_install(isolated, monkeypatch):
    rt = runtimes.BY_KEY["uv"]
    _serve_pinned(monkeypatch, "uv", {"uv.exe": b"evil"}, sha="0" * 64)
    with pytest.raises(ValueError, match="sha256 불일치"):
        runtimes.install_portable(rt, print)
    assert not (paths.bin_dir() / "uv.exe").exists() and not runtimes._marker(rt).exists()


def test_ensure_missing_git_never_calls_winget_and_reports_failure(isolated, monkeypatch):
    rt = runtimes.BY_KEY["git"]
    monkeypatch.setattr(runtimes, "IS_WIN", True)
    monkeypatch.setattr(runtimes, "_winget", lambda *a, **k: pytest.fail("winget 을 부름"))
    monkeypatch.setattr(runtimes, "find", lambda r: runtimes.Found(None, None))
    monkeypatch.setattr(runtimes, "install_portable", lambda r, log: (_ for _ in ()).throw(OSError("blocked")))
    lines = []
    found = runtimes.ensure(rt, lines.append)
    assert found.path is None and any("설치 실패" in line for line in lines)  # setup 이 [실패]로 센다(#112)


def test_ensure_keeps_existing_git(isolated, monkeypatch):
    rt = runtimes.BY_KEY["git"]
    monkeypatch.setattr(runtimes, "IS_WIN", True)
    monkeypatch.setattr(runtimes, "find", lambda r: runtimes.Found(r"C:\Program Files\Git\cmd\git.exe", "2.50.1", 2))
    monkeypatch.setattr(runtimes, "install_portable", lambda r, log: pytest.fail("이미 있는데 받음"))
    assert runtimes.ensure(rt, print, upgrade=True).path.endswith("git.exe")


# --- mail-skill 이 bin/ → cli/ 로(Cowork 호스팅 검사가 최상위 bin/ 거부, 2026-11-05) ----------------------------
def _fake_cmd_plugin(monkeypatch, layout):
    """layout: {폴더: {파일: 출력 문자열}}. 확장자 없는 것은 sh 스크립트, scripts/mail-secret 는 cli 의 심링크 대상."""
    def fake_fetch(plugin, workdir):
        root = Path(workdir) / plugin.name / "root"
        (root / "skills" / plugin.name).mkdir(parents=True, exist_ok=True)
        (root / "skills" / plugin.name / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        if plugin.name == "mail-skill":
            (root / "scripts").mkdir(exist_ok=True)
            (root / "scripts" / "mail-secret").write_text("#!/bin/sh\necho secret\n", encoding="utf-8")
            for d, files in layout.items():
                (root / d).mkdir(exist_ok=True)
                for f, say in files.items():
                    p = root / d / f
                    if say == "->scripts" and os.name != "nt":
                        p.symlink_to(Path("..") / "scripts" / f)
                    else:
                        p.write_text("@echo off\r\n" if "." in f else f"#!/bin/sh\necho {say}\n", encoding="utf-8")
        return root
    monkeypatch.setattr(plugbin, "fetch_root", fake_fetch)


def test_plugbin_reads_cli_dir_and_prefers_it_over_bin(isolated, monkeypatch, the_lock):
    _fake_cmd_plugin(monkeypatch, {
        "cli": {"mailskill": "from-cli", "mailskill.cmd": "", "mail-secret": "->scripts", "mail-secret.cmd": ""},
        "bin": {"mailskill": "from-bin", "mailskill.cmd": "", "old-only": "from-bin"},
    })
    res = REAL_PLUGBIN_ENSURE(_lock_with_mail_skill(the_lock), print)
    assert res["status"] == "ok"
    copy = plugbin.plugins_dir() / "mail-skill"
    link = plugbin.link_dir()
    made = [Path(c) for c in plugbin.recorded()["mail-skill"]["commands"]]
    names = [p.name for p in made]
    assert len(names) == len(set(n.lower() for n in names))  # 같은 이름은 한 번만
    if paths.IS_WIN:
        assert str(copy / "cli" / "mailskill.cmd") in (link / "mailskill.cmd").read_text(encoding="utf-8")
        assert "/cli/mailskill" in (link / "mailskill").read_text(encoding="utf-8").replace("\\", "/")
        assert (link / "old-only").is_file()  # bin 에만 있는 것도 전환기엔 올린다
    else:
        assert (link / "mailskill").resolve() == (copy / "cli" / "mailskill").resolve()
        assert (link / "old-only").resolve() == (copy / "bin" / "old-only").resolve()
        # Claude Code 는 cli/ 를 PATH 에 넣어 주지 않는다 → jaix 링크만으로 이름이 잡히고 실행돼야 한다
        monkeypatch.setenv("PATH", str(link))
        assert Path(shutil.which("mailskill")).parent == link
        out = subprocess.run(["mailskill"], capture_output=True, text=True).stdout.strip()
        assert out == "from-cli"
        out = subprocess.run(["mail-secret"], capture_output=True, text=True).stdout.strip()
        assert out == "secret"  # cli 의 심링크(→ ../scripts) 도 사본에서 그대로 돈다
        checks = doctor.check_plugin_bin(_lock_with_mail_skill(the_lock))
        assert [c.status for c in checks] == ["ok"] and "mailskill" in checks[0].message


def test_plugbin_cli_only_plugin_without_bin(isolated, monkeypatch, the_lock):
    _fake_cmd_plugin(monkeypatch, {"cli": {"mailskill": "from-cli", "mailskill.cmd": ""}})
    res = REAL_PLUGBIN_ENSURE(_lock_with_mail_skill(the_lock), print)
    assert res["status"] == "ok" and "mailskill" in res["commands"]
    assert (plugbin.plugins_dir() / "mail-skill" / "cli").is_dir()
