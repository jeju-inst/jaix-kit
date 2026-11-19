"""jaix report 와 가림(redact). 진짜 doctor·hermes·네트워크는 부르지 않는다 — 결과를 넘기거나 흉내 낸다."""
import json
from pathlib import Path

import pytest

from jaix import cli, connect, doctor, hermesbot, report, schedule
from jaix.redact import redact

LOCK_FILE = Path(__file__).resolve().parents[1] / ".claude-plugin" / "marketplace.json"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "JAIX_DATA", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("JAIX_LOCK", str(LOCK_FILE))
    monkeypatch.setattr(hermesbot, "find_hermes", lambda: None)
    monkeypatch.setattr(doctor, "run", lambda lock: [doctor.Check("ok", "uv", "0.11")])
    monkeypatch.setattr(connect, "statuses", lambda lock: [connect.Status("mail", "missing", "앱 비밀번호 설정 안 됨")])
    return tmp_path


# --- 가림 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,gone,kept", [
    ("SLACK_BOT_TOKEN=xoxb-TEST-5678-abcDEF", ["xoxb-TEST", "abcDEF"], ["SLACK_BOT_TOKEN"]),
    ("app xapp-TEST-A0B1-999-zzz9", ["A0B1-999"], ["xapp-***"]),
    ("user xoxp-TEST-22-33-aa user", ["xoxp-TEST"], ["xoxp-***"]),
    ("key sk-proj-AbCdEf1234567890xyz", ["AbCdEf123"], ["sk-***"]),
    ("gh ghp_ABCDEFGHIJKLMNOPQRSTuvwx1234", ["ABCDEFGHIJ"], ["ghp_***"]),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig", ["eyJhbGci"], []),
    ('{"api_key": "plainvalue1"}', ["plainvalue1"], ['"api_key": "***"']),
    ("password=hunter22", ["hunter22"], ["password=***"]),
    ('password="my secret value" next', ["my", "secret", "value"], ['password="***" next']),  # 따옴표 값은 통째로(Codex #189)
    ("pw: password='correct horse battery staple'", ["horse", "battery", "staple"], ["password='***'"]),
    ('password="ab"', ['"ab"'], ['password="***"']),  # 짧아도
    ('password="*Secret123!"', ["Secret123"], ['password="***"']),  # 자리표시처럼 시작해도 진짜 값(Codex #189)
    ("password=%Secret123!", ["Secret123"], ["password=***"]),
    ("password=<Secret1", ["Secret1"], ["password=***"]),
    (r"password=ab\cd ef", [r"ab\cd"], ["password=*** ef"]),
    ('{"error": "{\\"password\\": \\"hunter22\\"}"}', ["hunter22"], ['\\"***\\"']),  # JSON 안의 \"

    ('api_key="a\\"b c" z', ['b c'], ['api_key="***" z']),  # 이스케이프된 따옴표를 넘어서

    ("Authorization: Bearer abc.def-ghi12345", ["abc.def-ghi12345"], ["Bearer ***"]),
    ("rand Zq9xT2vL8mN4pR7sK1wY6uH3jB5cF0dG", ["Zq9xT2v"], ["rand ***"]),
    (r"C:\Users\홍길동\AppData\Local\jaix", ["홍길동"], [r"%USERPROFILE%\AppData\Local\jaix"]),
    (r'"C:\\Users\\kimcs\\x.json"', ["kimcs"], [r'"%USERPROFILE%\\x.json"']),
    ("c:/users/Lee/hermes", ["Lee"], ["%USERPROFILE%/hermes"]),
    ("/home/someone/.hermes", ["someone"], ["~/.hermes"]),
    ("from U01ABCDEF23 in D0123456789 and C0ABCDEFG1", ["U01ABCDEF23", "D0123456789", "C0ABCDEFG1"], ["U***", "D***", "C***"]),
    ("mail hong.gildong@ji.re.kr", ["hong.gildong"], ["***@ji.re.kr"]),
])
def test_redact_hides_secrets_and_identities(raw, gone, kept):
    out = redact(raw)
    for g in gone:
        assert g not in out, out
    for k in kept:
        assert k in out, out
    assert redact(out) == out  # 여러 번 해도 같다


@pytest.mark.parametrize("text", [
    "commit 7df2086ad3a3464b3751eb52917d591ab16d85c7",  # git 커밋은 판을 가리킨다
    "jaix 2026.11.19.2 · Hermes 0.21.5+4879.gdeedcd6",
    "hermes.exe config set mcp_servers.korea-rio → 코드 1",
    "[실패] Hermes 슬랙: Hermes 설정 실패(모델·도구·MCP)",
    "CONNECTED READY STATUS DEFAULT",
    "token expired — 다시 로그인",  # 토큰이라는 말만 있고 값이 없다
    "C:\\Program Files\\jaix\\jaix.exe",
    "password=%SLACK_PASSWORD% · token=<값> · password=***",  # 완전한 자리표시·가림 표시
])
def test_redact_keeps_what_diagnosis_needs(text):
    assert redact(text) == text


def test_redact_user_home(monkeypatch, tmp_path):
    home = tmp_path / "people" / "somebody"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert "somebody" not in redact(f"log at {home}/x.log")


# --- 기록의 실패 주변 ---------------------------------------------------------------------------------
def test_failure_lines_keeps_context_and_gaps():
    lines = [f"줄{i}" for i in range(30)]
    lines[5] = "    hermes.exe config set mcp_servers.korea-rio → 코드 1"
    lines[20] = "멈춤: ValueError: 깨진 settings.json"
    out = report.failure_lines("\n".join(lines), context=1)
    assert out == ["줄4", lines[5], "줄6", "…", "줄19", lines[20], "줄21"]


def test_failure_lines_limits_to_recent():
    text = "\n".join(f"실패 {i}" for i in range(500))
    out = report.failure_lines(text, limit=10)
    assert out[0] == "…(앞부분 줄임)" and out[-1] == "실패 499" and len(out) == 11


def test_failure_lines_none():
    assert report.failure_lines("모두 정상\n끝") == []


# --- 보고 전체 ----------------------------------------------------------------------------------------
def _seed(isolated):
    data = isolated / "jaix_data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "setup.log").write_text("시작\n    hermes.exe config set mcp_servers.korea-rio → 코드 1\n"
                                    "Error: xoxb-TEST-9-secretXYZ at C:\\Users\\홍길동\\x\n끝\n", encoding="utf-8")
    hermesbot._save_record({"status": "failed", "error": "Hermes 설정 실패(모델·도구·MCP)",
                            "error_detail": [{"key": "mcp_servers.korea-rio", "cmd": "hermes config set mcp_servers.korea-rio",
                                              "code": 1, "tail": "yaml.scanner.ScannerError"}]})
    schedule.status_file().write_text(json.dumps({"ok": False, "problems": ["Hermes 소음 정리 실패: skills.disabled"]}),
                                      encoding="utf-8")


def test_report_collects_everything_and_redacts(isolated, monkeypatch, capsys):
    _seed(isolated)
    lines = []
    args = cli.build_parser().parse_args(["report", "--offline"])
    assert args.func(args, lines.append) == 0
    out = "\n".join(lines)
    saved = list((isolated / "jaix_data").glob("report-*.txt"))
    assert len(saved) == 1
    text = saved[0].read_text(encoding="utf-8")
    for part in ("== 판 ==", "jaix ", "잠금:", "== jaix doctor --json ==", '"area": "uv"', "== Hermes 기록 ==",
                 "키 mcp_servers.korea-rio", "ScannerError", "== 연결 상태 ==", "[연결 필요] 회사메일",
                 "skills.disabled", "== setup.log 실패 주변", "→ 코드 1", "== update.log 실패 주변", "(없음)"):
        assert part in text, part
    assert "secretXYZ" not in text and "홍길동" not in text and "xoxb-***" in text
    assert text.rstrip() in out and "저장:" in out and "요약하지 말고" in out


def test_report_redacts_inside_json_sections(isolated):
    """doctor JSON·update-status 는 직렬화 전에 가린다 — 직렬화하면 따옴표가 \\" 가 되어 놓칠 수 있다(Codex #189)."""
    isolated.joinpath("jaix_data").mkdir(parents=True, exist_ok=True)
    schedule.status_file().write_text(json.dumps({"ok": False, "error": '{"password": "hunter22"}'}), encoding="utf-8")
    checks = [doctor.Check("fail", "x", 'auth failed: {"api_key": "sekret99"}', detail=['token="a b c"'])]
    text = redact(report.build(type("L", (), {"source": "s", "plugins": []})(), checks=checks, statuses=[],
                               hermes_version="없음"))
    assert "hunter22" not in text and "sekret99" not in text and '"a b c' not in text


def test_report_survives_broken_parts(isolated, monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda lock: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(connect, "statuses", lambda lock: (_ for _ in ()).throw(OSError("x")))
    lines = []
    args = cli.build_parser().parse_args(["report", "--offline"])
    assert args.func(args, lines.append) == 0
    text = "\n".join(lines)
    assert "doctor 를 돌리지 못함: RuntimeError" in text and "연결 상태" in text and "확인 오류: OSError" in text


def test_report_without_lock(isolated):
    lines = []
    args = cli.build_parser().parse_args(["report", "--offline"])
    assert report.cmd_report(args, lines.append, lock_loader=lambda *a: (_ for _ in ()).throw(FileNotFoundError("x"))) == 0
    assert "잠금 못 읽음(FileNotFoundError)" in "\n".join(lines)
