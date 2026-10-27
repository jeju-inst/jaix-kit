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
        return on_disk(version)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().splitlines()[-1]
    return on_disk(version)


def python_dir():
    """uv가 관리 Python을 푸는 곳(UV_PYTHON_INSTALL_DIR가 있으면 그것)."""
    env = os.environ.get("UV_PYTHON_INSTALL_DIR")
    if env:
        return Path(env)
    if IS_WIN:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "uv" / "python"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "uv" / "python"


def on_disk(version):
    """결과물 기준 판정: cpython-<version>.*/-* 폴더에 실행되는 python이 있는가.

    설치본(Inno) 자식 프로세스에서는 uv가 'os error 448'(신뢰할 수 없는 탑재 지점 — RedirectionGuard 상속 추정)을
    보고하지만 실제로는 Python과 정션이 만들어진다(jaix-kit#21). 종료 코드만 믿으면 성공을 실패로 적는다.
    """
    exe = "python.exe" if IS_WIN else "bin/python3"
    root = python_dir()
    try:
        candidates = sorted([*root.glob(f"cpython-{version}.*"), *root.glob(f"cpython-{version}-*")])
    except OSError:
        return None
    for d in candidates:
        try:  # 정션(cpython-3.12-…-none)은 상속된 RedirectionGuard 아래에서 WinError 448 을 낸다(#27)
            if (d / exe).is_file():
                return str(d / exe)
        except OSError:
            continue
    return None


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
            code = r.returncode
            msg = ([ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()][-1:] or [""])[0][:200]
        except (OSError, subprocess.TimeoutExpired) as e:
            code, msg = None, str(e)
        have = find(v, uv)  # 종료 코드가 아니라 결과물로 판정한다(#21: 448 을 보고해도 실제로는 깔림)
        good &= bool(have)
        if have and code == 0:
            log(f"  uv 관리 Python {v}: 설치함 ({have})")
        elif have:
            log(f"  uv 관리 Python {v}: 설치함 ({have}) — uv가 오류를 보고했지만 결과물 확인: {msg}")
        else:
            # 설치본 안에서만 막히는 경우가 있어, 상속 없는 로그온 자동 갱신(jaix update --quiet)이 다시 한다
            log(f"  uv 관리 Python {v}: 설치 실패 — {msg} (다음 로그온 자동 갱신 또는 `jaix update` 가 다시 시도)")
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
