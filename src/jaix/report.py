"""jaix report: 원격으로 원인을 파악할 수 있게 한 파일로 모은 문제 보고(jaix-kit#188).

판(jaix·OS·Hermes·플러그인 잠금), doctor --json 원문, Hermes 실패 원인 기록, 연결 상태, 최근 setup.log·update.log 의
실패 주변 줄을 모아 비밀·개인 식별 값을 가린 뒤(redact) data_dir/report-<시각>.txt 로 저장하고 화면에도 낸다.
구성원은 요약하지 않고 이 출력을 그대로 붙인다. 서버로 보내지는 않는다.
"""
import datetime
import json
import platform
import re
import sys

from jaix import __version__, connect, doctor, hermesbot, paths, schedule
from jaix.redact import redact, redact_json

LOG_TAIL = 400  # 기록 파일은 끝의 이만큼만 본다(최근 실행)
CONTEXT = 3  # 실패 줄 앞뒤로 함께 싣는 줄 수
LOG_LIMIT = 80  # 기록 한 파일에서 싣는 줄 상한(최근 것 우선)
FAIL_RE = re.compile(r"실패|멈춤|오류|못 함|못함|거부|→ 코드 [1-9-]|Traceback|Error|Exception|\[실패\]|FAILED", re.I)


def failure_lines(text, tail=LOG_TAIL, context=CONTEXT, limit=LOG_LIMIT):
    """기록 끝 tail 줄에서 실패로 보이는 줄과 그 앞뒤 context 줄. 떨어진 묶음 사이에는 '…'. 많으면 뒤쪽 limit 줄."""
    lines = (text or "").splitlines()[-tail:]
    keep = set()
    for i, ln in enumerate(lines):
        if FAIL_RE.search(ln):
            keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    out, prev = [], None
    for i in sorted(keep):
        if prev is not None and i != prev + 1:
            out.append("…")
        out.append(lines[i])
        prev = i
    if len(out) > limit:
        out = ["…(앞부분 줄임)", *out[-limit:]]
    return out


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _hermes_version():
    exe = hermesbot.find_hermes()
    if not exe:
        return "없음"
    return doctor._tool_version(exe) or "버전 확인 실패"


def _section(title, body):
    return [f"== {title} ==", *(body if isinstance(body, list) else [body]), ""]


def build(lock, now=None, hermes_version=None, checks=None, statuses=None):
    """가리기 전의 보고 글. 각 부분은 실패해도 그 자리에 이유만 적고 나머지를 싣는다."""
    now = now or datetime.datetime.now()
    out = [f"JAIX 문제 보고 {now.isoformat(timespec='seconds')}", ""]

    ver = [f"jaix {__version__}", f"OS {platform.platform()} · Python {platform.python_version()}"]
    try:
        ver.append(f"Hermes {hermes_version if hermes_version is not None else _hermes_version()}")
    except Exception as e:  # noqa: BLE001 — 보고는 끝까지 만든다
        ver.append(f"Hermes 확인 오류: {type(e).__name__}")
    ver.append(f"잠금: {lock.source}")
    try:
        ver += [f"  {p.name} {p.version or '-'} {p.sha[:12]}" for p in lock.plugins]
    except Exception as e:  # noqa: BLE001
        ver.append(f"  플러그인 목록 오류: {type(e).__name__}")
    out += _section("판", ver)

    try:
        checks = doctor.run(lock) if checks is None else checks
        failed = any(c.status == "fail" for c in checks)
        doc = json.dumps(redact_json({"version": __version__, "lock": lock.source, "ok": not failed,
                                      "checks": doctor.as_dicts(checks)}), ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        doc = f"doctor 를 돌리지 못함: {type(e).__name__}: {e}"
    out += _section("jaix doctor --json", doc)

    rec = hermesbot.recorded()
    if rec:
        her = [f"status: {rec.get('status')}"]
        for k in ("error", "last_error"):
            if rec.get(k):
                her.append(f"{k}: {rec[k]}")
        for k in ("error_detail", "last_error_detail"):
            if rec.get(k):
                her += [f"{k}:", *(f"  {ln}" for ln in hermesbot.detail_lines(rec[k]))]
        out += _section("Hermes 기록", her)

    try:
        sts = connect.statuses(lock) if statuses is None else statuses
        out += _section("연결 상태", connect.render(sts) or "(항목 없음)")
    except Exception as e:  # noqa: BLE001
        out += _section("연결 상태", f"확인 오류: {type(e).__name__}")

    last = schedule.last_status()
    if last:
        out += _section("마지막 갱신 상태(update-status.json)", json.dumps(redact_json(last), ensure_ascii=False))

    for name, path in (("setup.log", paths.data_dir() / "setup.log"), ("update.log", schedule.log_file())):
        text = _read(path)
        if text is None:
            body = "(없음)"
        else:
            body = failure_lines(text) or "(최근 기록에 실패로 보이는 줄 없음)"
        out += _section(f"{name} 실패 주변(최근 {LOG_TAIL}줄 중)", body)
    return "\n".join(out).rstrip() + "\n"


def report_path(now=None):
    now = now or datetime.datetime.now()
    return paths.data_dir() / f"report-{now.strftime('%Y%m%d-%H%M%S')}.txt"


def cmd_report(args, log, lock_loader=None):
    from jaix import lock as lockmod
    now = datetime.datetime.now()
    try:
        lock = (lock_loader or lockmod.load)(args.lock, args.channel, args.offline)
    except Exception as e:  # noqa: BLE001 — 잠금을 못 받아도(원외망·깨진 사본) 나머지는 보고한다
        class _NoLock:
            source = f"잠금 못 읽음({type(e).__name__})"
            plugins = []
        lock = _NoLock()
    text = redact(build(lock, now=now))
    path = report_path(now)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        saved = f"저장: {redact(str(path))}"
    except OSError as e:
        saved = f"파일로 저장하지 못함({type(e).__name__}) — 위 내용을 그대로 복사하세요"
    sys.stdout.flush()
    log(text.rstrip())
    log("")
    log(saved)
    log("이 출력 전체를(요약하지 말고) AI센터·소모임 채널에 붙여 주세요. 비밀번호·토큰·사용자 폴더 이름·슬랙 ID 는 가렸습니다.")
    return 0
