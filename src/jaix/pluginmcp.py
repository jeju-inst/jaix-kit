"""플러그인의 MCP 서버 정의 읽기 — 루트 .mcp.json 과 plugin.json 의 mcpServers 를 합친다.

Claude Code 플러그인은 MCP 를 두 곳 어디에나 적을 수 있다. korea-rio-mcp 는 v2026.11.21.1 부터 .mcp.json 을 지우고
.claude-plugin/plugin.json 의 mcpServers 로 옮겼다(korea-rio-mcp#9). .mcp.json 만 읽던 jaix 는 그 서버를
Codex 에 등록하지 못하고 selftest 에서도 빠뜨렸다. mcpServers 가 문자열이면 플러그인 폴더 기준 JSON 파일 경로다.
"""
import json
import re
import urllib.error
from pathlib import Path

MCP_JSON = ".mcp.json"
PLUGIN_JSONS = (".claude-plugin/plugin.json", "plugin.json")


def _servers(value):
    """mcpServers 값 → dict. 파일 형식({"mcpServers": {...}})도 받는다."""
    if isinstance(value, dict):
        inner = value.get("mcpServers")
        return dict(inner) if isinstance(inner, dict) else dict(value)
    return {}


def _merge(mcp_json, plugin_jsons, load):
    """.mcp.json 이 먼저, plugin.json 이 뒤(이름이 겹치면 .mcp.json 을 둔다). load(상대경로) → dict 또는 None."""
    out = dict(_servers((mcp_json or {}).get("mcpServers")))
    for pj in plugin_jsons:
        spec = (pj or {}).get("mcpServers")
        if isinstance(spec, str):
            spec = load(spec[2:] if spec.startswith("./") else spec) or {}  # "./" 만 뗀다 — 숨은 폴더(.config) 점은 둔다
        for name, s in _servers(spec).items():
            out.setdefault(name, s)
    return {"mcpServers": out}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def local(root):
    """깔린 플러그인 폴더의 MCP 설정 {"mcpServers": {...}}. 없으면 빈 목록."""
    if not root:
        return {"mcpServers": {}}
    root = Path(root)
    return _merge(_read_json(root / MCP_JSON), [_read_json(root / p) for p in PLUGIN_JSONS],
                  lambda rel: _read_json(root / rel))


def raw_url(plugin, name):
    m = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", plugin.url)
    if not m:
        return None
    sub = f"{plugin.subdir.strip('/')}/" if plugin.subdir else ""
    return f"https://raw.githubusercontent.com/{m.group(1)}/{plugin.sha}/{sub}{name}"


def remote(plugin, fetch):
    """잠금 커밋의 MCP 설정과 실패 여부 (설정, failed). 404 는 '그 파일 없음'이라 실패가 아니다."""
    failed = False

    def get(rel):
        nonlocal failed
        url = raw_url(plugin, rel)
        if not url:
            return None
        try:
            return fetch(url)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                failed = True
        except (urllib.error.URLError, OSError, ValueError):
            failed = True
        return None

    cfg = _merge(get(MCP_JSON), [get(p) for p in PLUGIN_JSONS], get)
    return cfg, failed
