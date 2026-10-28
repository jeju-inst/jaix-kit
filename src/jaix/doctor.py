"""jaix doctor: 런타임·PATH·마켓플레이스 등록·플러그인 버전이 잠금과 맞는지. 어긋나면 고치는 방법 한 줄(인수 시험 0-3).

판정: ok 통과 · warn 주의(동작은 함, 손볼 것 있음) · fail 실패(종료 코드 1) · skip 해당 없음.
"""
from dataclasses import asdict, dataclass
from pathlib import Path

from jaix import claude, codex, gw, hermes, hwpjar, paths, runtimes, schedule, uvpython, winenv
from jaix.lock import MARKETPLACE, same_commit
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


def check_uv_python():
    """플러그인 MCP(uvx)가 쓸 uv 관리 Python. Windows에서 없으면 Claude 앱이 받다가 가상화로 깨져
    MCP가 오류 없이 안 뜬다(jaix-kit#14). 맥·리눅스는 uvx가 처음 실행 때 받아도 되므로 주의로만."""
    area = "uv 관리 Python"
    if not runtimes.find(runtimes.BY_KEY["uv"]).path:
        return [Check("skip", area, "uv 없음 (위 uv 항목 참고)")]
    out = []
    missing = [v for v in uvpython.recorded() if not uvpython.find(v)]
    if missing:
        out.append(Check("fail" if IS_WIN else "warn", area,
                         f"{', '.join(missing)} 없음 — Claude 앱에서 HWP 등 플러그인 도구가 조용히 안 뜸",
                         "jaix setup (다시 실행)" if IS_WIN else f"uv python install {' '.join(missing)}"))
    else:
        out.append(Check("ok", area, ", ".join(uvpython.recorded())))
    for d in uvpython.virtualized_dirs():
        out.append(Check("warn", "uv 가상화 흔적", f"Claude 앱 안에서 받은 uv 파일: {d}",
                         "위 항목이 통과면 무해. 도구가 계속 안 보이면 이 폴더를 지우고 Claude 재시작"))
    return out


def check_hwp_jar(lock):
    """hwp-agent 변환기 jar. 없으면 처음 hwp를 변환할 때 에이전트가 setup 안내를 보고 우회한다(jaix-kit#19)."""
    if not hwpjar.plugin(lock):
        return []
    if hwpjar.dest().is_file():
        return [Check("ok", "HWP 변환기(jar)", str(hwpjar.dest()))]
    return [Check("fail", "HWP 변환기(jar)", f"없음 — hwp → hwpx 변환이 안 됨 ({hwpjar.dest()})", "jaix setup")]


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


def check_gw():
    area = "gw(그룹웨어)"
    if not gw.source():
        return [Check("skip", area, "끔 (--gw-source none)")]
    have, info = gw.installed_version(), gw.latest()
    if not info:
        if have:
            return [Check("ok", area, f"{have} 설치됨 (원내 위치에 닿지 않아 최신인지는 확인 못 함)"), *_gw_base_url()]
        if gw.unpublished():
            return [Check("skip", area, "아직 배포 전 — 배포가 시작되면 jaix update가 설치")]
        return [Check("warn", area, "원내 위치에 닿지 않아 설치 안 됨 (원내망 필요)", "원내망(사무실·VPN)에서 jaix setup")]
    if not have:
        return [Check("fail", area, f"원내 위치에 닿는데 설치 안 됨 (배포 {info['version']})", "jaix setup")]
    if not gw.same(have, info["version"]):
        return [Check("warn", area, f"{have} 설치됨 — 배포 버전은 {info['version']}", "jaix update"), *_gw_base_url()]
    return [Check("ok", area, f"{have} (배포 버전과 같음)"), *_gw_base_url()]


def _gw_base_url():
    """설치된 gw 가 그룹웨어 주소를 아는가(share.toml [gw].base_url 또는 GW_BASE_URL)."""
    if gw.base_url():
        return [Check("ok", "gw 그룹웨어 주소", "설정됨")]
    return [Check("warn", "gw 그룹웨어 주소", f"없음 — gw 가 그룹웨어에 접속하지 못함 ({gw.share_toml()})",
                  "원내망(사무실·VPN)에서 jaix setup")]


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
    missing = []
    for p in lock.plugins:
        rec = have.get(p.id)
        if claude.matches(p, rec):
            out.append(Check("ok", f"Claude {p.name}", p.label))
        elif rec:
            now = rec.get("version") or (rec.get("gitCommitSha") or "")[:7]
            out.append(Check("fail", f"Claude {p.name}", f"설치 {now} ≠ 잠금 {p.label}",
                             "Claude 앱을 완전히 종료했다가 다시 열기 (또는 jaix update)"))
        else:
            missing.append(p)
    if missing:
        # 잠금 대비 누락은 늘 실패(jaix-kit#19: 0개인데 '정상'으로 나왔다). Desktop 재시작만으로는 깔리지 않는다
        names = ", ".join(p.name for p in missing)
        out.append(Check("fail", "Claude 플러그인", f"{len(missing)}/{len(lock.plugins)}개 설치 안 됨: {names}",
                         "jaix setup" if cli else
                         "Claude 앱에서 Code 탭을 열었다 닫고 한 번 더 열기(첫 번째에 등록, 두 번째에 설치)"))
    if paths.desktop_installed():
        out.append(Check("skip", "Claude 데스크톱·Cowork",
                         "관리자 배포 대상(조직 플러그인) — jaix는 Code 탭·Claude Code에만 등록함"))
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
        elif same_commit(rec.get(p.id), p.sha) or (p.id not in rec and same_commit(snap_sha.get(p.name), p.sha)):
            out.append(Check("ok", f"Codex {p.name}", p.label))
        else:
            out.append(Check("fail", f"Codex {p.name}", f"잠금 {p.label}보다 옛 버전", "jaix update"))
    # Codex는 플러그인 MCP의 ${CLAUDE_PLUGIN_ROOT}를 치환하지 않는다(#23) → jaix가 쓴 절대경로 항목이 있어야 뜬다
    want = codex.mcp_servers(lock)
    owned = codex.owned_mcp()
    # 사용자가 같은 이름을 직접 정의한 것(jaix가 맡지 않은 것)은 그대로 둔다
    stale = [n for n, spec in want.items()
             if codex._current(n) != spec and (codex._current(n) is None or n in owned)]
    if stale:
        out.append(Check("fail", "Codex MCP", f"플러그인 MCP 경로가 config.toml에 없음/옛것: {', '.join(stale)} (0 tools로 실패함)",
                         "jaix update"))
    elif want:
        out.append(Check("ok", "Codex MCP", ", ".join(want)))
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


def check_autoupdate():
    """로그온 자동 갱신(jaix update --quiet). 실패는 다음 로그온에 다시 하므로 주의로만 보인다."""
    area = "로그온 자동 갱신"
    if not schedule.supported():
        return [Check("skip", area, "이 OS는 지원 안 함 — 가끔 jaix update")]
    if not schedule.registered():
        return [Check("warn", area, "등록 안 됨 — Codex·Hermes 도구가 저절로 갱신되지 않음", "jaix setup")]
    bad = schedule.run_mode()
    if bad:
        return [Check("warn", area, f"실행 모드 문제: {bad}", "jaix setup (다시 등록)")]
    last = schedule.last_status()
    if not last:
        return [Check("ok", area, "등록됨 (아직 돈 적 없음)")]
    if last.get("ok"):
        by = " (jaix setup)" if last.get("by") == "setup" else ""
        return [Check("ok", area, f"마지막 갱신 {last.get('time')}{by}")]
    why = last.get("error") or "; ".join(last.get("problems") or [])
    return [Check("warn", area, f"{last.get('time')} 실패: {why} (기록: {schedule.log_file()})", "jaix update")]


def run(lock):
    return [*check_runtimes(), *check_uv_python(), *check_hwp_jar(lock), *check_gw(), *check_path(), *check_claude(lock), *check_codex(lock),
            *check_hermes(lock), *check_autoupdate()]


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
