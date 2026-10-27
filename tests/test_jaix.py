import json
import sys
from pathlib import Path

import pytest

from jaix import paths
from jaix import claude, cli, codex, doctor, gw, hermes, hwpjar, lock, runtimes, schedule, uvpython, winenv

REAL_HWPJAR = {}
REAL_UV_ENSURE = uvpython.ensure  # isolated 픽스처가 막기 전의 진짜 함수
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
    # hwp 변환기 jar 도 진짜로 받지 않는다. 받는 자리는 tmp
    REAL_HWPJAR["ensure"] = REAL_HWPJAR.get("ensure", hwpjar.ensure)
    monkeypatch.setattr(hwpjar, "ensure", lambda lock, log, dry_run=False, offline=False: True)
    monkeypatch.setattr(hwpjar, "dest", lambda: tmp_path / "hwp-agent" / "hwp2hwpx.jar")
    monkeypatch.setattr(paths, "desktop_installed", lambda: False)
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
    assert codex.mcp_servers(the_lock) == {"hwp-agent": {"command": "uvx", "args": ["--from", str(root), "hwp-agent", "mcp"],
                                                       "env": {}}}
    assert codex.write_mcp(the_lock, print, cli="codex")
    assert calls[-1][:3] == ["mcp", "add", "hwp-agent"] and str(root) in calls[-1]
    n = len(calls)
    codex.write_mcp(the_lock, print, cli="codex")
    assert len(calls) == n  # 이미 맞으면 다시 쓰지 않음


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
    branch = next(p for p in the_lock.plugins if not p.version)
    # Claude Code 기록: branch 고정이면 version 칸에 12자리 해시
    assert claude.matches(branch, {"version": branch.sha[:12]})
    assert not claude.matches(branch, {"version": "0" * 12})
    tagged = next(p for p in the_lock.plugins if p.version)
    assert claude.matches(tagged, {"version": tagged.version}) and not claude.matches(tagged, {"version": tagged.sha[:12]})
