import json
import sys
from pathlib import Path

import pytest

from jaix import claude, cli, codex, doctor, gw, hermes, lock, runtimes, schedule, uvpython, winenv

REAL_MANAGED = claude.managed_declaration  # isolated 픽스처가 막기 전의 진짜 함수
LOCK_FILE = Path(__file__).resolve().parents[1] / ".claude-plugin" / "marketplace.json"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """실제 사용자 설정을 건드리지 않게 모든 경로를 tmp로."""
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("JAIX_LOCK", str(LOCK_FILE))
    monkeypatch.setattr(claude, "managed_declaration", lambda: None)
    # uv python install 은 진짜로 돌리지 않는다(내려받기)
    monkeypatch.setattr(uvpython, "ensure", lambda versions, log, dry_run=False: True)
    monkeypatch.setattr(uvpython, "needed", lambda lock, offline=False: [uvpython.DEFAULT])
    # 예약 작업은 진짜로 등록하지 않는다(맥이면 launchctl이 시험 중에 update를 돌린다)
    monkeypatch.setenv("JAIX_LAUNCH_AGENTS", str(tmp_path / "LaunchAgents"))
    monkeypatch.setattr(schedule, "_run", lambda args: (True, ""))
    monkeypatch.setattr(schedule, "run_mode", lambda: None)
    monkeypatch.setenv(gw.ENV, "none")  # 기본 원내 주소로 나가지 않게(gw 시험이 저마다 바꾼다)
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
