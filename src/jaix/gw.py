"""그룹웨어(gw) 공유 런타임: 원내 배포 위치의 latest.json → wheel → `uv tool install`.

gw는 라이선스상 원외 재배포가 안 돼 공개 플러그인·이 저장소에 넣지 않는다. jaix setup이 **원내 위치**에서 받아
설치한다(jeju-inst/ji-gw-ai#108 Q2 ②, 배포 형식은 ji-gw-ai#122). 배포 위치는 IP 게이트가 걸린 정적 서버다:
  <원본>/latest.json = {name, version, wheel, url, sha256, size, source_commit, published_at}
jaix는 latest.json을 읽고 wheel을 받아 sha256을 확인한 뒤 `uv tool install <wheel>`로 깐다.
설치된 버전이 latest.json과 다르면(새 버전·롤백 모두) 다시 깐다. 원본에 닿지 않으면(원내망이 아님) gw만 건너뛰고
doctor가 안내한다. 원본은 기본 DEFAULT_SOURCE, `jaix setup --gw-source <URL>`(jaix_home/config.json에 저장)이나
환경변수 JAIX_GW_SOURCE로 바꾼다. `none`이면 끈다.
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from jaix import net, paths, runtimes, winenv
from jaix.paths import IS_WIN

ENV = "JAIX_GW_SOURCE"
DEFAULT_SOURCE = "https://jaix.namun.net/gw/latest.json"
EXE = "gw"


def _config_file():
    return paths.jaix_home() / "config.json"


def _config():
    try:
        return json.loads(_config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_config(**values):
    data = {**_config(), **values}
    _config_file().parent.mkdir(parents=True, exist_ok=True)
    _config_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def source():
    """latest.json 주소. None이면 끈 것."""
    url = os.environ.get(ENV) or _config().get("gw_source") or DEFAULT_SOURCE
    return None if url.lower() == "none" else url


def save_source(url):
    _save_config(gw_source=url)


def unpublished(url=None):
    """배포처 이름이 DNS에 없다 = 아직 배포 전(원내망 밖이라 막힌 것과 구분한다)."""
    host = urlparse(url or source() or "").hostname
    if not host:
        return False
    try:
        socket.getaddrinfo(host, 443)
        return False
    except socket.gaierror:
        return True
    except OSError:
        return False


def latest(url=None, timeout=8):
    """원내 위치의 latest.json. 닿지 않거나(원외·IP 게이트 거절·배포 전) 형식이 틀리면 None."""
    url = url or source()
    if not url:
        return None
    try:
        data = net.get_json(url, timeout=timeout)
    except Exception:
        return None
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k]
                                             for k in ("name", "version", "wheel", "url", "sha256")):
        return None
    return data


def _uv():
    return runtimes.find(runtimes.BY_KEY["uv"]).path


def _run(args, timeout=60):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def tool_bin(uv=None):
    """uv tool이 실행파일을 두는 곳(Windows %USERPROFILE%\\.local\\bin)."""
    uv = uv or _uv()
    ok, out = _run([uv, "tool", "dir", "--bin"]) if uv else (False, "")
    return Path(out.splitlines()[-1]) if ok and out else None


def installed_version(uv=None):
    """jaix가 uv tool로 깐 gw의 버전. 개발용으로 따로 둔 gw(PATH의 다른 것)는 세지 않는다."""
    name = _config().get("gw_package")
    uv = uv or _uv()
    if not name or not uv:
        return None
    ok, out = _run([uv, "tool", "list"])
    norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()  # noqa: E731  패키지 이름 정규화(PEP 503)
    listed = dict(re.findall(r"^(\S+) v(\S+)", out, re.M)) if ok else {}
    version = next((v for n, v in listed.items() if norm(n) == norm(name)), None)
    if not version:
        return None
    # 실행파일이 실제로 도는지까지: gw --version이 버전을 말하면 그것을 믿는다
    exe = (tool_bin(uv) or Path()) / (EXE + (".exe" if IS_WIN else ""))
    ok, out = _run([str(exe), "--version"], timeout=30)
    v = re.search(r"\d+(?:\.\d+)+", out) if ok else None
    return v.group(0) if v else version


def same(a, b):
    key = lambda v: tuple(int(x) for x in re.findall(r"\d+", v or ""))  # noqa: E731  2026.10.27.1 == 2026.10.27.01
    return key(a) == key(b)


def setup(log, dry_run=False):
    """setup·update 공통: latest.json과 버전이 다르면 깐다. 돌려준 status는 doctor·update 문제 기록용."""
    url = source()
    if not url:
        log("  gw: 끔 (--gw-source none)")
        return {"status": "off"}
    info = latest(url)
    if not info and unpublished(url):
        log(f"  gw: 배포처({urlparse(url).hostname})가 아직 준비되지 않음(배포 전) → 건너뜀. 배포가 시작되면 `jaix update`가 설치")
        return {"status": "unpublished"}
    if not info:
        log(f"  gw: 원내 위치({url})에 닿지 않음 → 건너뜀. 원내망(사무실·VPN)에서 `jaix setup` 다시 실행")
        return {"status": "offsite"}
    if info.get("gw_base_url") and not dry_run:
        save_base_url(info["gw_base_url"], log)
    uv = _uv()
    if not uv:
        log("  gw: uv가 없어 설치 못 함 (위 uv 항목 참고)")
        return {"status": "failed"}
    have = installed_version(uv)
    if have and same(have, info["version"]):
        log(f"  gw: {have} (최신)")
        return {"status": "current", "version": have}
    if dry_run:
        log(f"  gw: {have or '없음'} → {info['version']} 설치 예정")
        return {"status": "planned"}
    try:
        _install(info, uv)
    except Exception as e:  # gw가 막혀도 나머지 설치는 계속한다. doctor가 남은 것을 알려 준다
        log(f"  gw: 설치 실패 — {e}")
        return {"status": "failed"}
    log(f"  gw: {have or '없음'} → {info['version']} 설치함")
    return {"status": "installed", "version": info["version"]}


# --- gw 런타임 사용자 설정(share.toml) ----------------------------------------------------------------
# gw 런타임은 그룹웨어 주소를 GW_BASE_URL → share.toml [gw].base_url 순으로 찾는다(ji-gw-ai). 원내 주소라
# 공개 저장소에 둘 수 없어, IP 제한 배포의 latest.json(gw_base_url)으로만 받는다 — 원외에서는 서버가 이 필드를
# 빼고 내주므로 없으면 파일을 건드리지 않는다. 비밀번호는 jaix가 다루지 않는다(`gw login`이 OS 자격 증명 저장소에).
def share_toml():
    """ji_gw_ai.core.paths 와 같은 규칙: JI_GW_CONFIG_DIR 또는 모든 OS에서 ~/.config/ji-gw-ai."""
    env = os.environ.get("JI_GW_CONFIG_DIR", "").strip()
    return (Path(env).expanduser() if env else Path.home() / ".config" / "ji-gw-ai") / "share.toml"


def base_url():
    """gw 런타임이 쓸 그룹웨어 주소(환경변수 우선). 없으면 None."""
    if os.environ.get("GW_BASE_URL", "").strip():
        return os.environ["GW_BASE_URL"].strip()
    try:
        return (tomllib.loads(share_toml().read_text(encoding="utf-8")).get("gw") or {}).get("base_url") or None
    except (OSError, ValueError):
        return None  # 깨진 파일은 런타임도 없는 것으로 본다


def save_base_url(url, log):
    """share.toml 의 [gw].base_url 만 바꾼다. 다른 키·표는 그대로 둔다."""
    f = share_toml()
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    try:
        cur = tomllib.loads(text)
    except ValueError:
        log(f"  gw: {f} 이 TOML 로 읽히지 않아 건드리지 않음 — 고친 뒤 jaix setup")
        return False
    if (cur.get("gw") or {}).get("base_url") == url:
        return True
    line = f"base_url = {json.dumps(url, ensure_ascii=False)}"
    head = re.search(r"""^[ \t]*\[[ \t]*(?:gw|"gw"|'gw')[ \t]*\][^\n]*$""", text, re.M)
    if head:
        nxt = re.search(r"^[ \t]*\[", text[head.end():], re.M)  # [gw] 표의 끝 = 다음 표 머리
        body_end = head.end() + (nxt.start() if nxt else len(text) - head.end())
        body = text[head.end():body_end]
        if re.search(r"^[ \t]*base_url[ \t]*=", body, re.M):
            body = re.sub(r"^[ \t]*base_url[ \t]*=.*$", line, body, count=1, flags=re.M)
        else:
            body = "\n" + line + body
        new = text[:head.end()] + body + text[body_end:]
    elif "gw" in cur:  # 인라인 표 등 알아보기 어려운 꼴
        log(f"  gw: {f} 의 [gw] 꼴을 알아보지 못해 건드리지 않음")
        return False
    else:
        new = text.rstrip("\n") + ("\n\n" if text.strip() else "") + f"[gw]\n{line}\n"
    try:
        if (tomllib.loads(new).get("gw") or {}).get("base_url") != url:
            raise ValueError("쓴 값이 읽히지 않음")
    except ValueError as e:
        log(f"  gw: share.toml 을 고치지 못함({e}) — 건드리지 않음")
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".jaix-tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, f)
    log(f"  gw: 그룹웨어 주소를 {f} 에 기록")
    return True


def _install(info, uv):
    dest = paths.jaix_home() / "gw" / Path(info["wheel"]).name  # uv가 wheel 파일 이름에서 버전을 읽으므로 이름 그대로
    net.download(info["url"], dest)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != info["sha256"].lower():
        dest.unlink(missing_ok=True)
        raise ValueError(f"sha256 불일치 (받은 것 {digest[:12]}… ≠ latest.json {info['sha256'][:12]}…) — 설치하지 않음")
    ok, out = _run([uv, "tool", "install", str(dest)], timeout=900)
    if not ok:
        raise RuntimeError((out.splitlines() or [""])[-1][:200])
    _save_config(gw_package=info["name"])
    for old in dest.parent.glob("*.whl"):  # 지금 깐 것 하나만 남긴다
        if old != dest:
            old.unlink(missing_ok=True)
    if IS_WIN:
        b = tool_bin(uv)
        if b:
            winenv.add_to_path([b])  # uv tool의 실행파일 폴더가 사용자 PATH에 없을 수 있다
