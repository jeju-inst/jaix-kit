"""문제 보고·실패 기록에 남기는 글에서 비밀·개인 식별 값을 가린다.

구성원이 `jaix report` 출력을 슬랙·GitHub 이슈(공개 저장소)에 그대로 붙이므로, 붙여도 되는 글로 만든다.
가리는 것: 슬랙 토큰(xox?-·xapp-), OpenAI 류 키(sk-), GitHub 토큰, JWT, `token=…` 꼴의 값, 길고 무작위해 보이는 값,
사용자 폴더 이름(C:\\Users\\<이름> → %USERPROFILE%), 슬랙 ID(U…·D…·C…·W…·G…), 메일 주소의 앞부분.
git 커밋(16진수만)·판 번호는 원인 파악에 쓰므로 두고, 틀릴 때는 더 가리는 쪽으로 틀린다.
"""
import re
from pathlib import Path

MASK = "***"

_SLACK_TOKEN = re.compile(r"\b(xox[abpers]|xapp)-[A-Za-z0-9-]+")
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_GITHUB = re.compile(r"\b(gh[pousr]|github_pat)_[A-Za-z0-9_]{16,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
# `token: x`·`"api_key": "x"`·`password=x` — 이름은 두고 값만. `Authorization: Bearer x` 는 Bearer 뒤를
_NAMED = re.compile(r"""(?ix)
    (\b[\w.-]*(?:token|secret|password|passwd|api[_-]?key|cookie|credential)[\w.-]*(?:\\?["'])?\s*[:=]\s*)
    (?:(\\?["'])((?:(?!\2)(?:\\.|[^\\\n]))*)\2  # 따옴표 값(JSON 안의 \" 포함): 닫는 따옴표까지 통째로(Codex #189 P1). 두 갈래가 겹치지 않아 선형
     |((?:[^\s"',}\\]|\\(?!["']))+))      # 따옴표 없는 값: 공백(또는 JSON 의 \" ) 전까지""")
# 비밀이 아닌 것으로 두는 값: 가림 표시 자체와 완전한 자리표시(%VAR%·<값>)만(Codex #189 P1)
_PLACEHOLDER = re.compile(r"\*\*\*|%[A-Za-z_][A-Za-z0-9_]*%|<[^<>\s]+>")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
# 경로 구분자(/)는 넣지 않는다 — 긴 경로가 통째로 가려지지 않게
_LONG = re.compile(r"(?<![A-Za-z0-9_\-+=])[A-Za-z0-9_\-+=]{32,}(?![A-Za-z0-9_\-+=])")
_USER_DIR = re.compile(r"""(?i)\b[A-Z]:(\\\\|\\|/)Users(?:\\\\|\\|/)[^\\/\s"':*?<>|]+""")
_POSIX_HOME = re.compile(r"(?<![\w.])/(?:Users|home)/[^/\s\"':]+")
_SLACK_ID = re.compile(r"\b[UDCWG](?=[A-Z0-9]*\d)[A-Z0-9]{8,12}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def _long(m):
    s = m.group(0)
    if len(s) in (40, 64) and re.fullmatch(r"[0-9a-fA-F]+", s):  # git 커밋·sha256 — 판·지문일 뿐 비밀이 아니다
        return s
    if not (re.search(r"[A-Za-z]", s) and re.search(r"\d", s)):  # 글자만·숫자만(경로 조각·긴 이름)은 무작위가 아니다
        return s
    return MASK


def _named(m):
    quote, value = m.group(2) or "", m.group(3) if m.group(2) else m.group(4)
    if not value or _PLACEHOLDER.fullmatch(value):
        return m.group(0)
    return f"{m.group(1)}{quote}{MASK}{quote}"


def _home_dirs():
    try:
        home = str(Path.home())
    except (RuntimeError, KeyError):
        return []
    return [home, home.replace("\\", "/"), home.replace("\\", "\\\\")] if len(home) > 3 else []


def redact_json(obj):
    """JSON 으로 내보낼 값의 문자열을 하나하나 가린다. 직렬화하면 따옴표가 \\" 로 바뀌어 이름 붙은 비밀을 놓칠 수
    있으므로(Codex #189 P1) 직렬화 전에 가린다."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_json(v) for v in obj]
    return obj


def redact(text):
    """text 의 비밀·개인 식별 값을 가린 글. 여러 번 해도 같다."""
    if not text:
        return text or ""
    s = str(text)
    for home in _home_dirs():  # 사용자 폴더가 Users 아래가 아니어도(도메인 PC 등) 가린다
        s = s.replace(home, "%USERPROFILE%")
    s = _USER_DIR.sub(lambda m: "%USERPROFILE%", s)
    s = _POSIX_HOME.sub("~", s)
    s = _SLACK_TOKEN.sub(lambda m: f"{m.group(1)}-{MASK}", s)
    s = _SK.sub(f"sk-{MASK}", s)
    s = _GITHUB.sub(lambda m: f"{m.group(1)}_{MASK}", s)
    s = _JWT.sub(MASK, s)
    s = _NAMED.sub(_named, s)
    s = _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", s)
    s = _LONG.sub(_long, s)
    s = _SLACK_ID.sub(lambda m: f"{m.group(0)[0]}{MASK}", s)
    s = _EMAIL.sub(lambda m: f"{MASK}@{m.group(1)}", s)
    return s
