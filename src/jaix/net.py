"""내려받기. urllib는 Windows 시스템 프록시(레지스트리)와 HTTPS_PROXY를 그대로 따른다."""
import json
import os
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

from jaix import __version__

UA = f"jaix/{__version__}"


def _request(url):
    headers = {"User-Agent": UA}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"  # CI에서 익명 한도(시간당 60회)를 피한다
    return urllib.request.Request(url, headers=headers)


def get_json(url, timeout=20):
    with urllib.request.urlopen(_request(url), timeout=timeout) as r:
        return json.load(r)


def download(url, dest, timeout=120):
    """url을 dest로 받는다. 받다 끊기면 반쯤 받은 파일을 남기지 않는다."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(_request(url), timeout=timeout) as r:
            shutil.copyfileobj(r, out)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dest


def latest_release_asset(repo, pattern):
    """GitHub repo의 최신 릴리스에서 이름이 pattern(정규식)에 맞는 첫 첨부의 (이름, URL)."""
    rel = get_json(f"https://api.github.com/repos/{repo}/releases/latest")
    for asset in rel.get("assets", []):
        if re.search(pattern, asset["name"]):
            return asset["name"], asset["browser_download_url"]
    raise LookupError(f"{repo} 최신 릴리스({rel.get('tag_name')})에 '{pattern}' 파일이 없음")
