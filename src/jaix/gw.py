"""그룹웨어(gw) 런타임: 자리만 둔다.

gw는 라이선스상 원외 재배포가 안 돼 공개 플러그인·이 저장소에 넣지 않는다. jaix setup이 **원내 위치**에서 받아
설치한다(2026-10-27 결정, jeju-inst/ji-gw-ai#108 Q2 ②). 위치는 아직 정해지지 않았으므로 원본 URL을 설정값으로만 받는다:
  jaix setup --gw-source <URL>   (jaix_home/config.json에 저장, 환경변수 JAIX_GW_SOURCE가 우선)
URL에 닿지 않으면(원내망이 아님) gw만 건너뛰고 doctor가 안내한다. URL은 gw 실행파일(.exe) 또는 그것을 담은 .zip으로 본다
— 형식이 정해지면 여기만 고친다.
"""
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from jaix import net, paths
from jaix.paths import IS_WIN

ENV = "JAIX_GW_SOURCE"


def _config_file():
    return paths.jaix_home() / "config.json"


def _config():
    try:
        return json.loads(_config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def source():
    return os.environ.get(ENV) or _config().get("gw_source") or None


def save_source(url):
    data = _config()
    data["gw_source"] = url
    _config_file().parent.mkdir(parents=True, exist_ok=True)
    _config_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def reachable(url, timeout=5):
    """원내 위치에 닿는가. 원외·VPN 끊김이면 False."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": net.UA})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def exe_path():
    return paths.bin_dir() / ("gw.exe" if IS_WIN else "gw")


def installed():
    """jaix가 원내 위치에서 깐 것만 본다(AI센터 PC의 개발용 gw와 헷갈리지 않게)."""
    return exe_path().is_file()


def setup(log, dry_run=False):
    url = source()
    if not url:
        log("  gw: 원본 위치가 아직 정해지지 않음 → 건너뜀")
        return {"status": "unset"}
    if not reachable(url):
        log(f"  gw: 원내 위치({urlparse(url).netloc})에 닿지 않음 → 건너뜀. 원내망에서 `jaix setup` 다시 실행")
        return {"status": "offsite"}
    if dry_run:
        log(f"  gw: {url} 에서 설치 예정")
        return {"status": "planned"}
    try:
        _install(url)
    except Exception as e:  # gw가 막혀도 나머지 설치는 계속한다. doctor가 남은 것을 알려 준다
        log(f"  gw: 설치 실패 — {e}")
        return {"status": "failed"}
    log(f"  gw: 설치함 ({url})")
    return {"status": "installed"}


def _install(url):
    name = Path(urlparse(url).path).name or "gw.exe"
    with tempfile.TemporaryDirectory() as tmp:
        file = net.download(url, Path(tmp) / name)
        paths.bin_dir().mkdir(parents=True, exist_ok=True)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(file) as z:  # 실행파일·DLL만 bin으로(런타임 포터블과 같은 방식)
                for info in z.infolist():
                    base = Path(info.filename).name
                    if not info.is_dir() and base.lower().endswith((".exe", ".dll")):
                        with z.open(info) as src, open(paths.bin_dir() / base, "wb") as out:
                            shutil.copyfileobj(src, out)
        else:
            shutil.copyfile(file, exe_path())
            if not IS_WIN:
                exe_path().chmod(0o755)
