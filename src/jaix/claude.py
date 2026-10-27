"""Claude 채널(Desktop Cowork·Code 탭, Claude Code CLI): 마켓플레이스 등록과 플러그인 설치.

두 갈래로 한다.
1. 사용자 settings.json에 extraKnownMarketplaces(jaix, autoUpdate) + enabledPlugins를 **병합**한다(쓰기 전 백업).
   Desktop은 다음 시작 때 이걸 보고 설치·자동 업데이트한다.
2. Claude Code 실행파일(PATH의 claude, 없으면 Desktop이 내려받은 것)이 있으면 지금 바로 설치까지 한다.

주의(2026-10-27 실측, Claude Code 2.1.311): `claude plugin marketplace add`는 settings.json을 다시 쓰면서
마켓플레이스 항목의 autoUpdate를 지운다(이미 등록돼 있어도). 그래서 CLI 단계를 먼저 하고 병합을 맨 나중에 한다.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from jaix import paths
from jaix.lock import GIT_URL, MARKETPLACE, REPO
from jaix.paths import IS_WIN

MARKET_ENTRY = {"source": {"source": "git", "url": GIT_URL}, "autoUpdate": True}


def settings_path():
    return paths.claude_dir() / "settings.json"


def is_jaix_source(entry):
    src = (entry or {}).get("source") or {}
    where = f"{src.get('url', '')} {src.get('repo', '')}".lower()
    return REPO in where


def read_json(path):
    """없으면 {}. 깨진 JSON이면 예외 — 덮어쓰면 사용자 설정이 날아가므로 멈춘다."""
    path = Path(path)
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: JSON 문법 오류({e}) — 덮어쓰지 않고 멈춤") from e


def managed_declaration():
    """관리자 배포(관리자 콘솔·managed settings)가 jaix 마켓플레이스를 이미 내려주면 그 파일 경로."""
    for f in paths.managed_settings_files():
        try:
            data = read_json(f)
        except (OSError, ValueError):
            continue
        for name, entry in (data.get("extraKnownMarketplaces") or {}).items():
            if name == MARKETPLACE or is_jaix_source(entry):
                return f
    return None


def merge_settings(settings, plugins):
    """settings(dict)에 jaix 등록을 병합한 새 dict와 (바꾼 것, 경고) 목록을 돌려준다. 원본은 건드리지 않는다.

    이미 있는 값은 존중한다: 다른 소스를 가리키는 'jaix'(개발용 디렉터리 등)와 사용자가 꺼 둔 플러그인은 그대로 둔다.
    """
    new = copy.deepcopy(settings)
    changes, warnings = [], []
    markets = new.setdefault("extraKnownMarketplaces", {})
    cur = markets.get(MARKETPLACE)
    if cur is None:
        markets[MARKETPLACE] = copy.deepcopy(MARKET_ENTRY)
        changes.append(f"마켓플레이스 {MARKETPLACE} 등록 (autoUpdate)")
    elif is_jaix_source(cur):
        if cur.get("autoUpdate") is not True:
            cur["autoUpdate"] = True
            changes.append(f"마켓플레이스 {MARKETPLACE} autoUpdate 켬")
    else:
        warnings.append(f"'{MARKETPLACE}' 마켓플레이스가 다른 소스를 가리킴({json.dumps(cur.get('source'), ensure_ascii=False)}) — 그대로 둠")
    enabled = new.setdefault("enabledPlugins", {})
    for p in plugins:
        if p.id not in enabled:
            enabled[p.id] = True
            changes.append(f"플러그인 켬: {p.id}")
        elif enabled[p.id] is False:
            warnings.append(f"{p.id} 는 꺼 둔 상태 — 그대로 둠")
    return new, changes, warnings


def backup_settings():
    """지금 settings.json을 옆에 복사해 둔다. 백업 경로(파일이 없으면 None)."""
    path = settings_path()
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.jaix-bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    return backup


def write_settings(data):
    """원자적으로 쓴다(쓰다 끊겨도 반쯤 쓴 파일이 남지 않게). 백업은 부르는 쪽이 먼저 한다."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="settings.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def find_cli():
    """claude 실행파일: PATH(+npm 전역) → Claude Desktop이 내려받은 Claude Code(가장 새 버전)."""
    exe = paths.which("claude")
    if exe:
        return exe
    name = "claude.exe" if IS_WIN else "claude"
    found = []
    for root in paths.desktop_claude_code_roots():  # 여러 위치 중 가장 높은 버전
        if not root.is_dir():
            continue
        for ver in root.iterdir():
            if ver.is_dir() and re.match(r"^\d+\.\d+\.\d+$", ver.name):
                found += [(tuple(map(int, ver.name.split("."))), str(p)) for p in ver.rglob(name) if p.is_file()]
    return max(found)[1] if found else None


def installed():
    """installed_plugins.json의 jaix 플러그인: {id: {version, gitCommitSha, ...}}."""
    try:
        data = read_json(paths.claude_dir() / "plugins" / "installed_plugins.json")
    except (OSError, ValueError):
        return {}
    out = {}
    for pid, recs in (data.get("plugins") or {}).items():
        if pid.endswith(f"@{MARKETPLACE}") and recs:
            user = [r for r in recs if r.get("scope") == "user"] or recs
            out[pid] = user[0]
    return out


def known_marketplace():
    try:
        return read_json(paths.claude_dir() / "plugins" / "known_marketplaces.json").get(MARKETPLACE)
    except (OSError, ValueError):
        return None


def matches(plugin, record):
    """설치본이 잠금과 같은가. 날짜 버전이 있으면 버전으로, 없으면 커밋으로 본다(Claude와 같은 기준)."""
    if not record:
        return False
    if plugin.version:
        return record.get("version") == plugin.version
    return record.get("gitCommitSha") == plugin.sha


def _run(cli, args, log):
    try:
        r = subprocess.run([cli, *args], capture_output=True, text=True, timeout=600,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"    claude {' '.join(args)} 실패: {e}")
        return False
    if r.returncode != 0:
        tail = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()][-1:] or [""]
        log(f"    claude {' '.join(args)} 실패(코드 {r.returncode}): {tail[0][:200]}")
        return False
    return True


def cli_sync(plugins, log, dry_run=False, update=False):
    """CLI로 마켓플레이스를 받고 잠금의 플러그인을 설치(update면 새 버전으로)한다. CLI가 없으면 False."""
    cli = find_cli()
    if not cli:
        log("  Claude Code 실행파일 없음 → Claude Desktop을 다시 시작하면 설정을 보고 설치합니다")
        return False
    log(f"  Claude Code: {cli}")
    if dry_run:
        return True
    if known_marketplace() is None:
        _run(cli, ["plugin", "marketplace", "add", GIT_URL], log)
    else:
        _run(cli, ["plugin", "marketplace", "update", MARKETPLACE], log)
    have = installed()
    for p in plugins:
        if p.id not in have:
            if _run(cli, ["plugin", "install", p.id], log):
                log(f"    설치: {p.id} {p.label}")
        elif update and not matches(p, have[p.id]):
            if _run(cli, ["plugin", "update", p.id], log):
                log(f"    갱신: {p.id} → {p.label} (앱 재시작 후 적용)")
    return True


def setup(lock, log, dry_run=False, update=False):
    """Claude 채널 등록 전체. 돌려준 dict는 안내문·보고용."""
    plugins = lock.plugins
    managed = managed_declaration()
    if managed:
        log(f"  관리자 배포가 jaix 마켓플레이스를 내려줌({managed}) → 사용자 설정 등록은 건너뜀")
    read_json(settings_path())  # 깨진 JSON이면 여기서 멈춘다 — CLI도 그 파일을 다시 쓰므로 돌리지 않는다
    # CLI의 marketplace add·install은 settings.json을 다시 쓴다. 손대기 전 원본을 백업해 둔다
    backup = None
    have = installed()
    if not dry_run and find_cli() and (known_marketplace() is None or any(p.id not in have for p in plugins)):
        backup = backup_settings()
    cli_ok = cli_sync(plugins, log, dry_run=dry_run, update=update)
    if managed:
        return {"managed": str(managed), "cli": cli_ok}
    current = read_json(settings_path())  # CLI가 고쳤을 수 있으니 다시 읽는다
    new, changes, warnings = merge_settings(current, plugins)
    for w in warnings:
        log(f"  주의: {w}")
    if changes and not dry_run:
        backup = backup or backup_settings()
        write_settings(new)
    for c in changes:
        log(f"  {'(예정) ' if dry_run else ''}{c}")
    if backup:
        log(f"  원래 설정 백업: {backup}")
    if not changes:
        log("  사용자 설정: 이미 등록됨")
    return {"managed": None, "cli": cli_ok, "changes": changes, "warnings": warnings}
