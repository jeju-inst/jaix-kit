"""jaix selftest. 외부 명령(uvx·hwp2pdf·claude·hermes)은 부르지 않고 가짜 runner·handshake 로 시험한다.
MCP 주고받기만 이 파이썬으로 띄운 가짜 서버로 진짜 stdio 를 거친다."""
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jaix import cli, doctor, gw, hancom, hermesbot, lock, paths, selftest, works

LOCK_FILE = Path(__file__).resolve().parents[1] / ".claude-plugin" / "marketplace.json"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    # 진짜 hermes 를 부르지 못하게(#115: 시험이 진짜 hermes 런처를 덮어쓴 사고). 이 파일의 시험은 hermes 를 부를 일이 없다
    real_popen = subprocess.Popen

    class GuardedPopen(real_popen):
        def __init__(self, args, *a, **kw):
            exe = args[0] if isinstance(args, (list, tuple)) and args else None
            if exe and Path(str(exe)).stem.lower() in ("hermes", "hermes-acp"):
                raise AssertionError(f"시험이 hermes 를 부름: {args}")
            super().__init__(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: None)
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "JAIX_DATA", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("JAIX_LOCK", str(LOCK_FILE))
    monkeypatch.setenv("JI_GW_CONFIG_DIR", str(tmp_path / "gwconf"))
    monkeypatch.setenv("HIMALAYA_CONFIG", str(tmp_path / "himalaya" / "config.toml"))
    monkeypatch.setenv("MAIL_SKILL_SECRETS", str(tmp_path / "mail" / "secrets.age"))
    for name in ("GW_BASE_URL", "GW_USER", "GW_PW", "HWP2PDF_CLI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(gw.ENV, raising=False)


@pytest.fixture
def the_lock():
    return lock.load(str(LOCK_FILE))


def _install_plugin(tmp_path, name, mcp):
    """Claude 가 깐 것처럼: installed_plugins.json 에 installPath, 그 폴더에 .mcp.json."""
    root = tmp_path / "plugins" / name
    root.mkdir(parents=True)
    if mcp is not None:
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": mcp}), encoding="utf-8")
    f = paths.claude_dir() / "plugins" / "installed_plugins.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"version": 2, "plugins": {}}
    data["plugins"][f"{name}@jaix"] = [{"scope": "user", "installPath": str(root), "version": "x"}]
    f.write_text(json.dumps(data), encoding="utf-8")
    return root


HWP_MCP = {"hwp-agent": {"command": "uvx", "args": ["--python", "3.12", "--from", "${CLAUDE_PLUGIN_ROOT}", "--with",
                                                    "mcp>=1.2,<2", "hwp-agent", "mcp"]}}


def _fake_hwpx(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", "<x/>")


# --- 출력 형식 -------------------------------------------------------------------------------------
def test_render_and_summary():
    res = [selftest._ok("A", "됨"), selftest._setup("B", "로그인 없음", "gw login"),
           selftest._skip("C", "원내망 아님"), selftest._fail("D", "안 됨", "jaix setup")]
    text = selftest.render(res)
    assert "[통과] A: 됨" in text
    assert "[설정 필요] B: 로그인 없음 — gw login" in text
    assert "[건너뜀] C: 원내망 아님" in text
    assert "[실패] D: 안 됨 — jaix setup" in text
    assert selftest.summary_line(res).startswith("결과: 통과 1 · 설정 필요 1 · 건너뜀 1 · 실패 1 (jaix ")


# --- 샘플 ------------------------------------------------------------------------------------------
def test_sample_sha_checked(monkeypatch):
    def bad(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"not the file")
    assert selftest.get_sample(bad) is None and not selftest.sample_cache().exists()

    import hashlib
    monkeypatch.setattr(selftest, "SAMPLE_SHA256", hashlib.sha256(b"not the file").hexdigest())
    assert selftest.get_sample(bad) == selftest.sample_cache()
    assert selftest.get_sample(lambda u, d: pytest.fail("두 번째는 받지 않음")) == selftest.sample_cache()


def test_sample_offline_is_none():
    def offline(url, dest):
        raise OSError("no network")
    assert selftest.get_sample(offline) is None


# --- 1. HWP ----------------------------------------------------------------------------------------
def test_hwp_agent_command_like_plugin(tmp_path, the_lock, monkeypatch):
    root = _install_plugin(tmp_path, "hwp-agent", HWP_MCP)
    monkeypatch.setattr(selftest, "resolve_command", lambda c: "/x/uvx")
    cmd, env = selftest.hwp_agent_command(the_lock)
    assert cmd == ["/x/uvx", "--python", "3.12", "--from", str(root), "--with", "mcp>=1.2,<2", "hwp-agent"]
    assert env["CLAUDE_PLUGIN_ROOT"] == str(root)


def test_check_hwp_converts_in_korean_space_path(tmp_path, the_lock, monkeypatch):
    _install_plugin(tmp_path, "hwp-agent", HWP_MCP)
    monkeypatch.setattr(selftest, "resolve_command", lambda c: "/x/uvx")
    sample = tmp_path / "s.hwp"
    sample.write_bytes(b"hwp")
    seen = []

    def runner(cmd, timeout, cwd=None, env=None):
        seen.append(cmd)
        if cmd[-3] == "convert":
            _fake_hwpx(cmd[-1])
        else:
            Path(cmd[-1]).write_text("동북아시아 공동 평화와 번영", encoding="utf-8")
        return 0, ""
    base, work = selftest.make_workdir()
    try:
        res, src = selftest.check_hwp(the_lock, work, sample, runner)
        assert [r.status for r in res] == ["ok", "ok"], selftest.render(res)
        assert "jaix 시험" in seen[0][-2] and seen[0][-2].endswith("공문.hwp")
        assert src.name == "공문.hwp"
    finally:
        shutil.rmtree(base)


def test_check_hwp_failures(tmp_path, the_lock, monkeypatch):
    base, work = selftest.make_workdir()
    try:
        res, _ = selftest.check_hwp(the_lock, work, None)
        assert res[0].status == "skip"
        sample = tmp_path / "s.hwp"
        sample.write_bytes(b"hwp")
        monkeypatch.setattr(selftest.paths, "which", lambda n: None)
        res, _ = selftest.check_hwp(the_lock, work, sample)
        assert res[0].status == "fail" and res[0].fix == "jaix setup"  # 플러그인 없음
        _install_plugin(tmp_path, "hwp-agent", HWP_MCP)
        monkeypatch.setattr(selftest, "resolve_command", lambda c: "/x/uvx")
        res, _ = selftest.check_hwp(the_lock, work, sample, lambda *a, **k: (2, "error: Java(JRE)가 필요합니다"))
        assert res[0].status == "fail" and "새 명령창" in res[0].fix

        def ascii_only(cmd, timeout, cwd=None, env=None):
            if "시험" in cmd[-2]:
                return 1, 'Exception in thread "main" java.nio.file.InvalidPathException: Illegal char\n\tat X.main(X.java:1)'
            _fake_hwpx(cmd[-1])
            return 0, ""
        res, _ = selftest.check_hwp(the_lock, work, sample, ascii_only)
        assert res[0].status == "fail" and "영문 경로는 됨" in res[0].message and "InvalidPathException" in res[0].message

        def not_zip(cmd, timeout, cwd=None, env=None):
            Path(cmd[-1]).write_bytes(b"junk")
            return 0, ""
        res, _ = selftest.check_hwp(the_lock, work, sample, not_zip)
        assert res[0].status == "fail" and "문서 묶음" in res[0].message
    finally:
        shutil.rmtree(base)


def test_valid_hwpx(tmp_path):
    good, bad = tmp_path / "a.hwpx", tmp_path / "b.hwpx"
    _fake_hwpx(good)
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("x.txt", "x")
    assert selftest.valid_hwpx(good) and not selftest.valid_hwpx(bad) and not selftest.valid_hwpx(tmp_path / "none")


# --- 2. PDF ----------------------------------------------------------------------------------------
def test_pdf_skips_without_hancom(monkeypatch, tmp_path):
    monkeypatch.setattr(hancom, "present", lambda: False)
    assert selftest.check_pdf(tmp_path / "a.hwp")[0].message == "한컴오피스 없음"


def test_pdf_consent_needed_is_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(hancom, "present", lambda: True)
    monkeypatch.setattr(doctor, "check_hancom_consent", lambda: [doctor.Check("warn", hancom.AREA, "답 없음")])
    res = selftest.check_pdf(tmp_path / "a.hwp", runner=lambda *a, **k: pytest.fail("변환을 시도하면 안 됨"))
    assert [r.status for r in res] == ["setup", "skip"]


def test_pdf_converts(monkeypatch, tmp_path):
    monkeypatch.setattr(hancom, "present", lambda: True)
    monkeypatch.setattr(doctor, "check_hancom_consent", lambda: [doctor.Check("ok", hancom.AREA, "답해 둠")])
    monkeypatch.setattr(selftest, "hwp2pdf_exe", lambda: "hwp2pdf-cli.exe")
    src = tmp_path / "공문.hwp"
    src.write_bytes(b"x")

    def runner(cmd, timeout, cwd=None, env=None):
        assert env["HWP2PDF_LOCAL"] == "1" and cmd[1:] == [str(src), "--pdf"]
        src.with_suffix(".pdf").write_bytes(b"%PDF-1.7\n")
        return 0, ""
    assert selftest.check_pdf(src, runner)[0].status == "ok"
    src.with_suffix(".pdf").write_bytes(b"<html>")
    assert selftest.check_pdf(src, lambda *a, **k: (1, "한글 실행 중"))[0].status == "fail"


# --- 3. MCP ----------------------------------------------------------------------------------------
def test_check_mcp(tmp_path, the_lock, monkeypatch):
    assert selftest.check_mcp(the_lock, tmp_path)[0].status == "fail"  # 아무것도 안 깔림
    root = _install_plugin(tmp_path, "hwp-agent", HWP_MCP)
    _install_plugin(tmp_path, "korea-rio-mcp", {"korea-rio": {"command": "uvx", "args": ["--from", "${CLAUDE_PLUGIN_ROOT}",
                                                                                         "korea-rio-mcp"]}})
    monkeypatch.setattr(selftest, "resolve_command", lambda c: "/x/uvx")
    calls = {}

    def handshake(cmd, env, cwd):
        calls[cmd[-1]] = (cmd, env)
        return (["a", "b", "c"], None) if cmd[-1] == "mcp" else (None, "응답 없음(시간 초과)")
    res = {r.area: r for r in selftest.check_mcp(the_lock, tmp_path, handshake)}
    assert res["MCP hwp-agent"].status == "ok" and res["MCP hwp-agent"].message == "도구 3개"
    assert res["MCP korea-rio"].status == "fail"
    assert str(root) in calls["mcp"][0] and "${CLAUDE_PLUGIN_ROOT}" not in " ".join(calls["mcp"][0])


FAKE_SERVER = r'''
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        print("not json noise", flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-06-18",
              "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}}), flush=True)
    elif msg.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [{"name": "t1"}, {"name": "t2"}]}}),
              flush=True)
'''


def test_mcp_handshake_real_stdio(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    tools, why = selftest.mcp_handshake([sys.executable, str(script)], dict(os.environ), str(tmp_path), timeout=30)
    assert why is None and tools == ["t1", "t2"]
    tools, why = selftest.mcp_handshake([sys.executable, "-c", "import sys; sys.exit(3)"], dict(os.environ),
                                        str(tmp_path), timeout=30)
    assert tools is None and why == "서버가 바로 끝남"


# --- 4. 그룹웨어 ------------------------------------------------------------------------------------
def test_gw(monkeypatch):
    monkeypatch.setenv(gw.ENV, "none")
    assert selftest.check_gw()[0].message.startswith("끔")
    monkeypatch.delenv(gw.ENV)
    assert selftest.check_gw()[0].status == "skip"  # 주소 없음
    monkeypatch.setenv("GW_BASE_URL", "http://10.1.2.3/gw")
    assert selftest.check_gw(reachable=lambda u: False)[0].message == "원내망 아님"
    monkeypatch.setattr(gw, "installed_version", lambda: "2026.10.30")
    res = selftest.check_gw(reachable=lambda u: True, saved=lambda: False)
    assert [r.status for r in res] == ["ok", "setup"] and res[1].fix == "명령창에서 gw login"
    assert "10.1.2.3" not in selftest.render(res) and "10.1.2.3" not in json.dumps(selftest.as_dicts(res))
    assert selftest.check_gw(reachable=lambda u: True, saved=lambda: True)[1].status == "ok"
    assert selftest.check_gw(reachable=lambda u: True, saved=lambda: None)[1].status == "skip"


def test_gw_login_saved_mac_uses_attributes_only(monkeypatch):
    monkeypatch.setattr(selftest, "IS_WIN", False)
    monkeypatch.setattr(selftest, "IS_MAC", True)
    seen = []

    def runner(cmd, timeout, cwd=None, env=None):
        seen.append(cmd)
        return 44, ""
    assert selftest.gw_login_saved(runner) is False
    assert "-w" not in seen[0] and "-g" not in seen[0] and seen[0][:2] == ["security", "find-generic-password"]
    monkeypatch.setenv("GW_USER", "u")
    monkeypatch.setenv("GW_PW", "p")
    assert selftest.gw_login_saved(lambda *a, **k: pytest.fail("환경변수면 저장소를 보지 않음")) is True


# --- 메일 · 웍스 -----------------------------------------------------------------------------------
def test_mail(the_lock):
    res = selftest.check_mail(the_lock)
    assert res[0].status == "setup" and "mailskill setup" in res[0].fix
    conf = Path(os.environ["HIMALAYA_CONFIG"])
    conf.parent.mkdir(parents=True)
    conf.write_text('[accounts.ji]\nemail = "a@b"\n', encoding="utf-8")
    assert selftest.check_mail(the_lock)[0].status == "setup"  # 비밀번호 파일 없음
    sec = Path(os.environ["MAIL_SKILL_SECRETS"])
    sec.parent.mkdir(parents=True)
    sec.write_bytes(b"age")
    assert selftest.check_mail(the_lock)[0].status == "ok"


def test_works(the_lock, monkeypatch):
    monkeypatch.setattr(works, "plugin", lambda lock: object())
    monkeypatch.setattr(works, "logged_in", lambda: False)
    assert selftest.check_works(the_lock)[0].fix == "jaix works login"
    monkeypatch.setattr(works, "plugin", lambda lock: None)
    assert selftest.check_works(the_lock) == []


# --- 5. Hermes -------------------------------------------------------------------------------------
def test_hermes(tmp_path, monkeypatch):
    assert selftest.check_hermes()[0].status == "skip"
    monkeypatch.setattr(hermesbot, "recorded", lambda: {"status": "connected", "model": "chatgpt"})
    fake = tmp_path / "bin" / "hermes"
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: str(fake))
    no_creds = lambda h, p: []  # noqa: E731
    res = selftest.check_hermes(no_creds)
    assert res[0].status == "fail" and "한 번도" in res[0].message  # 상태 파일 없음
    assert res[1].status == "setup" and "JAIX Hermes 로그인" in res[1].fix
    state = paths.hermes_home() / "gateway_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    state.write_text(json.dumps({"gateway_state": "running", "updated_at": now.isoformat(),
                                 "platforms": {"slack": {"state": "connected"}}}), encoding="utf-8")
    res = selftest.check_hermes(lambda h, p: [{"index": 1, "label": "x", "id": "i"}])
    assert [r.status for r in res] == ["ok", "ok"]
    state.write_text(json.dumps({"gateway_state": "running", "updated_at": (now - timedelta(hours=1)).isoformat(),
                                 "platforms": {"slack": {"state": "connected"}}}), encoding="utf-8")
    assert selftest.check_hermes(no_creds)[0].status == "fail"
    state.write_text(json.dumps({"gateway_state": "running", "updated_at": now.isoformat(),
                                 "platforms": {"slack": {"state": "retrying", "error_code": "auth"}}}), encoding="utf-8")
    assert "슬랙 연결 안 됨" in selftest.check_hermes(no_creds)[0].message
    assert selftest.check_hermes(lambda h, p: None)[1].status == "skip"


# --- 6. --agent -------------------------------------------------------------------------------------
def test_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest.claude, "find_cli", lambda: None)
    assert selftest.check_agent(tmp_path, None)[0].status == "skip"
    monkeypatch.setattr(selftest.claude, "find_cli", lambda: "claude")
    sample = tmp_path / "s.hwp"
    sample.write_bytes(b"x")
    answers = iter(["관광객이 늘었음\n숙박 수요도 증가할 것으로 전망됨", "관광객이 늘었다. 수요가 증가한다."])

    def runner(cmd, timeout, cwd=None, env=None):
        assert cmd[0] == "claude" and "--output-format" in cmd and "--max-turns" in cmd
        if "--allowedTools" in cmd:
            _fake_hwpx(Path(cwd) / "공문.hwpx")
            return 0, json.dumps({"type": "result", "is_error": False, "result": "완료"})
        return 0, json.dumps({"type": "result", "is_error": False, "result": next(answers)})
    res = selftest.check_agent(tmp_path, sample, runner)
    assert [r.status for r in res] == ["ok", "ok"], selftest.render(res)
    shutil.rmtree(tmp_path / "에이전트 시험")
    res = selftest.check_agent(tmp_path, sample, runner)
    assert res[1].status == "fail" and "다." in res[1].message
    res = selftest.check_agent(tmp_path, None, lambda *a, **k: (1, json.dumps({"is_error": True, "subtype": "error"})))
    assert [r.status for r in res] == ["skip", "fail"]


# --- CLI --------------------------------------------------------------------------------------------
def test_cli_selftest(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "run", lambda lock: [doctor.Check("fail", "x", "y")])
    seen = {}

    def fake_run(lock, agent=False, keep=False, log=print, download=None):
        seen["agent"] = agent
        return [selftest._ok("A"), selftest._setup("B", "로그인 없음", "gw login"), selftest._skip("C", "원내망 아님")]
    monkeypatch.setattr(selftest, "run_all", fake_run)
    assert cli.main(["selftest"]) == 0  # 설정 필요는 실패가 아니다
    out = capsys.readouterr().out
    assert "결과: 통과 1 · 설정 필요 1 · 건너뜀 1 · 실패 0" in out and "jaix doctor: 실패 1건" in out
    assert "PC 밖에서 직접 확인할 것" in out and "소모임 채널" not in out and seen["agent"] is False
    assert cli.main(["selftest", "--json", "--agent"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"] == {"ok": 1, "setup": 1, "skip": 1, "fail": 0} and data["doctor_failed"] == 1
    assert seen["agent"] is True
    monkeypatch.setattr(selftest, "run_all", lambda lock, **kw: [selftest._fail("D", "안 됨", "jaix setup")])
    assert cli.main(["selftest"]) == 1
    assert "이 결과 전체를 소모임 채널에 올려 주세요" in capsys.readouterr().out


def test_run_all_survives_crash(the_lock, monkeypatch):
    monkeypatch.setattr(selftest, "get_sample", lambda download=None: None)
    monkeypatch.setattr(selftest, "check_mcp", lambda lock, work: 1 / 0)
    monkeypatch.setattr(selftest, "check_gw", lambda: [])
    res = selftest.run_all(the_lock, log=lambda m: None)
    assert any(r.area == "MCP 서버" and r.status == "fail" and "ZeroDivisionError" in r.message for r in res)
