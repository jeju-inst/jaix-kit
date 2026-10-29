"""이미 깔린 것과 겹치는 도구를 찾는다(doctor 용, 읽기만 한다).

원칙(jaix-kit-dev 10-29, 사용자 승인): 같은 도구가 두 벌이면 알리기만 하고 지우지 않는다. 어느 것을 지울지는
사용자가 고른다. 같은 호스트(Claude·Codex)에 같은 도구가 두 벌 실리면 스킬 설명·MCP 도구 스키마가 매 요청에
두 번 들어가 토큰이 두 배로 든다.

- 겹침: jaix 플러그인이 깔린 호스트에서, 다른 마켓플레이스의 같은 이름 플러그인 · 사용자 스킬 폴더의 같은 이름
  스킬(심링크 포함) · jaix가 쓰지 않은 같은 이름 MCP 서버.
- 상시 분량: 그 호스트에 켜진 MCP 서버·스킬 수로 매 요청에 실리는 분량을 어림한다(TS-TOKEN).
"""
import json
import os
import re
import tomllib
from pathlib import Path

from jaix import claude, codex, paths
from jaix.lock import MARKETPLACE

# 어림 계수(docs/tool-standard.md TS-TOKEN). MCP 서버 하나 = 도구 하나의 상시 예산 상한 3k(TS-TOKEN-1,
# hwp-agent 실측 3,732). 스킬 하나 = frontmatter(name·description) 약 150 토큰.
MCP_TOKENS = 3000
SKILL_TOKENS = 150
# 이 값을 넘으면 알린다: jaix 묶음(플러그인 6개, 각 3k 이하 → 18k 이하)에 도구 네댓 개를 더한 정도.
# 연구원 좌석은 Pro의 약 1.25배라 상시 분량이 크면 사용량 한도에 빨리 닿는다(TS-TOKEN 머리말)
BUDGET = 30000


def norm(name):
    """같은 도구로 볼 이름: 대소문자·구분자(_ . 공백)를 맞추고 끝의 -mcp 를 뗀다(korea_rio ≈ korea-rio-mcp)."""
    n = re.sub(r"[-_.\s]+", "-", str(name)).strip("-").lower()
    return n[:-4] if n.endswith("-mcp") else n


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def plugin_mcp(root):
    """플러그인 폴더의 MCP 서버 이름(.mcp.json, 또는 plugin.json 의 mcpServers)."""
    if not root:
        return set()
    root = Path(root)
    names = set((_read_json(root / ".mcp.json").get("mcpServers") or {}))
    for pj in (root / ".claude-plugin" / "plugin.json", root / "plugin.json"):
        spec = _read_json(pj).get("mcpServers")
        if isinstance(spec, dict):
            names |= set(spec)
    return names


def skill_dirs(base):
    """base 아래 SKILL.md 가 있는 폴더(심링크도 따라간다). 숨은 폴더는 호스트 내장이라 뺀다."""
    base = Path(base) if base else None
    if not base or not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if not d.name.startswith(".") and (d / "SKILL.md").is_file())


def _names(plugin, root):
    """jaix 플러그인이 쓰는 이름: 플러그인 이름 · 저장소 이름 · (깔려 있으면) 스킬·MCP 서버 이름."""
    repo = re.sub(r"\.git$", "", plugin.url.rstrip("/").rsplit("/", 1)[-1]) if plugin.url else ""
    found = {plugin.name, repo} | plugin_mcp(root) | {d.name for d in skill_dirs(Path(root) / "skills" if root else None)}
    return {norm(n) for n in found if n}


def _describe(path):
    path = Path(path)
    return f"{path} → {path.resolve()}" if path.is_symlink() else str(path)


def _same_name(name, names):
    return norm(name) in names


# --- Claude --------------------------------------------------------------------------------------
def claude_json():
    """Claude Code 사용자 범위 MCP 가 있는 파일(CLAUDE_CONFIG_DIR 이면 그 안, 아니면 홈의 .claude.json)."""
    d = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(d) / ".claude.json" if d else Path.home() / ".claude.json"


def _claude_plugins():
    """설치·켜진 Claude 플러그인 {id: 설치 폴더}."""
    data = _read_json(paths.claude_dir() / "plugins" / "installed_plugins.json")
    try:
        enabled = claude.read_json(claude.settings_path()).get("enabledPlugins") or {}
    except (OSError, ValueError):
        enabled = {}
    out = {}
    for pid, recs in (data.get("plugins") or {}).items():
        if enabled.get(pid) is not True or not recs:
            continue
        rec = ([r for r in recs if r.get("scope") == "user"] or recs)[0]
        out[pid] = rec.get("installPath")
    return out


def claude_overlaps(lock):
    """{jaix 플러그인 이름: [겹치는 것 설명]} — Claude에 jaix 판이 깔린 플러그인만 본다."""
    plugins = _claude_plugins()
    mine = {pid: root for pid, root in plugins.items() if pid.endswith(f"@{MARKETPLACE}")}
    user_mcp = _read_json(claude_json()).get("mcpServers") or {}
    out = {}
    for p in lock.plugins:
        if p.id not in mine:
            continue
        names = _names(p, mine[p.id])
        hits = [f"Claude 플러그인 {pid}" for pid in plugins
                if pid not in mine and _same_name(pid.split("@", 1)[0], names)]
        hits += [f"Claude 스킬 {_describe(d)}" for d in skill_dirs(paths.claude_dir() / "skills") if _same_name(d.name, names)]
        hits += [f"Claude MCP '{n}' ({claude_json()})" for n in user_mcp if _same_name(n, names)]
        if hits:
            out[p.name] = hits
    return out


def claude_load():
    """(켜진 MCP 서버 수, 스킬 수) — 사용자 범위 MCP + 켜진 플러그인의 MCP·스킬 + 사용자 스킬 폴더."""
    plugins = _claude_plugins()
    mcp = set(_read_json(claude_json()).get("mcpServers") or {})
    skills = len(skill_dirs(paths.claude_dir() / "skills"))
    for pid, root in plugins.items():
        mcp |= {f"{pid}:{n}" for n in plugin_mcp(root)}
        skills += len(skill_dirs(Path(root) / "skills")) if root else 0
    return len(mcp), skills


# --- Codex ---------------------------------------------------------------------------------------
def _codex_config():
    try:
        return tomllib.loads((paths.codex_home() / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _codex_root(pid):
    name, _, market = pid.partition("@")
    base = paths.codex_home() / "plugins" / "cache" / market / name
    dirs = sorted((d for d in base.glob("*") if d.is_dir()), key=lambda d: (d.name != "local", d.name))
    return dirs[0] if dirs else None


def _codex_plugins():
    """켜진 Codex 플러그인 {id: 설치 폴더 또는 None}."""
    plugins = _codex_config().get("plugins") or {}
    return {pid: _codex_root(pid) for pid, v in plugins.items() if "@" in pid and (v or {}).get("enabled", True)}


def codex_overlaps(lock):
    plugins = _codex_plugins()
    mine = {pid for pid in plugins if pid.endswith(f"@{MARKETPLACE}")}
    owned = set(codex.owned_mcp())  # jaix가 config.toml 에 써 둔 서버(같은 도구의 Codex용 사본)는 겹침이 아니다
    servers = _codex_config().get("mcp_servers") or {}
    out = {}
    for p in lock.plugins:
        if p.id not in mine:
            continue
        names = _names(p, plugins[p.id])
        hits = [f"Codex 플러그인 {pid}" for pid in plugins
                if pid not in mine and _same_name(pid.split("@", 1)[0], names)]
        hits += [f"Codex 스킬 {_describe(d)}" for d in skill_dirs(paths.codex_home() / "skills") if _same_name(d.name, names)]
        # 플러그인 서버와 이름이 똑같은 config 항목은 Codex가 그것만 띄우고 플러그인 쪽을 건너뛴다(codex.py #23 설명)
        # → 두 벌이 아니라 사용자가 덮어쓴 것. 이름이 달라 둘 다 뜨는 것만 겹침이다
        exact = plugin_mcp(plugins[p.id])
        hits += [f"Codex MCP '{n}' (config.toml)" for n in servers
                 if n not in owned and n not in exact and _same_name(n, names)]
        if hits:
            out[p.name] = hits
    return out


def codex_load():
    plugins = _codex_plugins()
    mcp = set((_codex_config().get("mcp_servers") or {}))
    skills = len(skill_dirs(paths.codex_home() / "skills"))
    for root in plugins.values():
        mcp |= plugin_mcp(root)  # config.toml 에 같은 이름이 있으면 Codex는 플러그인 쪽을 건너뛴다
        skills += len(skill_dirs(Path(root) / "skills")) if root else 0
    return len(mcp), skills


def estimate(mcp, skills):
    return mcp * MCP_TOKENS + skills * SKILL_TOKENS
