"""로그온 자동 갱신: 로그온할 때마다 `jaix update --quiet`를 돌리는 사용자 범위 예약 작업.

Claude는 마켓플레이스 autoUpdate로 저절로 갱신되지만 Codex·Hermes는 그런 장치가 없어서 jaix가 대신 돈다.
- Windows: 작업 스케줄러 루트에 `jaix-update`. 로그온 트리거를 **이 사용자로** 못박은 XML로 등록한다
  (`schtasks /SC ONLOGON`은 모든 사용자 대상이라 관리자 권한을 요구한다). 하위 폴더를 만들려면 권한이 필요해서 루트에 둔다.
- macOS: ~/Library/LaunchAgents의 LaunchAgent(RunAtLoad). launchd의 PATH는 비어 있다시피 해서 등록할 때 PATH를 적어 둔다.
결과는 jaix_home의 update-status.json·update.log에 남고 doctor가 보여 준다.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from jaix import paths
from jaix.paths import IS_MAC, IS_WIN

TASK_NAME = "jaix-update"
AGENT_LABEL = "kr.re.ji.jaix.update"
LOG_LIMIT = 256 * 1024  # 넘으면 update.log.1로 돌린다


def supported():
    return IS_WIN or IS_MAC


def command():
    """예약 작업이 부를 명령. 설치본(PyInstaller)이면 jaix.exe 자신, 개발 설치면 같은 파이썬의 -m jaix."""
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "jaix"]
    return [*base, "update", "--quiet"]


def status_file():
    return paths.jaix_home() / "update-status.json"


def log_file():
    return paths.jaix_home() / "update.log"


def plist_path():
    return paths.launch_agents_dir() / f"{AGENT_LABEL}.plist"


def _user_id():
    domain, user = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")
    return f"{domain}\\{user}" if domain else user


def task_xml(cmd, user):
    exe, *args = cmd
    arg_text = " ".join(f'"{a}"' if " " in a else a for a in args)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>JAIX 도구를 잠금 버전에 맞춤(로그온 때 jaix update). jaix-setup 제거 시 함께 지워짐</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Delay>PT2M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{escape(exe)}"</Command>
      <Arguments>{escape(arg_text)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def plist_text(cmd, path_env):
    args = "\n".join(f"    <string>{escape(a)}</string>" for a in cmd)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{escape(path_env)}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardErrorPath</key>
  <string>{escape(str(log_file()))}</string>
</dict>
</plist>
"""


def _run(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    tail = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()][-1:] or [""]
    return r.returncode == 0, tail[0][:200]


def registered():
    if IS_WIN:
        return _run(["schtasks", "/Query", "/TN", TASK_NAME])[0]
    if IS_MAC:
        return plist_path().exists()
    return False


def run_mode():
    """등록된 작업의 실행 모드 문제(없으면 None). 세션 0(무인)에서는 한컴 COM이 뜨지 않아(hwp-render 실측)
    반드시 '사용자가 로그온할 때만 실행'(InteractiveToken)·일반 권한이어야 한다. Windows 외에는 늘 None."""
    if not IS_WIN:
        return None  # LaunchAgent는 gui/<uid> 도메인 = 로그온한 사용자 세션
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"], capture_output=True, timeout=60)
        raw = r.stdout
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", errors="replace")
        # 선언의 encoding="UTF-16"이 이미 푼 문자열과 어긋나 파서가 거절하므로 뗀다
        root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text.lstrip("\ufeff")))
    except (OSError, subprocess.TimeoutExpired, ET.ParseError, UnicodeError) as e:
        return f"작업 정의를 읽지 못함: {e}"
    return mode_problem(root)


def mode_problem(root):
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    logon = root.findtext("t:Principals/t:Principal/t:LogonType", default="", namespaces=ns)
    level = root.findtext("t:Principals/t:Principal/t:RunLevel", default="LeastPrivilege", namespaces=ns)
    if logon != "InteractiveToken":
        return f"'로그온할 때만 실행'이 아님({logon or '미지정'}) — 무인 세션에선 한컴 등이 뜨지 않음"
    if level != "LeastPrivilege":
        return f"관리자 권한으로 실행({level})"
    return None


def register(log, dry_run=False):
    """있으면 덮어써서(설치 위치가 바뀌었을 수 있다) 등록한다. 실패해도 설치는 계속한다."""
    if not supported():
        log("  로그온 자동 갱신: 이 OS는 지원 안 함 → 가끔 `jaix update`")
        return False
    cmd = command()
    if dry_run:
        log(f"  로그온 자동 갱신: 등록 예정 ({' '.join(cmd)})")
        return True
    if IS_WIN:
        with tempfile.TemporaryDirectory() as tmp:
            xml = Path(tmp) / "task.xml"
            xml.write_text(task_xml(cmd, _user_id()), encoding="utf-16")  # schtasks /XML은 UTF-16을 읽는다
            ok, msg = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml), "/F"])
    else:
        plist_path().parent.mkdir(parents=True, exist_ok=True)
        plist_path().write_text(plist_text(cmd, os.environ.get("PATH", "/usr/bin:/bin")), encoding="utf-8")
        target = f"gui/{os.getuid()}"
        _run(["launchctl", "bootout", target, str(plist_path())])  # 예전 것을 내려야 새 내용을 읽는다
        ok, msg = _run(["launchctl", "bootstrap", target, str(plist_path())])
    log(f"  로그온 자동 갱신: {'등록함' if ok else '등록 실패 — ' + msg}")
    return ok


def unregister():
    """설치본 제거(jaix cleanup)가 부른다. 없으면 아무 일 없음."""
    if IS_WIN:
        return registered() and _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])[0]
    if IS_MAC and plist_path().exists():
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path())])
        plist_path().unlink()
        return True
    return False


def open_log():
    """--quiet 갱신의 기록 파일. 커지면 하나만 남기고 돌린다."""
    f = log_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists() and f.stat().st_size > LOG_LIMIT:
        f.replace(f.with_name(f.name + ".1"))
    return f


def write_status(problems, error=None):
    data = {"time": datetime.now().isoformat(timespec="seconds"), "ok": not problems and not error,
            "problems": problems, "error": error}
    status_file().parent.mkdir(parents=True, exist_ok=True)
    status_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def last_status():
    try:
        return json.loads(status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
