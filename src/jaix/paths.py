"""플랫폼별 경로. 환경변수로 바꿀 수 있게 해 시험에서 실제 사용자 설정을 건드리지 않는다."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
# 콘솔 자식(uv·claude·codex·winget·schtasks)을 띄울 때 창을 만들지 않는다. 창 없는 jaixw.exe(로그온 작업)에서
# 부르면 자식마다 콘솔 창이 깜빡이기 때문. 모든 호출이 출력을 잡으므로 명령창에서 돌 때도 잃는 것이 없다
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0


def _env_path(name, default):
    value = os.environ.get(name)
    return Path(value) if value else default


def claude_dir():
    return _env_path("CLAUDE_CONFIG_DIR", Path.home() / ".claude")


def codex_home():
    return _env_path("CODEX_HOME", Path.home() / ".codex")


def hermes_home():
    return _env_path("HERMES_HOME", Path.home() / ".hermes")


def jaix_home():
    """jaix가 받은 포터블 런타임을 두는 곳(프로그램). Windows는 설치본과 같은 %LOCALAPPDATA%\\Programs\\jaix."""
    if IS_WIN:
        default = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / "jaix"
    else:
        default = Path.home() / ".local" / "share" / "jaix"
    return _env_path("JAIX_HOME", default)


def data_dir():
    """jaix의 기록·상태·받은 파일. Windows는 프로그램 폴더(제거하면 통째로 지워짐)와 나눠 %LOCALAPPDATA%\\jaix,
    그 밖에는 jaix_home과 같은 곳."""
    if IS_WIN:
        default = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "jaix"
    else:
        default = jaix_home()
    return _env_path("JAIX_DATA", default)


# 예전(v2026.10.27 까지) 프로그램 폴더에 두던 데이터. data_dir로 옮긴다
DATA_NAMES = ("setup.log", "setup-status.json", "guide.txt", "update.log", "update.log.1", "update-status.json",
              "codex-installed.json", "codex-mcp.json", "config.json", "uv-python.json", "gw")


def migrate_data():
    """프로그램 폴더에 남은 예전 데이터를 data_dir로 옮긴다. 새 자리에 이미 있으면 그쪽을 믿고 건드리지 않는다."""
    old, new = jaix_home(), data_dir()
    if old == new or not old.is_dir():
        return []
    moved = []
    for name in DATA_NAMES:
        src, dst = old / name, new / name
        try:
            if src.exists() and not dst.exists():
                new.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved.append(name)
        except OSError:
            pass  # 못 옮기면 새로 시작한다(기록일 뿐이다)
    return moved


def exe_dir():
    """설치본(PyInstaller)이면 jaix.exe 가 있는 폴더({app}\\jaix), 아니면 None."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else None


def self_command(windowless=False):
    """jaix 자신을 다시 부르는 명령. 설치본이면 jaix.exe, windowless면 옆의 창 없는 jaixw.exe(있으면)."""
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "jaix"]
    exe = Path(sys.executable)
    quiet = exe.with_name("jaixw.exe")
    return [str(quiet if windowless and IS_WIN and quiet.is_file() else exe)]


def bin_dir():
    return jaix_home() / "bin"


def launch_agents_dir():
    """macOS 로그온 자동 갱신(LaunchAgent) 파일을 두는 곳."""
    return _env_path("JAIX_LAUNCH_AGENTS", Path.home() / "Library" / "LaunchAgents")


def npm_global_bin():
    """npm 전역 설치(npm i -g)가 실행파일 바로가기(.cmd)를 두는 곳. Node를 PC 전체로 깔면 이 폴더가
    사용자 PATH에 없을 수 있다(jaix-kit#21). Windows 외에는 None(PATH로 찾는다)."""
    if IS_WIN:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "npm"
    return None


def which(name):
    """PATH → npm 전역 폴더(Windows) 순. Windows는 PATHEXT로 name.cmd·name.exe 를 찾는다."""
    exe = shutil.which(name)
    npm = npm_global_bin()
    return exe or (shutil.which(name, path=str(npm)) if npm and npm.is_dir() else None)


def winget_links():
    """winget 사용자 범위 설치가 실행파일 바로가기를 두는 곳(winget이 사용자 PATH에 넣는다)."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Microsoft" / "WinGet" / "Links"


def desktop_claude_code_roots():
    """Claude Desktop이 Code 탭용으로 내려받는 Claude Code 바이너리 폴더들(claude-code/<버전>/...).

    Windows MSIX(2026-10 실측, jaix-kit#19): 실제 위치는 %LOCALAPPDATA%\\Claude-Data\\claude_<id>\\claude-code.
    재시작 전엔 MSIX 가상화 위치(Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude\\claude-code)에 있을 수 있다.
    %APPDATA%\\Claude 는 예전(비 MSIX) 설치본.
    """
    if IS_WIN:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return [*sorted(local.glob("Claude-Data/claude_*/claude-code")),
                *sorted(local.glob("Packages/Claude_*/LocalCache/Roaming/Claude/claude-code")),
                roaming / "Claude" / "claude-code"]
    if IS_MAC:
        return [Path.home() / "Library" / "Application Support" / "Claude" / "claude-code"]
    return [Path.home() / ".config" / "Claude" / "claude-code"]


def desktop_installed():
    """Claude 데스크톱 앱이 이 사용자에게 있는가(Cowork·Code 탭)."""
    if IS_WIN:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return any(local.glob("Packages/Claude_*")) or any(local.glob("Claude-Data/claude_*")) \
            or (local / "AnthropicClaude").is_dir()
    if IS_MAC:
        return Path("/Applications/Claude.app").is_dir() or (Path.home() / "Applications" / "Claude.app").is_dir()
    return False


def managed_settings_files():
    """관리자 배포(managed settings) 파일 후보. 관리자 콘솔이 내려준 것은 claude_dir()/remote-settings.json."""
    if IS_WIN:
        roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClaudeCode"]
    elif IS_MAC:
        roots = [Path("/Library/Application Support/ClaudeCode")]
    else:
        roots = [Path("/etc/claude-code")]
    files = [claude_dir() / "remote-settings.json"]
    for root in roots:
        files.append(root / "managed-settings.json")
        drop_in = root / "managed-settings.d"
        if drop_in.is_dir():
            files.extend(sorted(drop_in.glob("*.json")))
    return files
