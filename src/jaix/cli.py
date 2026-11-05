"""jaix — 제주연구원 JAIX 도구 설치(setup) · 점검(doctor) · 갱신(update).

설치 프로그램 jaix-setup.exe는 체크박스만 받아 `jaix setup --channels …`에 넘기는 껍데기다
(ji-deploy-standards 3.2). 안내문도 여기서 만들어 설치 화면과 터미널이 같은 문구를 쓴다.
"""
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime

from jaix import __version__, claude, clis, codex, doctor, gw, hancom, hermes, hermesbot, hwpjar, hwprhwp, lock as lockmod, net, paths, plugbin, runtimes, schedule, selfupdate, uvpython, winenv, works

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
    missing = result.get("runtimes_missing") or []
    if missing:
        out += [f"※ [실패] 꼭 필요한 도구를 깔지 못했습니다: {', '.join(missing)}",
                "  이대로는 일부 jaix 도구가 동작하지 않습니다"
                + (" — Git 이 없으면 Claude 앱 Code 탭에 jaix 도구가 나타나지 않습니다." if "Git" in missing else "."),
                "  잠시 뒤(다른 네트워크에서) jaix-setup 을 다시 실행하세요. 그래도 안 되면 새 명령창에서 `jaix doctor` 결과와",
                f"  기록 파일 {paths.data_dir() / 'setup.log'} 을 AI센터에 보내 주세요.", ""]
    if "claude" in channels:
        quit_app = ("알림 영역(화면 오른쪽 아래 ^)에서 Claude 아이콘을 오른쪽 클릭 → Exit. "
                    "창의 X나 작업 표시줄에서 닫는 것만으로는 앱이 꺼지지 않습니다" if paths.IS_WIN
                    else "메뉴 막대의 Claude → Quit Claude(⌘Q). 창을 닫는 것만으로는 앱이 꺼지지 않습니다")
        out += [
            "■ Claude (데스크톱 앱의 Code 탭 · Claude Code)",
            "  1. Claude 앱을 완전히 종료했다가 다시 여세요(설치·업데이트 뒤마다).",
            f"     {quit_app}.",
            "     켜져 있던 앱은 jaix가 새로 정한 도구 위치(예: HWP2PDF_CLI)를 모릅니다.",
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
                "  Codex를 완전히 닫았다가 다시 여세요(설치·업데이트 뒤마다). 플러그인 목록에 jaix 도구가 켜져 있습니다.",
                "  켜져 있던 Codex는 jaix가 새로 정한 도구 위치(예: HWP2PDF_CLI)를 모릅니다.",
            ]
            out.append("  새 버전은 로그온할 때 jaix가 저절로 맞춥니다." if result.get("autoupdate")
                       else "  Codex는 저절로 갱신되지 않습니다. 가끔 명령창에서 `jaix update`를 실행하세요.")
        else:
            out += ["■ Codex", "  이 PC에서 Codex를 찾지 못했습니다. Codex를 설치한 뒤 jaix-setup을 다시 실행하세요."]
    terms = [n for n in ("claude", "codex") if n in channels and (result.get(f"{n}_cli") or {}).get("status")
             in ("present", "path-added", "installed")]
    failed = [n for n in ("claude", "codex") if n in channels and (result.get(f"{n}_cli") or {}).get("status") == "failed"]
    if terms:
        out += ["■ 명령창에서 쓰기",
                f"  새 명령창(PowerShell·cmd)을 열고 {' 또는 '.join(terms)} 를 입력하세요. 처음 한 번은 로그인을 묻습니다."]
    if failed:
        out += [f"  ※ {', '.join(failed)} 명령을 깔지 못했습니다. 잠시 뒤 jaix-setup 을 다시 실행하거나 jaix doctor 결과를 AI센터에 보내 주세요."]
    if "hermes" in channels:
        out += ["■ 슬랙으로도 쓰기 (Hermes)", *_hermes_guide(result.get("hermes") or {})]
    if (result.get("gw") or {}).get("status") in ("installed", "current"):
        out += ["■ 그룹웨어 (gw)",
                "  gw 를 처음 쓰기 전에 한 번 로그인하세요. 아이디·비밀번호는 이 PC에 안전하게 저장됩니다.",
                "  Claude·Codex 에게 'gw 로그인해 줘'라고 하면 입력 창이 뜹니다.",
                "  새 명령창에서 직접 `gw login` 을 치면 그 자리에서 묻습니다."]
    if net.rate_limit_hit:
        out += ["", f"※ {net.RATE_LIMIT_HINT}."]
    out += ["", "명령창(cmd·PowerShell)은 새로 여세요. 이미 열려 있던 창에서는 새로 깐 gw·jaix를 찾지 못합니다.",
            "문제가 있으면 새 명령창에서 `jaix doctor`를 실행해 결과를 AI센터에 보내 주세요."]
    return "\n".join(out)


def _hermes_guide(res):
    status = res.get("status")
    if status == "unsupported":
        return ["  이 OS에서는 jaix가 Hermes를 깔지 않습니다. hermes-slackbot 안내대로 설치하세요."]
    if status == "failed":
        kept = [f"  기존 슬랙 봇 Hermes-{res['kept']} 연결은 그대로 동작합니다."] if res.get("kept") else []
        return [f"  이번 설치에서 실패했습니다: {res.get('error')}", *kept,
                "  새 명령창에서 `jaix doctor` 결과를 AI센터에 보내 주세요."]
    login = " ".join(["hermes", *(res.get("login") or [])])
    lines = []
    if status == "connected":
        lines.append(f"  슬랙 봇 Hermes-{res.get('id')} 가 연결됐습니다. 이 PC가 켜져 있어야 봇이 답합니다.")
    elif status == "no-code":
        lines.append("  Hermes는 깔았지만 슬랙 연결 코드가 없어 연결하지 않았습니다. AI센터에서 코드를 받아 다시 설치하세요.")
    lines += ["  처음 한 번 AI 구독에 로그인하세요: 설치기 다음 화면 'AI 구독 로그인'의 [로그인 창 열기],",
              "  시작 메뉴의 'JAIX Hermes 로그인', 또는",
              f"  새 명령창에서 `{login}` 을 실행합니다(브라우저에서 승인)."]
    return lines


def _channels(value):
    chosen = [c.strip() for c in value.split(",") if c.strip()]
    bad = [c for c in chosen if c not in CHANNELS]
    if bad:
        raise SystemExit(f"모르는 채널: {', '.join(bad)} (가능: {', '.join(CHANNELS)})")
    return chosen


def _runtimes(value, lock=None):
    if value in (None, ""):
        return runtimes.select([], lock)
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
    args.task_fallback = True
    return cmd_setup(args, Log(args.log))


def _banner(what, how):
    """기록 섹션 머리줄: 언제·어느 길(작업 스케줄러인지 직접인지)·어느 실행파일로 돌았는지. 작업 스케줄러 기록은
    꺼져 있기 쉽고 한 번짜리 작업은 끝나면 지워져, 나중에 길을 되짚을 근거가 이것뿐이다(jaix-win v.13 실측)."""
    exe = Path(sys.executable).name if getattr(sys, "frozen", False) else "python -m jaix"
    return f"\n== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {what} ({how}) · {exe}"


def cmd_setup(args, log):
    if args.via_task and paths.IS_WIN:
        return _setup_via_task(args)
    lock = lockmod.load(args.lock, args.channel, args.offline)
    chosen = _channels(args.channels)
    if not args.dry_run:  # 본체 자기 업데이트가 설치기에 그대로 넘겨 이전 선택(Hermes 등)을 지킨다
        selfupdate.save_choice(chosen, args.hermes_model)
    # --status-out 은 --via-task 가 작업에 넘길 때만 붙는다
    how = "via task" if args.status_out else "direct, task fallback" if getattr(args, "task_fallback", False) else "direct"
    log(_banner("setup", how))
    log(f"jaix {__version__} · 잠금: {lock.source}")
    steps = Steps(log)
    if not args.dry_run:
        paths.bin_dir().mkdir(parents=True, exist_ok=True)
        steps.run("PATH", winenv.add_to_path, [paths.bin_dir()])
        for old in steps.run("PATH 정리", winenv.drop_old_exe_dir) or []:
            log(f"  PATH에서 뺌(예전 설치 위치): {old}")
    log("\n[1/3] 런타임")
    missing = []
    for rt in _runtimes(args.runtimes, lock):
        found = steps.run(rt.label, runtimes.ensure, rt, log, dry_run=args.dry_run)
        if paths.IS_WIN and not args.dry_run and found is not None and not runtimes.ok(rt, found):
            missing.append(rt.label)
    # Claude 앱(MSIX) 안에서 uvx가 Python을 처음 받으면 가상화로 깨진다(jaix-kit#14) → 앱 밖인 지금 깐다
    result = {}
    if missing:  # 내려받기가 막혀도 다음 단계는 하지만, 조용히 넘어가지 않는다(소모임 11/5: uv·Git·age 가 다 빠졌는데 설치는 성공)
        result["runtimes_missing"] = missing
        steps.failed.append("런타임(" + ", ".join(missing) + ")")
        steps.code = max(steps.code, 1)
    # ensure 들은 실패를 예외가 아니라 False 로 알린다 — 지난 실패 기록을 덮을지 판단에 쓴다
    result["uvpython"] = steps.run("uv 관리 Python", lambda: uvpython.ensure(uvpython.needed(lock, args.offline), log,
                                                                          dry_run=args.dry_run))
    # 첫 hwp 변환 때 에이전트가 우회하지 않게
    result["hwpjar"] = steps.run("HWP 변환기(jar)", hwpjar.ensure, lock, log, dry_run=args.dry_run, offline=args.offline)
    # 한글이 열려 있으면 hwp2pdf-cli가 건너뛴다 — 서버 없는 PC의 미리보기 폴백
    result["rhwp"] = steps.run("HWP 미리보기 엔진(rhwp)", hwprhwp.ensure, lock, log, dry_run=args.dry_run,
                               offline=args.offline)
    # 한컴 첫 실행 동의 창이 보이지 않는 한글을 막지 않게 — 한컴 PC이고 답(파일)이 없을 때만
    result["hancom_consent"] = steps.run(hancom.AREA, hancom.ensure, log, dry_run=args.dry_run)
    if args.gw_source and not args.dry_run:
        gw.save_source(args.gw_source)
    gw_res = steps.run("gw", gw.setup, log, dry_run=args.dry_run)
    if gw_res is not None:
        result["gw"] = gw_res
    works_res = steps.run("웍스(nworks)", works.ensure, lock, log, dry_run=args.dry_run, offline=args.offline)
    if works_res is not None:
        result["works"] = works_res
    # 스킬이 부르는 플러그인 bin/ 명령(예: mailskill). Claude Code 말고는 플러그인 bin 을 PATH 에 넣지 않는다
    pb_res = steps.run("플러그인 명령", plugbin.ensure, lock, log, dry_run=args.dry_run, offline=args.offline)
    if pb_res is not None:
        result["plugbin"] = pb_res
    log("\n[2/3] Claude")
    if "claude" in chosen:
        # 명령창의 claude: 있으면 그대로, PATH 에 없으면 올리고, 없으면 공식 네이티브 설치(사용자 요구 11/5).
        # 플러그인 설치(claude.setup)보다 먼저 — 새로 깐 CLI 로 플러그인을 넣는다
        res = steps.run("claude 명령", clis.ensure, "claude", log, dry_run=args.dry_run)
        if res is not None:
            result["claude_cli"] = res
            _cli_failed(steps, "claude 명령", res)
        # 다시 설치할 때 이미 깔린 옛 판도 잠금에 맞춘다(update 와 같게). 빠뜨리면 Codex 만 맞고 Claude 는 옛 판으로
        # 남아 doctor 가 실패를 보였다(jaix-win 11/4 ③)
        res = steps.run("Claude", claude.setup, lock, log, dry_run=args.dry_run, update=True)
        if res is not None:
            result["claude"] = res
            if not args.dry_run:  # doctor 가 이보다 먼저 켜진 Claude 앱을 "완전 종료 후 다시 열기"로 알린다
                steps.run("Claude 설정 시각", claude.mark_setup)
    else:
        log("  선택 안 함")
    log("\n[3/3] Codex · Hermes")
    if "codex" in chosen:
        res = steps.run("codex 명령", clis.ensure, "codex", log, dry_run=args.dry_run)
        if res is not None:
            result["codex_cli"] = res
            _cli_failed(steps, "codex 명령", res)
        res = steps.run("Codex", codex.setup, lock, log, dry_run=args.dry_run)
        if res is not None:
            result["codex"] = res
    if "hermes" in chosen:
        res = steps.run("Hermes", hermesbot.setup, lock, log, code_file=args.hermes_code_file, model=args.hermes_model,
                        dry_run=args.dry_run)
        if res is not None:
            result["hermes"] = res
            if res.get("status") == "failed":  # 실패는 설치 실패다(사용자 결정 ③) — 설치기가 종료 코드 10을 내게
                steps.failed.append("Hermes")
                steps.code = max(steps.code, 1)
    if not args.no_autoupdate:
        result["autoupdate"] = steps.run("로그온 자동 갱신", schedule.register, log, dry_run=args.dry_run)
    elif not args.dry_run and schedule.unregister():  # 끄라고 했으니 예전에 등록한 것도 지운다
        log("  로그온 자동 갱신: 지움 (--no-autoupdate)")
    if not args.dry_run and steps.code == 0 and not _setup_problems(result):
        # 다 맞췄으면 지난 로그온 자동 갱신의 실패 기록을 덮는다 — 남겨 두면 doctor 가 고쳐진 뒤에도 주의로 보인다
        schedule.write_status([], by="setup")
    text = guide(chosen, result)
    log("\n" + text)
    if args.guide_out:
        # Inno Setup LoadStringsFromFile가 UTF-8로 읽게 BOM을 붙인다
        Path(args.guide_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.guide_out, "w", encoding="utf-8-sig") as f:
            f.write(text + "\n")
    return steps.summary()


def _cli_failed(steps, area, res):
    """명령창 claude·codex 를 못 깔았으면 설치 실패로 센다(다른 단계는 계속) — 설치기 종료 코드 10, 지난 실패 기록 유지."""
    if res.get("status") == "failed":
        steps.failed.append(area)
        steps.code = max(steps.code, 1)


def _setup_problems(result):
    codex_res = result.get("codex") or {}
    return bool((result.get("hermes") or {}).get("status") == "failed"
                or (result.get("claude_cli") or {}).get("status") == "failed"
                or (result.get("codex_cli") or {}).get("status") == "failed"
                or result.get("uvpython") is False or result.get("hwpjar") is False or result.get("rhwp") is False
                or result.get("hancom_consent") is False
                or codex_res.get("error") or codex_res.get("failed")
                or (result.get("gw") or {}).get("status") == "failed"
                or (result.get("works") or {}).get("status") == "failed"
                or (result.get("plugbin") or {}).get("status") == "failed"
                or bool(result.get("runtimes_missing")))


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
    if getattr(args, "self_update", False):  # jaix update --self: 본체(설치본) 업데이트만
        return selfupdate.cmd_self(args, log)
    if not args.quiet:
        log(_banner("update", "direct"))
        problems = _update(args, log)
        if not args.dry_run:  # 손으로 고친 결과도 남겨야 doctor 가 지난 로그온 실패를 계속 보이지 않는다
            schedule.write_status(problems)
        if selfupdate.applies() and not args.offline and not args.dry_run:
            state = selfupdate.check()
            if state.get("newer") and sys.stdin and sys.stdin.isatty():  # 시작 메뉴 'JAIX 업데이트' 창 — 그 자리에서 묻는다
                log("")
                selfupdate.cmd_self(argparse.Namespace(yes=False), log)
            elif state.get("newer"):
                log(f"\n※ jaix 새 판 {state.get('latest')} 이 있습니다(지금 {__version__}). 본체 업데이트: jaix update --self")
        return 1 if problems else 0
    # 로그온 자동 갱신(예약 작업·시작프로그램 바로가기)이 부르는 경로: 화면에 쓰지 않고 기록·상태만 남긴다
    if args.delay:  # 바로가기는 로그온 즉시 돈다 — 네트워크가 올라올 틈(예약 작업의 '지연 2분' 대신)
        time.sleep(args.delay)
    log = Log(schedule.open_log(), quiet=True)
    log(_banner("update", "logon task") + " — 로그온 자동 갱신")
    # 첫 단계: 본체 새 판 확인·받기·검증(묻지 않음). 묻는 것은 도구 갱신이 끝난 뒤 — 답을 기다리느라 갱신이 밀리지 않게
    pending = None if args.dry_run else selfupdate.logon_prepare(log)
    try:
        problems = _update(args, log)
    except Exception as e:  # 잠금을 못 받음(오프라인)·깨진 설정 등 — 다음 로그온에 다시 한다
        log(f"멈춤: {e}")
        log(traceback.format_exc().rstrip())
        schedule.write_status([], error=str(e))
        selfupdate.logon_offer(pending, log)  # 새 판이 이 실패를 고친 것일 수도 있다
        return 1
    schedule.write_status(problems)
    for p in problems:
        log(f"문제: {p}")
    selfupdate.logon_offer(pending, log)
    return 1 if problems else 0


def _update(args, log):
    """돌려준 목록은 잠금에 못 맞춘 것들(--quiet 상태 기록용)."""
    problems = []
    lock = lockmod.load(args.lock, args.channel, args.offline)
    log(f"jaix {__version__} · 잠금: {lock.source}")
    log("\n[1/3] 런타임 갱신")
    for rt in runtimes.RUNTIMES:
        must = runtimes.required(rt, lock)
        if rt.applies and (must or runtimes.find(rt).path):
            found = runtimes.ensure(rt, log, dry_run=args.dry_run, upgrade=True)
            if must and not runtimes.ok(rt, found):
                problems.append(f"{rt.label} 없음")
    if not uvpython.ensure(uvpython.needed(lock, args.offline), log, dry_run=args.dry_run):  # 플러그인이 버전 고정을 바꿨으면 보충
        problems.append("uv 관리 Python 설치 실패")
    if not hwpjar.ensure(lock, log, dry_run=args.dry_run, offline=args.offline):
        problems.append("HWP 변환기(jar) 받기 실패")
    if not hwprhwp.ensure(lock, log, dry_run=args.dry_run, offline=args.offline):
        problems.append("HWP 미리보기 엔진(rhwp) 받기 실패")
    if gw.setup(log, dry_run=args.dry_run)["status"] == "failed":
        problems.append("gw 설치 실패")
    if works.ensure(lock, log, dry_run=args.dry_run, offline=args.offline)["status"] == "failed":
        problems.append("웍스(nworks) 설치 실패")
    pb = plugbin.ensure(lock, log, dry_run=args.dry_run, offline=args.offline)
    if pb["failed"]:
        problems.append(f"플러그인 명령 받기 실패: {', '.join(pb['failed'])}")
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
    # Hermes 업데이트가 새 기본 스킬·명령을 들여왔을 수 있어 jaix가 깐 Hermes 면 소음 정리를 다시 건다
    if hermesbot.recorded().get("quiet") and hermesbot.find_hermes() and not args.dry_run:
        if not hermesbot.quiet(hermesbot.find_hermes(), log):
            problems.append("Hermes 소음 정리 실패")
    return problems


def cmd_cleanup(args, log):
    """설치본 제거(jaix-setup 언인스톨러)가 부른다: 사용자 PATH에서 jaix 폴더와 로그온 자동 갱신을 뺀다.
    사용자 설정은 그대로 둔다."""
    if schedule.unregister():
        log("로그온 자동 갱신을 지움")
    clis.cleanup(log)  # jaix 가 깐 claude·codex 명령과 넣은 PATH 만
    for p in winenv.remove_from_path(paths.jaix_home()):
        log(f"PATH에서 뺌: {p}")
    # 지워질 jaix 사본을 가리키는 환경변수(HWP2PDF_CLI 등)도 뺀다 — 남기면 플러그인이 없는 파일을 부른다
    for rt in runtimes.RUNTIMES:
        if rt.env_var and winenv.remove_user_env_under(rt.env_var, paths.jaix_home()):
            log(f"환경변수 뺌: {rt.env_var}")
    return 0


def cmd_works(args, log):
    if args.works_cmd == "login":
        return works.login(log)
    return 2


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
    s.add_argument("--hermes-code-file", help="슬랙 연결 코드(JX-…)가 든 파일. 읽자마자 지움(코드는 명령줄에 싣지 않음)")
    s.add_argument("--hermes-model", choices=sorted(hermesbot.PROVIDERS), default="chatgpt",
                   help="Hermes가 쓸 AI 구독(기본 chatgpt)")
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
    u.add_argument("--delay", type=int, default=0, help="--quiet 일 때 시작 전에 기다릴 초(시작프로그램 바로가기용)")
    u.add_argument("--self", dest="self_update", action="store_true",
                   help="jaix 본체(설치본) 새 판을 지금 확인하고, 있으면 받아 검증한 뒤 물어서 설치기를 띄움")
    u.add_argument("--yes", action="store_true", help="--self 에서 묻지 않고 바로 설치기를 띄움")
    u.set_defaults(func=cmd_update)

    h = sub.add_parser("hermes", help="Hermes 관리자 명령")
    hsub = h.add_subparsers(dest="hermes_cmd", required=True)
    ho = hsub.add_parser("handoff", help="관리자(studio): 사람별 슬랙 토큰을 1회용 연결 코드로 내보냄")
    ho.add_argument("id", help="앱 Hermes-<아이디> 의 아이디")
    ho.add_argument("--user", required=True, help="구성원 슬랙 멤버 ID(U…) — 봇이 답할 유일한 사람")
    ho.add_argument("--ttl", type=float, default=hermesbot.TTL_HOURS, help="유효 시간(기본 72)")
    ho.add_argument("--spool", help=f"묶음 폴더(기본 {hermesbot.HANDOFF_SPOOL}, ji-gw-ai 배포처와 같게)")
    ho.set_defaults(func=hermesbot.cmd_handoff)
    ap_ = hsub.add_parser("approvals", help="이 PC Hermes 의 위험 명령 승인 방식(smart·manual). off 는 AI센터 관리자만")
    ap_.add_argument("mode", choices=hermesbot.APPROVAL_MODES)
    ap_.set_defaults(func=hermesbot.cmd_approvals)
    lg = hsub.add_parser("login", help="Hermes 의 AI 구독 로그인(설치기 마지막 화면이 부름)")
    lg.add_argument("--model", choices=sorted(hermesbot.PROVIDERS), default="chatgpt")
    lg.add_argument("--no-wait", action="store_true", help="끝나고 Enter 를 기다리지 않음")
    lg.add_argument("--force", action="store_true", help="이미 로그인돼 있어도 묻지 않고 다시 로그인(예전 자격은 정리)")
    lg.set_defaults(func=hermesbot.cmd_login)

    w = sub.add_parser("works", parents=[common], help="웍스(NAVER WORKS) 도구")
    wsub = w.add_subparsers(dest="works_cmd", required=True)
    wsub.add_parser("login", help="브라우저로 웍스 로그인(처음 한 번, 본인 계정 권한)")
    w.set_defaults(func=cmd_works)

    c = sub.add_parser("cleanup", parents=[common], help=argparse.SUPPRESS)
    c.set_defaults(func=cmd_cleanup)
    return ap


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw)
    args.raw_argv = raw[1:]  # 하위 명령 뒤의 인자(--via-task 가 그대로 다시 넘김)
    paths.migrate_data()  # 예전 설치본이 프로그램 폴더에 둔 기록·상태를 데이터 폴더로
    # --via-task 는 진행 줄을 setup.log 에서 읽어 흘리므로 같은 파일에 또 쓰지 않는다
    # hermes handoff 에는 --log 가 없다(연결 코드가 기록 파일에 남지 않게) → 없는 하위 명령도 있다(#67)
    log = Log(None if getattr(args, "via_task", False) and paths.IS_WIN else getattr(args, "log", None))
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
