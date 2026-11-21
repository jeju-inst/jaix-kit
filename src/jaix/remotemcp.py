"""잠금 플러그인의 원격(streamable-HTTP) MCP 서버 (jaix-kit#170).

플러그인 .mcp.json 의 `{"type": "http", "url": …}` 항목. Claude Code 는 플러그인에서 바로 띄우지만 Codex·Hermes 는
jaix 가 각자의 설정에 url 항목으로 적어 준다(codex.write_mcp · hermesbot.write_mcp).
- Hermes 는 Codex 를 고르지 않은 PC 에도 있으므로 Codex 설치본이 아니라 잠금 커밋의 .mcp.json 을 직접 읽는다.
- 읽은 목록은 데이터 폴더에 적어 둔다 — doctor 는 잠금 사본을 받지 않고(오프라인이어도) 이 기록으로 점검한다.
- 접속 확인(probe)은 initialize → tools/list 두 번만 보낸다. 도구는 부르지 않는다(일정 내용을 읽지 않음).
"""
import json
import urllib.error
import urllib.request

from jaix import __version__, net, paths, uvpython

HTTP_TYPES = (None, "http", "streamable-http", "streamable_http")
PROBE_TIMEOUT = 15


def servers_in(mcp_config):
    """.mcp.json 의 원격 HTTP 서버 {이름: {"url": url}}. stdio·sse 는 뺀다."""
    out = {}
    for name, spec in ((mcp_config or {}).get("mcpServers") or {}).items():
        if not isinstance(spec, dict) or "command" in spec:
            continue
        url = spec.get("url")
        if isinstance(url, str) and url.startswith("https://") and spec.get("type") in HTTP_TYPES:
            out[name] = {"url": url}
    return out


def _record():
    return paths.data_dir() / "remote-mcp.json"


def recorded():
    """지난 setup·update 가 잠금에서 읽은 원격 서버 {이름: {"url", "plugin"}}."""
    try:
        return json.loads(_record().read_text(encoding="utf-8")).get("servers") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def from_lock(lock, offline=False, fetch=None):
    """잠금 커밋의 플러그인 .mcp.json 에서 원격 서버를 모은다. 못 받으면(오프라인 등) 지난 기록을 쓴다."""
    if offline:
        return recorded()
    fetch = fetch or net.get_json
    out, failed = {}, False
    for p in lock.plugins:
        url = uvpython._raw_url(p, ".mcp.json")
        if not url:
            continue
        try:
            cfg = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code != 404:  # 404 = MCP 없는 플러그인
                failed = True
            continue
        except (urllib.error.URLError, OSError, ValueError):
            failed = True
            continue
        for name, spec in servers_in(cfg).items():
            out[name] = {**spec, "plugin": p.name}
    if failed and not out:
        return recorded()
    try:
        _record().parent.mkdir(parents=True, exist_ok=True)
        _record().write_text(json.dumps({"servers": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return out


def _post(url, body, session=None, timeout=PROBE_TIMEOUT):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "User-Agent": f"jaix/{__version__}"}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        sid = r.headers.get("Mcp-Session-Id")
        ctype = (r.headers.get("Content-Type") or "").lower()
    if "text/event-stream" in ctype:  # SSE 로 답하는 서버: 마지막 data 줄
        data = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
        raw = data[-1] if data else ""
    return (json.loads(raw) if raw.strip() else {}), sid


def probe(url, timeout=PROBE_TIMEOUT, post=None):
    """(도구 이름 목록, None) 또는 (None, 이유). 이유는 사람이 읽는 한 줄(주소 없이)."""
    post = post or _post
    try:
        init, sid = post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                               "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "jaix", "version": __version__}}}, None, timeout)
        if "error" in init:
            return None, f"초기화 오류 응답: {str(init['error'].get('message'))[:120]}"
        try:
            post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid, timeout)
        except (urllib.error.URLError, OSError, ValueError):
            pass  # 알림은 202·빈 본문 — 무상태 서버는 받지 않기도 한다
        res, _ = post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, sid, timeout)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"접속 못 함({getattr(e, 'reason', e)})"
    except (OSError, ValueError) as e:
        return None, f"접속 못 함({type(e).__name__})"
    if "error" in res:
        return None, f"도구 목록 오류 응답: {str(res['error'].get('message'))[:120]}"
    return [t.get("name") for t in (res.get("result") or {}).get("tools") or []], None
