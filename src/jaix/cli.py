"""jaix — 제주연구원 JAIX 도구 설치(setup) · 점검(doctor) · 갱신(update).

설치 프로그램 jaix-setup.exe는 체크박스만 받아 `jaix setup --channels …`에 넘기는 껍데기다
(ji-deploy-standards 3.2). 안내문도 여기서 만들어 설치 화면과 터미널이 같은 문구를 쓴다.
"""
import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime

from jaix import __version__, claude, codex, doctor, gw, hermes, hwpjar, lock as lockmod, paths, runtimes, schedule, uvpython, winenv

CHANNELS = ("claude", "codex", "hermes")

# 창 없는 jaixw.exe(PyInstaller --noconsole)에는 표준 출력이 없다(None) → print·argparse 오류가 죽지 않게 버린다
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
# 한국어 Windows 콘솔(cp949)·CI(cp1252)로 파이프될 때도 한글이 죽지 않게
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


class Steps:
    """단계마다 예외를 잡아 traceback 을 기록하고 다음 단계로 간다(#27: 설치본에서 조용히 죽음)."""

    def __init__(self, log):
        self.log, self.failed, self.code = log, [], 0

    def run(self, name, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001 — 한 단계가 막혀도 나머지를 한다. doctor 가 남은 것을 알려 준다
            self.log(f"  ✗ {name}: {type(e).__name__}: {e}")
            self.log(traceback.format_exc().rstrip())
            self.failed.append(name)
            self.code = max(self.code, 2 if isinstance(e, ValueError) else 1)  # 깨진 설정(덮어쓰지 않음)은 2
            return None

    def summary(self):
        if self.failed:
            self.log(f"\n일부 단계가 실패했습니다: {', '.join(self.failed)}")
            self.log("새 명령창에서 `jaix doctor` 를 실행해 결과를 AI센터에 보내 주세요.")
        return self.code


class Log:
    def __init__(self, path=None, quiet=False):
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a", encoding="utf-8") if path else None
        self.quiet = quiet

    def __call__(self, msg=""):
        if not self.quiet:
            print(msg, flush=True)
        if self.file:
            self.file.write(msg + "\n")
            self.file.flush()


def guide(channels, result):
    """채널별 "이렇게 쓰세요". 고른 채널만 보여 준다(ji-deploy-standards 3.1)."""
    out = []
    if "claude" in channels:
        quit_app = ("알림 영역(화면 오른쪽 아래 ^)에서 Claude 아이콘을 오른쪽 클릭 → Exit. "
                    "창의 X나 작업 표시줄에서 닫는 것만으로는 앱이 꺼지지 않습니다" if paths.IS_WIN
                    else "메뉴 막대의 Claude → Quit Claude(⌘Q). 창을 닫는 것만으로는 앱이 꺼지지 않습니다")
        out += [
            "■ Claude (데스크톱 앱의 Code 탭 · Claude Code)",
            "  1. Claude 앱을 완전히 종료했다가 다시 여세요.",
            f"     {quit_app}.",
            "  2. Code 탭에서 HWP 편집 · 업무일지 · 보고서 작성 표준 도구를 쓸 수 있습니다.",
            "     새 버전도 앱을 다시 열 때 저절로 받습니다.",
            "  3. 왼쪽 위 모델 선택에서 Sonnet을 고르세요. 사용량을 아낍니다.",
            "  4. Cowork(채팅)에서 쓰는 도구는 기관 관리자 배포로 내려옵니다.",
        ]
        if result.get("claude") and not result["claude"].get("cli") and not result["claude"].get("managed"):
            out += ["  ※ 아직 Claude Code를 찾지 못해 도구를 직접 깔지 못했습니다. Claude 앱에서 Code 탭을 열었다 닫고",
                    "     한 번 더 여세요(첫 번째에 도구 목록을 받고, 두 번째에 설치합니다)."]
        if result.get("claude", {}).get("managed"):
            out.append("  (도구 목록은 기관 관리자 설정으로 내려옵니다)")
    if "codex" in channels:
        if result.get("codex", {}).get("cli"):
            out += [
                "■ Codex",
                "  Codex를 다시 시작하세요. 플러그인 목록에 jaix 도구가 켜져 있습니다.",
            ]
            out.append("  새 버전은 로그온할 때 jaix가 저절로 맞춥니다." if result.get("autoupdate")
                       else "  Codex는 저절로 갱신되지 않습니다. 가끔 명령창에서 `jaix update`를 실행하세요.")
        else:
            out += ["■ Codex", "  이 PC에서 Codex를 찾지 못했습니다. Codex를 설치한 뒤 jaix-setup을 다시 실행하세요."]
    if "hermes" in channels:
        out += ["■ 슬랙으로도 쓰기 (Hermes)", f"  {hermes.NOT_YET}"]
    if (result.get("gw") or {}).get("status") in ("installed", "current"):
        out += ["■ 그룹웨어 (gw)",
                "  gw 를 처음 쓰기 전에 새 명령창에서 `gw login` 을 한 번 실행하세요.",
                "  뜨는 창에 그룹웨어 아이디·비밀번호를 넣으면 이 PC에 안전하게 저장됩니다."]
    out += ["", "명령창(cmd·PowerShell)은 새로 여세요. 이미 열려 있던 창에서는 새로 깐 gw·jaix를 찾지 못합니다.",
            "문제가 있으면 새 명령창에서 `jaix doctor`를 실행해 결과를 AI센터에 보내 주세요."]
    return "\n".join(out)


def _channels(value):
    chosen = [c.strip() for c in value.split(",") if c.strip()]
    bad = [c for c in chosen if c not in CHANNELS]
    if bad:
        raise SystemExit(f"모르는 채널: {', '.join(bad)} (가능: {', '.join(CHANNELS)})")
    return chosen


def _runtimes(value):
    if value in (None, ""):
        return runtimes.select([])
    if value == "none":
        return []
    if value == "all":
        return [rt for rt in runtimes.RUNTIMES if rt.applies]
    return runtimes.select([k.strip() for k in value.split(",") if k.strip()])


def _setup_via_task(args):
    """설치본(Inno)이 부르는 길: 같은 jaix setup 을 작업 스케줄러로 돌려 Inno 의 프로세스 완화 정책을 물려받지
    않게 한다(#27). 진행 줄은 setup.log 에서 읽어 이 프로세스의 표준 출력으로 흘려 설치 화면에 보인다."""
    raw = [a for a in args.raw_argv if a != "--via-task"]
    status = paths.data_dir() / "setup-status.json"
    base = paths.self_command(windowless=True)  # 작업이 도는 동안 콘솔 창이 뜨지 않게
    log_path = args.log or str(paths.data_dir() / "setup.log")
    if not args.log:
        raw += ["--log", log_path]
    code = schedule.run_via_task([*base, "setup", *raw, "--status-out", str(status)], log_path, status, Log())
    if code is not None:
        return code
    args.via_task = False  # 작업으로 못 돌렸으면 직접(상속된 채로라도) 한다
    return cmd_setup(args, Log(args.log))


def cmd_setup(args, log):
    if args.via_task and paths.IS_WIN:
        return _setup_via_task(args)
    lock = lockmod.load(args.lock, args.channel, args.offline)
    chosen = _channels(args.channels)
    log(f"jaix {__version__} · 잠금: {lock.source}")
    steps = Steps(log)
    if not args.dry_run:
        paths.bin_dir().mkdir(parents=True, exist_ok=True)
        steps.run("PATH", winenv.add_to_path, [paths.bin_dir()])
    log("\n[1/3] 런타임")
    for rt in _runtimes(args.runtimes):
        steps.run(rt.label, runtimes.ensure, rt, log, dry_run=args.dry_run)
    # Claude 앱(MSIX) 안에서 uvx가 Python을 처음 받으면 가상화로 깨진다(jaix-kit#14) → 앱 밖인 지금 깐다
    steps.run("uv 관리 Python", lambda: uvpython.ensure(uvpython.needed(lock, args.offline), log, dry_run=args.dry_run))
    # 첫 hwp 변환 때 에이전트가 우회하지 않게
    steps.run("HWP 변환기(jar)", hwpjar.ensure, lock, log, dry_run=args.dry_run, offline=args.offline)
    result = {}
    if args.gw_source and not args.dry_run:
        gw.save_source(args.gw_source)
    gw_res = steps.run("gw", gw.setup, log, dry_run=args.dry_run)
    if gw_res is not None:
        result["gw"] = gw_res
    log("\n[2/3] Claude")
    if "claude" in chosen:
        res = steps.run("Claude", claude.setup, lock, log, dry_run=args.dry_run)
        if res is not None:
            result["claude"] = res
    else:
        log("  선택 안 함")
    log("\n[3/3] Codex · Hermes")
    if "codex" in chosen:
        res = steps.run("Codex", codex.setup, lock, log, dry_run=args.dry_run)
        if res is not None:
            result["codex"] = res
    if "hermes" in chosen:
        log(f"  {hermes.NOT_YET}")
    if not args.no_autoupdate:
        result["autoupdate"] = steps.run("로그온 자동 갱신", schedule.register, log, dry_run=args.dry_run)
    elif not args.dry_run and schedule.unregister():  # 끄라고 했으니 예전에 등록한 것도 지운다
        log("  로그온 자동 갱신: 지움 (--no-autoupdate)")
    text = guide(chosen, result)
    log("\n" + text)
    if args.guide_out:
        # Inno Setup LoadStringsFromFile가 UTF-8로 읽게 BOM을 붙인다
        Path(args.guide_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.guide_out, "w", encoding="utf-8-sig") as f:
            f.write(text + "\n")
    return steps.summary()


def cmd_doctor(args, log):
    lock = lockmod.load(args.lock, args.channel, args.offline)
    checks = doctor.run(lock)
    failed = any(c.status == "fail" for c in checks)
    if args.json:
        print(json.dumps({"version": __version__, "lock": lock.source, "ok": not failed,
                          "checks": doctor.as_dicts(checks)}, ensure_ascii=False, indent=2))
    else:
        log(f"jaix {__version__} · 잠금: {lock.source}")
        log(doctor.render(checks))
        log("\n결과: " + ("고칠 것이 있습니다 — 위 → 줄을 따라 하세요" if failed else "정상"))
    return 1 if failed else 0


def cmd_update(args, log):
    if not args.quiet:
        return 1 if _update(args, log) else 0
    # 로그온 예약 작업이 부르는 경로: 화면에 쓰지 않고 기록·상태만 남긴다. 실패는 doctor가 보여 준다
    log = Log(schedule.open_log(), quiet=True)
    log(f"\n== {datetime.now().isoformat(timespec='seconds')} 로그온 자동 갱신")
    try:
        problems = _update(args, log)
    except Exception as e:  # 잠금을 못 받음(오프라인)·깨진 설정 등 — 다음 로그온에 다시 한다
        log(f"멈춤: {e}")
        log(traceback.format_exc().rstrip())
        schedule.write_status([], error=str(e))
        return 1
    schedule.write_status(problems)
    for p in problems:
        log(f"문제: {p}")
    return 1 if problems else 0


def _update(args, log):
    """돌려준 목록은 잠금에 못 맞춘 것들(--quiet 상태 기록용)."""
    problems = []
    lock = lockmod.load(args.lock, args.channel, args.offline)
    log(f"jaix {__version__} · 잠금: {lock.source}")
    log("\n[1/3] 런타임 갱신")
    for rt in runtimes.RUNTIMES:
        if rt.applies and (rt.required or runtimes.find(rt).path):
            found = runtimes.ensure(rt, log, dry_run=args.dry_run, upgrade=True)
            if rt.required and not runtimes.ok(rt, found):
                problems.append(f"{rt.label} 없음")
    if not uvpython.ensure(uvpython.needed(lock, args.offline), log, dry_run=args.dry_run):  # 플러그인이 버전 고정을 바꿨으면 보충
        problems.append("uv 관리 Python 설치 실패")
    if not hwpjar.ensure(lock, log, dry_run=args.dry_run, offline=args.offline):
        problems.append("HWP 변환기(jar) 받기 실패")
    if gw.setup(log, dry_run=args.dry_run)["status"] == "failed":
        problems.append("gw 설치 실패")
    log("\n[2/3] Claude · Codex 플러그인")
    claude.setup(lock, log, dry_run=args.dry_run, update=True)
    if claude.find_cli() and not args.dry_run:
        have = claude.installed()
        stale = [p.name for p in lock.plugins if p.id not in have or not claude.matches(p, have[p.id])]
        if stale:
            problems.append(f"Claude 플러그인 잠금과 다름: {', '.join(stale)}")
    if codex.find_cli():
        res = codex.setup(lock, log, dry_run=args.dry_run, update=True)
        if res.get("error"):
            problems.append(f"Codex {res['error']} 실패")
        if res.get("failed"):
            problems.append(f"Codex 플러그인 설치 실패: {', '.join(res['failed'])}")
    log("\n[3/3] Hermes 스킬")
    changed = hermes.sync(lock, log, dry_run=args.dry_run)
    log(f"  {len(changed)}개 맞춤" if changed else "  맞출 것 없음")
    return problems


def cmd_cleanup(args, log):
    """설치본 제거(jaix-setup 언인스톨러)가 부른다: 사용자 PATH에서 jaix 폴더와 로그온 자동 갱신을 뺀다.
    사용자 설정은 그대로 둔다."""
    if schedule.unregister():
        log("로그온 자동 갱신을 지움")
    for p in winenv.remove_from_path(paths.jaix_home()):
        log(f"PATH에서 뺌: {p}")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="jaix", description="제주연구원 JAIX 도구 설치·점검·갱신")
    ap.add_argument("--version", action="version", version=f"jaix {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lock", help="잠금 파일 경로(기본: GitHub의 채널 브랜치, 안 되면 묶은 사본)")
    common.add_argument("--channel", choices=sorted(lockmod.CHANNEL_BRANCH), default="stable",
                        help="stable(main, 전원) 또는 beta(AI센터 파일럿)")
    common.add_argument("--offline", action="store_true", help="잠금을 내려받지 않고 묶은 사본을 씀")
    common.add_argument("--log", help="진행 기록을 이 파일에도 덧붙임")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", parents=[common], help="런타임 설치 + 채널별 도구 등록")
    s.add_argument("--channels", default="claude,codex", help="claude,codex,hermes 중 쉼표로 (기본 claude,codex)")
    s.add_argument("--runtimes", help="설치할 런타임: 쉼표 목록 | all | none (기본: 필수만)")
    s.add_argument("--dry-run", action="store_true", help="바꾸지 않고 할 일만 보여 줌")
    s.add_argument("--gw-source", help=f"그룹웨어(gw) 런타임 원내 latest.json 주소(기본 {gw.DEFAULT_SOURCE}, 저장해 두고 "
                                       "update도 씀, none이면 끔). 원내망이 아니면 gw만 건너뜀")
    s.add_argument("--no-autoupdate", action="store_true", help="로그온 자동 갱신(jaix update --quiet)을 등록하지 않음")
    s.add_argument("--guide-out", help="마지막 안내문을 이 파일에 씀(설치 프로그램용)")
    s.add_argument("--via-task", action="store_true",
                   help=argparse.SUPPRESS)  # 설치본용: 작업 스케줄러로 돌려 설치본의 프로세스 정책을 물려받지 않음(#27)
    s.add_argument("--status-out", help=argparse.SUPPRESS)  # --via-task 가 기다리는 종료 코드 파일
    s.set_defaults(func=cmd_setup)

    d = sub.add_parser("doctor", parents=[common], help="런타임·등록·플러그인 버전이 잠금과 맞는지 점검")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)

    u = sub.add_parser("update", parents=[common], help="런타임 갱신 + 플러그인·Hermes 스킬을 잠금에 맞춤")
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--quiet", action="store_true",
                   help="화면에 쓰지 않고 update.log·update-status.json에만 남김(로그온 자동 갱신용)")
    u.set_defaults(func=cmd_update)

    c = sub.add_parser("cleanup", parents=[common], help=argparse.SUPPRESS)
    c.set_defaults(func=cmd_cleanup)
    return ap


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw)
    args.raw_argv = raw[1:]  # 하위 명령 뒤의 인자(--via-task 가 그대로 다시 넘김)
    paths.migrate_data()  # 예전 설치본이 프로그램 폴더에 둔 기록·상태를 데이터 폴더로
    # --via-task 는 진행 줄을 setup.log 에서 읽어 흘리므로 같은 파일에 또 쓰지 않는다
    log = Log(None if getattr(args, "via_task", False) and paths.IS_WIN else args.log)
    code = 1
    try:
        code = args.func(args, log)
    except FileNotFoundError as e:  # 잠금을 못 받았고 묶은 사본도 없음
        log(f"멈춤: {e}")
        code = 2
    except ValueError as e:  # 깨진 settings.json 등 — 덮어쓰지 않고 멈춘다
        log(f"멈춤: {e}")
        code = 2
    except KeyboardInterrupt:
        code = 130
    except Exception as e:  # noqa: BLE001 — 설치본 경로에서도 원인을 남긴다(#27)
        log(f"멈춤: {type(e).__name__}: {e}")
        log(traceback.format_exc().rstrip())
        code = 1
    finally:
        out = getattr(args, "status_out", None)
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(json.dumps({"code": code}), encoding="utf-8")
    return code
