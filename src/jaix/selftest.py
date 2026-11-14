"""jaix selftest: 도구를 실제로 한 번씩 돌려 본다(doctor 는 깔렸는지·설정이 맞는지까지만 본다).

베타 연구원이 명령 하나로 결과를 받아 소모임 채널에 붙여 넣게 하는 것이 목적이다. 각 줄은
[통과] · [설정 필요] <무엇> — <하는 법> · [건너뜀] <이유> · [실패] <이유> — <고치는 법>.

- 사용자가 직접 해야 하는 첫 설정(로그인·앱 비밀번호 등)은 실패가 아니라 [설정 필요]로 따로 센다.
  자격 증명은 값을 읽지 않고 "있음/없음"만 본다. 로그인을 대신 시도하거나 입력 창을 띄우지 않는다
  (입력 창은 jaix connect 가 연다 — [설정 필요] 줄이 그쪽을 가리킨다).
- 그룹웨어는 로그인 없이 닿는지만 보고, 주소는 출력하지 않는다(원내 주소).
- 슬랙 메시지는 보내지 않는다. Hermes 는 gateway 가 스스로 적는 상태 파일(gateway_state.json)만 읽는다.
- --agent 만 사용자의 Claude 사용량을 쓴다(기본 꺼짐).
"""
import json
import os
import queue
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from jaix import __version__, claude, codex, doctor, gw, hancom, hermesbot, net, paths, proc, remotemcp, runtimes, winenv, works
from jaix.paths import IS_MAC, IS_WIN

MARK = {"ok": "[통과]", "setup": "[설정 필요]", "skip": "[건너뜀]", "fail": "[실패]", "info": "[안내]"}
WORD = {"ok": "통과", "setup": "설정 필요", "skip": "건너뜀", "fail": "실패"}

# 시험용 HWP: hwp2pdf 저장소에 올라 있는 공개 간행물(제주발전연구원 『동북아시아 공동 평화와 번영』, 2002) 한 벌.
# hwp-agent 의 tests/fixtures/sample_hwp.hwp 는 저장소에 올라 있지 않다(.gitignore). 900KB 라 jaix 에 묶지 않고,
# 커밋을 고정해 받은 뒤 sha256 을 맞춰 보고 데이터 폴더에 둔다(두 번째부터는 받지 않음)
SAMPLE_URL = ("https://raw.githubusercontent.com/z0nam/hwp2pdf/00a59212f9c237ef743625736ffe5150179f7594/"
              "docs/fixtures/docx-failure-repro.hwp")
SAMPLE_SHA256 = "d32342ab74762448e52864843a857982c4182d91b9275c9673204ba74fc5c459"
SAMPLE_WORD = "평화"  # 추출한 본문에 있어야 할 낱말

HWP_PLUGIN = "hwp-agent"
MAIL_PLUGIN = "mail-skill"
MAIL_ACCOUNT = "ji"
GW_KEYRING = "ji-gw-ai"            # ji_gw_ai.core.credentials.SERVICE
GW_USER_ENTRY = "__gw_user__"      # 같은 파일의 _USER_ENTRY(아이디를 담는 항목)
HERMES_STALE = 300                 # gateway 는 60초마다 상태 파일을 다시 찍는다. 5분 넘게 묵었으면 멈춘 것
FIRST_RUN_TIMEOUT = 300            # uvx 첫 실행은 패키지를 받느라 오래 걸린다
MCP_TIMEOUT = 180
AGENT_TIMEOUT = 300
# [설정 필요] 줄의 "하는 법". 본인 비밀을 넣는 창은 jaix connect 가 연다(connect.py)
CONNECT_HINT = "시작 메뉴 'JAIX 계정 연결' (또는 jaix connect {item})"


@dataclass
class Result:
    status: str  # ok · setup · skip · fail
    area: str
    message: str = ""
    fix: str = ""


def _ok(area, msg=""):
    return Result("ok", area, msg)


def _skip(area, why):
    return Result("skip", area, why)


def _fail(area, why, fix=""):
    return Result("fail", area, why, fix)


def _setup(area, what, how):
    return Result("setup", area, what, how)


def _tail(text, n=1, width=200):
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    return " / ".join(lines[-n:])[:width]


def _why(text, width=300):
    """실패 출력의 요지: 예외 이름이 든 첫 줄(자바 stack trace 의 원인) + 마지막 줄."""
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    cause = next((ln for ln in lines if re.search(r"(Exception|Error)\b", ln) and not ln.startswith("at ")), None)
    picked = [cause] if cause and cause != (lines[-1] if lines else None) else []
    return " / ".join(picked + lines[-1:])[:width]


# --- 공통: 시험 폴더·샘플 ------------------------------------------------------------------------------
def sample_cache():
    return paths.data_dir() / "selftest" / "sample.hwp"


def _sha256(path):
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def get_sample(download=None):
    """시험용 HWP 경로. 없으면 받아 sha256 을 맞춰 본다. 못 받으면 None."""
    dest = sample_cache()
    if dest.is_file() and _sha256(dest) == SAMPLE_SHA256:
        return dest
    try:
        (download or net.download)(SAMPLE_URL, dest)
    except Exception:  # noqa: BLE001 — 인터넷이 막힌 PC: HWP 시험만 건너뛴다
        return None
    if _sha256(dest) != SAMPLE_SHA256:
        dest.unlink(missing_ok=True)
        return None
    return dest


# 시험 폴더·파일 이름. 한글 이름은 Windows 의 ANSI 코드 페이지가 한글을 담을 때만 쓴다 — 자바(hwp2hwpx)는 명령줄 인자를
# ANSI 코드 페이지로 읽어, 영문 Windows(cp1252, CI 러너)에서는 한글이 '?' 로 깨져 변환이 실패한다(실측 2026-11-06).
# 연구원 PC(한국어 Windows, cp949)는 한글 경로를 그대로 시험한다
KO_NAMES = {"dir": "jaix 시험", "hwp": "공문.hwp", "hwpx": "변환 결과.hwpx", "md": "추출.md", "agent": "에이전트 시험"}
EN_NAMES = {"dir": "jaix test", "hwp": "sample doc.hwp", "hwpx": "converted doc.hwpx", "md": "extracted.md",
            "agent": "agent test"}


def korean_path_ok():
    """한글 경로를 자바 등 ANSI 프로그램에 넘겨도 깨지지 않는 PC 인가(맥·리눅스는 늘 그렇다)."""
    if not IS_WIN:
        return True
    import ctypes

    try:
        acp = ctypes.windll.kernel32.GetACP()
    except (AttributeError, OSError):
        return True
    if acp == 65001:  # 'UTF-8 사용' 베타 옵션
        return True
    try:
        "".join(KO_NAMES.values()).encode(f"cp{acp}")
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def names():
    return KO_NAMES if korean_path_ok() else EN_NAMES


def make_workdir():
    """띄어쓰기(가능하면 한글도)가 든 경로 — 실제 연구원 폴더(바탕 화면 등)에서 깨지는 일을 잡으려고."""
    base = Path(tempfile.mkdtemp(prefix="jaix-selftest-"))
    work = base / names()["dir"]
    work.mkdir()
    return base, work


# --- 플러그인 위치·MCP 명령 ----------------------------------------------------------------------------
def plugin_root(name):
    """Claude 가 깐 플러그인 폴더(installed_plugins.json 의 installPath), 없으면 Codex 사본."""
    rec = claude.installed().get(f"{name}@{claude.MARKETPLACE}") or {}
    p = rec.get("installPath")
    if p and Path(p).is_dir():
        return Path(p)
    return codex.plugin_root(name)


def _subst(value, root):
    return codex._subst(value, root)


def resolve_command(cmd):
    """Claude 가 MCP 서버를 띄울 때처럼 PATH 에서 찾는다. uvx 는 PATH 에 없어도 jaix 가 찾은 uv 옆을 본다."""
    found = paths.which(cmd)
    if found:
        return found
    if Path(cmd).stem.lower() == "uvx":
        uv = runtimes.find(runtimes.BY_KEY["uv"]).path
        if uv:
            cand = Path(uv).with_name("uvx.exe" if IS_WIN else "uvx")
            if cand.is_file():
                return str(cand)
    return None


def mcp_specs(lock):
    """잠금 플러그인의 stdio MCP 서버 {서버 이름: (플러그인, command, args, env, root)}."""
    out = {}
    for p in lock.plugins:
        root = plugin_root(p.name)
        if not root:
            continue
        try:
            servers = json.loads((root / ".mcp.json").read_text(encoding="utf-8")).get("mcpServers") or {}
        except (OSError, ValueError):
            continue
        for name, spec in servers.items():
            if "command" not in spec:  # http 서버 등
                continue
            env = {k: str(v) for k, v in _subst(dict(spec.get("env") or {}), root).items()}
            out[name] = (p.name, spec["command"], [str(a) for a in _subst(list(spec.get("args") or []), root)], env, root)
    return out


def _env(extra=None, root=None):
    env = dict(os.environ)
    if root:
        env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env.update(extra or {})
    return env


def run(cmd, timeout, cwd=None, env=None):
    """(종료 코드, 출력). 실행 자체가 안 되면 (None, 이유)."""
    try:
        r = subprocess.run(proc.command(cmd[0], cmd[1:]), capture_output=True, cwd=cwd, env=env, timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=paths.NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None, f"{timeout}초 안에 끝나지 않음"
    except OSError as e:
        return None, f"실행 못 함({type(e).__name__})"
    return r.returncode, proc.decode(r.stdout) + proc.decode(r.stderr)


# --- 1. HWP 변환·추출 ----------------------------------------------------------------------------------
def hwp_agent_command(lock):
    """플러그인이 쓰는 그대로 `uvx --python 3.12 --from <플러그인> hwp-agent`. 플러그인이 없으면 PATH 의 hwp-agent."""
    spec = next((s for s in mcp_specs(lock).values() if s[0] == HWP_PLUGIN), None)
    if spec:
        _, command, args, env, root = spec
        exe = resolve_command(command)
        if exe and "--from" in args:
            # 서버 실행 인자에서 끝의 "hwp-agent mcp" 만 떼고 CLI 하위 명령을 붙인다
            pre = args[:args.index("hwp-agent")] if "hwp-agent" in args else args
            return [exe, *pre, "hwp-agent"], _env(env, root)
    exe = paths.which("hwp-agent")
    return ([exe], _env()) if exe else (None, None)


def valid_hwpx(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False
    return any(re.match(r"Contents/section\d+\.xml$", n) for n in names)


def check_hwp(lock, work, sample, runner=run):
    area_c, area_e = "HWP → HWPX 변환", "HWPX 본문 추출"
    if not any(p.name == HWP_PLUGIN for p in lock.plugins):
        return [_skip(area_c, "잠금에 hwp-agent 없음")], None
    if not sample:
        return [_skip(area_c, "시험용 HWP 를 받지 못함(인터넷 연결 확인)")], None
    cmd, env = hwp_agent_command(lock)
    if not cmd:
        return [_fail(area_c, "hwp-agent 플러그인을 찾지 못함", "jaix setup")], None
    n = names()
    src = work / n["hwp"]
    shutil.copyfile(sample, src)
    out = work / n["hwpx"]
    code, text = runner([*cmd, "convert", str(src), str(out)], FIRST_RUN_TIMEOUT, cwd=str(work), env=env)
    if code != 0 or not out.is_file():
        why = text if code is None else _why(text)
        if "Java(JRE)" in (text or "") or "변환기 jar" in (text or ""):
            return [_fail(area_c, f"변환 실패: {why}", "새 명령창에서 다시 실행(그래도 같으면 jaix setup)")], None
        # 영문 경로에서는 되는지 — 되면 한글·띄어쓰기 경로 문제다(연구원 폴더는 대개 한글이라 따로 알린다)
        plain = work.parent / "plain"
        plain.mkdir(exist_ok=True)
        shutil.copyfile(sample, plain / "sample.hwp")
        code2, _ = runner([*cmd, "convert", str(plain / "sample.hwp"), str(plain / "sample.hwpx")], FIRST_RUN_TIMEOUT,
                          cwd=str(plain), env=env)
        if code2 == 0 and valid_hwpx(plain / "sample.hwpx"):
            return [_fail(area_c, f"한글·띄어쓰기가 든 경로에서만 실패(영문 경로는 됨): {why}",
                          "당분간 영문 이름 폴더에서 변환하고, 이 결과를 소모임 채널에 올려 주세요")], None
        return [_fail(area_c, f"변환 실패: {why}", "jaix setup 뒤 다시 시험, 그래도 같으면 이 결과를 소모임 채널에")], None
    if not valid_hwpx(out):
        return [_fail(area_c, "만든 .hwpx 가 올바른 문서 묶음이 아님", "이 결과를 소모임 채널에 올려 주세요")], None
    where = ("한글·띄어쓰기 경로에서" if n is KO_NAMES
             else "띄어쓰기 경로에서(이 PC 의 문자 코드가 한글을 담지 못해 한글 경로는 시험 안 함)")
    res = [_ok(area_c, f"{where} 변환됨 ({out.stat().st_size // 1024}KB)")]
    md = work / n["md"]
    code, text = runner([*cmd, "extract", str(out), "-o", str(md)], FIRST_RUN_TIMEOUT, cwd=str(work), env=env)
    body = md.read_text(encoding="utf-8", errors="replace") if md.is_file() else ""
    if code != 0 or SAMPLE_WORD not in body:
        why = text if code is None else (_why(text) or "본문이 비어 있음")
        res.append(_fail(area_e, f"추출 실패: {why}", "이 결과를 소모임 채널에 올려 주세요"))
    else:
        res.append(_ok(area_e, f"{len(body):,}자"))
    return res, src


# --- 2. HWP → PDF (한컴) -------------------------------------------------------------------------------
def hwp2pdf_exe():
    env = os.environ.get("HWP2PDF_CLI") or (winenv.get_user_env("HWP2PDF_CLI") if IS_WIN else None)
    if env and Path(env).is_file():
        return env
    return runtimes.find(runtimes.BY_KEY["hwp2pdf"]).path


def check_pdf(src, runner=run):
    area = "HWP → PDF (한컴)"
    if not hancom.present():
        return [_skip(area, "한컴오피스 없음")]
    consent = doctor.check_hancom_consent()
    if any(c.status == "warn" for c in consent):
        return [_setup(hancom.AREA, "한컴 첫 실행 동의 창에 아직 답하지 않음",
                       "한글을 한 번 직접 열어 동의 창에 답하기(또는 jaix setup)"),
                _skip(area, "동의 창에 먼저 답해야 시험할 수 있음")]
    if not src:
        return [_skip(area, "시험용 HWP 없음(위 변환 항목 참고)")]
    exe = hwp2pdf_exe()
    if not exe:
        return [_fail(area, "hwp2pdf-cli 없음", "jaix setup")]
    pdf = src.with_suffix(".pdf")
    code, text = runner([exe, str(src), "--pdf"], FIRST_RUN_TIMEOUT, cwd=str(src.parent),
                        env=_env({"HWP2PDF_LOCAL": "1"}))
    try:
        head = pdf.read_bytes()[:5] if pdf.is_file() else b""
    except OSError:
        head = b""
    if head.startswith(b"%PDF"):
        return [_ok(area, f"PDF 만들어짐 ({pdf.stat().st_size // 1024}KB)")]
    why = text if code is None else (_tail(text, 2) or f"종료 코드 {code}")
    return [_fail(area, f"PDF 를 만들지 못함: {why}", "한글 창을 모두 닫고 다시 시험, 그래도 같으면 이 결과를 소모임 채널에")]


# --- 3. MCP 서버 ---------------------------------------------------------------------------------------
def mcp_handshake(cmd, env, cwd, timeout=MCP_TIMEOUT):
    """stdio 로 initialize → tools/list. (도구 이름 목록, None) 또는 (None, 이유)."""
    err = tempfile.TemporaryFile()
    try:
        p = subprocess.Popen(proc.command(cmd[0], cmd[1:]), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                             cwd=cwd, env=env, creationflags=paths.NO_WINDOW)
    except OSError as e:
        err.close()
        return None, f"실행 못 함({type(e).__name__})"
    lines = queue.Queue()

    def reader():
        for raw in p.stdout:
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()

    def send(msg):
        p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        p.stdin.flush()

    def wait_for(mid, until):
        while True:
            left = until - time.monotonic()
            if left <= 0:
                return None, "응답 없음(시간 초과)"
            try:
                raw = lines.get(timeout=left)
            except queue.Empty:
                return None, "응답 없음(시간 초과)"
            if raw is None:
                return None, "서버가 바로 끝남"
            try:
                msg = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue  # 서버가 표준 출력에 찍은 다른 줄
            if isinstance(msg, dict) and msg.get("id") == mid:
                if "error" in msg:
                    return None, f"오류 응답: {str(msg['error'].get('message'))[:120]}"
                return msg.get("result") or {}, None

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "jaix-selftest", "version": __version__}}})
        _, why = wait_for(1, time.monotonic() + timeout)
        if why:
            return None, why
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        res, why = wait_for(2, time.monotonic() + 60)
        if why:
            return None, why
        return [t.get("name") for t in res.get("tools") or []], None
    except OSError:
        return None, "서버가 입력을 받지 않음"
    finally:
        _stop(p)
        try:
            err.seek(0)
            tail = _tail(proc.decode(err.read()), 1)
        except OSError:
            tail = ""
        err.close()
        mcp_handshake.last_stderr = tail


mcp_handshake.last_stderr = ""


def _stop(p):
    try:
        p.stdin.close()
    except OSError:
        pass
    try:
        p.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    if IS_WIN:  # uvx 가 띄운 python 까지(트리째) 닫는다
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=paths.NO_WINDOW)
    else:
        p.kill()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def check_mcp(lock, work, handshake=None):
    handshake = handshake or mcp_handshake
    specs = mcp_specs(lock)
    if not specs:
        installed = any(plugin_root(p.name) for p in lock.plugins)
        if not installed:
            return [_fail("MCP 서버", "jaix 플러그인이 아직 깔리지 않음", "jaix setup")]
        return [_skip("MCP 서버", "MCP 서버를 쓰는 플러그인 없음")]
    out = []
    for name, (plugin, command, args, env, root) in sorted(specs.items()):
        area = f"MCP {name}"
        exe = resolve_command(command)
        if not exe:
            out.append(_fail(area, f"{command} 를 찾지 못함", "jaix setup 뒤 새 명령창에서 다시"))
            continue
        tools, why = handshake([exe, *args], _env(env, root), str(work))
        if why:
            hint = getattr(mcp_handshake, "last_stderr", "") if handshake is mcp_handshake else ""
            out.append(_fail(area, f"{why}{' — ' + hint if hint else ''}",
                             "jaix setup 뒤 다시 시험, 그래도 같으면 이 결과를 소모임 채널에"))
        elif not tools:
            out.append(_fail(area, "도구 0개", "이 결과를 소모임 채널에 올려 주세요"))
        else:
            out.append(_ok(area, f"도구 {len(tools)}개"))
    return out


def check_remote_mcp(lock, probe=None):
    """원격(HTTP) MCP: 등록 여부와 접속을 따로 본다. 접속은 initialize·tools/list 만 — 도구는 부르지 않는다."""
    probe = probe or remotemcp.probe
    out = []
    for name, st in sorted(doctor.remote_mcp_state(lock).items()):
        area = f"원격 MCP {name}"
        if not st["registered"] or st["missing"]:
            where = ", ".join(st["missing"]) or "Claude·Codex·Hermes 어디에도"
            out.append(_fail(area, f"등록 안 됨: {where}", "jaix update"))
            if not st["registered"]:
                continue
        tools, why = probe(st["url"])
        if why:
            out.append(_fail(area, f"접속 실패: {why}",
                             "인터넷 연결 확인 — 다른 사이트는 되는데 계속 실패하면 이 결과를 AI센터에(서버 쪽 문제)"))
        elif not tools:
            out.append(_fail(area, "접속은 되나 도구 0개", "이 결과를 AI센터에 보내 주세요"))
        else:
            out.append(_ok(area, f"접속됨 · 도구 {len(tools)}개 ({', '.join(st['registered'])})"))
    return out


# --- 4. 그룹웨어 ---------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None  # 3xx 도 "닿았다"로 본다(따라가지 않음)


def gw_reachable(url, timeout=5):
    """로그인 없이 첫 화면에 닿는가. 어떤 HTTP 응답이든(4xx·3xx 포함) 닿은 것이다."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, method="GET"), timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except urllib.error.URLError as e:
        return isinstance(e.reason, ssl.SSLError)  # 인증서 문제여도 서버에는 닿았다
    except (OSError, ValueError):
        return False


def gw_login_saved(runner=run):
    """`gw login` 이 자격 증명 저장소에 남긴 항목이 있는가. 값은 꺼내지 않는다. 모르면 None."""
    if os.environ.get("GW_USER") and os.environ.get("GW_PW"):
        return True
    if IS_WIN:
        return _win_cred_exists(GW_KEYRING)
    if IS_MAC:
        # -w·-g 없이 찾으면 항목 속성만 보고 비밀번호는 꺼내지 않는다(키체인 허용 창도 뜨지 않음)
        code, _ = runner(["security", "find-generic-password", "-s", GW_KEYRING, "-a", GW_USER_ENTRY], 15)
        return None if code is None else code == 0
    return None


def _win_cred_exists(prefix):
    """Windows 자격 증명 관리자에 대상 이름이 prefix 로 시작하는 항목이 있는가(keyring 의 대상 이름은 서비스 이름
    또는 '아이디@서비스'). 목록만 세고 항목의 내용은 보지 않는다."""
    import ctypes
    from ctypes import wintypes

    count, creds = wintypes.DWORD(), ctypes.c_void_p()
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                   ctypes.POINTER(ctypes.c_void_p)]
    adv.CredEnumerateW.restype = wintypes.BOOL
    ok = adv.CredEnumerateW(f"{prefix}*", 0, ctypes.byref(count), ctypes.byref(creds))
    if ok:
        adv.CredFree(creds)
        return count.value > 0
    return False if ctypes.get_last_error() == 1168 else None  # 1168 = ERROR_NOT_FOUND


def check_gw(reachable=None, saved=None):
    area = "그룹웨어"
    if not gw.source():
        return [_skip(area, "끔 (--gw-source none)")]
    url = gw.base_url()
    if not url:
        return [_skip(area, "원내망 아님(그룹웨어 주소를 아직 받지 않음)")]
    if not (reachable or gw_reachable)(url):
        return [_skip(area, "원내망 아님")]
    out = [_ok(area, "그룹웨어 접속됨")]
    if not (gw.installed_version() or paths.which(gw.EXE)):
        out.append(_skip("그룹웨어 로그인", "gw 가 설치되지 않음(jaix doctor 참고)"))
        return out
    have = (saved or gw_login_saved)()
    if have:
        out.append(_ok("그룹웨어 로그인", "저장된 로그인 정보 있음"))
    elif have is None:
        out.append(_skip("그룹웨어 로그인", "이 PC 에서는 저장 여부를 확인하지 못함"))
    else:
        out.append(_setup("그룹웨어 로그인", "저장된 로그인 정보 없음", CONNECT_HINT.format(item="gw")))
    return out


# --- 메일 · 웍스 (첫 설정) -----------------------------------------------------------------------------
def mail_config_paths():
    home = Path.home()
    conf = Path(os.environ["HIMALAYA_CONFIG"]) if os.environ.get("HIMALAYA_CONFIG") else \
        home / ".config" / "himalaya" / "config.toml"
    secrets = Path(os.environ["MAIL_SKILL_SECRETS"]) if os.environ.get("MAIL_SKILL_SECRETS") else \
        home / ".config" / "mail-skill" / "secrets.age"
    return conf, secrets


def check_mail(lock):
    """`mailskill doctor` 는 메일 서버에 실제로 로그인하고, 설정이 없으면 himalaya 가 대화형 마법사를 띄운다 →
    부르지 않고 `mailskill setup` 이 만드는 두 파일(계정 설정·암호화한 앱 비밀번호)이 있는지만 본다."""
    area = "회사메일"
    if not any(p.name == MAIL_PLUGIN for p in lock.plugins):
        return []
    conf, secrets = mail_config_paths()
    try:
        accounts = tomllib.loads(conf.read_text(encoding="utf-8")).get("accounts") or {}
    except (OSError, ValueError):
        accounts = {}
    if MAIL_ACCOUNT in accounts and secrets.is_file():
        return [_ok(area, "앱 비밀번호 설정 있음(로그인 시험은 안 함)")]
    return [_setup(area, "회사메일 앱 비밀번호 설정 안 됨", CONNECT_HINT.format(item="mail"))]


def check_works(lock):
    if not works.plugin(lock):
        return []
    if works.logged_in():
        return [_ok("웍스", "로그인돼 있음")]
    return [_setup("웍스", "아직 로그인 안 함", CONNECT_HINT.format(item="works"))]


# --- 5. Hermes ----------------------------------------------------------------------------------------
def _age(stamp):
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        try:
            t = datetime.fromtimestamp(float(stamp), timezone.utc)
        except (TypeError, ValueError):
            return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds()


def check_hermes(credentials=None):
    rec = hermesbot.recorded()
    if not rec.get("status"):
        return [_skip("Hermes 슬랙", "고르지 않음")]
    area = "Hermes 슬랙"
    if rec["status"] == "failed":
        return [_fail(area, "설치가 실패한 채로 남아 있음", "jaix doctor 결과를 소모임 채널에")]
    hermes = hermesbot.find_hermes()
    if not hermes:
        return [_fail(area, "hermes 실행 파일이 없음", "jaix setup --channels hermes")]
    out = []
    if rec["status"] == "no-code" and not hermesbot.linked_id(rec):
        out.append(_setup(area, "슬랙 연결 코드 없음", "AI센터에서 연결 코드를 받아 jaix-setup 다시"))
    else:
        out.append(_gateway())
    model = rec.get("model") or "chatgpt"
    provider = hermesbot.PROVIDERS.get(model, hermesbot.PROVIDERS["chatgpt"])["provider"]
    rows = (credentials or hermesbot.credentials)(hermes, provider)  # `hermes auth list` — 이름만, 값은 안 봄
    if rows is None:
        out.append(_skip("Hermes AI 구독 로그인", "로그인 목록을 읽지 못함"))
    elif rows:
        out.append(_ok("Hermes AI 구독 로그인", f"{model} 로그인돼 있음"))
    else:
        out.append(_setup("Hermes AI 구독 로그인", f"{model} 에 아직 로그인 안 함", CONNECT_HINT.format(item="hermes")))
    return out


def _gateway():
    """gateway 가 60초마다 다시 쓰는 상태 파일로 판단한다(토큰을 읽지 않고, 슬랙에 아무것도 보내지 않음)."""
    area = "Hermes 슬랙"
    fix = "PC 에서 로그아웃했다 다시 로그인(또는 명령창에서 hermes gateway start)"
    try:
        st = json.loads((paths.hermes_home() / "gateway_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _fail(area, "봇(gateway)이 한 번도 뜨지 않음", fix)
    age = _age(st.get("updated_at"))
    if st.get("gateway_state") not in ("running", "draining", "degraded") or age is None or age > HERMES_STALE:
        return _fail(area, f"봇(gateway)이 돌고 있지 않음 ({st.get('gateway_state') or '상태 모름'})", fix)
    slack = (st.get("platforms") or {}).get("slack") or {}
    if slack.get("state") != "connected":
        code = f", {slack['error_code']}" if slack.get("error_code") else ""
        return _fail(area, f"봇은 떠 있으나 슬랙 연결 안 됨 ({slack.get('state') or '기록 없음'}{code})",
                     "잠시 뒤 다시 시험, 그래도 같으면 이 결과를 소모임 채널에")
    return _ok(area, "봇이 떠 있고 슬랙에 연결됨")


# --- 6. --agent: Claude 가 실제로 도구를 쓰는지 ---------------------------------------------------------
REPORT_SRC = "관광객이 지난해보다 크게 늘었다. 이에 따라 숙박 수요도 함께 증가할 것으로 보인다."
ALLOWED_TOOLS = "mcp__plugin_hwp-agent_hwp-agent,mcp__hwp-agent,Bash(hwp-agent:*),Bash(uvx:*),Read,Glob"


def _claude_json(cli, prompt, cwd, max_turns, tools=None, runner=run):
    args = ["-p", prompt, "--output-format", "json", "--max-turns", str(max_turns)]
    if tools:
        args += ["--allowedTools", tools]
    code, text = runner([cli, *args], AGENT_TIMEOUT, cwd=str(cwd), env=_env())
    if code is None:
        return None, text
    try:
        data = json.loads(text[text.index("{"):]) if "{" in text else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return None, _tail(text, 2) or f"종료 코드 {code}"
    if data.get("is_error") or code != 0:
        return None, str(data.get("subtype") or data.get("result") or f"종료 코드 {code}")[:200]
    return data, None


def check_agent(work, sample, runner=run):
    cli = claude.find_cli()
    if not cli:
        return [_skip("Claude 에이전트", "claude 명령 없음")]
    out = []
    area = "Claude: HWP 변환 요청"
    if not sample:
        out.append(_skip(area, "시험용 HWP 없음"))
    else:
        n = names()
        d = work / n["agent"]
        d.mkdir(exist_ok=True)
        shutil.copyfile(sample, d / n["hwp"])
        stem = Path(n["hwp"]).stem
        prompt = (f"이 폴더의 '{n['hwp']}' 를 jaix HWP 도구(hwp-agent)로 HWPX 로 변환해 같은 폴더에 '{stem}.hwpx' 로 "
                  "저장해 주세요. 다른 일은 하지 말고, 끝나면 '완료' 한 낱말만 답하세요.")
        _, why = _claude_json(cli, prompt, d, 8, ALLOWED_TOOLS, runner)
        made = [f for f in d.glob("*.hwpx") if valid_hwpx(f)]
        if made:
            out.append(_ok(area, f"Claude 가 도구로 {made[0].name} 를 만듦"))
        else:
            out.append(_fail(area, f"변환 파일이 생기지 않음{': ' + why if why else ''}",
                             "Claude 앱을 완전히 종료했다 다시 열고 재시험, 그래도 같으면 이 결과를 소모임 채널에"))
    area = "Claude: 보고서 톤"
    prompt = ("다음 문단을 제주연구원 보고서 톤(음슴체, 문장 끝 마침표 없음)으로 고쳐 쓰세요. 고친 문단만 출력하세요.\n\n"
              + REPORT_SRC)
    data, why = _claude_json(cli, prompt, work, 3, None, runner)
    text = (data or {}).get("result") or ""
    if why or not text.strip():
        out.append(_fail(area, f"답을 받지 못함: {why or '빈 답'}", "claude 에 로그인돼 있는지 확인(명령창에서 claude)"))
    elif re.search(r"다\.", text):
        out.append(_fail(area, "'~다.' 로 끝나는 문장이 남음", "보고서 작성 표준 도구가 켜졌는지 jaix doctor 로 확인"))
    else:
        out.append(_ok(area, _tail(text, 1, 80)))
    return out


# --- 묶기 ---------------------------------------------------------------------------------------------
OUTSIDE = ["Claude 커넥터(Google·Slack·monday 등): claude.ai → 설정 → 커넥터에서 쓰려는 것이 '연결됨'인지",
           "Cowork(채팅)의 jaix 도구: Claude 앱 Customize → Plugins 에 jaix 도구가 보이는지"]


def run_all(lock, agent=False, keep=False, log=print, download=None):
    """모든 시험을 돌려 Result 목록을 돌려준다. log 는 진행 안내(시험마다 한 줄)용."""
    results = []
    base, work = make_workdir()
    try:
        log("시험용 HWP 준비 …")
        sample = get_sample(download)
        log("HWP 변환·추출 시험 … (처음에는 몇 분 걸릴 수 있음)")
        res, src = _guard("HWP → HWPX 변환", lambda: check_hwp(lock, work, sample), pair=True)
        results += res
        log("HWP → PDF 시험 …")
        results += _guard("HWP → PDF (한컴)", lambda: check_pdf(src))
        log("MCP 서버 시험 …")
        results += _guard("MCP 서버", lambda: check_mcp(lock, work))
        results += _guard("원격 MCP", lambda: check_remote_mcp(lock))
        log("그룹웨어·메일·웍스·Hermes 확인 …")
        results += _guard("그룹웨어", check_gw)
        results += _guard("회사메일", lambda: check_mail(lock))
        results += _guard("웍스", lambda: check_works(lock))
        results += _guard("Hermes 슬랙", check_hermes)
        if agent:
            log("Claude 에이전트 시험 … (본인 Claude 사용량을 조금 씀)")
            results += _guard("Claude 에이전트", lambda: check_agent(work, sample))
    finally:
        if keep:
            log(f"시험 폴더를 남겨 둠: {work}")
        else:
            shutil.rmtree(base, ignore_errors=True)
    return results


def _guard(area, fn, pair=False):
    """시험 하나가 예외로 죽어도 나머지는 돈다."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        res = [_fail(area, f"시험 중 오류: {type(e).__name__}", "이 결과를 소모임 채널에 올려 주세요")]
        return (res, None) if pair else res


def counts(results):
    return {k: sum(1 for r in results if r.status == k) for k in ("ok", "setup", "skip", "fail")}


def summary_line(results):
    c = counts(results)
    return f"결과: {' · '.join(f'{WORD[k]} {c[k]}' for k in ('ok', 'setup', 'skip', 'fail'))} (jaix {__version__})"


def render(results):
    lines = []
    for r in results:
        line = f"{MARK[r.status]} {r.area}" + (f": {r.message}" if r.message else "")
        if r.fix and r.status in ("fail", "setup"):
            line += f" — {r.fix}"
        lines.append(line)
    return "\n".join(lines)


def as_dicts(results):
    return [asdict(r) for r in results]
