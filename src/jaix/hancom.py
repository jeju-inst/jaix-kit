"""한컴오피스 2022 첫 실행 "사용성 데이터 수집 동의" 창을 미리 "동의 안 함"으로 답해 둔다.

그 계정에서 한글을 처음 띄우면 이 창이 뜬다. hwp2pdf-cli는 한글을 보이지 않게 띄우므로 아무도 못 보고,
약 2분 뒤 "서버 실행에 실패했습니다"로 끝나 rhwp 근사 렌더로 넘어간다(jaix-win 실측 2026-10-30).
답은 계정마다 %APPDATA%\\Hnc\\User\\Common\\120\\optionInfo.xml 에 있고, "동의 안 함"은 두 값이 0이다.

방침(사용자 결정 2026-10-30): **한컴이 깔린 PC에서 이 파일이 없을 때만** 두 값만 든 최소 파일을 쓴다.
파일이 있으면(이미 답했거나 한글이 만든 기본값) 무엇이 들었든 건드리지 않고, "동의"(1)는 쓰지 않는다.
최소 파일은 실측에서 창을 막은 바이트 그대로다(UTF-8 BOM·CRLF·209바이트) — hwp2pdf(z0nam/hwp2pdf#7)도
변환 직전에 같은 파일을 쓴다.
"""
import os
import re
from pathlib import Path

from jaix import runtimes
from jaix.paths import IS_WIN

AREA = "한컴 첫 실행 동의 창"
#: 실측한 한컴오피스 2022 의 옵션 폴더(=COM 서버 경로의 HOffice120). 다른 버전은 키·창이 같은지 확인 전이라 건너뛴다
VERSION = "120"
KEYS = ("EnableUsabilityLog", "EnableUsabilityLogSending")
MINIMAL = "\r\n".join([
    '<?xml version="1.0" encoding="utf-8"?>',
    "<root>",
    "  <Common>",
    "    <OptionInfo>",
    '      <EnableUsabilityLog value="0" />',
    '      <EnableUsabilityLogSending value="0" />',
    "    </OptionInfo>",
    "  </Common>",
    "</root>",
]) + "\r\n"


def option_info():
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Hnc" / "User" / "Common" / VERSION / "optionInfo.xml" if appdata else None


def installed_version():
    """hwp2pdf 가 띄우는 COM 서버(HWPFrame.HwpObject)의 실행 파일 경로에서 HOfficeNNN 을 읽는다.
    예: C:\\Program Files (x86)\\Hnc\\Office 2022\\HOffice120\\bin\\hwp.exe → "120" (namun-ji 실측). 모르면 None."""
    if not IS_WIN:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"HWPFrame.HwpObject\CLSID") as k:
            clsid = winreg.QueryValue(k, None)
    except OSError:
        return None
    for root in (r"CLSID", r"WOW6432Node\CLSID"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{root}\{clsid}\LocalServer32") as k:
                server = winreg.QueryValue(k, None)
        except OSError:
            continue
        ver = version_from_server(server)
        if ver:
            return ver
    return None


def version_from_server(server):
    m = re.search(r"\\HOffice(\d+)\\", server, re.I)
    return m.group(1) if m else None


def present():
    """한컴오피스가 깔린 Windows PC인가(HWPFrame.HwpObject 등록)."""
    return IS_WIN and runtimes.hancom_installed()


def applies():
    """미리 답할 PC인가 — 한컴 PC이고, 실측한 2022(120)일 때만."""
    return present() and installed_version() == VERSION


def answers(path):
    """파일에 기록된 두 값({키: "0"|"1"}). 읽지 못하면 빈 dict."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {}
    out = {}
    for key in KEYS:
        m = re.search(rf'<{key}\s+value="([^"]*)"', text)
        if m:
            out[key] = m.group(1)
    return out


def ensure(log, dry_run=False):
    """한컴 PC이고 파일이 없을 때만 "동의 안 함" 최소 파일을 쓴다. 실패해도 다른 설치는 계속한다."""
    path = option_info()
    if not applies() or path is None:
        return True
    if path.exists():
        log(f"  {AREA}: 이미 답 있음 또는 한글이 만든 설정 — 그대로 둠 ({path})")
        return True
    if dry_run:
        log(f"  {AREA}: '동의 안 함' 기록 예정 ({path})")
        return True
    try:
        created = _create_only(path, MINIMAL.encode("utf-8-sig"))
    except OSError as e:
        log(f"  {AREA}: 기록 실패 — {e} (첫 변환 때 한글 창에 답해야 할 수 있음)")
        return False
    if not created:
        log(f"  {AREA}: 방금 한글이 설정을 만듦 — 그대로 둠 ({path})")
        return True
    log(f"  {AREA}: '동의 안 함'으로 미리 기록 ({path})")
    return True


def _create_only(path, data):
    """path 가 없을 때만 data 로 만든다. 그사이 한글이 만든 파일은 덮어쓰지 않는다(False).

    임시 파일에 다 쓴 뒤 하드 링크로 붙인다 — 링크는 대상이 있으면 실패하고, 반쪽 파일도 남기지 않는다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        return True
    finally:
        tmp.unlink(missing_ok=True)
