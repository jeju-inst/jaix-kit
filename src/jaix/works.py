"""웍스(NAVER WORKS) 도구: 기성 `nworks` CLI + 기관 User OAuth 앱 하나 (docs/works.md).

- 무엇을 깔지는 잠금이 고정한 jaix-works 커밋의 runtime.json 이 정한다(원본 한 벌): nworks 정확한 버전과 npm
  무결성 해시, 로그인 스코프, 기관 앱 정보 위치. 못 읽으면 FALLBACK.
- nworks 는 jaix 데이터 폴더(works/)에 npm 으로 깔고 무결성 해시를 대조한다. 다르면 지우고 실패로 둔다.
  설치 스크립트는 돌리지 않는다(--ignore-scripts). 외부 개인 개발자 패키지라서다.
- 기관 앱 Client ID/Secret 은 공개 저장소에 둘 수 없어 IP 게이트가 걸린 원내 위치(client_source)에서만 받는다.
  원외면 건너뛰고 doctor 가 안내한다. jaix 는 비밀을 화면·기록에 쓰지 않는다.
- 로그인(`jaix works login`)은 비밀을 명령줄 인자가 아니라 환경변수로 넘기고, 스코프를 반드시 명시한다
  (nworks 기본값은 전체 스코프라 기관 앱에 없는 스코프가 섞여 웍스가 로그인을 통째로 거절한다).
"""
import json
import os
import shutil
import subprocess
import urllib.error
from pathlib import Path

from jaix import net, paths, proc, runtimes, uvpython, winenv
from jaix.paths import IS_WIN

PLUGIN = "jaix-works"
SPEC_FILE = "runtime.json"
PACKAGE = "nworks"
# jaix-works 첫 판의 값. 잠금의 runtime.json 을 못 읽을 때만 쓴다
FALLBACK = {
    "nworks": {"version": "1.3.1",
               "integrity": "sha512-sxlxy6Gv6/9ZCLtlAjGUapqDVb+h+A5/9ghrSKDfOGhQoMH3Bhz5BRrHcZPjx8vy8vAiwwaueVXq/p8Ko2Knag=="},
    "scope": "calendar calendar.read file file.read mail.read",
    "client_source": "https://jaix.namun.net/works/client.json",
}


def plugin(lock):
    return next((p for p in lock.plugins if p.name == PLUGIN), None)


def parse_spec(text):
    """runtime.json 내용 → 쓸 값. 필요한 키가 없으면 None."""
    try:
        data = json.loads(text)
        nw = data["nworks"]
        if all(isinstance(v, str) and v for v in (nw["version"], nw["integrity"], data["scope"],
                                                   data["client_source"])):
            return {"nworks": {"version": nw["version"], "integrity": nw["integrity"]},
                    "scope": data["scope"], "client_source": data["client_source"]}
    except (ValueError, KeyError, TypeError):
        pass
    return None


def spec(lock, offline=False):
    p = plugin(lock)
    url = p and uvpython._raw_url(p, SPEC_FILE)
    if url and not offline:
        try:
            with net.urllib.request.urlopen(net._request(url), timeout=20) as r:
                got = parse_spec(r.read().decode("utf-8", errors="replace"))
            if got:
                return got
        except (urllib.error.URLError, OSError, ValueError):
            pass
    return json.loads(json.dumps(FALLBACK))


# --- 위치 -------------------------------------------------------------------------------------------
def home():
    return paths.data_dir() / "works"


def bin_dir():
    return home() / "node_modules" / ".bin"


def exe():
    return shutil.which(PACKAGE, path=str(bin_dir())) if bin_dir().is_dir() else None


def link_dir():
    """맥·리눅스: nworks 바로가기를 두는 곳(흔히 PATH에 있는 ~/.local/bin). Windows는 실행 폴더를 PATH에 올린다."""
    return Path.home() / ".local" / "bin"


def expose(log):
    """스킬이 PATH의 `nworks` 를 부르므로 실행파일을 PATH에서 보이게 한다."""
    if IS_WIN:
        winenv.add_to_path([bin_dir()])
        return
    target = bin_dir() / PACKAGE
    link = link_dir() / PACKAGE
    try:
        link_dir().mkdir(parents=True, exist_ok=True)
        if link.is_symlink() and Path(os.readlink(link)) != target:
            link.unlink()
        if not link.exists() and not link.is_symlink():
            link.symlink_to(target)
        elif not link.is_symlink():
            log(f"  웍스: {link} 에 다른 파일이 있어 바로가기를 만들지 않음")
    except OSError as e:
        log(f"  웍스: 바로가기({link})를 만들지 못함 — {e}")


def on_path():
    """PATH에서 찾히는 nworks 가 jaix 가 깐 것인가."""
    found = shutil.which(PACKAGE)
    mine = exe()
    return bool(found and mine and Path(found).resolve() == Path(mine).resolve())


def client_file():
    return home() / "client.json"


def saved_spec_file():
    """설치 때 쓴 runtime.json 사본 — 로그인이 잠금을 다시 받지 않고 스코프를 읽는다."""
    return home() / "runtime.json"


def installed():
    """(설치된 버전, 무결성 해시). 없으면 (None, None)."""
    try:
        version = json.loads((home() / "node_modules" / PACKAGE / "package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None, None
    try:
        lock = json.loads((home() / "package-lock.json").read_text(encoding="utf-8"))
        integrity = lock["packages"][f"node_modules/{PACKAGE}"]["integrity"]
    except (OSError, ValueError, KeyError):
        integrity = None
    return version, integrity


def _npm():
    node = runtimes.find(runtimes.BY_KEY["node"]).path
    if node:
        beside = Path(node).parent / ("npm.cmd" if IS_WIN else "npm")
        if beside.is_file():
            return str(beside)
    return paths.which("npm")


def _npm_install(version):
    """home() 에 nworks@version 만 든 작은 프로젝트를 만들고 npm install. (성공, 마지막 줄)."""
    home().mkdir(parents=True, exist_ok=True)
    (home() / "package.json").write_text(json.dumps(
        {"name": "jaix-works-runtime", "private": True, "dependencies": {PACKAGE: version}}, indent=2), encoding="utf-8")
    npm = _npm()
    if not npm:
        return False, "npm 을 찾지 못함"
    try:
        code, out = proc.run(npm, ["install", "--no-audit", "--no-fund", "--ignore-scripts", "--prefix", str(home())],
                             timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:  # update 가 다른 단계까지 멈추지 않게 실패로 돌려준다
        return False, f"npm 실행 실패: {e}"
    return code == 0, (out.strip().splitlines() or [""])[-1][:200]


# --- 기관 앱 정보 -----------------------------------------------------------------------------------
def fetch_client(url, timeout=8):
    """원내 위치의 {client_id, client_secret}. 닿지 않거나 형식이 틀리면 None."""
    try:
        data = net.get_json(url, timeout=timeout)
    except Exception:
        return None
    if isinstance(data, dict) and all(isinstance(data.get(k), str) and data[k] for k in ("client_id", "client_secret")):
        return {"client_id": data["client_id"], "client_secret": data["client_secret"]}
    return None


def _write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if not IS_WIN:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def saved_client():
    try:
        data = json.loads(client_file().read_text(encoding="utf-8"))
        return data if data.get("client_id") and data.get("client_secret") else None
    except (OSError, ValueError, AttributeError):
        return None


# --- setup · update ---------------------------------------------------------------------------------
def ensure(lock, log, dry_run=False, offline=False):
    """잠금에 jaix-works 가 있을 때만. 돌려준 status: absent·planned·current·installed·failed (+client 여부)."""
    if not plugin(lock):
        return {"status": "absent"}
    sp = spec(lock, offline)
    want = sp["nworks"]
    node = runtimes.ensure(runtimes.BY_KEY["node"], log, dry_run=dry_run)
    if dry_run:
        log(f"  웍스: nworks {want['version']} 설치·기관 앱 정보 받기 예정")
        return {"status": "planned"}
    if not runtimes.ok(runtimes.BY_KEY["node"], node):
        log("  웍스: Node.js 가 없어 nworks 를 깔지 못함 (위 Node.js 항목 참고)")
        return {"status": "failed"}
    have, integrity = installed()
    status = "current"
    if have != want["version"] or integrity != want["integrity"]:
        ok, tail = _npm_install(want["version"])
        have, integrity = installed()
        if not ok or have != want["version"] or integrity != want["integrity"]:
            shutil.rmtree(home() / "node_modules", ignore_errors=True)
            why = tail if not ok else f"무결성 해시가 잠금과 다름 ({(integrity or '없음')[:20]}…)"
            log(f"  웍스: nworks 설치 실패 — {why}")
            return {"status": "failed"}
        status = "installed"
    _write_private(saved_spec_file(), json.dumps(sp, ensure_ascii=False, indent=2))
    expose(log)
    log(f"  웍스: nworks {have} ({'설치함' if status == 'installed' else '최신'})")
    client = fetch_client(sp["client_source"])
    if client:
        _write_private(client_file(), json.dumps(client))
        log("  웍스: 기관 앱 정보 받음 — 처음 쓸 때 `jaix works login` 으로 웍스 로그인")
    elif saved_client():
        log("  웍스: 원내 위치에 닿지 않음 — 전에 받은 기관 앱 정보를 그대로 씀")
    else:
        log("  웍스: 기관 앱 정보를 받지 못함(원내망 필요) → 원내망(사무실·VPN)에서 `jaix setup` 다시 실행")
    return {"status": status, "client": bool(client or saved_client())}


# --- 로그인 ----------------------------------------------------------------------------------------
def login_command(scope):
    return ["login", "--user", "--scope", scope]


def login(log):
    """브라우저 로그인. 비밀은 환경변수로만 넘긴다. 종료 코드를 돌려준다."""
    cli = exe()
    if not cli:
        log("웍스 도구(nworks)가 설치돼 있지 않습니다 → `jaix setup` 을 다시 실행하세요.")
        return 1
    client = saved_client()
    if not client:
        log("기관 앱 정보가 없습니다 → 원내망(사무실·VPN)에서 `jaix setup` 을 다시 실행하세요.")
        return 1
    try:
        scope = json.loads(saved_spec_file().read_text(encoding="utf-8"))["scope"]
    except (OSError, ValueError, KeyError):
        scope = FALLBACK["scope"]
    env = {**os.environ, "NWORKS_CLIENT_ID": client["client_id"], "NWORKS_CLIENT_SECRET": client["client_secret"]}
    log("브라우저에 웍스 로그인 화면이 열립니다. 로그인한 뒤 '허용'을 누르세요.")
    try:
        r = subprocess.run(proc.command(cli, login_command(scope)), env=env, timeout=600)
    except subprocess.TimeoutExpired:
        log("10분 안에 로그인이 끝나지 않았습니다. `jaix works login` 을 다시 실행하세요.")
        return 1
    log("웍스 로그인 완료." if r.returncode == 0 else
        "웍스 로그인 실패 — 위 메시지를 확인하고 `jaix works login` 을 다시 실행하세요.")
    return r.returncode


def user_token_file():
    """nworks 1.3.x 가 User OAuth 토큰을 두는 곳(프로필별 키). `whoami` 는 서비스 계정 토큰만 보여 줘서 못 쓴다."""
    return Path.home() / ".config" / "nworks" / "user-token.json"


def logged_in():
    """기본 프로필에 갱신 가능한 User OAuth 토큰이 있는가. 토큰 값은 읽어서 쓰지도 출력하지도 않는다."""
    try:
        entry = json.loads(user_token_file().read_text(encoding="utf-8")).get("default") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return bool(entry.get("refreshToken") or entry.get("accessToken"))
