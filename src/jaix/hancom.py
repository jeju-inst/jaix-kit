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
    return Path(appdata) / "Hnc" / "User" / "Common" / "120" / "optionInfo.xml" if appdata else None


def applies():
    return IS_WIN and runtimes.hancom_installed()


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
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(MINIMAL.encode("utf-8-sig"))
        os.replace(tmp, path)
    except OSError as e:
        log(f"  {AREA}: 기록 실패 — {e} (첫 변환 때 한글 창에 답해야 할 수 있음)")
        return False
    finally:
        tmp.unlink(missing_ok=True)
    log(f"  {AREA}: '동의 안 함'으로 미리 기록 ({path})")
    return True
