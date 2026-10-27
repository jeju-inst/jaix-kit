"""Codex 채널(Codex 데스크톱·CLI): 같은 잠금 파일을 Codex 마켓플레이스로 등록하고 플러그인을 설치한다.

2026-10-27 실측(codex-cli 0.160.0): Codex는 jaix-kit의 .claude-plugin/marketplace.json을 그대로 읽는다.
`codex plugin marketplace add <git URL>` → `codex plugin add <이름>@jaix` 로 세 플러그인이 다 깔린다.
Codex에는 autoUpdate가 없다. `codex plugin marketplace upgrade jaix` 뒤 `plugin add`를 다시 하면 캐시를 새로 받으므로
`jaix update`가 그 일을 한다. Codex는 설치본의 버전을 "local"로만 기록해서, jaix가 깐 커밋을 따로 적어 둔다.
"""
import json
import os
import re
import subprocess
import tomllib

from jaix import paths
from jaix.paths import IS_WIN
from jaix.lock import GIT_URL, MARKETPLACE, same_commit


def find_cli():
    return paths.which("codex")  # npm 전역(%APPDATA%\\npm\\codex.cmd)이 PATH에 없어도


def _config():
    try:
        return tomllib.loads((paths.codex_home() / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def marketplace_configured():
    return MARKETPLACE in (_config().get("marketplaces") or {})


def enabled_plugins():
    plugins = _config().get("plugins") or {}
    return {pid for pid, v in plugins.items() if pid.endswith(f"@{MARKETPLACE}") and (v or {}).get("enabled", True)}


def snapshot_lock():
    """Codex가 받아 둔 마켓플레이스 사본의 잠금 — jaix-kit의 어느 시점을 보고 있는지."""
    f = paths.codex_home() / ".tmp" / "marketplaces" / MARKETPLACE / ".claude-plugin" / "marketplace.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _record_file():
    return paths.jaix_home() / "codex-installed.json"


def recorded():
    """jaix가 Codex에 깔아 둔 플러그인별 커밋 {id: sha}."""
    try:
        return json.loads(_record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _run(cli, args, log):
    try:
        r = subprocess.run([cli, *args], capture_output=True, text=True, timeout=600,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"    codex {' '.join(args)} 실패: {e}")
        return False
    if r.returncode != 0:
        tail = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()][-1:] or [""]
        log(f"    codex {' '.join(args)} 실패(코드 {r.returncode}): {tail[0][:200]}")
        return False
    return True


def setup(lock, log, dry_run=False, update=False):
    cli = find_cli()
    if not cli:
        log("  Codex 없음 → 건너뜀 (Codex를 설치한 뒤 `jaix setup --channels codex`)")
        return {"cli": False}
    log(f"  Codex: {cli}")
    if dry_run:
        return {"cli": True, "failed": []}
    if not marketplace_configured():
        if not _run(cli, ["plugin", "marketplace", "add", GIT_URL], log):
            return {"cli": True, "error": "marketplace add"}
        log(f"    마켓플레이스 {MARKETPLACE} 등록")
    elif not _run(cli, ["plugin", "marketplace", "upgrade", MARKETPLACE], log):
        # 옛 사본에서 깔면 잠금과 다른 것이 깔린다. 기록을 앞으로 당기지 않고 doctor가 잡게 둔다
        log("    마켓플레이스를 새로 받지 못함 → 플러그인은 건드리지 않음")
        return {"cli": True, "error": "marketplace upgrade"}
    # 기록은 바라는 잠금이 아니라 실제로 받아 둔 사본의 커밋으로 남긴다
    snap = {e["name"]: e["source"].get("sha") for e in (snapshot_lock() or {}).get("plugins", [])}
    have, rec, failed = enabled_plugins(), recorded(), []
    for p in lock.plugins:
        stale = not same_commit(rec.get(p.id), p.sha)
        if p.id in have and not (update and stale):
            continue
        if _run(cli, ["plugin", "add", p.id], log):
            rec[p.id] = snap.get(p.name)
            note = "" if same_commit(snap.get(p.name), p.sha) else f" (받은 사본 {str(snap.get(p.name))[:7]} ≠ 잠금 — jaix update)"
            log(f"    {'갱신' if p.id in have else '설치'}: {p.id} {p.label}{note}")
        else:
            failed.append(p.name)
    _record_file().parent.mkdir(parents=True, exist_ok=True)
    _record_file().write_text(json.dumps(rec, indent=2), encoding="utf-8")
    if not write_mcp(lock, log, cli):
        failed.append("MCP 경로")
    ensure_sandbox(log)
    return {"cli": True, "failed": failed}


# --- Codex가 ${CLAUDE_PLUGIN_ROOT}를 치환하지 않는 문제(jaix-kit#23) ---------------------------------
# Codex(0.164)는 플러그인 .mcp.json의 ${CLAUDE_PLUGIN_ROOT}를 문자 그대로 uvx에 넘겨 MCP가 0 tools로 실패한다.
# jaix가 config.toml [mcp_servers]에 설치 위치의 절대경로로 같은 이름의 서버를 써 준다. 같은 이름이면 Codex는
# config 쪽을 쓰고 플러그인 쪽은 건너뛴다("skipping duplicate plugin MCP server name", codex mcp list로 확인).
# 쓰기는 `codex mcp add/remove`로 한다 — Codex가 config.toml을 다시 쓰면서 주석 표식을 지우므로 파일을 직접
# 고치지 않는다. jaix가 쓴 이름은 jaix_home/codex-mcp.json에 적어 두고 그것만 바꾸거나 지운다(사용자 항목 보존).
ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"


def plugin_root(name):
    """Codex가 깐 플러그인 폴더(CODEX_HOME/plugins/cache/jaix/<이름>/<버전>, 버전은 보통 local)."""
    base = paths.codex_home() / "plugins" / "cache" / MARKETPLACE / name
    dirs = sorted((d for d in base.glob("*") if d.is_dir()), key=lambda d: (d.name != "local", d.name))
    return dirs[0] if dirs else None


def _subst(value, root):
    if isinstance(value, str):
        return value.replace(ROOT_VAR, str(root))
    if isinstance(value, list):
        return [_subst(v, root) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, root) for k, v in value.items()}
    return value


def mcp_servers(lock):
    """잠금 플러그인 중 Codex에 깔린 것의 stdio MCP 서버를 절대경로로 바꾼 것 {서버 이름: {command, args, env}}."""
    out, have = {}, enabled_plugins()
    for p in lock.plugins:
        root = plugin_root(p.name)
        if not root or p.id not in have:
            continue
        try:
            servers = json.loads((root / ".mcp.json").read_text(encoding="utf-8")).get("mcpServers") or {}
        except (OSError, ValueError):
            continue
        for name, spec in servers.items():
            if "command" in spec and "cwd" not in spec:  # codex mcp add 가 cwd를 받지 않는다
                out[name] = _subst({"command": spec["command"], "args": list(spec.get("args") or []),
                                    "env": dict(spec.get("env") or {})}, root)
    return out


def _mcp_record():
    return paths.jaix_home() / "codex-mcp.json"


def owned_mcp():
    try:
        return json.loads(_mcp_record().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _current(name):
    try:
        cur = (tomllib.loads((paths.codex_home() / "config.toml").read_text(encoding="utf-8"))
               .get("mcp_servers") or {}).get(name)
    except (OSError, ValueError):
        return None
    if cur is None:
        return None
    return {"command": cur.get("command"), "args": list(cur.get("args") or []), "env": dict(cur.get("env") or {})}


def write_mcp(lock, log, cli=None, dry_run=False):
    """jaix가 맡은 MCP 서버를 지금 설치 상태(절대경로)에 맞춘다. 사용자가 같은 이름을 직접 정의했으면 그대로 둔다."""
    cli = cli or find_cli()
    if not cli:
        return False
    want, owned = mcp_servers(lock), owned_mcp()
    ok = True
    for name, spec in want.items():
        cur = _current(name)
        if cur == spec:  # 이미 맞음(기록을 잃었어도 jaix가 쓴 것과 같으면 맡는다)
            owned[name] = spec
            continue
        if cur is not None and name not in owned:
            log(f"    MCP {name}: config.toml에 사용자 정의가 있어 그대로 둠")
            continue
        if cur is not None and cur != owned[name]:  # jaix가 쓴 뒤 사용자가 고침 → 그 뒤로는 사용자 것
            log(f"    MCP {name}: jaix가 쓴 뒤 바뀌어 있어 그대로 둠(이제 사용자 정의로 봄)")
            owned.pop(name)
            continue
        if dry_run:
            log(f"    MCP {name}: 절대경로로 쓸 예정")
            continue
        args = ["mcp", "add", name, *[f"--env={k}={v}" for k, v in spec["env"].items()], "--", spec["command"],
                *spec["args"]]
        if _run(cli, args, log):
            owned[name] = spec
            log(f"    MCP {name}: 플러그인 위치의 절대경로로 씀")
        else:
            ok = False
    for name in [n for n in owned if n not in want]:  # 잠금에서 빠진 플러그인의 서버는 jaix가 지운다
        if dry_run:
            continue
        if _current(name) == owned[name]:  # 사용자가 바꿔 놓았으면 지우지 않는다
            _run(cli, ["mcp", "remove", name], log)
            log(f"    MCP {name}: 지움 (잠금·설치에서 빠짐)")
        owned.pop(name)
    if not dry_run:
        _mcp_record().parent.mkdir(parents=True, exist_ok=True)
        _mcp_record().write_text(json.dumps(owned, ensure_ascii=False, indent=2), encoding="utf-8")
    return ok


def ensure_sandbox(log, dry_run=False):
    """Windows: 첫 실행의 샌드박스 질문을 없앤다. 표준 사용자는 기본(관리자 권한) 샌드박스를 못 쓰므로
    [windows] sandbox = "unelevated". 이미 값이 있으면 건드리지 않는다."""
    if not IS_WIN:
        return False
    cfg = paths.codex_home() / "config.toml"
    try:
        text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
        if "sandbox" in (tomllib.loads(text).get("windows") or {}):
            return False
    except (OSError, ValueError):
        return False
    has_table = "windows" in tomllib.loads(text) if text.strip() else False
    # 머리는 [windows] · ["windows"] · 뒤 주석 등 여러 꼴이 될 수 있다
    m = re.search(r"""^[ \t]*\[[ \t]*(?:windows|"windows"|'windows')[ \t]*\][^\n]*$""", text, re.M)
    if m:  # 표가 있으면 머리 바로 아래에 넣는다
        new = text[:m.end()] + '\nsandbox = "unelevated"' + text[m.end():]
    elif has_table:  # 인라인 표 등 알아보기 어려운 꼴 — 손대지 않는다
        log("    Codex 샌드박스: [windows] 표 꼴을 알아보지 못해 그대로 둠")
        return False
    else:
        new = text.rstrip("\n") + ('\n\n' if text.strip() else "") + '[windows]\nsandbox = "unelevated"\n'
    try:
        tomllib.loads(new)
    except ValueError:
        return False  # 깨진 파일을 쓰지 않는다
    if not dry_run:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(new, encoding="utf-8")
        log('    Codex 샌드박스: [windows] sandbox = "unelevated" (관리자 권한 없이 쓰는 방식)')
    return True
