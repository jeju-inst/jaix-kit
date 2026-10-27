import json
import sys
from pathlib import Path

import pytest

from jaix import claude, cli, codex, doctor, gw, hermes, lock, runtimes, uvpython, winenv

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


def test_gw_unset_is_skipped(monkeypatch):
    monkeypatch.delenv(gw.ENV, raising=False)
    assert gw.setup(print)["status"] == "unset"
    assert doctor.check_gw()[0].status == "skip"


def test_gw_offsite_is_skipped_with_hint(monkeypatch):
    monkeypatch.setenv(gw.ENV, "http://127.0.0.1:9/gw.exe")  # 닿지 않는 곳 = 원외
    assert gw.setup(print)["status"] == "offsite"
    c = doctor.check_gw()[0]
    assert c.status == "warn" and "원내망" in c.fix


def test_gw_source_saved_and_installed(isolated, monkeypatch):
    monkeypatch.delenv(gw.ENV, raising=False)
    src = isolated / "share" / "gw.exe"
    src.parent.mkdir()
    src.write_bytes(b"MZ fake")
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    url = src.as_uri()
    assert cli.main(["setup", "--runtimes", "none", "--channels", "claude", "--gw-source", url]) == 0
    assert gw.source() == url and gw.exe_path().read_bytes() == b"MZ fake"
    assert doctor.check_gw()[0].status == "ok"


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
