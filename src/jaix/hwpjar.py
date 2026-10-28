"""hwp-agent 변환기 jar(hwp2hwpx.jar)를 미리 받는다 (jaix-kit#19 ⑤).

hwp-agent는 hwp → hwpx 변환에 이 jar를 쓰고, 없으면 `hwp-agent setup`으로 받으라고 한다. 처음 변환할 때
에이전트가 그 안내를 보고 다른 길로 우회하지 않게 jaix setup이 같은 자리(hwp-agent의 사용자 데이터 폴더)에
미리 받아 둔다. 받을 주소·sha256은 잠금이 고정한 hwp-agent 커밋의 fetch_jar.py에서 읽는다(원본 한 벌) —
못 읽으면 아래 기본값을 쓴다.
"""
import hashlib
import os
import re
import urllib.error
from pathlib import Path

from jaix import net, uvpython
from jaix.paths import IS_WIN

PLUGIN = "hwp-agent"
SPEC_FILE = "src/hwp_agent/convert/fetch_jar.py"
ASSET = "hwp2hwpx.jar"
# hwp-agent v2026.10.26.4의 값. 잠금의 fetch_jar.py를 못 읽을 때만 쓴다
FALLBACK = {"url": "https://github.com/z0nam/hwp-agent/releases/download/converter-jar/hwp2hwpx.jar",
            "sha256": "578a7f8397342dca1d52845330462d5038a4706967a9c43c0e04faf5f6f3d0ce"}


def dest():
    """hwp-agent fetch_jar.data_dir()와 같은 자리 — 거기 있으면 hwp-agent가 그대로 쓴다."""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "hwp-agent" / ASSET


def parse_spec(text):
    """fetch_jar.py 소스에서 {url, sha256}. 형식을 못 알아보면 None."""
    tag = re.search(r'^_RELEASE_TAG\s*=\s*"([^"]+)"', text, re.M)
    asset = re.search(r'^_ASSET\s*=\s*"([^"]+)"', text, re.M)
    url = re.search(r'f"(https://[^"]+)"', text)
    sha = re.search(r'^JAR_SHA256\s*=\s*"([0-9a-f]{64})"', text, re.M)
    if not (tag and asset and url and sha):
        return None
    return {"url": url.group(1).replace("{_RELEASE_TAG}", tag.group(1)).replace("{_ASSET}", asset.group(1)),
            "sha256": sha.group(1)}


def plugin(lock):
    return next((p for p in lock.plugins if p.name == PLUGIN), None)


def spec(lock, offline=False):
    p = plugin(lock)
    url = p and uvpython._raw_url(p, SPEC_FILE)
    if url and not offline:
        try:
            with net.urllib.request.urlopen(net._request(url), timeout=20) as r:
                got = parse_spec(r.read().decode("utf-8", errors="replace"))
            if got:
                return got
        except (urllib.error.URLError, OSError, ValueError):
            pass
    return dict(FALLBACK)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure(lock, log, dry_run=False, offline=False):
    """잠금에 hwp-agent가 있을 때만. 있으면 sha256이 맞는지 보고, 다르면(새 jar) 다시 받는다."""
    if not plugin(lock):
        return True
    want, jar = spec(lock, offline), dest()
    if jar.is_file() and _sha256(jar) == want["sha256"]:
        log(f"  HWP 변환기(jar): 있음 ({jar})")
        return True
    if dry_run:
        log(f"  HWP 변환기(jar): 받을 예정 ({want['url']})")
        return True
    try:
        part = net.download(want["url"], jar.with_name(jar.name + ".part"))
        got = _sha256(part)
        if got != want["sha256"]:
            part.unlink(missing_ok=True)
            raise ValueError(f"sha256 불일치 ({got[:12]}… ≠ {want['sha256'][:12]}…)")
        part.replace(jar)
    except Exception as e:  # 막혀도 나머지 설치는 계속한다. doctor가 남은 것을 알려 준다
        log(f"  HWP 변환기(jar): 받기 실패 — {e}")
        return False
    log(f"  HWP 변환기(jar): 받음 ({jar})")
    return True
