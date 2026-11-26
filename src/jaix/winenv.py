"""사용자 PATH(HKCU\\Environment) 다루기. 시스템 PATH는 절대 건드리지 않는다.

Windows가 아니면 레지스트리 대신 지금 프로세스의 PATH만 고친다(맥은 개발·AI센터용).
"""
import os
import re

from jaix import paths
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


def system_path_entries():
    if not IS_WIN:
        return []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
    except OSError:
        return []
    return [p for p in value.split(";") if p]


def fresh_path():
    """새로 연 명령창이 보게 될 PATH(시스템 + 사용자, 레지스트리 기준). Windows 가 아니면 지금 PATH.
    설치 전부터 떠 있던 창·앱(Claude 앱 포함)은 옛 PATH 를 물려받아 이것과 다를 수 있다."""
    if not IS_WIN:
        return os.environ.get("PATH", "")
    return os.pathsep.join(os.path.expandvars(p) for p in [*system_path_entries(), *user_path_entries()])


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


def get_user_env(name):
    """사용자 환경변수(HKCU\\Environment) 값. 없거나 Windows 가 아니면 None."""
    if not IS_WIN:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def set_user_env(name, value):
    """사용자 환경변수를 쓰고 지금 프로세스에도 넣는다. 새로 연 앱·창부터 보인다. 바꿨으면 True."""
    os.environ[name] = str(value)
    if not IS_WIN or get_user_env(name) == str(value):
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
    _broadcast()
    return True


def remove_user_env_under(name, prefix):
    """사용자 환경변수 name 이 prefix 아래를 가리킬 때만 지운다(사용자가 바꿔 둔 값은 둔다). 지웠으면 True."""
    value = get_user_env(name)
    if not value:
        return False
    root = _norm(prefix)
    if not (_norm(value) == root or _norm(value).startswith(root + "\\")):
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, name)
    _broadcast()
    os.environ.pop(name, None)
    return True


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


def remove_entry(path):
    """사용자 PATH에서 path 와 같은 항목만 뺀다(그 아래 폴더는 둔다). 뺀 것을 돌려준다."""
    if not IS_WIN:
        return []
    entries = user_path_entries()
    keep = [p for p in entries if _norm(p) != _norm(path)]
    removed = [p for p in entries if p not in keep]
    if removed:
        _write_user_path(keep)
    return removed


def drop_old_exe_dir():
    """예전(onefile) 설치본이 사용자 PATH에 넣은 프로그램 폴더 자체를 뺀다. 지금 설치본은 jaix.exe 를 그 아래
    jaix\\ 에 두므로 그 항목은 빈 자리를 가리킨다(jaix-kit#46). 그 자리에 jaix.exe 가 아직 있으면 둔다."""
    here, home = paths.exe_dir(), paths.jaix_home()
    if here is None or _norm(here) == _norm(home) or (home / "jaix.exe").exists():
        return []
    return remove_entry(home)


def refresh_process_path():
    """winget 등 다른 설치기가 사용자 PATH를 바꾼 뒤 지금 프로세스에도 반영한다."""
    if not IS_WIN:
        return
    extra = [os.path.expandvars(p) for p in user_path_entries()] + [str(paths.winget_links())]
    current = os.environ.get("PATH", "").split(os.pathsep)
    have = {_norm(p) for p in current if p}
    os.environ["PATH"] = os.pathsep.join(current + [p for p in extra if _norm(p) not in have])


# --- 사용자 PATH 길이(11/26 이중화 PC) -------------------------------------------------------------------
# 사용자 Path(REG_EXPAND_SZ)가 너무 길면 Windows 가 새로 여는 창에 사용자 PATH 를 통째로 싣지 않는다.
# 그러면 jaix·claude·WindowsApps 가 한꺼번에 사라지고, 안내문의 "새 창을 여세요" 가 통하지 않는다.
# 실측: 사용자 Path 3279자(71항목) PC 의 새 PowerShell 창 PATH 가 시스템 PATH(1218자)뿐이었다.
# 한도는 2047자로 본다(펼치기 전·후 어느 쪽에 걸리는지 확정하지 못해 둘 다 이 안에 들게 줄인다).
PATH_LIMIT = 2047
_LOCAL_DRIVE = re.compile(r"^[A-Za-z]:\\")
_SHORT_VARS = ("LOCALAPPDATA", "APPDATA", "USERPROFILE")  # 긴 접두부터 — %LOCALAPPDATA% 가 %USERPROFILE%\AppData\Local 보다 짧다


def _joined(entries):
    return ";".join(entries)


def _expanded_len(entries, env=None):
    env = os.environ if env is None else env
    def expand(p):
        for k in _SHORT_VARS + ("SystemRoot", "ProgramFiles", "ProgramData"):
            p = p.replace(f"%{k}%", env.get(k, f"%{k}%"))
        return p
    return len(_joined(expand(p) for p in entries))


def plan_shrink(entries, system_entries, exists, env=None, limit=PATH_LIMIT):
    """사용자 PATH 를 한도 안으로 줄이는 계획(순수 함수). (새 항목 목록, [(뺀 항목, 이유)]).
    1) 빈 칸·중복 빼기 2) 시스템 PATH 에도 있는 것 빼기 3) 아직 길면, 이 PC 로컬 드라이브에 없는 폴더 빼기
    (드라이브째 없는 것·네트워크 경로·%변수%가 안 풀리는 것은 두기) 4) 아직 길면 사용자 폴더 아래 AppData\\Local 같은 앞부분을
    %LOCALAPPDATA% 로 줄여 쓰기(뜻은 같다). 순서·다른 항목은 그대로 둔다."""
    env = os.environ if env is None else env
    removed, keep, seen = [], [], set()
    system = {_norm(p) for p in system_entries}
    for p in entries:
        n = _norm(p) if p.strip() else ""
        if not n:
            continue
        if n in seen:
            removed.append((p, "중복"))
        elif n in system:
            removed.append((p, "시스템 PATH 에 이미 있음"))
        else:
            seen.add(n)
            keep.append(p)
    too_long = lambda e: len(_joined(e)) > limit or _expanded_len(e, env) > limit
    if too_long(keep):
        nxt = []
        for p in keep:
            full = os.path.expandvars(p)
            # 드라이브는 있는데 폴더가 없을 때만 — 빼 둔 USB·외장 드라이브(E: 등)의 항목은 지금 안 보일 뿐이다
            if "%" not in full and _LOCAL_DRIVE.match(full) and exists(full[:3]) and not exists(full):
                removed.append((p, "없는 폴더"))
            else:
                nxt.append(p)
        keep = nxt
    if len(_joined(keep)) > limit:
        short = []
        for p in keep:
            for k in _SHORT_VARS:
                base = env.get(k)
                if base and _norm(p).startswith(_norm(base) + "\\"):
                    p = f"%{k}%" + p[len(base.rstrip("\\/")):]
                    break
            short.append(p)
        keep = short
    return keep, removed


def shrink_user_path(log=print, dry_run=False):
    """사용자 PATH 가 한도를 넘으면 원래 값을 jaix 기록 폴더에 남기고 줄인다. 바꿨으면 True."""
    if not IS_WIN:
        return False
    entries = user_path_entries()
    if len(_joined(entries)) <= PATH_LIMIT and _expanded_len(entries) <= PATH_LIMIT:
        return False
    keep, removed = plan_shrink(entries, system_path_entries(), os.path.isdir)
    before, after = len(_joined(entries)), len(_joined(keep))
    log(f"  사용자 PATH 가 너무 깁니다({before}자, {len(entries)}개): 새 창이 PATH 를 통째로 못 받습니다. 줄입니다.")
    for p, why in removed:
        log(f"    뺌({why}): {p}")
    if keep != entries:
        if dry_run:
            log(f"  (예정) {before}자 → {after}자")
            return False
        import datetime
        backup = paths.data_dir() / f"path-backup-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(_joined(entries), encoding="utf-8")
        _write_user_path(keep)
        log(f"  {before}자 → {after}자. 원래 값: {backup}")
    if len(_joined(keep)) > PATH_LIMIT or _expanded_len(keep) > PATH_LIMIT:
        log(f"  아직 깁니다({after}자). 안 쓰는 프로그램의 PATH 항목을 '환경 변수 편집'에서 지우거나 AI센터에 알려 주세요.")
    return keep != entries


def path_length_state():
    """(상태, 사용자 PATH 글자 수): ok · long. Windows 가 아니면 ok."""
    if not IS_WIN:
        return "ok", 0
    entries = user_path_entries()
    n = len(_joined(entries))
    return ("long" if n > PATH_LIMIT or _expanded_len(entries) > PATH_LIMIT else "ok"), n


# --- PowerShell 7 창에서 부를 때(jaix-kit#205) ----------------------------------------------------------
# PS7(pwsh) 은 자기 모듈 폴더(Documents\PowerShell\Modules, Program Files\PowerShell\…)를 PSModulePath 앞에 붙여
# 자식에게 물려준다. jaix 가 그 창에서 Windows PowerShell 5.1(mail-setup.ps1·Hermes 설치 스크립트)을 부르면
# 5.1 이 PS7 용 Microsoft.PowerShell.Security 를 읽다 실패한다(ConvertTo-SecureString CouldNotAutoloadMatchingModule).
# jaix 자신은 PSModulePath 를 쓰지 않으므로, 시작할 때 PS7 폴더만 빼 두면 모든 자식이 깨끗한 값을 받는다.
# 다른 항목(기관이 넣은 모듈 경로 등)은 그대로 둔다. pwsh 는 시작할 때 자기 폴더를 다시 붙이므로 영향이 없다.
def _is_ps7_module_dir(entry):
    parts = [p for p in _norm(entry).lower().replace("/", "\\").split("\\") if p]
    return "powershell" in parts  # WindowsPowerShell 은 다른 이름이라 걸리지 않는다


def clean_psmodulepath(env=None):
    """env(기본 os.environ)의 PSModulePath 에서 PS7 모듈 폴더를 뺀다. 바뀌었으면 True. 다 빠지면 변수를 지운다
    (5.1 은 변수가 없으면 기본값을 스스로 만든다)."""
    env = os.environ if env is None else env
    value = env.get("PSModulePath")
    if not value:
        return False
    entries = [e for e in value.split(";") if e]
    keep = [e for e in entries if not _is_ps7_module_dir(e)]
    if len(keep) == len(entries):
        return False
    if keep:
        env["PSModulePath"] = ";".join(keep)
    else:
        env.pop("PSModulePath", None)
    return True
