"""Codex 채널(Codex 데스크톱·CLI): 같은 잠금 파일을 Codex 마켓플레이스로 등록하고 플러그인을 설치한다.

2026-10-27 실측(codex-cli 0.160.0): Codex는 jaix-kit의 .claude-plugin/marketplace.json을 그대로 읽는다.
`codex plugin marketplace add <git URL>` → `codex plugin add <이름>@jaix` 로 세 플러그인이 다 깔린다.
Codex에는 autoUpdate가 없다. `codex plugin marketplace upgrade jaix` 뒤 `plugin add`를 다시 하면 캐시를 새로 받으므로
`jaix update`가 그 일을 한다. Codex는 설치본의 버전을 "local"로만 기록해서, jaix가 깐 커밋을 따로 적어 둔다.
"""
import json
import shutil
import subprocess
import tomllib

from jaix import paths
from jaix.lock import GIT_URL, MARKETPLACE


def find_cli():
    return shutil.which("codex")


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
        return {"cli": True}
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
    have, rec = enabled_plugins(), recorded()
    for p in lock.plugins:
        stale = rec.get(p.id) != p.sha
        if p.id in have and not (update and stale):
            continue
        if _run(cli, ["plugin", "add", p.id], log):
            rec[p.id] = snap.get(p.name)
            note = "" if snap.get(p.name) == p.sha else f" (받은 사본 {str(snap.get(p.name))[:7]} ≠ 잠금 — jaix update)"
            log(f"    {'갱신' if p.id in have else '설치'}: {p.id} {p.label}{note}")
    _record_file().parent.mkdir(parents=True, exist_ok=True)
    _record_file().write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return {"cli": True}
