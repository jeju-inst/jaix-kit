"""Hermes 채널(개인 슬랙 봇): 이번 버전은 자리만 둔다.

설치(`--channels hermes`)는 다음 버전이다 — 개인 슬랙 앱을 관리자가 미리 만들고 토큰을 넘기는 절차가 먼저 필요하다.
여기에는 잠금의 플러그인 스킬을 Hermes 스킬 폴더에 **복사**하는 부분만 있다(Windows는 심링크 대신 복사).
`jaix update`는 이전에 jaix가 복사해 둔 스킬(.jaix.json 표시가 있는 폴더)만 잠금 커밋에 맞춘다.
"""
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

from jaix import net, paths

NOT_YET = "Hermes(슬랙으로도 쓰기)는 다음 버전에서 켭니다. 지금은 Claude·Codex 채널만 설치합니다."
MARKER = ".jaix.json"


def skills_dir():
    return paths.hermes_home() / "skills" / "jaix"


def copy_skill(src, dst, meta):
    """src 스킬 폴더를 dst로 통째로 바꿔 넣는다(옛 파일이 남지 않게). meta는 표시 파일에 적는다."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".jaix-new")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp, symlinks=False)
    (tmp / MARKER).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if dst.exists():
        shutil.rmtree(dst)
    tmp.rename(dst)


def _codeload(url, sha):
    repo = url.removeprefix("https://github.com/").removesuffix(".git")
    return f"https://codeload.github.com/{repo}/tar.gz/{sha}"


def plugin_skills(plugin, workdir):
    """잠금 커밋의 소스를 받아 플러그인 skills/<이름>/SKILL.md 폴더들을 돌려준다."""
    archive = net.download(_codeload(plugin.url, plugin.sha), Path(workdir) / f"{plugin.name}.tar.gz")
    out = Path(workdir) / plugin.name
    with tarfile.open(archive) as t:
        t.extractall(out, filter="data")
    top = next(out.iterdir())  # codeload는 <repo>-<sha>/ 하나로 묶는다
    skills = top / plugin.subdir / "skills" if plugin.subdir else top / "skills"
    return [d for d in sorted(skills.iterdir()) if (d / "SKILL.md").is_file()] if skills.is_dir() else []


def installed():
    """jaix가 복사해 둔 스킬: {스킬 폴더 이름: 표시 내용}."""
    root = skills_dir()
    if not root.is_dir():
        return {}
    out = {}
    for d in root.iterdir():
        try:
            out[d.name] = json.loads((d / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return out


def sync(lock, log, dry_run=False):
    """이미 복사해 둔 스킬만 잠금 커밋으로 맞춘다. 새로 까는 일은 하지 않는다(다음 버전)."""
    have = installed()
    if not have:
        return []
    by_name = {p.name: p for p in lock.plugins}
    stale = {meta.get("plugin") for meta in have.values()
             if meta.get("plugin") in by_name and meta.get("sha") != by_name[meta["plugin"]].sha}
    changed = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in sorted(stale):
            p = by_name[name]
            log(f"  Hermes 스킬 {name} → {p.label}")
            if dry_run:
                continue
            for skill in plugin_skills(p, tmp):
                copy_skill(skill, skills_dir() / skill.name, {"plugin": p.name, "ref": p.ref, "sha": p.sha})
                changed.append(skill.name)
    return changed
