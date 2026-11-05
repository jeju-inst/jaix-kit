"""명령창 claude·codex: 있으면 그대로, PATH 밖이면 올리고, 없으면 깐다. 네트워크·설치·레지스트리는 가짜."""
import hashlib
import json
from pathlib import Path

import pytest

from jaix import clis, paths, winenv

BIN = b"MZ fake claude"


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("JAIX_HOME", "JAIX_DATA"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setattr(clis, "IS_WIN", True)
    home = tmp_path / "home"
    monkeypatch.setattr(clis.Path, "home", classmethod(lambda cls: home))
    npm = tmp_path / "npm"
    monkeypatch.setattr(paths, "npm_global_bin", lambda: npm)
    state = {"path": [], "fresh": str(tmp_path / "empty")}
    monkeypatch.setattr(clis, "fresh_path", lambda: state["fresh"])
    monkeypatch.setattr(winenv, "add_to_path", lambda dirs, dry_run=False: [str(d) for d in dirs if not state["path"].append(str(d))])
    monkeypatch.setattr(winenv, "remove_entry", lambda p: [p] if p in state["path"] and not state["path"].remove(p) else [])
    return tmp_path, home, npm, state


def _exe(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_bytes(b"x")
    f.chmod(0o755)
    return f


def test_present_on_fresh_path_is_left_alone(env):
    tmp, home, npm, state = env
    found = _exe(tmp / "sysbin", "claude")
    state["fresh"] = str(tmp / "sysbin")
    res = clis.ensure("claude", lambda m="": None, installer=lambda log: pytest.fail("깔지 않아야 함"))
    assert res["status"] == "present" and res["path"] == str(found) and not state["path"]
    assert not clis.recorded()


def test_installed_but_not_on_path_gets_path_added(env):
    tmp, home, npm, state = env
    _exe(npm, "codex")  # npm 전역에 있지만 %APPDATA%\npm 이 PATH 에 없음
    res = clis.ensure("codex", lambda m="": None, installer=lambda log: pytest.fail("깔지 않아야 함"))
    assert res["status"] == "path-added" and state["path"] == [str(npm)]
    assert clis.recorded()["codex"]["path_added"] == str(npm) and "how" not in clis.recorded()["codex"]
    _exe(home / ".local" / "bin", "claude")  # 네이티브 설치 런처만 있음
    assert clis.ensure("claude", lambda m="": None)["status"] == "path-added"
    assert str(home / ".local" / "bin") in state["path"]


def test_missing_installs_and_records(env):
    tmp, home, npm, state = env

    def fake_claude(log):
        return str(_exe(home / ".local" / "bin", "claude")), "2.1.311"
    res = clis.ensure("claude", lambda m="": None, installer=fake_claude)
    assert res["status"] == "installed" and str(home / ".local" / "bin") in state["path"]
    rec = clis.recorded()["claude"]
    assert rec["how"] == "native" and rec["version"] == "2.1.311" and rec["path_added"]


def test_desktop_only_copy_counts_as_missing(env, monkeypatch):
    """Claude Desktop 이 Code 탭용으로 받아 둔 사본은 명령창에서 안 잡히므로 '없음'으로 보고 CLI 를 깐다."""
    tmp, home, npm, state = env
    calls = []
    clis.ensure("claude", lambda m="": None, installer=lambda log: calls.append(1) or (str(_exe(home / ".local" / "bin", "claude")), "1.0.0"))
    assert calls == [1]


def test_install_failure_is_reported_not_raised(env):
    def boom(log):
        raise RuntimeError("sha256 불일치")
    res = clis.ensure("claude", lambda m="": None, installer=boom)
    assert res["status"] == "failed" and "sha256" in res["error"]


def test_install_claude_follows_official_script(env, monkeypatch):
    tmp, home, npm, state = env
    monkeypatch.delenv("PROCESSOR_ARCHITECTURE", raising=False)
    want = hashlib.sha256(BIN).hexdigest()
    seen = []

    def download(url, dest):
        seen.append(url)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(BIN)

    def run(cmd, timeout=600):
        seen.append(cmd[1:])
        _exe(home / ".local" / "bin", "claude")
        return 0, "ok"
    exe, version = clis.install_claude(
        lambda m="": None, get_text=lambda url: seen.append(url) or "2.1.311",
        get_json=lambda url: seen.append(url) or {"platforms": {"win32-x64": {"checksum": want}}},
        download=download, run=run)
    assert version == "2.1.311" and exe.endswith("claude")
    assert seen[:3] == [f"{clis.CLAUDE_DIST}/stable", f"{clis.CLAUDE_DIST}/2.1.311/manifest.json",
                        f"{clis.CLAUDE_DIST}/2.1.311/win32-x64/claude.exe"]
    assert seen[3] == ["install", "stable"]
    assert not list((paths.data_dir() / "downloads").glob("*.exe"))  # 받은 파일은 지운다


def test_install_claude_rejects_bad_checksum_and_html(env):
    def download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="sha256"):
        clis.install_claude(lambda m="": None, get_text=lambda u: "2.1.311",
                            get_json=lambda u: {"platforms": {"win32-x64": {"checksum": "00" * 32}}},
                            download=download, run=lambda c, timeout=600: pytest.fail("검증 전에 실행하지 않는다"))
    with pytest.raises(RuntimeError, match="판 번호"):
        clis.install_claude(lambda m="": None, get_text=lambda u: "<html>", get_json=None)


def test_cleanup_removes_only_what_jaix_installed(env):
    tmp, home, npm, state = env
    launcher = _exe(home / ".local" / "bin", "claude")
    (home / ".local" / "share" / "claude" / "versions").mkdir(parents=True)
    _exe(npm, "codex")  # 사용자가 원래 가진 codex — jaix 는 PATH 만 넣었다
    clis.ensure("codex", lambda m="": None)
    clis._remember("claude", path=str(launcher), how="native", path_added=str(home / ".local" / "bin"))
    state["path"].append(str(home / ".local" / "bin"))
    clis.cleanup(lambda m="": None)
    assert not launcher.exists() and not (home / ".local" / "share" / "claude").exists()
    assert (npm / "codex").exists()  # 원래 있던 것은 그대로
    assert str(home / ".local" / "bin") not in state["path"]  # 비었으니 PATH 에서 뺌
    assert str(npm) in state["path"]  # 다른 것이 남은 폴더는 PATH 에 둔다
    assert not clis.record_file().exists()


def test_doctor_rows(env):
    tmp, home, npm, state = env
    _exe(tmp / "sysbin", "claude")
    state["fresh"] = str(tmp / "sysbin")
    clis._remember("claude", how="native")
    rows = {r[1]: r for r in clis.doctor_rows(["claude", "codex"])}
    assert rows["claude 명령"][0] == "ok" and "설치함(jaix)" in rows["claude 명령"][2]
    assert rows["codex 명령"][0] == "warn" and "안 잡힘" in rows["codex 명령"][2]
    assert [r[1] for r in clis.doctor_rows(["claude"])] == ["claude 명령"]


def test_guide_tells_to_open_new_terminal():
    from jaix import cli
    text = cli.guide(["claude", "codex"], {"claude_cli": {"status": "installed"}, "codex_cli": {"status": "failed"},
                                           "codex": {"cli": True}})
    assert "새 명령창(PowerShell·cmd)을 열고 claude 를 입력" in text and "codex 명령을 깔지 못했습니다" in text
