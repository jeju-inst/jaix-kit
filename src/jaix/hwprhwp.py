"""hwp-agent 폴백 렌더 엔진 rhwp를 미리 받는다.

hwp-agent의 렌더(pdf·verify)는 이 PC의 한글(hwp2pdf-cli) → 변환 서버 → rhwp 순으로 쓴다. 한글이 열려 있으면
hwp2pdf-cli가 건너뛰므로, 서버가 없는 연구원 PC에서는 rhwp가 없으면 미리보기가 결과 없이 끝난다. 그래서 jaix setup이
hwp-agent의 사용자 데이터 폴더(`hwp-agent setup`이 받는 자리)에 미리 받아 둔다.

버전·sha256은 잠금이 고정한 hwp-agent 커밋의 fetch_rhwp.py에서 읽는다(원본 한 벌). 그 파일이 없는 hwp-agent(옛 커밋)는
받은 rhwp를 찾지도 않으므로 건너뛴다. rhwp 자체(github.com/edwardkim/rhwp)는 MIT — 릴리스의 LICENSE를 바이너리 옆에 함께 둔다.
"""
import hashlib
import io
import platform
import re
import tarfile
import urllib.error
import zipfile

from jaix import hwpjar, net, uvpython
from jaix.paths import IS_WIN

SPEC_FILE = "src/hwp_agent/render/fetch_rhwp.py"


def slug():
    """hwp-agent fetch_rhwp.platform_slug()와 같은 규칙."""
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if IS_WIN:
        return "windows-x86_64"  # ARM Windows도 x64 빌드를 에뮬레이션으로 돌린다
    if platform.system() == "Darwin":
        return "macos-aarch64" if arm else "macos-x86_64"
    return "linux-aarch64" if arm else "linux-x86_64"


def dest_dir():
    """hwp-agent fetch_rhwp.rhwp_dir()와 같은 자리 — 거기 있으면 hwp-agent가 그대로 쓴다."""
    return hwpjar.dest().parent / "rhwp"


def exe():
    return dest_dir() / ("rhwp.exe" if IS_WIN else "rhwp")


def installed_version():
    marker = dest_dir() / "VERSION"
    if not (marker.is_file() and exe().is_file()):
        return None
    return marker.read_text(encoding="utf-8").strip() or None


def parse_spec(text, want_slug=None):
    """fetch_rhwp.py 소스에서 {version, url, asset, sha256}. 형식을 못 알아보면 None."""
    ver = re.search(r'^RHWP_VERSION\s*=\s*"([^"]+)"', text, re.M)
    repo = re.search(r'^RHWP_REPO\s*=\s*"([^"]+)"', text, re.M)
    s = want_slug or slug()
    entry = re.search(r'"' + re.escape(s) + r'":\s*\(\s*f?"([^"]+)",\s*"([0-9a-f]{64})"', text)
    if not (ver and repo and entry):
        return None
    asset = entry.group(1).replace("{RHWP_VERSION}", ver.group(1))
    return {"version": ver.group(1), "asset": asset, "sha256": entry.group(2),
            "url": f"https://github.com/{repo.group(1)}/releases/download/{ver.group(1)}/{asset}"}


def spec(lock, offline=False):
    """잠금의 hwp-agent가 고정한 rhwp. 그 커밋에 fetch_rhwp.py가 없거나 못 읽으면 None."""
    p = hwpjar.plugin(lock)
    url = p and uvpython._raw_url(p, SPEC_FILE)
    if not url or offline:
        return None
    try:
        with net.urllib.request.urlopen(net._request(url), timeout=20) as r:
            return parse_spec(r.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _extract(archive, asset, name):
    """압축에서 rhwp/<name>과 rhwp/LICENSE만 이름으로 꺼낸다(다른 파일은 풀지 않는다)."""
    want = {f"rhwp/{name}": name, "rhwp/LICENSE": "LICENSE"}
    out = {}
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for member, to in want.items():
                if member in zf.namelist():
                    out[to] = zf.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            for member, to in want.items():
                try:
                    fh = tf.extractfile(member)
                except KeyError:
                    continue
                if fh is not None:
                    out[to] = fh.read()
    if name not in out:
        raise ValueError(f"{asset} 안에 rhwp/{name} 없음")
    return out


def ensure(lock, log, dry_run=False, offline=False):
    """잠금에 hwp-agent가 있고 그 커밋이 rhwp를 고정할 때만. 고정 버전이 이미 있으면 그대로 둔다.
    실패해도 다른 설치는 계속한다 — rhwp는 한글이 열려 있을 때의 미리보기용 폴백이다."""
    if not hwpjar.plugin(lock):
        return True
    want = spec(lock, offline)
    if want is None:
        log("  HWP 미리보기 엔진(rhwp): 건너뜀 (잠금의 hwp-agent에 rhwp 고정 없음 또는 오프라인)")
        return True
    if installed_version() == want["version"]:
        log(f"  HWP 미리보기 엔진(rhwp): 있음 ({want['version']}, {exe()})")
        return True
    if dry_run:
        log(f"  HWP 미리보기 엔진(rhwp): 받을 예정 ({want['url']})")
        return True
    d = dest_dir()
    try:
        part = net.download(want["url"], d / (want["asset"] + ".part"))
        try:
            data = part.read_bytes()
        finally:
            part.unlink(missing_ok=True)
        got = hashlib.sha256(data).hexdigest()
        if got != want["sha256"]:
            raise ValueError(f"sha256 불일치 ({got[:12]}… ≠ {want['sha256'][:12]}…)")
        for name, body in _extract(data, want["asset"], exe().name).items():
            tmp = d / (name + ".part")
            tmp.write_bytes(body)
            tmp.replace(d / name)
        if not IS_WIN:
            exe().chmod(0o755)
        (d / "VERSION").write_text(want["version"] + "\n", encoding="utf-8")
    except Exception as e:  # 막혀도 나머지 설치는 계속한다. doctor가 남은 것을 알려 준다
        log(f"  HWP 미리보기 엔진(rhwp): 받기 실패 — {e}")
        return False
    log(f"  HWP 미리보기 엔진(rhwp): 받음 ({want['version']}, {exe()})")
    return True

