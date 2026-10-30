"""jaix doctor: 런타임·PATH·마켓플레이스 등록·플러그인 버전이 잠금과 맞는지. 어긋나면 고치는 방법 한 줄(인수 시험 0-3).

판정: ok 통과 · warn 주의(동작은 함, 손볼 것 있음) · fail 실패(종료 코드 1) · skip 해당 없음.
"""
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from jaix import claude, codex, gw, hermes, hermesbot, hwpjar, hwprhwp, overlap, paths, proc, runtimes, schedule, uvpython, winenv, works
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
        if runtimes.ok(rt, found) and runtimes.outdated(rt, found):
            out.append(Check("warn", rt.label, f"{found.version} — 업데이트 필요: {rt.min_version} 이상({rt.min_reason})",
                             "jaix update (직접 설치했으면 새 설치기로)"))
        elif runtimes.ok(rt, found):
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


def check_rhwp(lock):
    """hwp-agent 폴백 렌더 엔진. 없으면 한글이 열린 PC에서 미리보기(pdf·verify)가 결과 없이 끝난다."""
    if not hwpjar.plugin(lock):
        return []
    if hwprhwp.exe().is_file():
        return [Check("ok", "HWP 미리보기 엔진(rhwp)", f"{hwprhwp.installed_version() or '버전 미상'} · {hwprhwp.exe()}")]
    return [Check("warn", "HWP 미리보기 엔진(rhwp)",
                  "없음 — 한글이 열려 있으면 미리보기 렌더가 안 됨(한글을 닫으면 한컴으로 렌더)", "jaix setup")]


def _same(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def check_path():
    if not IS_WIN:
        return []
    out = []
    # jaix가 깐 폴더와 winget 바로가기 폴더는 사용자 PATH에 있어야 새 창·다시 연 앱이 찾는다
    dirs = {paths.bin_dir()}
    # 설치본(Inno 가 {app}\\jaix 에 깔고 PATH 에 넣음)만: 새 명령창이 jaix 를 찾으려면 그 폴더가 있어야 한다.
    # 풀어서 쓰는 jaix-windows.zip 은 PATH 에 넣지 않으므로 묻지 않는다
    if paths.exe_dir() and _same(paths.exe_dir(), paths.jaix_home() / "jaix"):
        dirs.add(paths.exe_dir())
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
    other = gw.foreign()
    if other:  # 개발용 gw를 지키려고 jaix가 일부러 건너뛴 것 — 실패가 아니다
        return [Check("skip", area, f"개발용 gw가 있어 jaix가 설치·갱신하지 않음: {'; '.join(other)}")]
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


def check_works(lock):
    area = "웍스(nworks)"
    if not works.plugin(lock):
        return []
    want = works.spec(lock)["nworks"]
    have, integrity = works.installed()
    if not have:
        return [Check("fail", area, "설치 안 됨", "jaix setup")]
    if have != want["version"] or integrity != want["integrity"]:
        return [Check("warn", area, f"{have} 설치됨 — 잠금은 {want['version']}", "jaix update")]
    out = [Check("ok", area, f"{have} (잠금과 같음, {works.home()})")]
    if IS_WIN and not winenv.in_user_path(works.bin_dir()):
        out.append(Check("warn", area, "실행 폴더가 사용자 PATH에 없음", "jaix setup"))
    elif not IS_WIN and not works.on_path():
        out.append(Check("warn", area, "PATH에서 jaix 가 깐 nworks 가 안 보임 — 스킬이 부르지 못함",
                         f"{works.link_dir()} 를 PATH에 추가하고 jaix setup"))
    if not works.saved_client():
        out.append(Check("warn", "웍스 기관 앱 정보", "없음 — 원내망에서 받아야 함", "원내망(사무실·VPN)에서 jaix setup"))
    elif not works.logged_in():
        out.append(Check("warn", "웍스 로그인", "아직 안 함 — 처음 쓸 때 한 번", "jaix works login"))
    else:
        out.append(Check("ok", "웍스 로그인", "됨"))
    return out


def _gw_base_url():
    """설치된 gw 가 그룹웨어 주소를 아는가(share.toml [gw].base_url 또는 GW_BASE_URL)."""
    if gw.base_url():
        return [Check("ok", "gw 그룹웨어 주소", "설정됨")]
    return [Check("warn", "gw 그룹웨어 주소", f"없음 — gw 가 그룹웨어에 접속하지 못함 ({gw.share_toml()})",
                  "원내망(사무실·VPN)에서 jaix setup")]


# 플러그인 도구 중 셸 명령으로도 부르는 것: {플러그인 이름: 실행파일 이름}. 스킬이 PATH에서 찾으므로
# 따로 깐 옛 실행파일(단독 Inno 설치본 등)이 먼저 잡히면 잠금과 다른 판이 돈다
PATH_TOOLS = {"hwp-agent": "hwp-agent"}


def _tool_version(exe):
    try:
        code, out = proc.run(exe, ["--version"], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"\d+(?:\.\d+)+(?:\+\S+)?", out) if code == 0 else None
    return m.group(0) if m else None


def check_path_tools(lock):
    out = []
    for p in lock.plugins:
        name = PATH_TOOLS.get(p.name)
        exe = paths.which(name) if name and p.version else None
        if not exe:
            continue
        have = _tool_version(exe)
        area = f"PATH의 {name}"
        if have and gw.same(have, p.version) and "+" not in have:
            out.append(Check("ok", area, f"{have} (잠금과 같음 · {exe})"))
            continue
        what = "버전을 읽지 못함" if not have else f"개발판 {have}" if "+" in have or have.startswith("0.") else have
        out.append(Check("warn", area, f"{what} ≠ 잠금 {p.version} — 스킬이 셸 명령으로 부르면 이것이 잡힘 ({exe})",
                         "따로 깐 것이면 지우거나(설정 → 앱) 잠금 버전으로 올리기. 개발용이면 그대로 둬도 됨"))
    return out


def check_overlaps(lock):
    """같은 도구가 한 호스트에 두 벌 — 알리기만 한다. 지울 것은 사용자가 고른다."""
    out = []
    for host, found in (("Claude", overlap.claude_overlaps(lock)), ("Codex", overlap.codex_overlaps(lock))):
        for name, hits in found.items():
            out.append(Check("warn", f"{host} 중복 {name}",
                             f"jaix 것 말고도 있음: {'; '.join(hits)} — 같은 도구가 두 번 실려 토큰이 두 배로 듦",
                             "하나만 남기세요(jaix는 지우지 않음). jaix 것을 쓰려면 위 플러그인을 끄거나 스킬 링크·MCP 항목을 지우기"))
    return out


def check_load():
    """켜진 MCP 서버·스킬이 많으면 매 요청에 실리는 분량이 커져 사용량 한도에 빨리 닿는다(TS-TOKEN)."""
    out = []
    for host, (mcp, skills) in (("Claude", overlap.claude_load()), ("Codex", overlap.codex_load())):
        if not mcp and not skills:
            continue
        est = overlap.estimate(mcp, skills)
        msg = f"MCP 서버 {mcp}개 · 스킬 {skills}개 (상시 약 {est // 1000}k 토큰 어림)"
        if est > overlap.BUDGET:
            out.append(Check("warn", f"{host} 도구 수", msg + f" — {overlap.BUDGET // 1000}k를 넘어 사용량 한도에 빨리 닿을 수 있음",
                             "안 쓰는 MCP 서버·플러그인을 끄기"))
        else:
            out.append(Check("ok", f"{host} 도구 수", msg))
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
        # 기록이 낡아도 깔린 사본이 잠금과 같으면 통과(#48: marketplace upgrade 가 사본만 새로 받는 일이 있다)
        elif (same_commit(rec.get(p.id), p.sha) or same_commit(codex.cache_head(p.name), p.sha)
              or (p.id not in rec and same_commit(snap_sha.get(p.name), p.sha))):
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


def check_hermes_bot():
    """jaix가 깐 Hermes 슬랙 봇. jaix가 손댄 적이 없으면 보지 않는다."""
    rec = hermesbot.recorded()
    if not rec.get("status"):
        return []
    area = "Hermes 슬랙"
    if rec["status"] == "failed":
        return [Check("fail", area, rec.get("error") or "설치 실패", "jaix setup --channels hermes (AI센터 연결 코드 필요)")]
    if not hermesbot.find_hermes():
        return [Check("fail", area, "hermes 실행 파일이 없음", "jaix setup --channels hermes")]
    if rec["status"] == "no-code":
        return [Check("warn", area, "Hermes는 있으나 슬랙 연결 안 됨(연결 코드 없음)", "AI센터에서 연결 코드를 받아 jaix-setup 다시")]
    out = []
    if not (hermesbot.env_has("SLACK_BOT_TOKEN") and hermesbot.env_has("SLACK_APP_TOKEN")):
        out.append(Check("fail", area, "Hermes .env 에 슬랙 토큰이 없음", "AI센터에 새 연결 코드 요청"))
    elif IS_WIN and not hermesbot.startup_entries():
        out.append(Check("fail", area, "gateway 시작프로그램 항목이 없음 — 로그온 때 봇이 뜨지 않음",
                         "hermes gateway install"))
    else:
        slack = rec.get("slack") or {}
        out.append(Check("ok", area, f"Hermes-{slack.get('id')} 연결 기록 {slack.get('connected')}"))
    return out


def check_hermes(lock):
    have = hermes.installed()
    if not have:
        return [*check_hermes_bot()] or [Check("skip", "Hermes", "고르지 않음(설치기의 '슬랙으로도 쓰기')")]
    sha = {p.name: p.sha for p in lock.plugins}
    stale = sorted(n for n, m in have.items() if m.get("plugin") in sha and m.get("sha") != sha[m["plugin"]])
    if stale:
        return [Check("fail", "Hermes 스킬", f"잠금과 다름: {', '.join(stale)}", "jaix update")]
    return [*check_hermes_bot(), Check("ok", "Hermes 스킬", f"{len(have)}개 잠금과 같음")]


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
    return [*check_runtimes(), *check_uv_python(), *check_hwp_jar(lock), *check_rhwp(lock), *check_gw(), *check_works(lock), *check_path(), *check_claude(lock), *check_codex(lock),
            *check_hermes(lock), *check_autoupdate(), *check_path_tools(lock), *check_overlaps(lock), *check_load()]


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
