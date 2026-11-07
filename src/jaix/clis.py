"""명령창의 `claude`·`codex`: 있으면 그대로, PATH 에 안 잡혀 있으면 사용자 PATH 에 올리고, 없으면 깐다(Windows).

사용자 요구(2026-11-05): "jaix 깔고 나면 터미널에서 claude, codex 치면 바로 됐으면". 비전문가가 많다.

- 이미 새 창에서 잡히면 아무것도 안 한다(업데이트도 그 도구 자신의 몫).
- 깔려 있는데 PATH 에 없으면(npm 전역 %APPDATA%\\npm 미등록, 네이티브 ~\\.local\\bin 미등록) 그 폴더를 사용자 PATH 에 넣는다.
- 없으면:
  - Claude Code: 공식 네이티브 설치(claude.ai/install.ps1)가 하는 것을 그대로 한다 — downloads.claude.ai 에서 stable
    판 번호와 manifest 의 sha256 을 받아 claude.exe 를 받고 검증한 뒤 `claude.exe install stable` 이 런처
    (~\\.local\\bin\\claude.exe)를 둔다. 스크립트를 내려받아 파이프 실행하지 않는다(받는 것·검증을 jaix 가 기록).
    Claude Desktop 이 Code 탭용으로 받아 둔 사본만 있으면 '없음'으로 본다(판마다 경로가 바뀌고 앱 안 가상화 경로다).
  - Codex CLI: jaix 의 Node(포터블 LTS)로 `npm install -g @openai/codex --prefix %APPDATA%\\npm` — npm 판이 공식
    배포이고, Windows 보조 실행파일(샌드박스·명령 실행기)이 함께 오며, codex 자신의 업데이트 안내(npm i -g)와 같은 자리다.
- 로그인은 하지 않는다(안내만). jaix 가 깐 것은 data_dir/cli-installed.json 에 남겨 doctor 에 '설치함(jaix)'으로
  보이고, 제거(jaix cleanup) 때 jaix 가 깐 것만 지운다.
"""
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from jaix import net, paths, runtimes, winenv
from jaix.paths import IS_WIN

CLAUDE_DIST = "https://downloads.claude.ai/claude-code-releases"
CLAUDE_CHANNEL = "stable"
CODEX_PACKAGE = "@openai/codex"
DESKTOP_URL = "https://claude.ai/download"
LOGIN_HINT = "새 명령창(PowerShell·cmd)을 열고 {name} 을 한 번 실행해 로그인하세요."


def record_file():
    return paths.data_dir() / "cli-installed.json"


def recorded():
    try:
        data = json.loads(record_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(rec):
    record_file().parent.mkdir(parents=True, exist_ok=True)
    record_file().write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def _remember(name, **fields):
    rec = recorded()
    rec[name] = {**rec.get(name, {}), **fields, "time": datetime.now().isoformat(timespec="seconds")}
    _save(rec)


# --- 새 창에서 잡히나 --------------------------------------------------------------------------------
def fresh_path():
    return winenv.fresh_path()


def on_fresh_path(name):
    return shutil.which(name, path=fresh_path())


# --- 이미 깔려 있는 자리(PATH 밖) -----------------------------------------------------------------------
def local_bin():
    """Claude Code 네이티브 설치가 런처를 두는 곳(~\\.local\\bin). install.ps1·`claude install` 과 같다."""
    return Path.home() / ".local" / "bin"


def _candidates(name):
    """PATH 에 없을 때 찾아볼 표준 설치 자리 — 찾으면 그 폴더를 PATH 에 올린다."""
    out = []
    if name == "claude":
        out.append(local_bin())
    npm = paths.npm_global_bin()
    if npm:
        out.append(npm)
    return out


def find_installed(name):
    """(실행파일, PATH 에 올릴 폴더). 새 창에서 이미 잡히면 폴더는 None."""
    exe = on_fresh_path(name)
    if exe:
        return exe, None
    for d in _candidates(name):
        hit = shutil.which(name, path=str(d)) if d.is_dir() else None
        if hit:
            return hit, d
    return None, None


# --- 설치 -------------------------------------------------------------------------------------------
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _claude_platform():
    return "win32-arm64" if os.environ.get("PROCESSOR_ARCHITECTURE") == "ARM64" else "win32-x64"


def _get_text(url):
    import urllib.request
    with urllib.request.urlopen(net._request(url), timeout=20) as r:
        return r.read().decode("utf-8").strip()


def install_claude(log, get_text=None, get_json=None, download=None, run=None):
    """install.ps1 과 같은 순서: 판 번호 → manifest sha256 → claude.exe 받기·검증 → `claude.exe install stable`."""
    get_text, get_json = get_text or _get_text, get_json or net.get_json
    version = get_text(f"{CLAUDE_DIST}/{CLAUDE_CHANNEL}")
    if not version[:1].isdigit():
        raise RuntimeError(f"downloads.claude.ai 가 판 번호 대신 다른 내용을 돌려줌({version[:40]!r})")
    platform = _claude_platform()
    want = ((get_json(f"{CLAUDE_DIST}/{version}/manifest.json").get("platforms") or {}).get(platform) or {}).get("checksum")
    if not want:
        raise RuntimeError(f"manifest 에 {platform} 이 없음")
    dest = paths.data_dir() / "downloads" / f"claude-{version}-{platform}.exe"
    log(f"    Claude Code {version} 받는 중(downloads.claude.ai)…")
    (download or net.download)(f"{CLAUDE_DIST}/{version}/{platform}/claude.exe", dest)
    try:
        got = _sha256(dest)
        if got != want.lower():
            raise RuntimeError(f"sha256 불일치(받은 것 {got[:12]}…)")
        code, out = (run or _run)([str(dest), "install", CLAUDE_CHANNEL])
        if code != 0:
            raise RuntimeError(f"claude install 종료 코드 {code}: {out.strip().splitlines()[-1:] or ''}")
    finally:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass  # 실행 직후 잠김 — 다음 실행 때 지워도 된다
    exe = shutil.which("claude", path=str(local_bin()))
    if not exe:
        raise RuntimeError(f"설치 뒤 {local_bin()} 에 claude 가 없음")
    return exe, version


def _npm():
    node = runtimes.find(runtimes.BY_KEY["node"]).path
    if node:
        beside = Path(node).parent / ("npm.cmd" if IS_WIN else "npm")
        if beside.exists():
            return str(beside)
    return paths.which("npm")


def install_codex(log, dry_run=False, run=None):
    """jaix Node 로 npm 전역(%APPDATA%\\npm)에 @openai/codex. 스크립트는 돌리지 않는다(--ignore-scripts)."""
    node = runtimes.ensure(runtimes.BY_KEY["node"], log, dry_run=dry_run)
    if not runtimes.ok(runtimes.BY_KEY["node"], node):
        raise RuntimeError("Node.js 를 준비하지 못함")
    npm, prefix = _npm(), paths.npm_global_bin()
    if not npm or not prefix:
        raise RuntimeError("npm 을 찾지 못함")
    log(f"    Codex CLI 받는 중(npm {CODEX_PACKAGE}, 수백 MB)…")
    code, out = (run or _run)([npm, "install", "-g", "--no-audit", "--no-fund", "--ignore-scripts", "--prefix",
                               str(prefix), f"{CODEX_PACKAGE}@latest"], timeout=1200)
    if code != 0:
        raise RuntimeError(f"npm 종료 코드 {code}: {out.strip().splitlines()[-1:] or ''}")
    exe = shutil.which("codex", path=str(prefix))
    if not exe:
        raise RuntimeError(f"설치 뒤 {prefix} 에 codex 가 없음")
    return exe, prefix


def _run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout,
                       creationflags=paths.NO_WINDOW)
    from jaix import proc
    return r.returncode, proc.decode(r.stdout) + proc.decode(r.stderr)


# --- setup 단계 -------------------------------------------------------------------------------------
def ensure(name, log, dry_run=False, installer=None):
    """name: claude|codex. 돌려주는 값 {"status": present|path-added|installed|failed|skipped, "path", ...}."""
    exe, add = find_installed(name)
    if exe and not add:
        log(f"  {name}: 있음 ({exe}) — 그대로 둠")
        return {"status": "present", "path": exe}
    if exe:
        log(f"  {name}: 있음 ({exe}) — 새 명령창에서 잡히게 사용자 PATH 에 {add} 를 넣음")
        if not dry_run:
            added = winenv.add_to_path([add])
            if added:
                _remember(name, path_added=str(add))
        return {"status": "path-added", "path": exe, "dir": str(add)}
    if not IS_WIN:
        hint = ("curl -fsSL https://claude.ai/install.sh | bash" if name == "claude" else "npm i -g @openai/codex")
        log(f"  {name}: 없음 — 이 OS 에서는 jaix 가 깔지 않습니다: {hint}")
        return {"status": "skipped"}
    if dry_run:
        log(f"  {name}: 없음 — 깔 예정")
        return {"status": "dry-run"}
    try:
        if name == "claude":
            exe, version = (installer or install_claude)(log)
            folder = local_bin()
            _remember("claude", path=exe, version=version, how="native", dir=str(folder))
        else:
            exe, folder = (installer or install_codex)(log)
            _remember("codex", path=exe, how="npm", dir=str(folder))
    except Exception as e:  # 받기·검증·설치 실패 — 다른 단계는 계속(설치 결과에 실패로 남는다)
        log(f"  {name}: 설치 실패 — {e}")
        return {"status": "failed", "error": str(e)}
    added = winenv.add_to_path([folder])
    if added:
        _remember(name, path_added=str(folder))
    log(f"  {name}: 설치함 ({exe})")
    return {"status": "installed", "path": exe}


# --- 제거(jaix cleanup) -----------------------------------------------------------------------------
def cleanup(log):
    """jaix 가 깐 것·넣은 PATH 만 되돌린다. 사용자가 원래 갖고 있던 것은 건드리지 않는다."""
    rec = recorded()
    c = rec.get("claude") or {}
    if c.get("how") == "native" and c.get("path"):
        for p in (Path(c["path"]), Path.home() / ".local" / "share" / "claude"):  # 런처와 판 보관 폴더
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
                log(f"jaix 가 깐 Claude Code 지움: {p}")
            except OSError as e:
                log(f"Claude Code 지우기 실패({p}): {e}")
    x = rec.get("codex") or {}
    if x.get("how") == "npm" and x.get("dir"):
        d = Path(x["dir"])
        for p in (d / "node_modules" / "@openai" / "codex", d / "codex", d / "codex.cmd", d / "codex.ps1"):
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
            except OSError:
                pass
        log(f"jaix 가 깐 Codex CLI 지움: {d}")
    for name in ("claude", "codex"):
        added = (rec.get(name) or {}).get("path_added")
        # npm 전역·~\.local\bin 은 다른 도구(uv tool 등)도 쓰므로, 그 폴더에 무엇이 남아 있으면 PATH 에서 빼지 않는다
        if added and not (Path(added).is_dir() and any(Path(added).iterdir())):
            for p in winenv.remove_entry(added):
                log(f"PATH에서 뺌: {p}")
    try:
        record_file().unlink(missing_ok=True)
    except OSError:
        pass


# --- doctor -----------------------------------------------------------------------------------------
def doctor_rows(channels=("claude", "codex")):
    """[(status, area, message, fix)] — 고른 채널의 claude·codex 명령이 새 창에서 잡히나."""
    rows = []
    rec = recorded()
    for name, label in (("claude", "claude 명령"), ("codex", "codex 명령")):
        if name not in channels:
            continue
        exe = on_fresh_path(name)
        mine = rec.get(name) or {}
        by = " · 설치함(jaix)" if mine.get("how") else (" · PATH 넣음(jaix)" if mine.get("path_added") else "")
        if exe:
            rows.append(("ok", label, f"새 창에서 잡힘 ({exe}){by}", None))
        else:
            hidden, _ = find_installed(name)
            why = f"깔려 있지만 PATH 에 없음 ({hidden})" if hidden else "없음"
            rows.append(("warn", label, f"새 창에서 안 잡힘 — {why}", "jaix setup (또는 jaix-setup 을 다시 실행)"))
    return rows
