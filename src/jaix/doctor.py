"""jaix doctor: 런타임·PATH·마켓플레이스 등록·플러그인 버전이 잠금과 맞는지. 어긋나면 고치는 방법 한 줄(인수 시험 0-3).

판정: ok 통과 · warn 주의(동작은 함, 손볼 것 있음) · fail 실패(종료 코드 1) · skip 해당 없음.
"""
from dataclasses import asdict, dataclass
from pathlib import Path

from jaix import claude, codex, hermes, paths, runtimes, winenv
from jaix.lock import MARKETPLACE
from jaix.paths import IS_WIN

MARK = {"ok": "[통과]", "warn": "[주의]", "fail": "[실패]", "skip": "[생략]"}
FIX_SETUP = "jaix setup" if IS_WIN else "jaix setup (맥은 안내된 설치 명령)"


@dataclass
class Check:
    status: str
    area: str
    message: str
    fix: str = ""


def check_runtimes():
    out = []
    for rt in runtimes.RUNTIMES:
        if not rt.applies:
            if rt.key == "hwp2pdf":
                out.append(Check("skip", rt.label, "Windows 전용(한컴오피스) — 이 OS에서는 rhwp 근사 렌더를 씀"))
            continue
        found = runtimes.find(rt)
        if runtimes.ok(rt, found):
            out.append(Check("ok", rt.label, f"{found.version or '있음'} ({found.path})"))
        elif not rt.required:
            out.append(Check("skip", rt.label, f"없음 — 선택 도구({rt.purpose})", f"jaix setup --runtimes {rt.key}"))
        elif found.path:
            out.append(Check("fail", rt.label, f"{found.version} — {rt.min_major} 이상 필요 ({rt.purpose})",
                             FIX_SETUP if IS_WIN else rt.hint))
        else:
            out.append(Check("fail", rt.label, f"없음 ({rt.purpose})", FIX_SETUP if IS_WIN else rt.hint))
        if rt.key == "hwp2pdf" and found.path and not runtimes.hancom_installed():
            out.append(Check("warn", "한컴오피스", "없음 → HWP 렌더는 rhwp 근사 렌더로 대체 (hwp2pdf는 설치돼 있음)",
                             "정확한 렌더가 필요하면 한컴오피스 설치"))
    return out


def check_path():
    if not IS_WIN:
        return []
    out = []
    # jaix가 깐 폴더와 winget 바로가기 폴더는 사용자 PATH에 있어야 새 창·다시 연 앱이 찾는다
    dirs = {paths.bin_dir()}
    for rt in runtimes.RUNTIMES:
        found = runtimes.find(rt)
        if found.managed:
            dirs.add(rt.path_dir())
        elif found.path and Path(found.path).parent == paths.winget_links():
            dirs.add(paths.winget_links())
    for d in sorted(dirs, key=str):
        if not d.is_dir():
            continue
        if winenv.in_user_path(d):
            out.append(Check("ok", "PATH", f"{d}"))
        else:
            out.append(Check("fail", "PATH", f"{d} 가 사용자 PATH에 없음", "jaix setup 다시 실행 후 새 창 열기"))
    return out


def check_claude(lock):
    out = []
    managed = claude.managed_declaration()
    if managed:
        out.append(Check("ok", "Claude 등록", f"관리자 배포가 jaix 마켓플레이스를 내려줌 ({managed})"))
    else:
        try:
            settings = claude.read_json(claude.settings_path())
        except ValueError as e:
            return [Check("fail", "Claude 설정", f"{claude.settings_path()} 를 읽을 수 없음: {e}",
                          "파일의 JSON 문법을 고친 뒤 jaix setup")]
        entry = (settings.get("extraKnownMarketplaces") or {}).get(MARKETPLACE)
        if not entry:
            out.append(Check("fail", "Claude 등록", "사용자 설정에 jaix 마켓플레이스 없음", "jaix setup"))
        elif not claude.is_jaix_source(entry):
            out.append(Check("warn", "Claude 등록", f"'jaix'가 다른 소스를 가리킴: {entry.get('source')}",
                             "개발용 설정이면 그대로 두고, 아니면 그 항목을 지운 뒤 jaix setup"))
        elif entry.get("autoUpdate") is not True:
            out.append(Check("fail", "Claude 자동 업데이트", "autoUpdate가 꺼져 있음 — 새 버전이 저절로 오지 않음",
                             "jaix setup (autoUpdate를 다시 켬)"))
        else:
            out.append(Check("ok", "Claude 등록", "jaix 마켓플레이스 · autoUpdate 켜짐"))
        enabled = settings.get("enabledPlugins") or {}
        off = [p.id for p in lock.plugins if enabled.get(p.id) is not True]
        if off:
            out.append(Check("fail", "Claude 플러그인 켜기", f"꺼져 있음: {', '.join(off)}", "jaix setup"))
    have = claude.installed()
    cli = claude.find_cli()
    for p in lock.plugins:
        rec = have.get(p.id)
        if claude.matches(p, rec):
            out.append(Check("ok", f"Claude {p.name}", p.label))
        elif rec:
            now = rec.get("version") or (rec.get("gitCommitSha") or "")[:7]
            out.append(Check("fail", f"Claude {p.name}", f"설치 {now} ≠ 잠금 {p.label}",
                             "Claude 앱을 완전히 종료했다가 다시 열기 (또는 jaix update)"))
        else:
            # 설정은 맞는데 아직 앱을 다시 열지 않은 경우. CLI까지 있는데 없으면 설치가 실패한 것
            out.append(Check("fail" if cli else "warn", f"Claude {p.name}", f"아직 설치 안 됨 (잠금 {p.label})",
                             "jaix setup" if cli else "Claude Desktop을 다시 시작하면 설치됨"))
    return out


def check_codex(lock):
    if not codex.find_cli():
        return [Check("skip", "Codex", "설치 안 됨")]
    if not codex.marketplace_configured():
        return [Check("fail", "Codex 등록", "jaix 마켓플레이스 없음", "jaix setup --channels codex")]
    out = [Check("ok", "Codex 등록", "jaix 마켓플레이스")]
    snap = codex.snapshot_lock()
    snap_sha = {p["name"]: p["source"].get("sha") for p in (snap or {}).get("plugins", [])}
    enabled, rec = codex.enabled_plugins(), codex.recorded()
    for p in lock.plugins:
        if p.id not in enabled:
            out.append(Check("fail", f"Codex {p.name}", "설치 안 됨", "jaix setup --channels codex"))
        elif rec.get(p.id) == p.sha or (p.id not in rec and snap_sha.get(p.name) == p.sha):
            out.append(Check("ok", f"Codex {p.name}", p.label))
        else:
            out.append(Check("fail", f"Codex {p.name}", f"잠금 {p.label}보다 옛 버전", "jaix update"))
    return out


def check_hermes(lock):
    have = hermes.installed()
    if not have:
        return [Check("skip", "Hermes", "다음 버전에서 켬")]
    sha = {p.name: p.sha for p in lock.plugins}
    stale = sorted(n for n, m in have.items() if m.get("plugin") in sha and m.get("sha") != sha[m["plugin"]])
    if stale:
        return [Check("fail", "Hermes 스킬", f"잠금과 다름: {', '.join(stale)}", "jaix update")]
    return [Check("ok", "Hermes 스킬", f"{len(have)}개 잠금과 같음")]


def run(lock):
    return [*check_runtimes(), *check_path(), *check_claude(lock), *check_codex(lock), *check_hermes(lock)]


def render(checks):
    lines = []
    for c in checks:
        line = f"{MARK[c.status]} {c.area}: {c.message}"
        if c.fix and c.status in ("warn", "fail"):
            line += f"\n        → {c.fix}"
        lines.append(line)
    return "\n".join(lines)


def as_dicts(checks):
    return [asdict(c) for c in checks]
