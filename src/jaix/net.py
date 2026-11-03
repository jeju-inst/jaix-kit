"""내려받기. urllib는 Windows 시스템 프록시(레지스트리)와 HTTPS_PROXY를 그대로 따른다."""
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
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


RATE_LIMIT_HINT = ("GitHub 내려받기 한도에 걸렸습니다(같은 인터넷 주소에서 한 시간에 60번). "
                   "10-20분 뒤 jaix setup 을 다시 실행하세요")


class RateLimited(RuntimeError):
    """GitHub API 익명 한도. 메시지는 연구원이 읽는 안내다."""


rate_limit_hit = False  # 이번 실행에서 한도에 걸린 적이 있는지(마지막 안내문에 한 줄 더 쓰려고)


def _rate_limited(err):
    return isinstance(err, urllib.error.HTTPError) and err.code in (403, 429) and (
        err.code == 429 or err.headers.get("X-RateLimit-Remaining") == "0"
        or "rate limit" in str(err.reason).lower())


def _api_release(repo):
    return get_json(f"https://api.github.com/repos/{repo}/releases/latest")


def _web_release(repo, timeout=20):
    """API 를 쓰지 않는 길: github.com 의 releases/latest 가 넘겨 주는 태그와 그 태그의 첨부 목록 HTML.
    API 한도(공인 IP 하나당 시간당 60회)와 따로 센다 — 원내 여러 PC 가 한 IP 로 동시에 설치할 때를 위해."""
    with urllib.request.urlopen(_request(f"https://github.com/{repo}/releases/latest"), timeout=timeout) as r:
        tag = urllib.parse.unquote(r.geturl().rstrip("/").rsplit("/", 1)[-1])
    with urllib.request.urlopen(_request(f"https://github.com/{repo}/releases/expanded_assets/{tag}"),
                                timeout=timeout) as r:
        html = r.read().decode("utf-8", "replace")
    names = re.findall(rf'href="/{re.escape(repo)}/releases/download/{re.escape(tag)}/([^"?#]+)"', html)
    base = f"https://github.com/{repo}/releases/download/{tag}/"
    return {"tag_name": tag, "assets": [{"name": urllib.parse.unquote(n), "browser_download_url": base + n}
                                        for n in dict.fromkeys(names)]}


def latest_release_asset(repo, pattern):
    """GitHub repo의 최신 릴리스에서 이름이 pattern(정규식)에 맞는 첫 첨부의 (이름, URL).
    API 가 한도에 걸리면 github.com 웹 경로로 다시 찾고, 그것도 막히면 잠시 쉬었다가 한 번 더 한다."""
    rel = None
    try:
        rel = _api_release(repo)
    except urllib.error.HTTPError as e:
        if not _rate_limited(e):
            raise
    for attempt in range(2):
        if rel is not None:
            break
        try:
            rel = _web_release(repo)
        except urllib.error.HTTPError as e:
            if not (e.code in (403, 429) and attempt == 0):
                global rate_limit_hit
                rate_limit_hit = True
                raise RateLimited(RATE_LIMIT_HINT) from None
            time.sleep(WEB_RETRY_SECONDS)
    for asset in rel.get("assets", []):
        if re.search(pattern, asset["name"]):
            return asset["name"], asset["browser_download_url"]
    raise LookupError(f"{repo} 최신 릴리스({rel.get('tag_name')})에 '{pattern}' 파일이 없음")


WEB_RETRY_SECONDS = 30
