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

from jaix import codex, hermes as skills, net, paths, secret, uvpython
from jaix.paths import IS_WIN

INSTALL_PS1 = "https://hermes-agent.nousresearch.com/install.ps1"
HANDOFF_URL = "https://jaix.namun.net/hermes/handoff"
HANDOFF_SPOOL = "~/.local/share/jaix-handoff/hermes"  # ji-gw-ai share/deploy.toml [handoff] spool 과 같게
TTL_HOURS = 72
CODE_RE = re.compile(r"^JX-[A-Z2-7]{26}$")
# setup_pc.py 를 받는 커밋(z0nam/hermes-slackbot). 바꿀 때는 그 저장소의 시험을 확인하고 올린다
SLACKBOT_REPO = "z0nam/hermes-slackbot"
SLACKBOT_SHA = "7df2086ad3a3464b3751eb52917d591ab16d85c7"  # hermes-slackbot#24: 기본 플러그인(slack-forwarded·slack-model-display)·base_name
PROVIDERS = {  # 설치기의 구독 선택 → Hermes model 설정. Nous Portal 은 쓰지 않는다
    # open: hermes 의 openai-codex 로그인은 device code 방식이라 브라우저를 스스로 열지 않는다(주소와 코드만 찍음,
    # hermes_cli/auth_codex.py) → jaix 가 그 주소를 연다(jaix-win 11/5). anthropic 은 hermes 가 직접 연다
    "chatgpt": {"provider": "openai-codex", "default": "gpt-6.1-sol",
                "base_url": "https://chatgpt.com/backend-api/codex", "login": ["auth", "add", "openai-codex"],
                "open": "https://auth.openai.com/codex/device",
                "how": ["잠시 뒤 브라우저에 OpenAI 로그인 페이지가 열립니다. ChatGPT 계정으로 로그인한 뒤,",
                        "이 창에 나오는 코드(예: ABCD-12345)를 그 페이지에 넣으세요."]},
    "claude": {"provider": "anthropic", "default": "claude-sonnet-5-5",
               "login": ["auth", "add", "anthropic", "--type", "oauth"],
               "how": ["회사 Claude 계정(Team)으로 로그인하세요 — 개인 Claude 구독(Pro·Max)도 연결은 되지만 Anthropic 약관상 권하지 않습니다.",
                       "브라우저에 Claude 승인 페이지가 열립니다(안 열리면 이 창에 나온 주소를 복사해 브라우저에 붙여 넣으세요).",
                       "승인하면 나오는 코드를 복사해 이 창에 붙여 넣고 Enter 를 누르세요."]},
}
OFF_TOOLSETS = ["browser", "computer_use"]
# 비개발자에게 소음·혼선이면 설치 때 막는다(jaix-kit-dev 10-30, jaix-win 2차 실측 관찰)
QUIET = {"compression.codex_gpt55_autoraise_notice": "false"}  # 첫 대화의 영어 "Codex … caps context at 500K" 안내
# 슬래시 명령 제한(Hermes gateway/slash_access): allow_admin_from 에 아무도 아닌 ID 를 두면 사용자는 아래 목록만 쓸 수
# 있고 /help 에도 이것만 보인다. 뺀 것: /login·/topup(쓰지 않는 Nous 계정·결제), /yolo(위험 명령 승인을 이 세션에서
# 통째로 건너뜀). 목록은 Hermes v0.21.5 GATEWAY_KNOWN_COMMANDS 에서 셋을 뺀 것 — 새 판의 새 명령은 jaix가 올릴 때까지 막힌다
SLASH_NOBODY = "U00JAIXNONE"
# 위험 명령 승인 방식(사용자 결정 10-30): 연구원은 smart·manual 만, off 는 AI센터 관리자만. Hermes 는 슬랙 /approvals
# 로 바꾸는 것을 모드와 상관없이 관리자 전용으로 막으므로(gateway _handle_approvals_command), 연구원은 PC 에서
# `jaix hermes approvals smart|manual` 로 바꾼다. off 는 이 명령이 받지 않는다
APPROVAL_MODES = ("smart", "manual")
SLASH_DENIED = ("login", "topup", "yolo")
SLASH_ALLOWED = [
    "agents", "approvals", "approve", "bg", "blueprint", "bp", "branch", "btw", "bundles", "busy", "codex-runtime",
    "codex_runtime", "commands", "compact", "compress", "context", "ctx", "curator", "debug", "deny", "diff",
    "egress", "fast", "footer", "fork", "goal", "hb", "heartbeat", "help", "init", "insights", "kanban", "learn",
    "loop", "memory", "moa", "model", "new", "pause", "personality", "plan", "platform", "proactive", "profile",
    "q", "queue", "reasoning", "refine", "reload-mcp", "reload-skills", "reload_mcp", "reload_skills", "reset",
    "restart", "resume", "retry", "review", "rollback", "s", "save", "sessions", "set-home", "sethome", "skills",
    "start", "status", "steer", "stop", "subgoal", "suggest", "suggestions", "tasks", "title", "topic", "undo",
    "update", "usage", "v", "verbose", "version", "voice", "whoami",
]
# 기본봇을 사용자 봇(Hermes-namun)처럼 맞춘다(사용자 결정 11/8). 사용자가 정한 값은 덮지 않는다(_own_scalar).
# agent.system_prompt 는 Hermes 시스템 프롬프트 뒤에 붙는 사용자 몫 덧붙임이다(hermes_cli/personality.py)
SYSTEM_PROMPT = (
    "제주연구원 연구원을 돕는 비서로서 한국어로 답한다. 답의 길이는 요청의 무게에 맞춘다 — 한 줄 질문에는 한 줄로 답하고, "
    "끝낸 일은 무엇을 바꿨고 무엇을 확인했고 무엇이 남았는지만 짧게 보고하며 과정을 다시 늘어놓지 않는다. "
    "\"좋은 질문입니다\", \"기꺼이 도와드리겠습니다\" 같은 군말, 요청을 되풀이하는 말, 이미 한 말의 재요약, "
    "사용자에게 보이는 도구 호출 중계는 하지 않는다. 꾸밈말보다 사실로 말하고, 확실하지 않으면 그렇다고 분명히 말한다. "
    "맞아서 동의하고, 사용자가 말했다는 이유로 동의하지 않는다. 자세한 설명은 사용자가 원하거나 가르치는 자리이거나 "
    "중요한 일일 때만 한다. 메일 발송·결재 상신·파일 삭제처럼 되돌리기 어려운 일은 하기 전에 확인을 받는다."
)
FOOTER_KEY = "display.platforms.slack.runtime_footer.enabled"
PROMPT_KEY = "agent.system_prompt"
BASE_NAME_KEY = "plugins.entries.slack-model-display.settings.base_name"
ROOM_KEY = "slack.free_response_channels"
INSTALL_TIMEOUT = 3600  # 첫 설치 실측 14분·3GB(namun-ji). 느린 망을 넉넉히


class HandoffError(RuntimeError):
    """연결 코드로 토큰을 받지 못함. 메시지는 연구원이 읽는 안내다."""


# --- 관리자: 묶음 만들기 ----------------------------------------------------------------------------
def new_code():
    """JX- + 128비트 난수의 base32 26자."""
    return "JX-" + base64.b32encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")


def code_key(code):
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def slack_call(method, token, timeout=20, **params):
    import urllib.parse
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=urllib.parse.urlencode(params).encode("ascii"),
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def bot_name_matches(auth, ident):
    """슬랙 auth.test 의 user 는 봇 표시 이름을 사용자 이름 규칙으로 바꾼 것이라 구분자가 빠진다
    (Hermes-jitest → 'hermesjitest', jaix-kit#69). 하이픈·밑줄·점을 지우고 비교한다."""
    squash = lambda v: re.sub(r"[-_.\s]", "", v.lower())
    return squash(auth.get("user") or "") == squash(f"hermes-{ident}")


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


def issued_path(spool):
    """코드 발급 기록(아이디·멤버·시각만, 코드·토큰 없음). 묶음 폴더 옆에 둔다 — 묶음은 받으면 지워지므로."""
    return Path(spool).expanduser().parent / "issued.jsonl"


def issued_before(spool, ident):
    """이 아이디에 코드를 낸 마지막 기록. 없으면 None."""
    last = None
    try:
        lines = issued_path(spool).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("id") == ident:
            last = rec
    return last


def record_issued(spool, ident, user, expires):
    path = issued_path(spool)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": ident, "user": user, "issued_at": now,
                            "expires_at": expires.isoformat(timespec="seconds")}) + "\n")


def cmd_handoff(args, log):
    """관리자(studio)용. 토큰은 숨김 입력으로만 받는다."""
    ident = args.id.strip().lower()
    if not re.fullmatch(r"[a-z0-9]{1,21}", ident):
        log("아이디는 영문 소문자·숫자 1-21자(앱 Hermes-<아이디>와 같게)")
        return 2
    if not args.user.startswith("U"):
        log("--user 는 U로 시작하는 슬랙 멤버 ID")
        return 2
    spool = args.spool or HANDOFF_SPOOL
    before = issued_before(spool, ident)
    if before and not getattr(args, "again", False):
        log(f"Hermes-{ident} 에는 이미 연결 코드를 낸 적이 있습니다({before.get('issued_at', '?')}, {before.get('user', '?')}).")
        log("봇 하나를 두 PC 에서 돌리면 슬랙 메시지가 두 PC 로 나뉘어 들어가 대화가 끊깁니다(Socket Mode 는 이벤트를 연결 하나에만 보냄).")
        log("코드가 만료됐거나 PC 를 옮기는 것이면 --again 을 붙여 다시 내세요. PC 를 옮길 때는 예전 PC 의 Hermes 를 먼저 끄게 하세요.")
        return 3
    log("토큰을 붙여 넣으세요. 글자 대신 *가 찍힙니다.")
    # xapp 먼저: 관리자는 App-Level Token 을 만든 직후라 클립보드에 xapp 가 있다(onboard_batch 첫 사용 피드백, 11/10)
    app = secret.ask_secret("App-Level Token (xapp-…)", secret.slack_token("xapp-"), "xapp-로 시작", log=log)
    bot = app and secret.ask_secret("Bot User OAuth Token (xoxb-…)", secret.slack_token("xoxb-"), "xoxb-로 시작", log=log)
    if not (bot and app):
        log("토큰을 받지 못해 멈춥니다(세 번 모두 형식이 맞지 않음).")
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
    code, expires = write_bundle(spool, ident, args.user, bot, app, args.ttl)
    record_issued(spool, ident, args.user, expires)
    local = expires.astimezone().strftime("%m/%d %H:%M")
    log(f"확인됨: 봇 {auth.get('user')} · 워크스페이스 {auth.get('team')}")
    log(f"\n연결 코드 (1회용, {local}까지, 원내망에서만):\n\n  {code}\n")
    log("이 코드만 구성원에게 보내세요(슬랙 DM 가능). 토큰은 보내지 않습니다.")
    log("구성원은 jaix-setup 에서 '슬랙으로도 쓰기'를 고르고 이 코드를 붙여 넣습니다.")
    return 0


# --- 연구원 PC: 코드로 받기 -------------------------------------------------------------------------
def handoff_url():
    return os.environ.get("JAIX_HANDOFF_URL") or HANDOFF_URL


def read_code_file(path, keep=False):
    """설치기가 남긴 코드 파일을 읽고 바로 지운다(형식이 틀려도 지운다). keep(--dry-run)이면 남긴다."""
    path = Path(path)
    try:
        code = path.read_text(encoding="utf-8-sig").strip().upper()
    finally:
        if not keep:
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
    """config.yaml 에 name 이라는 키가 있을 수 있는지. YAML 파서가 없으니 보수적으로 본다: section 이 있고
    파일 어디든 name 이 (들여쓰기·따옴표와 상관없이) 키로 나오면 있다고 본다 — 사용자 항목을 덮어쓰지 않는 쪽으로 틀린다."""
    if not re.search(rf"^\s*{re.escape(section)}\s*:", text, re.M):
        return False
    return bool(re.search(rf"""^\s*(?:-\s*)?["']?{re.escape(name)}["']?\s*:""", text, re.M))


def _config_digest():
    try:
        return hashlib.sha256(config_path().read_bytes()).hexdigest()
    except OSError:
        return None


class _Setter:
    """hermes 설정 명령을 값이 바뀐 것만 부른다. hermes.exe 는 부를 때마다 서명 없는 python 을 하나 더 띄우는데,
    창 없는 jaixw.exe 가 그걸 수십 번(재설치·로그온 갱신마다) 되풀이하는 것이 Defender 행동 판정에 보탰을 수 있다
    (jaix-win 11/4). 건너뛰는 조건: 지난번 jaix 가 같은 값을 넣었고, 그 뒤 config.yaml 이 바뀌지 않았음(지문 같음).
    사용자·Hermes 가 파일을 고쳤으면 지문이 달라져 전부 다시 넣는다(사용자 값을 덮지 않는 규칙은 부르는 쪽이 지킨다)."""

    def __init__(self, hermes, log):
        self.hermes, self.log = hermes, log
        rec = recorded()
        fresh = rec.get("config_digest") is not None and rec.get("config_digest") == _config_digest()
        self.applied = dict(rec.get("applied") or {}) if fresh else {}
        self.skipped = self.ran = 0
        self.backed_up = False

    def __call__(self, key, value, args):
        if self.applied.get(key) == value:
            self.skipped += 1
            return True
        if not self.backed_up:
            saved = backup_config()
            if saved:
                self.log(f"    config.yaml 백업: {saved.name}")
            self.backed_up = True
        self.ran += 1
        ok = _run([self.hermes, *args], self.log)[0]
        if ok:
            self.applied[key] = value
        else:
            self.applied.pop(key, None)
        return ok

    def save(self):
        rec = recorded()
        rec["applied"], rec["config_digest"] = self.applied, _config_digest()
        _save_record(rec)
        if self.skipped:
            self.log(f"    Hermes 설정: 바뀐 것만 넣음({self.ran}건, 그대로인 {self.skipped}건은 건너뜀)")


def configure(hermes, model, log, dry_run=False):
    """모델·도구·MCP. 값은 `hermes config set`(YAML/JSON 값)과 `hermes tools disable`로 넣는다(Hermes가 형식을 지킨다)."""
    spec = PROVIDERS[model]
    if dry_run:
        log(f"    설정: 모델 {spec['provider']} · 끌 도구 {', '.join(OFF_TOOLSETS)} · MCP(jaix 항목)")
        return True
    put = _Setter(hermes, log)
    ok = True
    for key in ("provider", "default", "base_url"):
        if key in spec:
            ok &= put(f"model.{key}", spec[key], ["config", "set", f"model.{key}", spec[key]])
    for platform in ("cli", "slack"):
        ok &= put(f"tools:{platform}", list(OFF_TOOLSETS), ["tools", "disable", *OFF_TOOLSETS, "--platform", platform])
    ok &= write_mcp(hermes, log, put)
    put.save()
    return ok


def approval_mode():
    """config.yaml 의 approvals.mode (없으면 None — Hermes 기본값 smart). YAML 파서 없이 그 절만 본다."""
    try:
        text = config_path().read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^approvals:\s*$(.*?)(?=^\S|\Z)", text, re.M | re.S)
    mm = m and re.search(r"^\s+mode:\s*['\"]?(\w+)", m.group(1), re.M)
    return mm.group(1).lower() if mm else None


def cmd_approvals(args, log):
    """연구원 PC: 위험 명령 승인 방식을 smart·manual 중에서 바꾼다(off 는 관리자만, 이 명령은 받지 않음)."""
    hermes = find_hermes()
    if not hermes:
        log("Hermes 가 없습니다. jaix-setup 에서 '슬랙으로도 쓰기'를 고르세요.")
        return 1
    ok, _ = _run([hermes, "config", "set", "approvals.mode", args.mode], log)
    if not ok:
        return 1
    log(f"승인 방식: {args.mode} ({'위험해 보이는 명령만 묻기' if args.mode == 'smart' else '위험 명령마다 묻기'}). "
        "gateway 를 다시 시작하지 않아도 다음 명령부터 적용됩니다.")
    return 0


# hermes-slackbot make_manifest.ID_RE 와 같다(슬랙 슬래시 명령: 소문자, "/hermes-" 포함 32자 이하)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,20}$")


def slash_command(ident):
    return f"hermes-{ident}"


def cmd_rename(args, log):
    """관리자가 슬랙 앱을 Hermes-<새 아이디>로 바꾼 뒤(hermes-slackbot provision_app.py rename), 이 PC 쪽을 맞춘다:
    HERMES_SLACK_SLASH → hermes-<새 아이디>, gateway 재시작, 연결 기록 갱신. 토큰·앱은 그대로다."""
    new = (args.id or "").strip().lower().removeprefix("hermes-")
    if not ID_RE.match(new):
        log(f"아이디 '{args.id}' 는 쓸 수 없습니다 — 소문자·숫자·-·_ 로 21자 이하(AI센터가 알려 준 새 아이디 그대로)")
        return 2
    rec = recorded()
    slack = rec.get("slack") or {}
    old = slack.get("id")
    if rec.get("status") != "connected" or not old:
        log("이 PC의 Hermes 는 jaix 로 슬랙에 연결된 기록이 없습니다. 먼저 jaix-setup 으로 연결하세요.")
        return 1
    hermes = find_hermes()
    if not hermes:
        log("Hermes 가 없습니다. jaix-setup 에서 '슬랙으로도 쓰기'를 고르세요.")
        return 1
    want = slash_command(new)
    if old == new and env_value("HERMES_SLACK_SLASH") == want:
        log(f"이미 Hermes-{new} (/{want}) 입니다. 바꿀 것이 없습니다.")
        return 0
    if args.dry_run:
        log(f"(예정) Hermes-{old} → Hermes-{new}: HERMES_SLACK_SLASH={want}, gateway 재시작, 연결 기록 갱신")
        return 0
    # UPPER_SNAKE 키는 hermes 가 .env 에 쓴다(공식 경로 — setup_pc·install.py 와 같은 값)
    ok, _ = _run([hermes, "config", "set", "HERMES_SLACK_SLASH", want], log)
    if not ok:
        log("슬래시 명령을 바꾸지 못했습니다(위 기록). 아무것도 바꾸지 않았습니다.")
        return 1
    _rename_base_name(hermes, old, new, log)
    if old != new:
        slack = dict(slack, id=new, renamed_from=old,
                     renamed=datetime.datetime.now().isoformat(timespec="seconds"))
        rec["slack"] = slack
        _save_record(rec)
    log(f"슬래시 명령: /{want} (Hermes-{old} → Hermes-{new})")
    ok, _ = _run([hermes, "gateway", "restart"], log, timeout=180)
    if not ok:
        log("gateway 를 다시 시작하지 못했습니다. 새 명령창에서 `hermes gateway restart` 를 실행하세요.")
        return 1
    log(f"gateway 다시 시작함. 슬랙에서 /{want} help 를 쳐 보세요(DM 은 그대로 됩니다).")
    return 0


def _rename_base_name(hermes, old, new, log):
    """답 이름 표시(slack-model-display base_name)를 Hermes-<새 아이디>로. install.py 가 넣은 Hermes-<옛 아이디> 일 때만
    바꾼다 — 없으면(플러그인을 안 쓰는 PC) 만들지 않고, 사용자가 고친 이름은 그대로 둔다. 실패해도 rename 은 계속한다."""
    try:
        text = config_path().read_text(encoding="utf-8")
    except OSError:
        return
    cur = _yaml_scalar(text, "plugins", "entries", "slack-model-display", "settings", "base_name")
    if not cur or cur.lower() == f"hermes-{new}" or cur.lower() != f"hermes-{old}":
        return
    if _run([hermes, "config", "set", BASE_NAME_KEY, f"Hermes-{new}"], log)[0]:
        log(f"답 이름 표시: Hermes-{new}")
    else:
        log("답 이름 표시(base_name)를 바꾸지 못했습니다 — 답 위 이름이 옛 아이디로 보일 수 있습니다(위 기록).")


def show_console():
    """jaix.exe 는 hide_console="hide-early"(installer/jaix.spec)로 빌드돼, 설치기가 띄워 콘솔을 혼자 가지면 창이
    숨는다. 로그인은 기기 코드를 읽고 붙여 넣어야 하므로 다시 보이게 한다(Codex #86 P1). Windows 외·콘솔 없음은 그대로."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return False
        ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    except (AttributeError, OSError):
        return False


def _call_login(cmd):
    """로그인 명령을 같은 콘솔에서 돌린다. Ctrl+C 는 콘솔의 모든 프로세스에 가므로 jaix 도 KeyboardInterrupt 를
    받는다 — 여기서 받아 자식이 끝나길 기다리고 '취소'(130)로 돌려준다. 그냥 두면 main 이 130 으로 끝내 창이 결과를
    읽기 전에 닫혔다(jaix-win 11/4: Ctrl+C 뒤 한두 줄만 보이고 닫힘)."""
    p = subprocess.Popen(cmd, env=_child_env())
    try:
        return p.wait()
    except KeyboardInterrupt:
        try:
            p.wait(timeout=10)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            p.kill()
        return CANCELLED


CANCELLED = 130
ALREADY = 3  # 이미 로그인돼 있어 다시 하지 않음(설치기 페이지가 '이미 로그인됨'으로 보인다)


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


# hermes_cli/auth_codex.py 의 기기 코드 안내: "2. Enter this code:\n     <코드>"
# 코드 뒤에 공백·줄바꿈이 와야 받는다 — 파이프가 코드 중간에서 끊겨 오면 앞부분만 복사하게 된다(Codex #109)
DEVICE_CODE = re.compile(r"Enter this code:\s*([A-Z0-9]{4,}-[A-Z0-9]{4,})(?=\s)")


# hermes_cli/auth_commands.py _warn_same_codex_account 의 영문 경고
SAME_ACCOUNT_WARNING = re.compile(r"same OpenAI account as openai-codex credential|keep just one", re.I)


def _call_login_tee(cmd, on_text):
    """chatgpt(기기 코드) 로그인만: 출력을 파이프로 받아 그대로 창에 쓰며 on_text 로 넘긴다(코드를 클립보드에).
    표준 입력은 그대로 물려준다. 파이프면 Python 이 출력을 모아 두므로 PYTHONUNBUFFERED, 색 코드는 지우고 쓴다."""
    import codecs
    import sys
    env = {**_child_env(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        while True:
            chunk = p.stdout.read1(4096)
            if not chunk:
                break
            text = _strip_ansi(dec.decode(chunk))
            sys.stdout.write(text)
            sys.stdout.flush()
            on_text(text)
        return p.wait()
    except KeyboardInterrupt:
        try:
            p.wait(timeout=10)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            p.kill()
        return CANCELLED


def _copy_clipboard(text):
    if not IS_WIN:
        return False
    try:
        return subprocess.run(["clip"], input=text.encode("ascii", "ignore"), creationflags=paths.NO_WINDOW,
                              timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _auth(hermes, args, timeout=60):
    """hermes auth 공식 명령(list·remove)을 창 없이. (종료 코드, 출력)."""
    try:
        r = subprocess.run([hermes, "auth", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, env=_child_env(), creationflags=paths.NO_WINDOW, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# `hermes auth list <provider>` 의 줄: "  #1  <label>   oauth   id=<id> priority=0 <source>..."
CRED_ROW = re.compile(r"^\s*#(\d+)\s+(.+?)\s+(\S+)\s+id=(\S+)\s+priority=(-?\d+)")


def credentials(hermes, provider, auth=None):
    """provider 의 자격 목록 [{index, label, id}]. 목록을 못 읽으면 None(모름 — 정리하지 않는다)."""
    code, out = (auth or (lambda a: _auth(hermes, a)))(["list", provider])
    if code != 0:
        return None
    rows = []
    for line in out.splitlines():
        m = CRED_ROW.match(line)
        if m:
            rows.append({"index": int(m.group(1)), "label": m.group(2).strip(), "id": m.group(4)})
    return rows


def prune_credentials(hermes, provider, old_ids, log, auth=None, warned=False):
    """새로 로그인한 뒤 같은 provider 의 예전 자격을 지운다(공식 `hermes auth remove`, id 로). 새 자격이 목록에
    있을 때만 한다 — 같은 OpenAI 계정이면 예전 것은 OpenAI 가 이미 폐기했고, Hermes 가 그것을 고르면 봇이 실패한다."""
    run = auth or (lambda a: _auth(hermes, a))
    after = credentials(hermes, provider, run)
    if not after or not old_ids:
        return 0
    if not [c for c in after if c["id"] not in old_ids]:
        log("  (새 자격을 목록에서 찾지 못해 예전 자격은 그대로 둡니다)")
        return 0
    removed = 0
    for c in after:
        if c["id"] in old_ids:
            code, out = run(["remove", provider, c["id"]])
            if code == 0:
                removed += 1
            else:
                log(f"  예전 자격 #{c['index']} 정리 실패(새 자격은 그대로): {out.strip().splitlines()[-1:] or ''}")
    if removed and warned:  # Hermes 의 영문 경고가 'hermes auth remove …' 를 치라고 한다 — 연구원이 따라 치지 않게
        log(f"  ↑ 위 영문 경고(warning: … keep just one / hermes auth remove …)는 신경 쓰지 마세요 — "
            f"jaix 가 예전 {provider} 자격 {removed}개를 정리했습니다(새로 로그인한 것만 남김).")
    elif removed:
        log(f"  예전 {provider} 자격 {removed}개를 정리했습니다(새로 로그인한 것만 남김).")
    return removed


def duplicate_credentials():
    """doctor 용: 기록된 모델의 provider 자격이 둘 이상이면 (provider, 개수, 모델), 아니면 None."""
    hermes = find_hermes()
    if not hermes:
        return None
    model = recorded().get("model") or "chatgpt"
    provider = PROVIDERS.get(model, PROVIDERS["chatgpt"])["provider"]
    rows = credentials(hermes, provider)
    return (provider, len(rows), model) if rows and len(rows) > 1 else None


def _login_record(model, code):
    """창이 닫힌 뒤에도 되짚을 수 있게 결과만 남긴다(값·토큰은 없다 — hermes 가 직접 받는다)."""
    try:
        f = paths.data_dir() / "hermes-login.log"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as out:
            out.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} model={model} code={code}\n")
    except OSError:
        pass


OPEN_DELAY = 3  # 기기 코드가 창에 찍힌 뒤에 브라우저가 앞으로 오게
CLOSE_AFTER = {0: 5, ALREADY: 5}  # --no-wait(설치기 페이지): 결과를 읽을 틈. 성공·이미 로그인 5초, 그 밖 15초
CLOSE_AFTER_OTHER = 15


def _open_url(url):
    try:
        if IS_WIN:
            os.startfile(url)  # 기본 브라우저
            return True
        import webbrowser
        return bool(webbrowser.open(url))
    except OSError:
        return False


def _pause(seconds, log):
    """Enter 를 누르거나 seconds 가 지나면 돌아온다(Windows 콘솔). 설치기 페이지가 결과를 다시 보여 주지만, 승인 직후
    창이 바로 닫혀 무슨 일이 있었는지 못 봤다(jaix-win 11/5)."""
    log(f"이 창은 {seconds}초 뒤 저절로 닫힙니다(Enter 를 누르면 바로).")
    try:
        import msvcrt
    except ImportError:
        return
    import time
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            if msvcrt.kbhit() and msvcrt.getwch() in ("\r", "\n"):
                return
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass


def cmd_login(args, log, run=None, wait=None, opener=None, pause=None, auth=None, ask=None, copy=None):
    """AI 구독 로그인 창: 설치기 'AI 구독 로그인' 페이지·시작 메뉴가 이것을 연다(설치기가 cmd.exe 를 직접 띄우지
    않게, #86). hermes 의 로그인은 브라우저 승인과 붙여넣기를 받으므로 이 콘솔을 그대로 물려준다. 성공·실패·취소
    모두 결과를 보이고, Enter 를 기다리거나(Windows) --no-wait 면 몇 초 보인 뒤 닫는다."""
    show_console()  # 숨은 창이면 안내·기기 코드·Enter 대기를 아무도 못 본다 — 무엇보다 먼저
    again = f"jaix hermes login --model {args.model}"
    hermes = find_hermes()
    if not hermes:
        log("Hermes 가 없습니다. jaix-setup 에서 '슬랙으로도 쓰기'를 고르세요.")
        code = 1
    else:
        prov = PROVIDERS[args.model]
        before = credentials(hermes, prov["provider"], auth)
        code = None
        if before and not getattr(args, "force", False):
            who = ", ".join(c["label"] for c in before)
            if getattr(args, "no_wait", False):  # 설치기 페이지: 묻지 않고 건너뜀(한 번 더 누르면 --force)
                log(f"이미 로그인돼 있습니다({who}). 다시 로그인하려면 [다시 로그인]을 한 번 더 누르세요.")
                code = ALREADY
            else:
                try:
                    answer = (ask or input)(f"이미 로그인돼 있습니다({who}). 다시 로그인할까요? [y/N] ")
                except (EOFError, KeyboardInterrupt):
                    answer = ""
                if str(answer).strip().lower() not in ("y", "yes", "예", "ㅛ"):
                    log("그대로 둡니다.")
                    code = ALREADY
    if hermes and code is None:
        log(f"Hermes AI 로그인 ({args.model})")
        for line in prov.get("how", []):
            log(f"  {line}")
        log("승인을 기다리는 동안에는 키를 눌러도 반응이 없습니다. 그만두려면 Ctrl+C.")
        log("")
        timer = None
        if prov.get("open"):
            import threading

            def _open(url=prov["open"]):
                if not (opener or _open_url)(url):
                    log(f"\n브라우저를 열지 못했습니다. 브라우저 주소창에 {url} 을 붙여 넣고, 이 창의 코드를 넣으세요.")
            timer = threading.Timer(OPEN_DELAY, _open)
            timer.daemon = True
            timer.start()
        seen = {"buf": "", "copied": False, "warned": False}

        def on_text(text):  # 기기 코드를 클립보드에(chatgpt 만 — anthropic 은 붙여넣기 입력을 받으니 파이프로 바꾸지 않는다)
            seen["buf"] = (seen["buf"] + text)[-600:]
            if SAME_ACCOUNT_WARNING.search(seen["buf"]):
                seen["warned"] = True
            if seen["copied"]:
                return
            m = DEVICE_CODE.search(seen["buf"])
            if m:
                seen["copied"] = True
                if (copy or _copy_clipboard)(m.group(1)):
                    log(f"\n  ▶ 코드 {m.group(1)} 를 복사해 두었습니다 — 브라우저 입력칸에서 Ctrl+V\n")
        try:
            if run:
                code = run([hermes, *prov["login"]])
            elif prov.get("open"):
                code = _call_login_tee([hermes, *prov["login"]], on_text)
            else:
                code = _call_login([hermes, *prov["login"]])
        except OSError as e:
            log(f"로그인을 시작하지 못함: {e}")
            code = 1
        finally:
            if timer:
                timer.cancel()  # 곧바로 끝났으면(오류) 브라우저를 열지 않는다
        log("")
        if code == 0:
            log("로그인 완료.")
            if before:
                prune_credentials(hermes, prov["provider"], {c["id"] for c in before}, log, auth, warned=seen["warned"])
        elif code == CANCELLED:
            log(f"로그인을 취소했습니다. 나중에 새 명령창에서 `{again}` 로 다시 하세요.")
        else:
            log(f"로그인이 끝나지 않았습니다(코드 {code}). 새 명령창에서 `{again}` 로 다시 하세요.")
        _login_record(args.model, code)
    if IS_WIN and getattr(args, "no_wait", False):  # 설치기 페이지: 결과를 잠깐 보이고 닫혀 페이지로 돌아간다
        (pause or _pause)(CLOSE_AFTER.get(code, CLOSE_AFTER_OTHER), log)
    elif IS_WIN:
        try:  # 시작 메뉴로 연 창은 끝나면 바로 닫힌다 — 결과를 읽을 틈을 준다
            (wait or input)("창을 닫으려면 Enter 를 누르세요.")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


def builtin_skills():
    """Hermes 스킬 폴더의 스킬 이름(jaix가 복사한 skills/jaix/ 아래는 뺀다). SKILL.md 의 name, 없으면 폴더 이름."""
    root = paths.hermes_home() / "skills"
    names = set()
    for md in root.rglob("SKILL.md") if root.is_dir() else []:
        if skills.skills_dir() in md.parents:
            continue
        try:
            m = re.search(r"^name:\s*[\"']?([^\"'\n]+)", md.read_text(encoding="utf-8", errors="replace"), re.M)
        except OSError:
            m = None
        names.add(m.group(1).strip() if m else md.parent.name)
    return sorted(names - set(skills.installed()))  # 같은 이름이면 jaix 스킬까지 꺼지므로 뺀다


def quiet(hermes, log):
    """첫 대화의 영어 안내, 쓰지 않는/위험한 슬래시 명령, Hermes 기본 스킬(상시 분량)을 끈다.
    사용자가 이미 정한 값(jaix 기록에 없는 slack.allow_admin_from·skills.disabled)은 덮지 않는다."""
    rec = recorded()
    owned = rec.get("quiet") or {}
    try:
        text = config_path().read_text(encoding="utf-8")
    except OSError:
        text = ""
    put = _Setter(hermes, log)
    ok = True
    for key, value in QUIET.items():
        ok &= put(key, value, ["config", "set", key, value])
    if _yaml_has_key(text, "slack", "allow_admin_from") and not owned.get("slash"):
        log("    슬래시 명령 제한: 사용자 설정(slack.allow_admin_from)이 있어 그대로 둠")
    else:
        allow = sorted(set(SLASH_ALLOWED) | set(skills.installed()))  # jaix 스킬의 슬래시 명령은 열어 둔다
        for key, value in (("slack.allow_admin_from", json.dumps([SLASH_NOBODY])),
                           ("slack.user_allowed_commands", json.dumps(allow))):
            ok &= put(key, value, ["config", "set", key, value])
        owned["slash"] = True
        log(f"    슬래시 명령: /{', /'.join(SLASH_DENIED)} 막음")
    if _yaml_has_key(text, "skills", "disabled") and "skills" not in owned:  # 빈 목록도 jaix 것이다
        log("    기본 스킬: 사용자 설정(skills.disabled)이 있어 그대로 둠")
    else:
        off = builtin_skills()
        value = json.dumps(off, ensure_ascii=False)
        ok &= put("skills.disabled", value, ["config", "set", "skills.disabled", value])
        owned["skills"] = off
        log(f"    기본 스킬 {len(off)}개 끔(jaix 스킬만 켬)")
    # 첫 DM 답 앞의 "No home channel is set for Slack … /hermes sethome" 안내를 없앤다(jaix-win 11/5). 처음 연결 때
    # setup_pc.py 가 넣지만, 그보다 먼저 연결된 PC 는 다시 설치해도 연결을 건너뛰어 비어 있다. 이미 있으면(사용자가
    # /sethome 으로 고른 것 포함) 건드리지 않는다. 공식 경로: `hermes config set SLACK_HOME_CHANNEL …` 은 .env 에 쓴다
    if env_has("SLACK_ALLOWED_USERS") and not env_has("SLACK_HOME_CHANNEL"):
        home = home_channel()
        if home:
            # 지금 .env 에 없다는 것을 방금 확인했다 — 지난번에 넣은 값 기록(config.yaml 지문만 봄)으로 건너뛰지 않는다(Codex #111)
            put.applied.pop("SLACK_HOME_CHANNEL", None)
            ok &= put("SLACK_HOME_CHANNEL", home, ["config", "set", "SLACK_HOME_CHANNEL", home])
            log("    슬랙 홈 채널: 본인과의 DM 으로 정함(첫 답의 'No home channel' 안내 없앰)")
    ok &= _own_scalar(put, owned, PROMPT_KEY, _yaml_scalar(text, "agent", "system_prompt"), SYSTEM_PROMPT, log,
                      "기본 지시문(agent.system_prompt)")
    ok &= _own_scalar(put, owned, FOOTER_KEY,
                      _yaml_scalar(text, "display", "platforms", "slack", "runtime_footer", "enabled"), "false", log,
                      "슬랙 답 끝 정보줄(runtime_footer)")
    put.save()
    rec = recorded()
    rec["quiet"] = owned
    _save_record(rec)
    ident = (rec.get("slack") or {}).get("id")
    if ident:  # 이미 연결된 PC(jaix update·재설치). 처음 연결은 setup() 이 connect_slack 뒤에 부른다
        refresh_kit(hermes, ident, log)  # 실패해도 막지 않는다(다음 update 때 다시)
        ok &= bot_room(hermes, ident, log)
    return ok


def refresh_kit(hermes, ident, log):
    """이미 연결된 PC 에 hermes-slackbot 새 판의 플러그인을 깐다(install.py <id>). 처음 연결 때는 setup_pc.py 가
    install.py 를 부르지만, 그 뒤 판에서 늘어난 기본 플러그인은 jaix update 로만 받을 수 있다(hermes-slackbot#24).
    기록된 판(slack.kit)이 SLACKBOT_SHA 와 다를 때만, 판마다 한 번. 성공해야 기록을 바꾼다(실패는 다음 update 때 다시).
    install.py 는 base_name 을 Hermes-<id> 로 덮으므로, 사용자가 다른 이름을 정해 뒀으면 끝난 뒤 되돌린다.
    gateway 재시작은 install.py 를 실제로 돌렸을 때만."""
    rec = recorded()
    if (rec.get("slack") or {}).get("kit") == SLACKBOT_SHA:
        return True
    python = uvpython.find(uvpython.DEFAULT)
    if not python:
        log(f"    슬랙 플러그인 갱신: uv 관리 Python {uvpython.DEFAULT} 이 없어 건너뜀(다음 jaix update 때 다시)")
        return False
    # 판마다 한 번이지만 받기·플러그인 켜기·gateway 재시작으로 몇 분 걸린다(jaix-test 실측 업데이트 1분 → 5분 40초)
    log("    슬랙 플러그인 새 판을 받아 까는 중 — 몇 분 걸릴 수 있습니다(판마다 한 번)")
    try:
        text = config_path().read_text(encoding="utf-8")
    except OSError:
        text = ""
    before = _yaml_scalar(text, "plugins", "entries", "slack-model-display", "settings", "base_name")
    # 사용자 이름은 install.py 전에 기록에 남긴다 — 되돌리기가 실패하면 파일엔 Hermes-<id> 만 남아, 다음 재시도에서
    # 원래 이름을 알 수 없게 된다(Codex #145)
    keep = (rec.get("slack") or {}).get("keep_name") or (
        before if before and before != YAML_BLOCK and before.lower() != f"hermes-{ident}" else None)
    if keep:
        rec.setdefault("slack", {})["keep_name"] = keep
        _save_record(rec)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            kit = _slackbot_dir(tmp)
            ok, _ = _run([python, str(kit / "scripts" / "install.py"), ident], log, timeout=600)
    except (OSError, ValueError, tarfile.TarError, StopIteration) as e:
        log(f"    슬랙 플러그인 갱신: 받지 못해 건너뜀({type(e).__name__}) — 다음 jaix update 때 다시")
        return False
    if not ok:
        log("    슬랙 플러그인 갱신 실패(위 기록) — 다음 jaix update 때 다시")
        return False
    if keep and not _run([hermes, "config", "set", BASE_NAME_KEY, keep], log)[0]:
        log("    답 이름 표시를 원래 값으로 되돌리지 못함 — 다음 jaix update 때 다시")
        return False
    if keep:
        log("    답 이름 표시: 사용자 설정을 그대로 둠")
    rec = recorded()
    rec.setdefault("slack", {})["kit"] = SLACKBOT_SHA
    rec["slack"].pop("keep_name", None)
    _save_record(rec)
    if _run([hermes, "gateway", "restart"], log, timeout=180)[0]:
        log("    슬랙 플러그인을 새 판으로 맞추고 Hermes gateway 를 다시 시작함")
    else:
        log("    슬랙 플러그인을 새 판으로 맞춤 — gateway 를 다시 시작하지 못해 다음 로그온부터 적용됩니다")
    return True


YAML_BLOCK = "\x00block"  # 목록·하위 매핑·| > 블록 등 한 줄로 못 읽는 값 — 사용자 것으로 본다


def _unquote(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r"\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)", _yaml_escape, raw[1:-1])
    return raw


YAML_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
                "e": "\x1b", "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029"}


def _yaml_escape(m):
    """큰따옴표 YAML 스칼라의 이스케이프(PyYAML 은 allow_unicode 없이 한글을 \\uXXXX, 접힌 줄 앞 공백을 '\\ ' 로 쓴다)."""
    esc = m.group(1)
    if esc[0] in "xuU" and len(esc) > 1:
        return chr(int(esc[1:], 16))
    return YAML_ESCAPES.get(esc, esc)  # '\\ ' '\\"' '\\/' '\\\\' 는 글자 그대로


def _fold(first, more):
    """여러 줄로 접힌 스칼라(PyYAML·ruamel 은 긴 값을 80자 근처에서 접는다)를 한 줄로. 접힌 줄 사이는 공백 하나,
    큰따옴표 안의 줄 끝 '\\' 는 공백 없이 잇는다. 빈 줄(문단)은 지원하지 않고 그대로 공백으로 잇는다."""
    out = first.strip()
    for line in more:
        part = line.strip()
        out = out[:-1] + part if out.endswith("\\") and out.startswith('"') else f"{out} {part}"
    return out


def _yaml_scalar(text, *path):
    """config.yaml 에서 path(블록 매핑) 끝의 스칼라 값. 없으면 None, 빈 값이면 '', 목록·하위 매핑·블록 스칼라처럼
    한 줄 값으로 읽을 수 없으면 YAML_BLOCK. YAML 파서가 없어 들여쓰기만 본다 — 부르는 쪽은 모르는 값을 사용자 것으로 본다."""
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    depth = lambda l: len(l) - len(l.lstrip())
    i, parent = 0, -1
    for n, name in enumerate(path):
        child = None
        key = re.compile(rf"""\s*["']?{re.escape(name)}["']?\s*:(?:\s+(.*))?$""")
        while i < len(lines):
            line = lines[i]
            i += 1
            indent = depth(line)
            if indent <= parent:
                return None
            child = indent if child is None else child
            m = key.match(line) if indent == child else None
            if m:
                if n < len(path) - 1:
                    inline = (m.group(1) or "").strip()
                    if inline and not inline.startswith("#"):  # 흐름 매핑({…})·앵커 등 — 모르는 모양은 사용자 것
                        return YAML_BLOCK
                    parent = indent
                    break
                more = []
                while i < len(lines) and depth(lines[i]) > indent:
                    more.append(lines[i])
                    i += 1
                value = (m.group(1) or "").strip()
                if not value:  # 하위 줄이 있거나, 들여쓰지 않은 목록(키와 같은 깊이의 '- ')이면 값이 있는 것
                    same_indent_list = i < len(lines) and depth(lines[i]) == indent and lines[i].lstrip().startswith("-")
                    return YAML_BLOCK if more or same_indent_list else ""
                if value[0] in "|>[{&*!" or (more and more[0].lstrip().startswith("- ")):
                    return YAML_BLOCK
                return _unquote(_fold(value, more))
        else:
            return None
    return None


def _own_scalar(put, owned, key, current, want, log, label):
    """사용자가 정하지 않은 설정만 jaix 값으로. current 가 비었거나, jaix 가 지난번 넣은 값(owned[key]) 그대로면
    jaix 것이다(새 판의 바뀐 값으로 올린다). jaix 가 넣은 뒤 config.yaml 이 바뀌지 않았으면(_Setter 기록) 읽은 값과
    상관없이 jaix 것이다. 그 밖의 값은 사용자가 고친 것이라 그대로 둔다."""
    if put.applied.get(key) == want:
        owned[key] = want
        return True
    if current and current not in (owned.get(key), want):
        log(f"    {label}: 사용자 설정이 있어 그대로 둠")
        owned.pop(key, None)
        return True
    if current == want:
        owned[key] = want
        return True
    if put(key, want, ["config", "set", key, want]):
        owned[key] = want
        return True
    return False


def _room_find(call, token, name):
    """봇이 들어가 있는 비공개 채널 중 name. (id, 오류)."""
    cursor = None
    for _ in range(50):
        r = call("conversations.list", token, types="private_channel", exclude_archived="true", limit=200,
                 **({"cursor": cursor} if cursor else {}))
        if not r.get("ok"):
            return None, r.get("error") or "unknown"
        for c in r.get("channels") or []:
            if c.get("name") == name:
                return c.get("id"), None
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return None, None


ROOM_ERRORS = {
    "name_taken": "같은 이름의 채널이 이미 있는데 봇이 들어가 있지 않아 전용 채널을 만들지 않았습니다(AI센터에 알려 주세요)",
    "missing_scope": "슬랙 앱 권한이 옛 것이라 전용 채널을 만들지 않았습니다(AI센터가 앱 권한을 고친 뒤 jaix update)",
}


def _room(token, user, name, log, call):
    """전용 비공개 채널 ID 와 주인 초대 여부. 실패는 설치를 막지 않는다 — 한 줄 안내 후 (None, False)."""
    def skip(error):
        log(f"    전용 채널 {name}: {ROOM_ERRORS.get(error, f'만들지 못해 건너뜀({error})')}")
        return None, False
    try:
        cid, error = _room_find(call, token, name)
        if error:
            return skip(error)
        if not cid:
            r = call("conversations.create", token, name=name, is_private="true")
            if not r.get("ok"):
                return skip(r.get("error") or "unknown")
            cid = (r.get("channel") or {}).get("id")
            log(f"    전용 채널 {name}: 만듦")
        r = call("conversations.invite", token, channel=cid, users=user)
        invited = r.get("ok") or r.get("error") == "already_in_channel"
        if not invited:
            log(f"    전용 채널 {name}: 주인을 초대하지 못함({r.get('error')}) — 다음 jaix update 때 다시 함")
        return cid, invited
    except (OSError, ValueError) as e:
        return skip(type(e).__name__)


def bot_room(hermes, ident, log, call=None):
    """전용 비공개 채널 hermes-<id>(주인 초대, 멘션 없이 답함). 재실행해도 같다. 사용자가 정한
    slack.free_response_channels 는 덮지 않는다. 슬랙 쪽 실패는 설치를 막지 않는다. 답 이름 표시(slack-model-display
    base_name)는 hermes-slackbot install.py 가 넣는다(hermes-slackbot#24) — jaix 는 rename 때만 따라 바꾼다."""
    rec = recorded()
    owned = rec.get("room") or {}
    # 기록은 이 연결(봇)의 것이다. 새 연결 코드로 다른 봇을 붙였으면 그 봇은 옛 채널에 없으니 다시 확인한다(Codex #145).
    # rename 은 같은 봇이라 연결 시각을 그대로 둔다
    linked = (rec.get("slack") or {}).get("connected")
    if owned.get("connected") != linked:
        owned["invited"] = False
    owned["connected"] = linked
    try:
        text = config_path().read_text(encoding="utf-8")
    except OSError:
        text = ""
    put = _Setter(hermes, log)
    ok, restart = True, False
    current = _yaml_scalar(text, "slack", "free_response_channels")
    mine = owned.get(ROOM_KEY)
    if current and current != mine:
        log("    전용 채널: 사용자 설정(slack.free_response_channels)이 있어 그대로 둠")
        owned.pop(ROOM_KEY, None)
    # 이미 넣었고(파일에 그 값이 있거나, 넣은 뒤 config.yaml 이 바뀌지 않음) 주인도 들어가 있으면 슬랙을 다시 부르지 않는다
    elif not (mine and owned.get("invited") and (current == mine or put.applied.get(ROOM_KEY) == mine)):
        token, user = env_value("SLACK_BOT_TOKEN"), (env_value("SLACK_ALLOWED_USERS") or "").split(",")[0].strip()
        if token and user:
            cid, invited = _room(token, user, f"hermes-{ident}".lower(), log, call or slack_call)
            if cid:
                owned["invited"] = invited
                ok &= _own_scalar(put, owned, ROOM_KEY, current, cid, log, "전용 채널")
                if owned.get(ROOM_KEY) == cid:
                    log(f"    전용 채널 hermes-{ident}: 멘션 없이 답하게 함")
                    restart = current != cid
    # gateway 는 설정을 시작할 때만 읽는다. 연결(setup_pc)·플러그인 갱신이 gateway 를 먼저 다시 띄운 뒤라, 새로 넣은
    # 전용 채널은 한 번 더 다시 띄워야 먹는다(jaix-test 실측 11/9: 채널은 생겼는데 멘션 없는 말에 답 안 함)
    if restart:
        if _run([hermes, "gateway", "restart"], log, timeout=180)[0]:
            log("    전용 채널 설정을 적용하려고 Hermes gateway 를 다시 시작함")
        else:
            log("    gateway 를 다시 시작하지 못해 전용 채널은 다음 로그온부터 멘션 없이 답합니다")
    put.save()
    rec = recorded()
    rec["room"] = owned
    _save_record(rec)
    return ok


def write_mcp(hermes, log, put=None):
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
        if (put or _Setter(hermes, log))(f"mcp_servers.{name}", value, ["config", "set", f"mcp_servers.{name}", value]):
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
    # setup_pc.py 가 이 판의 install.py 까지 돌렸다 → refresh_kit 이 같은 판을 다시 깔지 않게 기록
    rec["slack"] = {"id": bundle["id"], "connected": datetime.datetime.now().isoformat(timespec="seconds"),
                    "kit": SLACKBOT_SHA}
    _save_record(rec)
    log(f"    슬랙: Hermes-{bundle['id']} 연결됨")
    return True


def setup(lock, log, code_file=None, model="chatgpt", dry_run=False):
    """채널 hermes. 돌려주는 값은 안내문·doctor 용 {"status": …}."""
    if not IS_WIN:
        log("    Hermes 무인 설치는 Windows 만 합니다(맥은 hermes-slackbot 안내대로)")
        return {"status": "unsupported"}
    rec = recorded()
    # 이미 연결된 PC 에서 다시 설치(새 판 덮어 설치·같은 코드 재입력)해도 연결 기록을 잃지 않게 기억해 둔다(jaix-win 2차 12)
    linked = linked_id(rec)
    rec.update({"model": model, "status": "installing"})
    if not dry_run:
        _save_record(rec)
    # 코드 파일은 무엇보다 먼저 읽고 지운다(아래 단계가 실패해도 디스크에 남지 않게)
    code, code_error = None, None
    if code_file:
        try:
            code = read_code_file(code_file, keep=dry_run)
        except HandoffError as e:
            code_error = str(e)
    if not install_hermes(log, dry_run):
        return _done({"status": "failed", "error": "Hermes 설치 실패"}, dry_run)
    hermes = find_hermes() or "hermes"
    if not configure(hermes, model, log, dry_run):
        # 코드는 아직 쓰지 않았다(서버에 그대로) — 고친 뒤 같은 코드로 다시 하면 된다
        log("    Hermes 설정이 다 들어가지 않아 슬랙 연결을 멈춥니다(위 기록). 연결 코드는 아직 쓰지 않았습니다.")
        return _done({"status": "failed", "error": "Hermes 설정 실패(모델·도구·MCP)"}, dry_run)
    skills.install(lock, log, dry_run)
    # 스킬을 복사한 뒤에 한다(jaix 스킬 이름을 열어 두고 기본 스킬만 끄려면 jaix 스킬이 먼저 있어야 함)
    if not dry_run and not quiet(hermes, log):
        log("    Hermes 소음 정리가 다 들어가지 않아 슬랙 연결을 멈춥니다(위 기록). 연결 코드는 아직 쓰지 않았습니다.")
        return _done({"status": "failed", "error": "Hermes 설정 실패(명령 제한·기본 스킬)"}, dry_run, linked, log)
    if code_error:
        log(f"    {code_error}")
        return _done({"status": "failed", "error": code_error}, dry_run, linked, log)
    if not code:
        if linked:
            log(f"    슬랙 연결: Hermes-{linked} 그대로 씀(새 연결 코드 없음 — 필요 없음)")
            return _done({"status": "connected", "id": linked, "login": PROVIDERS[model]["login"]}, dry_run)
        log("    슬랙 연결 코드가 없어 슬랙 연결은 건너뜀 — AI센터에서 코드를 받아 jaix-setup 을 다시 실행하세요")
        return _done({"status": "no-code", "login": PROVIDERS[model]["login"]}, dry_run)
    if dry_run:
        return {"status": "dry-run"}
    try:
        bundle = claim(code)
    except HandoffError as e:
        log(f"    {e}")
        return _done({"status": "failed", "error": str(e)}, dry_run, linked, log)
    if not connect_slack(bundle, log):
        return _done({"status": "failed", "error": "슬랙 연결 실패(gateway)"}, dry_run, linked, log)
    bot_room(hermes, bundle["id"], log)  # 전용 채널. 실패해도 봇은 돈다(안내만)
    return _done({"status": "connected", "id": bundle["id"], "login": PROVIDERS[model]["login"]}, dry_run)


def _done(result, dry_run, linked=None, log=None):
    """기록에 남긴다. 이미 연결돼 있던 PC 에서 이번 시도가 실패하면(코드 재사용·원외망 등) 이번 실행은 실패로
    돌려주되(설치기 종료 코드 10), 기록은 connected 로 두고 last_error 만 남긴다 — 봇은 그대로 돌기 때문이다."""
    if not dry_run:
        rec = recorded()
        if linked and result["status"] == "failed":
            rec["status"], rec["error"], rec["last_error"] = "connected", None, result.get("error")
            result["kept"] = linked
            if log:
                log(f"    기존 연결 Hermes-{linked} 는 그대로 둡니다")
        else:
            rec["status"], rec["error"] = result["status"], result.get("error")
            rec.pop("last_error", None)
        _save_record(rec)
    return result


# --- doctor 용 ------------------------------------------------------------------------------------
def linked_id(rec=None):
    """이 PC 가 jaix 로 슬랙에 연결된 봇 아이디(아니면 None): 연결 기록(slack.id)이 있고 Hermes .env 에 봇·앱 토큰이
    있으면 연결된 것이다. status 는 보지 않는다 — 다시 설치가 중간에 끊겨 'installing' 으로 남았다가 코드 없는 다음
    실행이 'no-code' 로 덮은 PC 도 봇은 그대로 돈다(jaix-kit-win .08.3 jaix-test: 로그·doctor 가 '연결 코드 없음')."""
    rec = recorded() if rec is None else rec
    ident = (rec.get("slack") or {}).get("id")
    return ident if ident and env_has("SLACK_BOT_TOKEN") and env_has("SLACK_APP_TOKEN") else None


def startup_entries():
    if not IS_WIN:
        return []
    d = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return sorted(d.glob("Hermes_Gateway*.vbs")) if d.is_dir() else []


def env_value(key):
    """Hermes .env 의 값(없으면 None). 토큰을 읽을 때도 쓰므로 값을 기록하지 않는다."""
    try:
        lines = (paths.hermes_home() / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if "=" in line and line.split("=", 1)[0].strip() == key:
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def home_channel(call=None):
    """SLACK_HOME_CHANNEL 로 쓸 값: 봇과 소유자의 DM(D…, conversations.open — setup_pc.py 와 같다). Slack 이 거절하면
    (im:write 없음·오프라인) 소유자 멤버 ID(U…) — chat.postMessage 는 U… 를 그 사람과의 DM 으로 보낸다."""
    user = (env_value("SLACK_ALLOWED_USERS") or "").split(",")[0].strip()
    if not user:
        return None
    token = env_value("SLACK_BOT_TOKEN")
    if token:
        try:
            r = (call or slack_call)("conversations.open", token, users=user)
            if r.get("ok") and (r.get("channel") or {}).get("id"):
                return r["channel"]["id"]
        except (OSError, ValueError):
            pass
    return user


def env_has(key):
    try:
        lines = (paths.hermes_home() / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.split("=", 1)[0].strip() == key and line.split("=", 1)[1].strip()
               for line in lines if "=" in line)
