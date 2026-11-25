"""Windows 스마트 앱 컨트롤(SAC). 켜져 있으면 서명 없는 exe(jaix 설치기·hwp2pdf-cli 등)를 예외 버튼 없이 막는다
(WinError 4551, 11/25 연구원 PC). 끄는 것 말고는 길이 없어 doctor·업데이트가 원인과 끄는 곳을 알려 준다."""
from jaix.paths import IS_WIN

AREA = "스마트 앱 컨트롤"
BLOCKED = 4551  # ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION: "애플리케이션 제어 정책에서 이 파일을 차단했습니다"
WHERE = "시작 메뉴 → Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤 설정 → 끄기"
_KEY = r"SYSTEM\CurrentControlSet\Control\CI\Policy"
_STATES = {0: "off", 1: "on", 2: "eval"}


def state(read=None):
    """'on'·'eval'·'off', 모르면 None(Windows 아님·값 없음)."""
    if read is None:
        if not IS_WIN:
            return None
        read = _read_registry
    try:
        return _STATES.get(read())
    except OSError:
        return None


def _read_registry():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _KEY) as k:
        return int(winreg.QueryValueEx(k, "VerifiedAndReputablePolicyState")[0])


def blocked(err):
    """OSError 가 응용 프로그램 제어 정책 차단인가."""
    return getattr(err, "winerror", None) == BLOCKED


def hint():
    return f"Windows 스마트 앱 컨트롤이 막았습니다. {WHERE} 후 다시 하세요(백신·SmartScreen 은 그대로 켜져 있음)."


def doctor_rows(read=None):
    st = state(read)
    if st == "on":
        return [("fail", AREA, "켜져 있음 — JAIX 설치기·도구(서명 없음)가 예외 없이 막힙니다", WHERE)]
    if st == "eval":
        return [("warn", AREA, "평가 모드 — Windows 가 곧 켤 수 있고, 켜지면 JAIX 도구가 막힙니다", WHERE)]
    if st == "off":
        return [("ok", AREA, "꺼짐", "")]
    return []
