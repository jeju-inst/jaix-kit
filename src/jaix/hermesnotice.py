"""JAIX 새 판 알림을 Hermes 봇으로: 게이트웨이 훅을 깔고, 훅이 부르면 소유자 DM 에 한 줄 보낸다.

설치본은 로그온 자동 갱신이 없어(#46) 새 판이 나와도 아무도 모르고 지나갔다(2026-11-25). Hermes 게이트웨이는
로그온 때 켜져 계속 도니, 그 훅(~/.hermes/hooks/jaix-notice)이 켜질 때와 대화가 끝날 때 — 한 시간에 한 번만 —
`jaix notice --for hermes --send` 를 뒤에서 돌린다. 새 판이면 jaix 가 봇 토큰으로 소유자 DM 에 보낸다(LLM 안 씀).
설치는 하지 않는다 — 받기·설치는 시작 메뉴 'JAIX 업데이트'(서명 없는 설치기의 무인 실행은 Defender 위험, #46).
"""
from jaix import paths

HOOK = "jaix-notice"

HOOK_YAML = """name: jaix-notice
description: JAIX 새 판이 나오면 내 슬랙 DM 으로 한 줄 알림(설치는 하지 않음). jaix 가 깔고 jaix update 가 덮어씀.
events:
  - gateway:startup
  - agent:end
"""

# 훅 본문. __CMD__ 자리에 jaix 를 부르는 명령(목록)이 들어간다.
HANDLER = """# jaix 가 깐 Hermes 훅(jaix-kit src/jaix/hermesnotice.py). jaix update 가 덮어씁니다.
# 게이트웨이가 켜질 때와 대화가 끝날 때(한 시간에 한 번만) jaix 에 새 판 알림을 맡긴다. 실패해도 아무 일 없다.
import subprocess
import threading
import time

CMD = __CMD__
GAP = 60 * 60
STARTUP_DELAY = 120  # 로그온 직후 네트워크가 올라올 틈
_last = [0.0]


def _run(delay):
    time.sleep(delay)
    try:
        subprocess.run(CMD + ["notice", "--for", "hermes", "--send"], capture_output=True, timeout=120,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def handle(event_type, context):
    now = time.time()
    if now - _last[0] < GAP:
        return
    _last[0] = now
    delay = STARTUP_DELAY if event_type == "gateway:startup" else 0
    threading.Thread(target=_run, args=(delay,), daemon=True).start()
"""


def hook_dir():
    return paths.hermes_home() / "hooks" / HOOK


def files(cmd=None):
    cmd = list(cmd or paths.self_command())
    return {"HOOK.yaml": HOOK_YAML, "handler.py": HANDLER.replace("__CMD__", repr(cmd))}


def install(log, cmd=None):
    """훅을 깐다(내용이 같으면 그대로). 게이트웨이가 다음에 켜질 때부터 돈다. 실패해도 막지 않는다."""
    want, d = files(cmd), hook_dir()
    try:
        if all((d / n).is_file() and (d / n).read_text(encoding="utf-8") == t for n, t in want.items()):
            return True
        d.mkdir(parents=True, exist_ok=True)
        for n, t in want.items():
            (d / n).write_text(t, encoding="utf-8")
    except OSError as e:
        log(f"    새 판 알림 훅: 깔지 못함({type(e).__name__}) — 다음 jaix update 때 다시")
        return False
    log("    새 판 알림: JAIX 새 판이 나오면 내 Hermes 봇이 DM 으로 알려 줌")
    return True


def send_owner(text, call=None):
    """소유자 DM(SLACK_HOME_CHANNEL)에 봇 이름으로 한 줄 보낸다. 성공하면 True. 토큰은 기록하지 않는다."""
    from jaix import hermesbot  # 순환을 피한다(hermesbot 이 install 을 부른다)
    if not hermesbot.linked_id():
        return False
    token, home = hermesbot.env_value("SLACK_BOT_TOKEN"), hermesbot.env_value("SLACK_HOME_CHANNEL")
    if not (token and home):
        return False
    try:
        res = (call or hermesbot.slack_call)("chat.postMessage", token, channel=home, text=text)
    except Exception:  # noqa: BLE001 — 오프라인 등. 다음에 다시
        return False
    return bool(isinstance(res, dict) and res.get("ok"))
