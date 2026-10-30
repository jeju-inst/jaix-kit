import dataclasses
import json
import re
import sys
from pathlib import Path

import pytest

from jaix import paths, proc
from jaix import claude, cli, codex, doctor, gw, hermes, hermesbot, hwpjar, hwprhwp, lock, overlap, runtimes, schedule, uvpython, winenv

REAL_HWPJAR = {}
REAL_RHWP_ENSURE = hwprhwp.ensure  # isolated 픽스처가 막기 전의 진짜 함수
REAL_UV_ENSURE = uvpython.ensure  # isolated 픽스처가 막기 전의 진짜 함수
REAL_GW_FOREIGN = gw.foreign  # isolated 픽스처가 막기 전의 진짜 함수
REAL_MANAGED = claude.managed_declaration  # isolated 픽스처가 막기 전의 진짜 함수
LOCK_FILE = Path(__file__).resolve().parents[1] / ".claude-plugin" / "marketplace.json"

REAL_HERMES_SETUP = hermesbot.setup

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """실제 사용자 설정을 건드리지 않게 모든 경로를 tmp로."""
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
    monkeypatch.setattr(paths, "desktop_installed", lambda: False)
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
    tokens = iter(["xoxb-TEST-1", "xapp-TEST-1"])
    monkeypatch.setattr(hermesbot.getpass, "getpass", lambda prompt: next(tokens))
    monkeypatch.setattr(hermesbot, "slack_call", lambda m, t: {"ok": True, "user": "hermes-bob", "team": "T"})
    args = type("A", (), {"id": "demo", "user": "U0TEST", "ttl": 72, "spool": str(tmp_path / "spool")})()
    assert hermesbot.cmd_handoff(args, print) == 1          # 다른 사람 봇 → 멈춤, 묶음 없음
    assert not (tmp_path / "spool").exists()
    tokens = iter(["xoxb-TEST-1", "xapp-TEST-1"])
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
    data["plugins"].append({**data["plugins"][0], "name": "mail"})
    return lock.Lock(data, the_lock.source)


def test_mail_runtimes_required_only_when_mail_in_lock(the_lock):
    keys = lambda lk: {rt.key for rt in runtimes.select([], lk)}
    assert not {"himalaya", "age"} & keys(the_lock)
    assert {"himalaya", "age"} <= keys(_with_mail(the_lock))
    assert not runtimes.required(runtimes.BY_KEY["age"], None)


def test_doctor_mail_runtime_missing_fails_only_with_mail(the_lock, monkeypatch):
    monkeypatch.setattr(runtimes, "find", lambda rt: runtimes.Found(None, None))
    by = lambda lk: {c.area: c.status for c in doctor.check_runtimes(lk)}
    assert by(the_lock)["himalaya"] == "skip"
    assert by(_with_mail(the_lock))["himalaya"] == "fail"


def test_doctor_mail_python(the_lock, monkeypatch):
    assert doctor.check_mail_python(the_lock) == []
    lk = _with_mail(the_lock)
    monkeypatch.setattr(runtimes, "find", lambda rt: runtimes.Found("/x/uv", "0.9"))
    monkeypatch.setattr(uvpython, "find", lambda v, uv=None: None)
    [c] = doctor.check_mail_python(lk)
    assert c.status == "fail" and "3.12" in c.message
    monkeypatch.setattr(uvpython, "find", lambda v, uv=None: "/py/3.12/python")
    assert doctor.check_mail_python(lk)[0].status == "ok"
