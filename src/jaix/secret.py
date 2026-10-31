"""숨김 입력: 한 글자마다 *를 찍어 들어가는 것이 보이게 한다(사용자 피드백 2026-10-30 — getpass 는 아무 반응이 없어
붙여넣기가 됐는지 알 수 없었다). 값 자체는 어디에도 찍지 않고, 확인되면 길이만 보인다.

맥·리눅스는 termios raw, Windows 는 msvcrt.getwch. 터미널이 아니면(파이프·시험) getpass 로 떨어진다.
"""
import getpass
import os
import sys

from jaix.paths import IS_WIN

BACKSPACE = {"\x08", "\x7f"}
ENTER = {"\r", "\n"}


class Cancelled(KeyboardInterrupt):
    pass


def _feed(chars, out):
    """키 입력 흐름을 받아 값을 모은다. 글자마다 *, 백스페이스는 지운다. Enter 에서 끝. (순수 — 시험용)"""
    buf = []
    for ch in chars:
        if ch in ENTER:
            break
        if ch == "\x03":  # Ctrl+C
            raise Cancelled()
        if ch in ("\x04", "\x1a"):  # Ctrl+D·Ctrl+Z: 비었을 때만 취소(gw login 과 같게)
            if not buf:
                raise EOFError()
            continue
        if ch == "\x15":  # Ctrl+U: 지금까지 친 것을 모두 지움(raw 모드라 터미널이 대신 해 주지 않는다)
            out.write("\b \b" * len(buf))
            buf.clear()
        elif ch in BACKSPACE:
            if buf:
                buf.pop()
                out.write("\b \b")
        elif ch in ("\x00", "\xe0"):  # Windows 의 기능키 앞 글자 — 다음 글자와 함께 버린다
            next(chars, None)
        elif ch.isprintable():
            buf.append(ch)
            out.write("*")
        out.flush()
    return "".join(buf)


def _read_posix(fd, out, prompt):
    """raw 모드로 바꿔 읽고 반드시 되돌린다(제너레이터로 두면 되돌림이 늦어질 수 있어 함수 하나로)."""
    import termios
    import tty
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd, termios.TCSANOW)  # 기본값 TCSAFLUSH 는 프롬프트 직후 미리 붙여 넣은 글자를 버린다
        # 프롬프트는 에코를 끈 뒤에 띄운다 — 먼저 띄우면 그 사이 붙여 넣은 토큰이 평문으로 찍힌다(getpass 와 같은 순서)
        out.write(prompt)
        out.flush()

        def chars():
            while True:
                data = os.read(fd, 1024).decode("utf-8", "replace")  # 붙여넣기는 한 번에 여러 글자로 온다
                if not data:
                    return
                yield from data
        return _feed(chars(), out)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_windows(out, prompt):
    import msvcrt
    out.write(prompt)  # getwch 는 에코하지 않는다
    out.flush()

    def chars():
        while True:
            yield msvcrt.getwch()
    return _feed(chars(), out)


def masked_input(prompt, out=None):
    """prompt 를 보이고 값을 받는다. 터미널이면 *를 찍고, 아니면 getpass."""
    out = out or sys.stderr
    stdin = sys.stdin
    if not (stdin and stdin.isatty() and out.isatty()):
        return getpass.getpass(prompt)
    try:
        if IS_WIN:
            import msvcrt  # noqa: F401 — 없으면 getpass 로
        else:
            import termios
            termios.tcgetattr(stdin.fileno())
    except (ImportError, OSError, ValueError):
        return getpass.getpass(prompt)
    try:
        return _read_windows(out, prompt) if IS_WIN else _read_posix(stdin.fileno(), out, prompt)
    finally:
        out.write("\n")
        out.flush()


def ask_secret(label, valid, hint, attempts=3, reader=None, log=print):
    """형식(valid)이 맞을 때까지 묻는다. 틀리면 값은 보이지 않은 채 hint 와 함께 다시 묻는다. 맞으면 길이만 보인다.
    attempts 번 모두 틀리면 None."""
    reader = reader or masked_input  # 부를 때 찾는다(시험이 masked_input 을 바꿔 끼울 수 있게)
    for _ in range(attempts):
        value = reader(f"{label}: ").strip()
        if valid(value):
            log(f"  받음 ({len(value)}자)")
            return value
        log(f"  형식이 맞지 않음 — 다시 붙여 넣으세요 ({hint})")
    return None


def slack_token(prefix, min_len=30):
    """슬랙 토큰 형식: 접두사 + 공백 없는 충분한 길이(실제 xoxb·xapp 는 50자 이상)."""
    return lambda v: v.startswith(prefix) and len(v) >= min_len and not any(c.isspace() for c in v)
