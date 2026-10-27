"""플러그인 MCP(uvx)가 쓸 uv 관리 Python을 앱 밖에서 미리 깐다 (jaix-kit#14).

Claude Desktop(Windows MSIX)이 띄운 uvx가 Python을 처음 받으면 %APPDATA%\\uv\\python 쓰기가 MSIX 가상화로
%LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming 에 돌려지고, uv가 만든 정션은 실제 경로를 가리켜 깨진다.
MCP는 화면에 오류 없이 안 뜬다. 앱 밖에서 `uv python install`을 해 두면 uvx가 그것을 쓴다(namun-ji 실측).
고를 버전: 잠금의 플러그인 .mcp.json에서 uvx/uv에 고정한 --python, 그리고 고정이 없을 때 uvx가 고를 기본 DEFAULT.
"""
import json
import os
import re
import subprocess
import urllib.error
from pathlib import Path, PureWindowsPath  # 명령 경로는 \\ · / 둘 다 올 수 있다

from jaix import net, paths, runtimes
from jaix.paths import IS_WIN

DEFAULT = "3.12"  # 고정 없는 uvx가 쓰게 미리 깔 버전(hwp-agent requires-python >=3.11)


def _raw_url(plugin, name):
    m = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", plugin.url)
    if not m:
        return None
    sub = f"{plugin.subdir.strip('/')}/" if plugin.subdir else ""
    return f"https://raw.githubusercontent.com/{m.group(1)}/{plugin.sha}/{sub}{name}"


def pins(mcp_config):
    """.mcp.json에서 uvx/uv 서버가 고정한 Python 버전들."""
    out = set()
    for server in (mcp_config.get("mcpServers") or {}).values():
        if PureWindowsPath(str(server.get("command", ""))).stem.lower() not in ("uv", "uvx"):
            continue
        args = [str(a) for a in server.get("args") or []]
        for i, a in enumerate(args):
            if a in ("--python", "-p") and i + 1 < len(args):
                out.add(args[i + 1])
            elif a.startswith("--python="):
                out.add(a.split("=", 1)[1])
    return out


def needed(lock, offline=False):
    """미리 깔 버전 목록. 못 받는 .mcp.json은 건너뛴다(기본 버전은 늘 넣는다)."""
    versions = {DEFAULT}
    if not offline:
        for p in lock.plugins:
            url = _raw_url(p, ".mcp.json")
            if not url:
                continue
            try:
                versions |= pins(net.get_json(url))
            except (urllib.error.URLError, OSError, ValueError):
                pass  # .mcp.json 없음(MCP 없는 플러그인)·오프라인
    return sorted(versions)


def _record():
    return paths.jaix_home() / "uv-python.json"


def recorded():
    """setup·update가 마지막으로 맞춘 버전들(doctor가 잠금을 받지 않고 점검하려고)."""
    try:
        return json.loads(_record().read_text(encoding="utf-8"))["versions"]
    except (OSError, ValueError, KeyError):
        return [DEFAULT]


def _uv():
    return runtimes.find(runtimes.BY_KEY["uv"]).path


def find(version, uv=None):
    """uv가 관리하는(내려받은) Python 중 version에 맞는 것의 경로. 시스템 Python은 세지 않는다."""
    uv = uv or _uv()
    if not uv:
        return None
    try:
        # --system·--no-project: 작업 폴더의 .venv를 관리 Python으로 잘못 세지 않게
        r = subprocess.run([uv, "python", "find", "--system", "--no-project", "--python-preference", "only-managed",
                            version],
                           capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else None


def ensure(versions, log, dry_run=False):
    uv = _uv()
    if not uv:
        log("  uv 관리 Python: uv가 없어 건너뜀")
        return False
    good = True
    for v in versions:
        have = find(v, uv)
        if have:
            log(f"  uv 관리 Python {v}: 있음 ({have})")
            continue
        if dry_run:
            log(f"  uv 관리 Python {v}: 설치 예정 (uv python install {v})")
            continue
        try:
            r = subprocess.run([uv, "python", "install", v], capture_output=True, text=True, timeout=900,
                               encoding="utf-8", errors="replace")
            ok = r.returncode == 0
            msg = ([ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()][-1:] or [""])[0][:200]
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, msg = False, str(e)
        good &= ok
        log(f"  uv 관리 Python {v}: {'설치함' if ok else '설치 실패 — ' + msg}")
    if not dry_run:
        _record().parent.mkdir(parents=True, exist_ok=True)
        _record().write_text(json.dumps({"versions": list(versions)}), encoding="utf-8")
    return good


def virtualized_dirs():
    """MSIX 가상화로 Claude 앱 안에만 보이는 uv 폴더(앱이 uv Python을 직접 받으려 한 흔적)."""
    if not IS_WIN:
        return []
    packages = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Packages"
    return sorted(str(p) for p in packages.glob("Claude_*/LocalCache/Roaming/uv") if p.is_dir())
