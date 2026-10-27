"""플랫폼별 경로. 환경변수로 바꿀 수 있게 해 시험에서 실제 사용자 설정을 건드리지 않는다."""
import os
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


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
    """jaix가 받은 포터블 런타임을 두는 곳. Windows는 설치본과 같은 %LOCALAPPDATA%\\Programs\\jaix."""
    if IS_WIN:
        default = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / "jaix"
    else:
        default = Path.home() / ".local" / "share" / "jaix"
    return _env_path("JAIX_HOME", default)


def bin_dir():
    return jaix_home() / "bin"


def launch_agents_dir():
    """macOS 로그온 자동 갱신(LaunchAgent) 파일을 두는 곳."""
    return _env_path("JAIX_LAUNCH_AGENTS", Path.home() / "Library" / "LaunchAgents")


def winget_links():
    """winget 사용자 범위 설치가 실행파일 바로가기를 두는 곳(winget이 사용자 PATH에 넣는다)."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Microsoft" / "WinGet" / "Links"


def desktop_claude_code_root():
    """Claude Desktop이 Code 탭용으로 내려받는 Claude Code 바이너리 폴더(claude-code/<버전>/...)."""
    if IS_WIN:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude-code"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude-code"
    return Path.home() / ".config" / "Claude" / "claude-code"


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
