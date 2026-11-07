"""jaix 본체(설치본 jaix.exe·jaixw.exe) 자기 업데이트 — **jaix 가 설치기를 받거나 실행하지 않는다.**

- GitHub releases/latest 를 간격을 두고 확인한다(기본 6시간, 릴리스 본문에 CRITICAL_MARKER 가 있으면 1시간).
- 새 판이면 알리고, 사용자가 원하면 **브라우저로** jaix-setup.exe 를 받게 연다. 사용자가 받은 파일을 직접 실행한다.
  예전에는 jaix 가 updates 폴더로 받아 sha256 확인 뒤 /SILENT 로 띄웠는데, 서명 없는 jaix 가 사용자 폴더의 서명 없는
  exe 를 조용히 실행하는 흐름이 드로퍼 모양이라 Defender 행동 탐지에 걸렸다(jaix-test 11/7: .07.6 을 --self --yes 로
  깐 3초 뒤 updates 사본이 Behavior:Win32/Execution.A!ml. 같은 경로 .07.3·.07.5 는 무사 — 확률적).
  브라우저 다운로드는 Mark-of-the-Web + SmartScreen 평판 경로라 Windows 가 보통의 설치로 다룬다(#139 와 같은 원리:
  서명 없는 jaix 가 스스로 무언가를 실행·상주시키지 않는다).
- 이전 선택(채널·Hermes 모델)은 설치기가 setup-choice.json 을 읽어 체크 기본값으로 둔다(ApplyPreviousChoice).
  열린 jaix 창은 설치기가 닫는다([Setup] CloseApplications=force — 예전 /FORCECLOSEAPPLICATIONS 와 같음).
- 예전 흐름이 updates 폴더에 남긴 jaix-setup-*.exe 는 확인 때 지운다(prune_installers).
- 수동: `jaix update --self`. 점검: doctor 의 "jaix 본체" 줄.
"""
import ctypes
import json
import os
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
RELEASES = f"https://github.com/{REPO}/releases/latest"


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


def prune_installers(log=None):
    """예전 흐름이 updates 폴더에 받아 둔 설치기를 모두 지운다(이제 jaix 는 받지 않는다). 지운 파일 목록."""
    gone = []
    try:
        found = list(updates_dir().glob("jaix-setup-*.exe"))
    except OSError:
        return []
    for f in found:
        try:
            f.unlink()
            gone.append(f)
        except OSError:  # 이미 격리됐거나 잠김 — 다음에 다시
            continue
    if gone and log:
        log(f"jaix 업데이트: 예전에 받아 둔 설치기 {len(gone)}개 지움")
    return gone


def check(force=False, fetch=None, now=None):
    """최신 릴리스를 확인해 상태에 남기고 돌려준다. 간격 안이면(force 아니면) 묻지 않고 지난 상태.
    상태: latest(태그)·newer·url·digest·critical·checked_at·error."""
    prune_installers()
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


def _win_processes(names=JAIX_EXES, with_start=False):
    """[(pid, 실행파일 전체 경로)] — Toolhelp 스냅숏 + QueryFullProcessImageNameW(권한 없는 것은 건너뜀).
    with_start 면 [(pid, 경로, 시작 시각 epoch 초)] (GetProcessTimes)."""
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
            if pe.szExeFile.lower() in names:
                h = k.OpenProcess(0x1000, False, pe.th32ProcessID)  # PROCESS_QUERY_LIMITED_INFORMATION
                if h:
                    buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                    if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        if not with_start:
                            out.append((pe.th32ProcessID, buf.value))
                        else:
                            ft = [wintypes.FILETIME() for _ in range(4)]
                            if k.GetProcessTimes(h, *(ctypes.byref(f) for f in ft)):
                                ticks = (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
                                out.append((pe.th32ProcessID, buf.value, (ticks - 116444736000000000) / 1e7))
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


def open_windows_note():
    n = len(other_jaix())
    return f"\n열려 있는 JAIX 창 {n}개(Hermes 로그인·점검 창 등)는 설치기가 설치 중에 닫습니다." if n else ""


def _open_url(url):
    try:
        if IS_WIN:
            os.startfile(url)  # noqa: S606 — 기본 브라우저
            return True
        import webbrowser
        return bool(webbrowser.open(url))
    except OSError:
        return False


def steps(state):
    """사용자가 할 일(브라우저 다운로드 → 실행 → 설치기)."""
    return [f"브라우저에서 jaix-setup.exe({state.get('latest')})를 받습니다. 받기가 끝나면:",
            "  1) 브라우저의 다운로드 목록에서 [파일 열기]",
            "  2) 'Windows의 PC 보호' 파란 화면이 뜨면 [추가 정보] → [실행]",
            "  3) 설치기: 지난번 고른 AI 가 체크돼 있습니다 — [다음] 을 눌러 끝까지(열린 JAIX 창은 설치기가 닫음)",
            f"브라우저가 안 열리면 여기서 받으세요: {RELEASES}"]


def open_download(state, log, opener=None):
    """새 판 설치기를 브라우저로 받게 연다. jaix 는 파일을 받거나 실행하지 않는다."""
    url = state.get("url") or RELEASES
    ok = (opener or _open_url)(url)
    state["opened"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    for line in steps(state):
        log(line)
    if not ok:
        log("(브라우저를 열지 못했습니다 — 위 주소를 직접 여세요)")
    return ok


def dialog_text(state):
    """로그온 경로는 로그가 파일에만 남는다 — 브라우저 뒤 할 일(SmartScreen·릴리스 주소)을 대화상자 본문에 싣는다."""
    return (f"JAIX 새 판이 있습니다.\n\n지금: {__version__}\n새 판: {state.get('latest')}\n\n"
            f"[예]를 누르면 브라우저가 새 판 설치기를 받습니다.{open_windows_note()}\n"
            + "\n".join(steps(state)[1:]) + "\n\n"
            f"[아니요]를 누르면 다음 로그온 때 다시 묻습니다({GUIDE} 로도 할 수 있습니다).")


def ask_dialog(state):
    """로그온 갱신(창 없는 jaixw)이 묻는 작은 대화상자. [예] → True."""
    if not IS_WIN:
        return False
    text = dialog_text(state)
    MB_YESNO, MB_ICONINFORMATION, MB_SETFOREGROUND, MB_TOPMOST, IDYES = 0x4, 0x40, 0x10000, 0x40000, 6
    try:
        return ctypes.windll.user32.MessageBoxW(None, text, "JAIX 업데이트",
                                                MB_YESNO | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST) == IDYES
    except (AttributeError, OSError):
        return False


def logon_prepare(log, fetch=None):
    """로그온 갱신 첫 단계: 새 판 확인만 한다(받지 않음). 실패해도 갱신을 막지 않는다."""
    if not applies():
        return None
    try:
        state = check(fetch=fetch)
        return state if state.get("newer") else None
    except Exception as e:  # 자기 업데이트 때문에 도구 갱신이 멈추면 안 된다
        log(f"jaix 새 판 확인 중 오류(무시): {e}")
        return None


def logon_offer(state, log, ask=None, opener=None):
    """로그온 갱신 끝: 새 판이 있으면 묻고, [예]면 브라우저로 받게 연다."""
    if not state:
        return False
    if not (ask or ask_dialog)(state):
        state["declined"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        log(f"jaix 새 판 {state.get('latest')}: 사용자가 나중에 하기로 함")
        return False
    return open_download(state, log, opener)


def cmd_self(args, log, fetch=None, opener=None, ask=None):
    """jaix update --self: 지금 확인하고, 새 판이면 물어서(--yes 면 묻지 않고) 브라우저로 설치기를 받게 연다."""
    if not IS_WIN or paths.exe_dir() is None:
        log("jaix 본체 업데이트는 Windows 설치본(jaix-setup)에서만 합니다. 여기서는 새 판을 받아 다시 설치하세요: "
            + RELEASES)
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
    log(f"새 판 {state.get('latest')} 이 있습니다(지금 {__version__}).")
    if dry_run:
        log("--dry-run 이라 브라우저를 열지 않습니다.")
        return 0
    if not getattr(args, "yes", False):
        try:
            answer = (ask or input)("브라우저로 새 판 설치기를 받을까요? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if str(answer).strip().lower() not in ("y", "yes", "예", "ㅛ"):
            log("나중에 하기로 했습니다.")
            return 0
    return 0 if open_download(state, log, opener) else 1


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
