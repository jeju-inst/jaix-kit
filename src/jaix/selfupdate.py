"""jaix 본체(설치본 jaix.exe·jaixw.exe) 자기 업데이트. 경험 설계는 hwp2pdf(src/hwp2pdf/updater.py)를 따른다.

- 로그온 갱신(jaixw update --quiet)이 GitHub releases/latest 를 간격을 두고 조용히 확인하고(기본 6시간, 릴리스
  본문에 CRITICAL_MARKER 가 있으면 1시간), 새 판이면 jaix-setup.exe 를 updates 폴더로 받아 릴리스 첨부의
  sha256(digest)로 검증해 둔다.
- **조용히 설치하지 않는다.** 갱신이 끝나면 작은 대화상자로 묻고, 사용자가 [예]를 누를 때만 설치기를
  `/JAIXAUTOUPDATE=1` 로 띄운다. 서명 없는 설치기라 무인 다운로드+무인 실행은 Defender 행동 탐지 위험이 크다(#46).
- 받기 실패·검증 실패·격리(파일이 사라짐)는 기록만 하고 다음 로그온에 다시 한다.
- 수동: `jaix update --self`. 점검: doctor 의 "jaix 본체" 줄.
"""
import ctypes
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from jaix import __version__, net, paths
from jaix.paths import IS_WIN

REPO = "jeju-inst/jaix-kit"
ASSET = "jaix-setup.exe"
CHECK_INTERVAL = 6 * 60 * 60
CRITICAL_INTERVAL = 60 * 60
# GitHub 릴리스에는 중요도 칸이 없다 — 릴리스 본문에 이 줄을 넣으면 1시간 간격으로 확인한다(hwp2pdf 와 같은 방식)
CRITICAL_MARKER = "jaix-priority: critical"
GUIDE = "시작 메뉴 'JAIX 업데이트' 또는 명령창에서 jaix update --self"


def updates_dir():
    return paths.data_dir() / "updates"


def state_file():
    return updates_dir() / "state.json"


def choice_file():
    """jaix setup 이 받은 채널·모델. 자기 업데이트가 설치기에 그대로 넘겨 이전 선택을 지킨다."""
    return paths.data_dir() / "setup-choice.json"


def parse_version(value):
    """'v2026.11.05.1' → (2026, 11, 5, 1). 숫자가 아닌 마디에서 멈춘다('0.0.0+dev' → (0, 0))."""
    parts = []
    for part in str(value or "").strip().lstrip("vV").split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def current():
    """설치본의 묶음 버전(태그 빌드만 찍힌다). 개발판(0.0.0+dev)이면 None — 비교하지 않는다."""
    v = parse_version(__version__)
    return None if not v or "+dev" in __version__ or not any(v) else v


def applies():
    """스스로 바꿀 수 있는 것: Windows 설치본(Inno 가 깐 jaix.exe)이고 태그 빌드일 때."""
    return IS_WIN and paths.exe_dir() is not None and current() is not None


def load_state():
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 기록일 뿐이다 — 다음에 다시 확인한다


def due(state, now=None):
    try:
        checked = float(state["checked_at"])
    except (KeyError, TypeError, ValueError):
        return True  # 확인한 적 없음(또는 지난번 실패)
    interval = CRITICAL_INTERVAL if state.get("critical") else CHECK_INTERVAL
    return (time.time() if now is None else now) - checked >= interval


def _fetch():
    # digest 가 API 응답에만 있어 웹 경로(net._web_release)로 물러서지 않는다 — 한도에 걸리면 다음에 다시
    return net.get_json(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=15)


def check(force=False, fetch=None, now=None):
    """최신 릴리스를 확인해 상태에 남기고 돌려준다. 간격 안이면(force 아니면) 묻지 않고 지난 상태.
    상태: latest(태그)·newer·url·digest·critical·checked_at·error."""
    state = load_state()
    if state.get("current") != __version__:  # 그사이 본체가 바뀜(자기 업데이트·수동 설치) — 지난 판정은 버린다
        state.pop("checked_at", None)
    if not force and not due(state, now):
        return _rejudge(state)
    try:
        rel = (fetch or _fetch)()
    except Exception as e:  # 오프라인·한도·GitHub 장애 — checked_at 을 안 바꿔 다음 실행에 다시 한다
        state["error"] = f"확인 실패: {e}"
        save_state(state)
        return _rejudge(state)
    tag = str(rel.get("tag_name") or "")
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == ASSET), None)
    cur = current()
    state.update({
        "checked_at": time.time() if now is None else now,
        "checked": datetime.now().isoformat(timespec="seconds"),
        "current": __version__,
        "latest": tag.lstrip("vV"),
        "newer": bool(cur and parse_version(tag) > cur and asset),
        "critical": CRITICAL_MARKER in str(rel.get("body") or "").lower(),
        "url": (asset or {}).get("browser_download_url"),
        "digest": (asset or {}).get("digest"),
        "error": None if asset else f"{tag} 에 {ASSET} 이 없음",
    })
    save_state(state)
    return state


def _rejudge(state):
    """지난 상태의 newer 를 지금 도는 판에 대고 다시 판단한다(이미 깐 판·더 낮은 판을 권하지 않게)."""
    cur = current()
    state["newer"] = bool(cur and state.get("url") and parse_version(state.get("latest")) > cur)
    return state


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _expected(state):
    d = str(state.get("digest") or "")
    return d.split(":", 1)[1].lower() if d.lower().startswith("sha256:") else None


def installer_path(state):
    return updates_dir() / f"jaix-setup-{state.get('latest')}.exe"


def verified(state):
    """받아 둔 설치기가 있고 digest 와 맞으면 그 경로. 격리로 사라졌거나 다르면 None."""
    want, path = _expected(state), installer_path(state)
    try:
        return path if want and path.is_file() and sha256(path) == want else None
    except OSError:
        return None


def fetch_installer(state, log, download=None):
    """새 판 설치기를 받아 sha256 으로 검증한다. 성공하면 경로, 아니면 None(상태에 이유를 남김)."""
    if not state.get("newer"):
        return None
    if not _expected(state):
        state["error"] = "릴리스 첨부에 sha256 이 없어 받지 않음"
        save_state(state)
        return None
    have = verified(state)
    if have:
        return have
    path = installer_path(state)
    for old in updates_dir().glob("jaix-setup-*.exe"):  # 지난 판 설치기는 지운다
        if old != path:
            old.unlink(missing_ok=True)
    try:
        (download or net.download)(state["url"], path)
        got = sha256(path)
    except Exception as e:  # 끊김·격리(쓰는 중 지워짐·접근 거부)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        state["error"] = f"받기 실패: {e}"
        save_state(state)
        log(f"jaix 새 판 {state.get('latest')} 받기 실패: {e} — 다음에 다시")
        return None
    if got != _expected(state):
        path.unlink(missing_ok=True)
        state["error"] = f"sha256 불일치(받은 것 {got[:12]}…) — 지움"
        save_state(state)
        log(f"jaix 새 판 {state.get('latest')}: {state['error']}")
        return None
    state["error"] = None
    state["downloaded"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    log(f"jaix 새 판 {state.get('latest')} 받아 둠(sha256 확인): {path}")
    return path


def setup_choice():
    """설치기에 넘길 (채널, Hermes 모델). jaix setup 이 남긴 기록이 없으면(v2026.11.05 이전 설치) 흔적으로 추정."""
    try:
        rec = json.loads(choice_file().read_text(encoding="utf-8"))
        channels = [c for c in rec.get("channels") or [] if c in ("claude", "codex", "hermes")]
        if channels:
            return channels, rec.get("hermes_model") or "chatgpt"
    except (OSError, ValueError, AttributeError):
        pass
    from jaix import hermesbot  # 무겁지 않지만 순환을 피한다

    channels = []
    if paths.claude_dir().exists():
        channels.append("claude")
    if (paths.data_dir() / "codex-installed.json").exists() or paths.codex_home().exists():
        channels.append("codex")
    hrec = hermesbot.recorded()
    if hrec.get("status"):
        channels.append("hermes")
    return channels or ["claude"], hrec.get("model") or "chatgpt"


def save_choice(channels, model):
    try:
        choice_file().parent.mkdir(parents=True, exist_ok=True)
        choice_file().write_text(json.dumps({"channels": list(channels), "hermes_model": model}, ensure_ascii=False),
                                 encoding="utf-8")
    except OSError:
        pass


# --- 열려 있는 다른 jaix 창 ---------------------------------------------------------------------------
# 'JAIX Hermes 로그인' 창(Enter 대기)·점검 중인 jaix.exe 가 열려 있으면 jaix 폴더 파일이 잠겨, 설치기가 /SILENT 인데도
# Abort/Retry/Ignore 상자를 띄우고 멈췄다(jaix-win .8→.9, install-2026.11.05.9.log). 콘솔 프로그램은 재시작 관리자가
# 점잖게 닫지 못한다 → 설치기를 띄우기 전에 jaix 가 알리고 닫는다(+ 설치기에 /FORCECLOSEAPPLICATIONS 안전망)
JAIX_EXES = ("jaix.exe", "jaixw.exe")


def _win_processes():
    """[(pid, 실행파일 전체 경로)] — Toolhelp 스냅숏 + QueryFullProcessImageNameW(권한 없는 것은 건너뜀)."""
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.OpenProcess.restype = wintypes.HANDLE

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    snap = k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out = []
    try:
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        ok = k.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.lower() in JAIX_EXES:
                h = k.OpenProcess(0x1000, False, pe.th32ProcessID)  # PROCESS_QUERY_LIMITED_INFORMATION
                if h:
                    buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                    if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        out.append((pe.th32ProcessID, buf.value))
                    k.CloseHandle(h)
            ok = k.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k.CloseHandle(snap)
    return out


def other_jaix(processes=None):
    """이 설치본 폴더의 jaix.exe·jaixw.exe 중 나 말고 떠 있는 것 [(pid, 이름)]."""
    here = paths.exe_dir()
    if not IS_WIN or here is None:
        return []
    try:
        procs = (processes or _win_processes)()
    except (OSError, AttributeError, ValueError):
        return []
    me = os.getpid()
    norm = lambda p: os.path.normcase(os.path.abspath(str(p)))  # noqa: E731
    return [(pid, Path(exe).name) for pid, exe in procs if pid != me and norm(Path(exe).parent) == norm(here)]


def _terminate(pid):
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x0001 | 0x00100000, False, pid)  # PROCESS_TERMINATE | SYNCHRONIZE
    if not h:
        return False
    try:
        ok = bool(k.TerminateProcess(h, 1))
        k.WaitForSingleObject(h, 3000)
        return ok
    finally:
        k.CloseHandle(h)


def close_others(log, find=None, kill=None):
    """다른 jaix 창을 닫는다. 못 닫은 것이 있어도 진행(설치기의 /FORCECLOSEAPPLICATIONS 가 한 번 더 한다)."""
    others = (find or other_jaix)()
    for pid, name in others:
        ok = (kill or _terminate)(pid)
        log(f"jaix 업데이트: 열려 있던 {name}(pid {pid}) {'닫음' if ok else '닫지 못함'}")
    return others


def open_windows_note():
    n = len(other_jaix())
    return f"\n열려 있는 JAIX 창 {n}개(Hermes 로그인·점검 창 등)는 닫고 업데이트합니다." if n else ""


def installer_args(state):
    channels, model = setup_choice()
    args = ["/SILENT", "/CURRENTUSER", "/FORCECLOSEAPPLICATIONS", "/JAIXAUTOUPDATE=1", f"/CHANNELS={','.join(channels)}",
            f"/LOG={updates_dir() / ('install-' + str(state.get('latest')) + '.log')}"]
    if "hermes" in channels:
        args.append(f"/HERMESMODEL={model}")
    return args


def launch(state, log, popen=None, close=None):
    """검증된 설치기를 띄우고 곧장 돌아온다(호출자는 바로 끝나야 설치기가 jaix 폴더를 바꿀 수 있다)."""
    path = verified(state)
    if not path:
        state["error"] = "받아 둔 설치기가 없거나 sha256 이 다름(격리됐을 수 있음) — 다음에 다시 받음"
        save_state(state)
        log(f"jaix 업데이트: {state['error']}")
        return False
    (close or close_others)(log)
    cmd = [str(path), *installer_args(state)]
    flags = (0x00000008 | 0x00000200) if IS_WIN else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        (popen or subprocess.Popen)(cmd, creationflags=flags, close_fds=True, cwd=str(updates_dir()))
    except OSError as e:  # 실행 차단(Defender·SmartScreen)
        state["error"] = f"설치기 실행 실패: {e}"
        save_state(state)
        log(f"jaix 업데이트: {state['error']}")
        return False
    state["launched"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    log(f"jaix 업데이트 설치기 실행: {' '.join(cmd)}")
    return True


def ask_dialog(state):
    """로그온 갱신(창 없는 jaixw)이 묻는 작은 대화상자. [예] → True."""
    if not IS_WIN:
        return False
    text = (f"JAIX 새 판이 있습니다.\n\n지금: {__version__}\n새 판: {state.get('latest')}\n\n"
            f"지금 업데이트할까요? 몇 분 걸리며, 끝나면 알려 드립니다.{open_windows_note()}\n"
            f"[아니요]를 누르면 다음 로그온 때 다시 묻습니다({GUIDE} 로도 할 수 있습니다).")
    MB_YESNO, MB_ICONINFORMATION, MB_SETFOREGROUND, MB_TOPMOST, IDYES = 0x4, 0x40, 0x10000, 0x40000, 6
    try:
        return ctypes.windll.user32.MessageBoxW(None, text, "JAIX 업데이트",
                                                MB_YESNO | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST) == IDYES
    except (AttributeError, OSError):
        return False


def logon_prepare(log, fetch=None, download=None):
    """로그온 갱신 첫 단계: 확인·받기·검증만 한다(묻지 않음). 실패해도 갱신을 막지 않는다."""
    if not applies():
        return None
    try:
        state = check(fetch=fetch)
        if not state.get("newer"):
            return None
        return state if fetch_installer(state, log, download) else None
    except Exception as e:  # 자기 업데이트 때문에 도구 갱신이 멈추면 안 된다
        log(f"jaix 새 판 확인 중 오류(무시): {e}")
        return None


def logon_offer(state, log, ask=None, popen=None):
    """로그온 갱신 끝: 받아 둔 새 판이 있으면 묻고, [예]면 설치기를 띄운다."""
    if not state:
        return False
    if not (ask or ask_dialog)(state):
        state["declined"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        log(f"jaix 새 판 {state.get('latest')}: 사용자가 나중에 하기로 함")
        return False
    return launch(state, log, popen)


def cmd_self(args, log, fetch=None, download=None, popen=None, ask=None):
    """jaix update --self: 지금 확인하고, 새 판이면 받아 검증한 뒤 물어서(--yes 면 묻지 않고) 설치기를 띄운다."""
    if not IS_WIN or paths.exe_dir() is None:
        log("jaix 본체 업데이트는 Windows 설치본(jaix-setup)에서만 합니다. 여기서는 새 판을 받아 다시 설치하세요: "
            f"https://github.com/{REPO}/releases/latest")
        return 1
    if current() is None:
        log(f"개발판(jaix {__version__})이라 본체 업데이트를 하지 않습니다.")
        return 1
    dry_run = getattr(args, "dry_run", False)
    state = check(force=True, fetch=fetch)
    if state.get("error") and not state.get("newer"):
        log(f"새 판을 확인하지 못했습니다: {state['error']}")
        return 1
    if not state.get("newer"):
        log(f"jaix {__version__} — 최신입니다.")
        return 0
    if dry_run:
        log(f"새 판 {state.get('latest')} 이 있습니다(지금 {__version__}). --dry-run 이라 받거나 설치하지 않습니다.")
        return 0
    log(f"새 판 {state.get('latest')} 이 있습니다(지금 {__version__}). 설치기를 받는 중…")
    if not fetch_installer(state, log, download):
        log(f"받지 못했습니다: {state.get('error')}. 잠시 뒤 다시 하거나 "
            f"https://github.com/{REPO}/releases/latest 에서 jaix-setup.exe 를 받아 실행하세요.")
        return 1
    if not getattr(args, "yes", False):
        try:
            note = open_windows_note().strip()
            if note:
                log(note)
            answer = (ask or input)("지금 업데이트할까요? 설치기가 열리고 이 창의 jaix 는 끝납니다 [y/N] ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if str(answer).strip().lower() not in ("y", "yes", "예", "ㅛ"):
            log("나중에 하기로 했습니다.")
            return 0
    return 0 if launch(state, log, popen) else 1


def doctor_status(check_now=True, fetch=None):
    """doctor 한 줄용 (상태, 문구, 고칠 법). 해당 없으면 None."""
    if current() is None:
        return None
    state = check(fetch=fetch) if check_now and applies() else load_state()
    if state.get("newer"):
        return ("warn", f"새 판 {state.get('latest')} 있음 (지금 {__version__})", GUIDE)
    if state.get("latest"):
        return ("ok", f"{__version__} — 최신 (확인 {state.get('checked', '?')})", None)
    if state.get("error"):
        return ("ok", f"{__version__} — 새 판 확인 못 함: {state['error']}", None)
    return ("ok", __version__, None)
