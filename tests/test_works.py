"""웍스(nworks) — 잠금 runtime.json 읽기, 무결성 대조, 기관 앱 정보, 로그인 명령에 비밀이 실리지 않는지."""
import json
import os
from types import SimpleNamespace

import pytest

from jaix import cli, doctor, lock as lockmod, paths, runtimes, works

WANT = works.FALLBACK["nworks"]
REAL_EXISTING = works.existing  # 자동 픽스처가 바꾸기 전 원본


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("JAIX_HOME", "JAIX_DATA"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setattr(works.winenv, "add_to_path", lambda dirs, dry_run=False: None)
    monkeypatch.setattr(works.winenv, "in_user_path", lambda p: True)
    monkeypatch.setattr(works, "on_path", lambda: True)
    # 이 머신 PATH 의 진짜 nworks 를 보지 않게(있는 경우의 시험은 아래에서 따로)
    monkeypatch.setattr(works, "existing", lambda want: None)
    # Node 는 있는 것으로, 진짜로 깔지 않는다
    found = runtimes.Found("/usr/bin/node", "22.11.0", 22)
    monkeypatch.setattr(runtimes, "ensure", lambda rt, log, dry_run=False, upgrade=False: found)
    monkeypatch.setattr(runtimes, "find", lambda rt: found)
    return tmp_path


def _lock(with_works=True):
    p = lockmod.Plugin("jaix-works", "2026.11.1.1", "a" * 40, "v2026.11.1.1", "https://github.com/jeju-inst/jaix-works.git")
    return SimpleNamespace(plugins=[p] if with_works else [], source="test")


def _fake_npm(monkeypatch, integrity=WANT["integrity"], ok=True):
    def install(version):
        nm = works.home() / "node_modules"
        (nm / "nworks").mkdir(parents=True, exist_ok=True)
        (nm / "nworks" / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        (nm / ".bin").mkdir(exist_ok=True)
        (works.home() / "package-lock.json").write_text(json.dumps(
            {"packages": {"node_modules/nworks": {"version": version, "integrity": integrity}}}), encoding="utf-8")
        return ok, "added 1 package"
    monkeypatch.setattr(works, "_npm_install", install)


def test_spec_parse_and_fallback():
    text = json.dumps({"nworks": WANT, "scope": "file.read", "client_source": "https://x/client.json"})
    assert works.parse_spec(text)["scope"] == "file.read"
    assert works.parse_spec('{"nworks": {}}') is None
    assert works.spec(_lock(), offline=True) == works.FALLBACK


def test_absent_from_lock_does_nothing():
    assert works.ensure(_lock(False), print) == {"status": "absent"}
    assert doctor.check_works(_lock(False)) == []


def test_install_checks_integrity(monkeypatch):
    monkeypatch.setattr(works, "fetch_client", lambda url, timeout=8: None)
    _fake_npm(monkeypatch, integrity="sha512-tampered")
    res = works.ensure(_lock(), print, offline=True)
    assert res["status"] == "failed" and not (works.home() / "node_modules").exists()
    _fake_npm(monkeypatch)
    assert works.ensure(_lock(), print, offline=True)["status"] == "installed"
    assert works.ensure(_lock(), print, offline=True)["status"] == "current"


def test_client_saved_privately_and_not_logged(monkeypatch):
    _fake_npm(monkeypatch)
    secret = "s3cr3t-value"
    monkeypatch.setattr(works, "fetch_client", lambda url, timeout=8: {"client_id": "cid", "client_secret": secret})
    lines = []
    res = works.ensure(_lock(), lines.append, offline=True)
    assert res["client"] is True
    assert works.saved_client()["client_secret"] == secret
    assert not any(secret in str(x) for x in lines)
    if not paths.IS_WIN:
        assert oct(os.stat(works.client_file()).st_mode & 0o777) == "0o600"


def test_login_passes_secret_by_env_with_explicit_scope(monkeypatch):
    _fake_npm(monkeypatch)
    monkeypatch.setattr(works, "fetch_client", lambda url, timeout=8: {"client_id": "cid", "client_secret": "sec"})
    works.ensure(_lock(), print, offline=True)
    monkeypatch.setattr(works, "exe", lambda: "/x/nworks")
    seen = {}

    def run(cmd, env=None, timeout=None):
        seen["cmd"], seen["env"] = cmd, env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(works.subprocess, "run", run)
    assert works.login(print) == 0
    assert "sec" not in " ".join(map(str, seen["cmd"]))
    assert seen["env"]["NWORKS_CLIENT_SECRET"] == "sec"
    assert seen["cmd"][-2:] == ["--scope", works.FALLBACK["scope"]]


def test_login_without_client_tells_how(monkeypatch):
    monkeypatch.setattr(works, "exe", lambda: "/x/nworks")
    lines = []
    assert works.login(lines.append) == 1 and "원내망" in lines[-1]


def test_doctor_states(monkeypatch):
    assert doctor.check_works(_lock())[0].status == "fail"
    _fake_npm(monkeypatch)
    monkeypatch.setattr(works, "fetch_client", lambda url, timeout=8: {"client_id": "c", "client_secret": "s"})
    works.ensure(_lock(), print, offline=True)
    monkeypatch.setattr(works, "spec", lambda lock, offline=False: works.FALLBACK)
    checks = {c.area: c.status for c in doctor.check_works(_lock())}
    assert checks == {"웍스(nworks)": "ok", "웍스 로그인": "warn"}
    tok = works.user_token_file()
    tok.parent.mkdir(parents=True)
    tok.write_text(json.dumps({"default": {"refreshToken": "r"}}), encoding="utf-8")
    assert {c.area: c.status for c in doctor.check_works(_lock())}["웍스 로그인"] == "ok"


def test_cli_works_login_parses():
    args = cli.build_parser().parse_args(["works", "login"])
    assert args.func is cli.cmd_works and args.works_cmd == "login"


def test_npm_launch_failure_is_a_failed_status(monkeypatch):
    def boom(cli, args, timeout=600):
        raise works.subprocess.TimeoutExpired("npm", 900)
    monkeypatch.setattr(works, "_npm", lambda: "/x/npm")
    monkeypatch.setattr(works.proc, "run", boom)
    monkeypatch.setattr(works, "fetch_client", lambda url, timeout=8: None)
    assert works.ensure(_lock(), print, offline=True)["status"] == "failed"


@pytest.mark.skipif(paths.IS_WIN, reason="맥·리눅스 바로가기")
def test_expose_links_into_local_bin(monkeypatch):
    _fake_npm(monkeypatch)
    monkeypatch.setattr(works, "fetch_client", lambda url, timeout=8: None)
    works.ensure(_lock(), print, offline=True)
    link = works.link_dir() / "nworks"
    assert link.is_symlink() and os.readlink(link) == str(works.bin_dir() / "nworks")


def test_existing_nworks_is_used_instead_of_npm(monkeypatch):
    """이미 깔린 nworks 가 있으면 npm 으로 한 벌 더 깔지 않는다(사용자 요구 11/9)."""
    monkeypatch.setattr(works, "existing", lambda want: ("/usr/local/bin/nworks", "1.3.2"))
    monkeypatch.setattr(works, "_npm_install", lambda v: pytest.fail("npm 을 부르면 안 됨"))
    monkeypatch.setattr(works, "fetch_client", lambda url, timeout=8: {"client_id": "c", "client_secret": "s"})
    lines = []
    assert works.ensure(_lock(), lines.append, offline=True)["status"] == "existing"
    assert any("이미 설치된 nworks 1.3.2" in ln for ln in lines)
    monkeypatch.setattr(works, "spec", lambda lock, offline=False: works.FALLBACK)
    checks = {c.area: c.status for c in doctor.check_works(_lock())}
    assert checks["웍스(nworks)"] == "ok"
    assert works.cli() == "/usr/local/bin/nworks"


def test_existing_accepts_same_major_not_older(monkeypatch):
    monkeypatch.setattr(works.shutil, "which", lambda name, path=None: "/opt/bin/nworks" if path is None else None)
    for out, ok in (("1.3.1", True), ("1.4.0", True), ("1.2.9", False), ("2.0.0", False), ("garbage", False)):
        monkeypatch.setattr(works.proc, "run", lambda c, a, timeout=30, out=out: (0, out + "\n"))
        assert bool(REAL_EXISTING("1.3.1")) is ok, out
    monkeypatch.setattr(works.proc, "run", lambda c, a, timeout=30: (1, "1.3.1\n"))
    assert REAL_EXISTING("1.3.1") is None


def test_npm_failure_shows_npm_error_lines(monkeypatch):
    out = ("npm error code EPERM\nnpm error syscall rename\nnpm error path C:\\x\n"
           "npm error A complete log of this run can be found in: C:\\log.txt\n")
    monkeypatch.setattr(works, "_npm", lambda: "/x/npm")
    monkeypatch.setattr(works.proc, "run", lambda c, a, timeout=600: (1, out))
    ok, why = works._npm_install("1.3.1")
    assert not ok and "EPERM" in why and "rename" in why and "complete log" not in why
