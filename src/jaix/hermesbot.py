"""Hermes(슬랙으로도 쓰기) 무인 설치와 슬랙 토큰 1회 전달 — 설계 docs/design-hermes-unattended.md (사용자 승인 2026-10-30).

연구원 PC(Windows):
  1. Hermes가 없으면 공식 install.ps1 을 비대화형으로 돌린다(-NonInteractive -SkipBrowser -SkipComputerUse).
  2. 설정: 모델 공급자(고른 구독), browser·computer_use 도구 끄기, jaix가 Codex에 쓴 MCP 항목만 넣기.
  3. 연결 코드(JX-…)로 원내 배포처에서 사람별 슬랙 토큰을 한 번 받아(받으면 서버에서 지워짐) hermes-slackbot
     setup_pc.py --secrets-file 에 넘긴다. setup_pc 가 .env 백업·기록, gateway 를 UAC 없이 시작프로그램으로 등록,
     slack connected 까지 확인한다. 실패는 설치 실패다(사용자 결정 ③).
관리자(studio): `jaix hermes handoff <id> --user U…` 가 토큰 두 개를 숨김 입력으로 받아 확인한 뒤 배포처 묶음을
  만들고 연결 코드를 출력한다. 토큰·코드는 명령줄·로그에 싣지 않는다.
"""
import base64
import datetime
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from jaix import codex, hermes as skills, net, paths, uvpython
from jaix.paths import IS_WIN

INSTALL_PS1 = "https://hermes-agent.nousresearch.com/install.ps1"
HANDOFF_URL = "https://jaix.namun.net/hermes/handoff"
HANDOFF_SPOOL = "~/.local/share/jaix-handoff/hermes"  # ji-gw-ai share/deploy.toml [handoff] spool 과 같게
TTL_HOURS = 72
CODE_RE = re.compile(r"^JX-[A-Z2-7]{26}$")
# setup_pc.py 를 받는 커밋(z0nam/hermes-slackbot). 바꿀 때는 그 저장소의 시험을 확인하고 올린다
SLACKBOT_REPO = "z0nam/hermes-slackbot"
SLACKBOT_SHA = "c721c7b3a92a34b9289ba800b38dda1d6636023b"
PROVIDERS = {  # 설치기의 구독 선택 → Hermes model 설정. Nous Portal 은 쓰지 않는다
    "chatgpt": {"provider": "openai-codex", "default": "gpt-6.1-sol",
                "base_url": "https://chatgpt.com/backend-api/codex", "login": ["auth", "add", "openai-codex"]},
    "claude": {"provider": "anthropic", "default": "claude-sonnet-5-5",
               "login": ["auth", "add", "anthropic", "--type", "oauth"]},
}
OFF_TOOLSETS = ["browser", "computer_use"]
INSTALL_TIMEOUT = 3600  # 첫 설치 실측 14분·3GB(namun-ji). 느린 망을 넉넉히


class HandoffError(RuntimeError):
    """연결 코드로 토큰을 받지 못함. 메시지는 연구원이 읽는 안내다."""


# --- 관리자: 묶음 만들기 ----------------------------------------------------------------------------
def new_code():
    """JX- + 128비트 난수의 base32 26자."""
    return "JX-" + base64.b32encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")


def code_key(code):
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def slack_call(method, token, timeout=20):
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=b"",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def bot_name_matches(auth, ident):
    return (auth.get("user") or "").lower().replace("_", "-") == f"hermes-{ident}"


def write_bundle(spool, ident, user, bot, app, ttl_hours=TTL_HOURS, code=None):
    """spool/sha256(코드).json 을 0600 으로 만든다(같은 이름이 있으면 실패). (코드, 만료 시각)을 돌려준다."""
    spool = Path(spool).expanduser()
    spool.mkdir(parents=True, exist_ok=True)
    if not IS_WIN:
        os.chmod(spool, 0o700)
    code = code or new_code()
    expires = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=ttl_hours)
    body = json.dumps({"id": ident, "user": user, "bot_token": bot, "app_token": app,
                       "expires_at": expires.isoformat(timespec="seconds")}).encode("utf-8")
    fd = os.open(spool / f"{code_key(code)}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(body)
    return code, expires


def cmd_handoff(args, log):
    """관리자(studio)용. 토큰은 숨김 입력으로만 받는다."""
    ident = args.id.strip().lower()
    if not re.fullmatch(r"[a-z0-9]{1,21}", ident):
        log("아이디는 영문 소문자·숫자 1-21자(앱 Hermes-<아이디>와 같게)")
        return 2
    if not args.user.startswith("U"):
        log("--user 는 U로 시작하는 슬랙 멤버 ID")
        return 2
    bot = getpass.getpass("Bot User OAuth Token (xoxb-…, 입력은 보이지 않음): ").strip()
    app = getpass.getpass("App-Level Token (xapp-…, 입력은 보이지 않음): ").strip()
    if not bot.startswith("xoxb-") or not app.startswith("xapp-"):
        log("토큰 형식이 다름(xoxb- / xapp-)")
        return 2
    auth = slack_call("auth.test", bot)
    if not auth.get("ok"):
        log(f"봇 토큰을 슬랙이 거부: {auth.get('error')}")
        return 1
    if not bot_name_matches(auth, ident):
        log(f"이 봇 토큰은 '{auth.get('user')}' 것입니다(Hermes-{ident} 아님). 멈춥니다.")
        return 1
    conn = slack_call("apps.connections.open", app)
    if not conn.get("ok"):
        log(f"앱 수준 토큰을 슬랙이 거부: {conn.get('error')} (connections:write 범위가 필요)")
        return 1
    code, expires = write_bundle(args.spool or HANDOFF_SPOOL, ident, args.user, bot, app, args.ttl)
    local = expires.astimezone().strftime("%m/%d %H:%M")
    log(f"확인됨: 봇 {auth.get('user')} · 워크스페이스 {auth.get('team')}")
    log(f"\n연결 코드 (1회용, {local}까지, 원내망에서만):\n\n  {code}\n")
    log("이 코드만 구성원에게 보내세요(슬랙 DM 가능). 토큰은 보내지 않습니다.")
    log("구성원은 jaix-setup 에서 '슬랙으로도 쓰기'를 고르고 이 코드를 붙여 넣습니다.")
    return 0


# --- 연구원 PC: 코드로 받기 -------------------------------------------------------------------------
def handoff_url():
    return os.environ.get("JAIX_HANDOFF_URL") or HANDOFF_URL


def read_code_file(path):
    """설치기가 남긴 코드 파일을 읽고 바로 지운다(형식이 틀려도 지운다)."""
    path = Path(path)
    try:
        code = path.read_text(encoding="utf-8-sig").strip().upper()
    finally:
        path.unlink(missing_ok=True)
    if not CODE_RE.match(code):
        raise HandoffError("슬랙 연결 코드 형식이 다릅니다(JX-로 시작하는 29자). AI센터에서 받은 코드를 그대로 붙여 넣으세요.")
    return code


def claim(code, timeout=30):
    """배포처에서 묶음을 한 번 받는다. 코드는 URL이 아니라 본문으로 보낸다(기록에 남지 않게)."""
    req = urllib.request.Request(handoff_url(), data=code.encode("ascii"), method="POST",
                                 headers={"User-Agent": net.UA, "Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = {403: "원내망이 아니라 슬랙 토큰을 받지 못했습니다. 원내망에서 `jaix setup --channels hermes` 를 다시 하세요"
                    "(코드는 아직 쓸 수 있습니다).",
               410: "이 연결 코드는 이미 사용되었습니다. 직접 쓰지 않았다면 AI센터에 바로 알려 주세요.",
               404: "연결 코드가 없거나 만료되었습니다(72시간). AI센터에 새 코드를 요청하세요.",
               400: "연결 코드 형식이 다릅니다."}.get(e.code, f"배포처 오류 {e.code}")
        raise HandoffError(msg) from None
    except (urllib.error.URLError, OSError) as e:
        raise HandoffError(f"배포처({handoff_url()})에 닿지 않습니다: {type(e).__name__}. 원내망인지 확인하세요.") from None
    if not (str(data.get("bot_token", "")).startswith("xoxb-") and str(data.get("app_token", "")).startswith("xapp-")
            and data.get("id") and str(data.get("user", "")).startswith("U")):
        raise HandoffError("배포처가 돌려준 묶음이 온전하지 않습니다. AI센터에 새 코드를 요청하세요.")
    return data


# --- 연구원 PC: Hermes 설치·설정 --------------------------------------------------------------------
def hermes_bin_dir():
    return (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "hermes" / "bin") if IS_WIN else None


def find_hermes():
    found = paths.which("hermes")
    if found:
        return found
    d = hermes_bin_dir()
    exe = d / "hermes.exe" if d else None
    return str(exe) if exe and exe.is_file() else None


def _child_env():
    """막 깐 Hermes 를 이 프로세스 PATH 가 모른다(설치가 사용자 PATH 만 바꿈) → 자식에게 붙여 준다."""
    env = dict(os.environ)
    d = hermes_bin_dir()
    if d:
        env["PATH"] = f"{d}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(cmd, log, timeout=600):
    """출력은 기록에 남기되 끝 몇 줄만. 표준 입력은 주지 않는다(대화형 질문은 기본값으로 지나감)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, env=_child_env(), creationflags=paths.NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"    {Path(cmd[0]).name}: {type(e).__name__}")
        return False, ""
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-8:])
        log(f"    {Path(cmd[0]).name} {' '.join(cmd[1:3])} → 코드 {r.returncode}\n{tail}")
    return r.returncode == 0, out


def install_hermes(log, dry_run=False):
    if find_hermes():
        log("    Hermes: 이미 있음")
        return True
    if dry_run:
        log("    Hermes: 공식 설치 스크립트를 비대화형으로 돌릴 예정")
        return True
    log("    Hermes: 공식 설치 스크립트를 내려받아 설치합니다(10-20분, 약 3GB)")
    with tempfile.TemporaryDirectory() as tmp:
        script = net.download(INSTALL_PS1, Path(tmp) / "install.ps1")
        ok, _ = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                      "-NonInteractive", "-SkipBrowser", "-SkipComputerUse"], log, timeout=INSTALL_TIMEOUT)
    if not (ok and find_hermes()):
        log("    Hermes 설치 실패 — 위 기록을 AI센터에 보내 주세요")
        return False
    return True


def _record_file():
    return paths.data_dir() / "hermes.json"


def recorded():
    try:
        return json.loads(_record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_record(rec):
    _record_file().parent.mkdir(parents=True, exist_ok=True)
    _record_file().write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def config_path():
    return paths.hermes_home() / "config.yaml"


def backup_config():
    src = config_path()
    if not src.is_file():
        return None
    dst = src.with_name(f"config.yaml.jaix-bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(src, dst)
    return dst


def _yaml_has_key(text, section, name):
    """config.yaml 의 section 바로 아래(2칸 들여쓰기)에 name 이 있는지. YAML 파서 없이 jaix가 덮어쓸지만 가린다."""
    m = re.search(rf"^{re.escape(section)}:\s*$(.*?)(?=^\S)", text + "\n_", re.M | re.S)
    return bool(m and re.search(rf"^  {re.escape(name)}:", m.group(1), re.M))


def configure(hermes, model, log, dry_run=False):
    """모델·도구·MCP. 값은 `hermes config set`(YAML/JSON 값)과 `hermes tools disable`로 넣는다(Hermes가 형식을 지킨다)."""
    spec = PROVIDERS[model]
    if dry_run:
        log(f"    설정: 모델 {spec['provider']} · 끌 도구 {', '.join(OFF_TOOLSETS)} · MCP(jaix 항목)")
        return True
    saved = backup_config()
    if saved:
        log(f"    config.yaml 백업: {saved.name}")
    ok = True
    for key in ("provider", "default", "base_url"):
        if key in spec:
            ok &= _run([hermes, "config", "set", f"model.{key}", spec[key]], log)[0]
    for platform in ("cli", "slack"):
        ok &= _run([hermes, "tools", "disable", *OFF_TOOLSETS, "--platform", platform], log)[0]
    ok &= write_mcp(hermes, log)
    return ok


def write_mcp(hermes, log):
    """jaix가 Codex에 쓴 MCP 항목(codex-mcp.json)만 Hermes 에 넣는다. import-agent 는 항목을 고를 수 없어 쓰지 않는다
    (jaix-win Q9). 이미 같은 이름이 있으면 jaix가 넣은 것(기록)일 때만 바꾼다."""
    want = codex.owned_mcp()
    if not want:
        log("    MCP: Codex 채널에서 jaix가 쓴 항목이 없어 건너뜀")
        return True
    rec = recorded()
    owned = rec.get("mcp") or {}
    try:
        text = config_path().read_text(encoding="utf-8")
    except OSError:
        text = ""
    ok = True
    for name, spec in want.items():
        if _yaml_has_key(text, "mcp_servers", name) and name not in owned:
            log(f"    MCP {name}: Hermes 에 사용자 항목이 있어 그대로 둠")
            continue
        value = json.dumps({"command": spec["command"], "args": spec["args"], **({"env": spec["env"]} if spec.get("env") else {})},
                           ensure_ascii=False)
        if _run([hermes, "config", "set", f"mcp_servers.{name}", value], log)[0]:
            owned[name] = spec
            log(f"    MCP {name}: 넣음")
        else:
            ok = False
    rec["mcp"] = owned
    _save_record(rec)
    return ok


def _slackbot_dir(workdir):
    archive = net.download(f"https://codeload.github.com/{SLACKBOT_REPO}/tar.gz/{SLACKBOT_SHA}",
                           Path(workdir) / "hermes-slackbot.tar.gz")
    out = Path(workdir) / "hermes-slackbot"
    with tarfile.open(archive) as t:
        t.extractall(out, filter="data")
    return next(out.iterdir())


def connect_slack(bundle, log):
    """받은 묶음을 setup_pc.py 에 파일로 넘긴다(읽자마자 setup_pc 가 지운다). 실패는 설치 실패다."""
    python = uvpython.find(uvpython.DEFAULT)
    if not python:
        log(f"    uv 관리 Python {uvpython.DEFAULT} 이 없어 슬랙 연결을 못 함")
        return False
    rec = recorded()
    # jaix가 전에 넣은 토큰이면 바꾼다(관리자가 새 코드를 낸 경우). 사용자가 직접 넣은 토큰은 setup_pc 가 지킨다
    replace = rec.get("slack", {}).get("id") is not None
    with tempfile.TemporaryDirectory() as tmp:
        kit = _slackbot_dir(tmp)
        pending = paths.data_dir() / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        fd, secret = tempfile.mkstemp(dir=pending, prefix="slack-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"bot_token": bundle["bot_token"], "app_token": bundle["app_token"]}, f)
        try:
            ok, out = _run([python, str(kit / "scripts" / "setup_pc.py"), bundle["id"], "--user", bundle["user"],
                            "--secrets-file", secret, *(["--replace"] if replace else [])], log, timeout=900)
        finally:
            Path(secret).unlink(missing_ok=True)
    if not ok:
        if "already set" in out:
            log("    이 PC의 Hermes 에 다른 슬랙 토큰이 있어 바꾸지 않았습니다. AI센터에 알려 주세요.")
        return False
    rec["slack"] = {"id": bundle["id"], "connected": datetime.datetime.now().isoformat(timespec="seconds")}
    _save_record(rec)
    log(f"    슬랙: Hermes-{bundle['id']} 연결됨")
    return True


def setup(lock, log, code_file=None, model="chatgpt", dry_run=False):
    """채널 hermes. 돌려주는 값은 안내문·doctor 용 {"status": …}."""
    if not IS_WIN:
        log("    Hermes 무인 설치는 Windows 만 합니다(맥은 hermes-slackbot 안내대로)")
        return {"status": "unsupported"}
    rec = recorded()
    rec.update({"model": model, "status": "installing"})
    if not dry_run:
        _save_record(rec)
    # 코드 파일은 무엇보다 먼저 읽고 지운다(아래 단계가 실패해도 디스크에 남지 않게)
    code, code_error = None, None
    if code_file:
        try:
            code = read_code_file(code_file)
        except HandoffError as e:
            code_error = str(e)
    if not install_hermes(log, dry_run):
        return _done({"status": "failed", "error": "Hermes 설치 실패"}, dry_run)
    hermes = find_hermes() or "hermes"
    if not configure(hermes, model, log, dry_run):
        log("    설정 일부가 들어가지 않았습니다(위 기록)")
    skills.install(lock, log, dry_run)
    if code_error:
        log(f"    {code_error}")
        return _done({"status": "failed", "error": code_error}, dry_run)
    if not code:
        log("    슬랙 연결 코드가 없어 슬랙 연결은 건너뜀 — AI센터에서 코드를 받아 jaix-setup 을 다시 실행하세요")
        return _done({"status": "no-code", "login": PROVIDERS[model]["login"]}, dry_run)
    if dry_run:
        return {"status": "dry-run"}
    try:
        bundle = claim(code)
    except HandoffError as e:
        log(f"    {e}")
        return _done({"status": "failed", "error": str(e)}, dry_run)
    if not connect_slack(bundle, log):
        return _done({"status": "failed", "error": "슬랙 연결 실패(gateway)"}, dry_run)
    return _done({"status": "connected", "id": bundle["id"], "login": PROVIDERS[model]["login"]}, dry_run)


def _done(result, dry_run):
    if not dry_run:
        rec = recorded()
        rec["status"] = result["status"]
        rec["error"] = result.get("error")
        _save_record(rec)
    return result


# --- doctor 용 ------------------------------------------------------------------------------------
def startup_entries():
    if not IS_WIN:
        return []
    d = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return sorted(d.glob("Hermes_Gateway*.vbs")) if d.is_dir() else []


def env_has(key):
    try:
        lines = (paths.hermes_home() / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.split("=", 1)[0].strip() == key and line.split("=", 1)[1].strip()
               for line in lines if "=" in line)
