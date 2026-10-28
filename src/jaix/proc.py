"""claude·codex 같은 외부 CLI 실행. Windows npm 전역 설치는 실행파일이 아니라 배치 래퍼(codex.cmd)라서
cmd.exe를 거치는데, list2cmdline은 공백 없는 인자를 따옴표로 감싸지 않아 `mcp>=1.2,<2` 의 `>`·`<` 가
리다이렉션으로 해석된다(jaix-kit#36: "액세스가 거부되었습니다"·"지정된 파일을 찾을 수 없습니다").
- 래퍼가 npm cmd-shim이면 cmd를 거치지 않고 래퍼가 부르는 `node <패키지>.js` 를 직접 부른다.
- 아니면 cmd 특수문자가 든 인자를 큰따옴표로 감싼 명령줄을 직접 만들어 `cmd /d /s /c` 로 넘긴다.
- 출력은 bytes로 받아 UTF-8, 안 되면 OEM 코드페이지(한국어 Windows cp949)로 읽는다 — cmd 오류 문구가 깨지지 않게.
"""
import ctypes
import os
import re
import subprocess
from pathlib import Path

from jaix import paths
from jaix.paths import IS_WIN

# cmd가 따옴표 밖에서 해석하는 문자(리다이렉션·파이프·연결·묶음·구분자·변수)
_CMD_SPECIAL = re.compile(r'[\s"&|<>^(),;=%!]')


def _quote(arg):
    """MSVCRT 규칙(node 등의 argv 파싱)으로 되읽히는 큰따옴표 인용. 특수문자가 없으면 그대로."""
    if arg and not _CMD_SPECIAL.search(arg):
        return arg
    arg = re.sub(r'(\\*)"', r'\1\1\\"', arg)
    arg = re.sub(r'(\\+)$', r'\1\1', arg)
    return f'"{arg}"'


def _is_batch(cli):
    return IS_WIN and Path(cli).suffix.lower() in (".cmd", ".bat")


def _npm_shim(cli):
    """npm cmd-shim 래퍼면 [node, 스크립트]. 래퍼 본문: "%_prog%"  "%dp0%\\node_modules\\…\\bin\\codex.js" %*"""
    try:
        text = Path(cli).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'"%dp0%\\([^"]+\.(?:js|cjs|mjs))"\s+%\*', text, re.I)
    if not m:
        return None
    here = Path(cli).parent
    script = here / m.group(1).replace("\\", "/")  # pathlib는 Windows에서도 / 를 받는다
    node = here / "node.exe"
    node = str(node) if node.is_file() else paths.which("node")
    return [node, str(script)] if node and script.is_file() else None


def command(cli, args):
    """subprocess에 넘길 명령: 실행파일이면 목록 그대로, 배치 래퍼면 node 직접 또는 인용한 cmd 명령줄(문자열)."""
    if not _is_batch(cli):
        return [cli, *args]
    direct = _npm_shim(cli)
    if direct:
        return [*direct, *args]
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    # /s: 바깥 따옴표 한 쌍만 벗기고 나머지는 그대로 실행한다
    return f'"{comspec}" /d /s /c "{" ".join(_quote(a) for a in [cli, *args])}"'


def decode(data):
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if IS_WIN:
        try:
            return data.decode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", errors="replace")
        except (AttributeError, LookupError, OSError):
            pass
    return data.decode("utf-8", errors="replace")


def run(cli, args, timeout=600):
    """(종료 코드, 출력 stdout+stderr). 실행 자체가 안 되면 OSError·TimeoutExpired 를 그대로 올린다."""
    r = subprocess.run(command(cli, args), capture_output=True, creationflags=paths.NO_WINDOW, timeout=timeout)
    return r.returncode, decode(r.stdout) + decode(r.stderr)
