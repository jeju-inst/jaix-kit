#!/usr/bin/env python3
"""jaix-kit 잠금 목록(marketplace.json) 점검·갱신.

  jaixlock.py check          모든 외부 소스가 40자 sha로 고정돼 있고, ref가 태그면 그 태그가 sha를 가리키는지 확인
  jaixlock.py bump NAME REF  NAME 플러그인의 ref를 REF(태그·브랜치)로 바꾸고 sha를 원격에서 다시 받아 고정
"""
import json
import re
import subprocess
import sys
from pathlib import Path

MARKET = Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def git_url(src):
    url = src.get("url") or src.get("repo")
    if src["source"] == "github" or re.fullmatch(r"[\w.-]+/[\w.-]+", url or ""):
        return f"https://github.com/{url}.git"
    return url


def resolve(url, ref, kind=None):
    """ref(태그면 peel한 커밋, 브랜치면 head)의 sha와 종류를 돌려준다.

    kind를 주면 그 이름공간만 본다 — 태그가 지워지고 같은 이름 브랜치만 남은 경우를
    브랜치로 잘못 받아들이지 않기 위해서다.
    """
    out = subprocess.run(["git", "ls-remote", url, f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}"],
                         capture_output=True, text=True, check=True).stdout
    refs = dict(reversed(line.split("\t")) for line in out.splitlines() if line)
    if kind != "branch" and f"refs/tags/{ref}^{{}}" in refs:
        return refs[f"refs/tags/{ref}^{{}}"], "tag"
    if kind != "branch" and f"refs/tags/{ref}" in refs:
        return refs[f"refs/tags/{ref}"], "tag"
    if kind != "tag" and f"refs/heads/{ref}" in refs:
        return refs[f"refs/heads/{ref}"], "branch"
    raise LookupError(f"{url}: {kind or 'ref'} '{ref}' 없음")


def ref_kind(entry):
    return entry.get("metadata", {}).get("jaix", {}).get("refKind")


def load():
    return json.loads(MARKET.read_text(encoding="utf-8"))


def save(d):
    MARKET.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check():
    bad = 0
    for p in load()["plugins"]:
        src = p["source"]
        if isinstance(src, str):
            continue
        name, sha, ref = p["name"], src.get("sha", ""), src.get("ref")
        if not SHA_RE.match(sha):
            print(f"✗ {name}: sha 고정 없음"); bad += 1; continue
        if ref:
            try:
                remote_sha, kind = resolve(git_url(src), ref, ref_kind(p))
            except LookupError as e:
                print(f"✗ {name}: {e}"); bad += 1; continue
            if kind == "tag" and remote_sha != sha:
                print(f"✗ {name}: 태그 {ref}={remote_sha[:12]} 인데 잠금은 {sha[:12]}"); bad += 1; continue
            if kind == "branch":
                print(f"△ {name}: 브랜치 {ref} 위의 커밋 {sha[:12]}로 고정 (태그 권장)")
                continue
        print(f"✓ {name}: {ref or '-'} @ {sha[:12]}")
    sys.exit(1 if bad else 0)


def bump(name, ref):
    d = load()
    for p in d["plugins"]:
        if p["name"] == name:
            src = p["source"]
            try:
                sha, kind = resolve(git_url(src), ref)
            except LookupError as e:
                sys.exit(str(e))
            src["ref"], src["sha"] = ref, sha
            p.setdefault("metadata", {}).setdefault("jaix", {})["refKind"] = kind
            save(d)
            print(f"{name}: {ref} ({kind}) @ {sha[:12]}")
            return
    sys.exit(f"플러그인 '{name}' 없음")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["check"]:
        check()
    elif args[:1] == ["bump"] and len(args) == 3:
        bump(args[1], args[2])
    else:
        sys.exit(__doc__)
