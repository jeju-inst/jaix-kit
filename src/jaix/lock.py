"""잠금 목록(.claude-plugin/marketplace.json) 읽기. jaix는 읽기만 하고 고치지 않는다(고치는 건 갱신 봇).

찾는 순서: --lock 파일 → JAIX_LOCK → GitHub의 채널 브랜치(main=stable, beta) → 실행파일에 묶은 사본
→ 소스 체크아웃의 파일. 관리자 콘솔·autoUpdate가 따라가는 것은 GitHub 쪽이므로 온라인 사본을 먼저 본다.
"""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from jaix import net

MARKETPLACE = "jaix"
REPO = "jeju-inst/jaix-kit"
GIT_URL = f"https://github.com/{REPO}.git"
RAW_URL = "https://raw.githubusercontent.com/" + REPO + "/{branch}/.claude-plugin/marketplace.json"
CHANNEL_BRANCH = {"stable": "main", "beta": "beta"}


@dataclass
class Plugin:
    name: str
    version: str | None  # 날짜 태그 고정이면 "2026.10.26.4", 브랜치 고정이면 None(sha로 판단)
    sha: str
    ref: str
    url: str
    subdir: str = ""  # git-subdir 소스의 path (플러그인이 저장소 하위 폴더에 있을 때)

    @property
    def id(self):
        return f"{self.name}@{MARKETPLACE}"

    @property
    def label(self):
        return self.version or f"{self.ref}@{self.sha[:7]}"


@dataclass
class Lock:
    data: dict
    source: str

    @property
    def plugins(self):
        out = []
        for p in self.data["plugins"]:
            src = p["source"]
            out.append(Plugin(p["name"], p.get("version"), src.get("sha", ""), src.get("ref", ""),
                              src.get("url") or src.get("repo", ""), src.get("path", "")))
        return out


def _bundled_candidates():
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller 단일 exe가 풀린 곳
    if base:
        yield Path(base) / "marketplace.json"
    yield Path(__file__).resolve().parents[2] / ".claude-plugin" / "marketplace.json"


def load(path=None, channel="stable", offline=False):
    path = path or os.environ.get("JAIX_LOCK")
    if path:
        return Lock(json.loads(Path(path).read_text(encoding="utf-8")), str(path))
    errors = []
    if not offline:
        url = RAW_URL.format(branch=CHANNEL_BRANCH[channel])
        try:
            return Lock(net.get_json(url, timeout=10), url)
        except Exception as e:  # 네트워크가 막혀도 묶은 사본으로 점검은 계속한다
            errors.append(f"{url}: {e}")
    for cand in _bundled_candidates():
        if cand.is_file():
            return Lock(json.loads(cand.read_text(encoding="utf-8")), f"{cand} (오프라인 사본)")
    raise FileNotFoundError("잠금 목록을 찾지 못함: " + "; ".join(errors))
