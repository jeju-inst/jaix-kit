"""사용자 PATH(HKCU\\Environment) 다루기. 시스템 PATH는 절대 건드리지 않는다.

Windows가 아니면 레지스트리 대신 지금 프로세스의 PATH만 고친다(맥은 개발·AI센터용).
"""
import os

from jaix.paths import IS_WIN

if IS_WIN:
    import ctypes
    import winreg


def _norm(path):
    return os.path.normcase(os.path.normpath(os.path.expandvars(str(path)))).rstrip("\\/")


def user_path_entries():
    if not IS_WIN:
        return []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return []
    return [p for p in value.split(";") if p]


def _write_user_path(entries):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(entries))
    _broadcast()


def _broadcast():
    """열려 있는 탐색기·새 터미널이 바뀐 PATH를 보게 WM_SETTINGCHANGE를 알린다."""
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                             SMTO_ABORTIFHUNG, 5000, ctypes.byref(result))


def in_user_path(path):
    return _norm(path) in {_norm(p) for p in user_path_entries()}


def add_to_path(dirs, dry_run=False):
    """dirs를 사용자 PATH 끝에 넣고(이미 있으면 건너뜀) 지금 프로세스 PATH 앞에도 붙인다. 새로 넣은 것을 돌려준다."""
    dirs = [str(d) for d in dirs]
    current = os.environ.get("PATH", "").split(os.pathsep)
    for d in reversed(dirs):
        if _norm(d) not in {_norm(p) for p in current if p}:
            current.insert(0, d)
    if not dry_run:
        os.environ["PATH"] = os.pathsep.join(current)
    if not IS_WIN:
        return []
    entries = user_path_entries()
    have = {_norm(p) for p in entries}
    added = [d for d in dirs if _norm(d) not in have]
    if added and not dry_run:
        _write_user_path(entries + added)
    return added


def remove_from_path(prefix):
    """prefix 아래 경로를 사용자 PATH에서 뺀다(설치본 제거용). 뺀 것을 돌려준다."""
    if not IS_WIN:
        return []
    root = _norm(prefix)
    entries = user_path_entries()
    keep = [p for p in entries if not (_norm(p) == root or _norm(p).startswith(root + "\\"))]
    removed = [p for p in entries if p not in keep]
    if removed:
        _write_user_path(keep)
    return removed


def refresh_process_path():
    """winget 등 다른 설치기가 사용자 PATH를 바꾼 뒤 지금 프로세스에도 반영한다."""
    if not IS_WIN:
        return
    links = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links")
    extra = [os.path.expandvars(p) for p in user_path_entries()] + [links]
    current = os.environ.get("PATH", "").split(os.pathsep)
    have = {_norm(p) for p in current if p}
    os.environ["PATH"] = os.pathsep.join(current + [p for p in extra if _norm(p) not in have])
