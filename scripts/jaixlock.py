#!/usr/bin/env python3
"""jaix-kit 잠금 목록(marketplace.json) 점검·갱신.

  jaixlock.py check          모든 외부 소스가 40자 sha로 고정돼 있고, ref가 태그면 그 태그가 sha를 가리키는지 확인
  jaixlock.py bump NAME REF  NAME 플러그인의 ref를 REF(태그·브랜치)로 바꾸고 sha를 원격에서 다시 받아 고정
  jaixlock.py update         모든 플러그인을 최신으로: 태그 고정이면 가장 새 날짜 태그(vYYYY.MM.DD.N),
                             브랜치 고정이면 그 브랜치 head. 바뀐 것을 한 줄씩 출력(갱신 봇 PR 본문용)

버전은 날짜 버전 하나뿐이다. 태그 고정 entry 는 version 에 태그(v 뺀 것)를 적고, 도구 plugin.json 에는
version 을 두지 않는다 — Claude 는 plugin.json version 을 먼저 보므로 거기 남아 있으면 업데이트를 못 알아챈다.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

MARKET = Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CALVER_RE = re.compile(r"^v(\d{4})\.(\d{2})\.(\d{2})\.(\d+)$")


# 한국어 Windows 콘솔(cp949)·CI(cp1252)에서도 한글·기호가 죽지 않게
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")


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


def latest_calver(url):
    out = subprocess.run(["git", "ls-remote", "--tags", "--refs", url], capture_output=True, text=True, check=True).stdout
    tags = [line.split("\t")[1].removeprefix("refs/tags/") for line in out.splitlines() if line]
    tags = [t for t in tags if CALVER_RE.match(t)]
    return max(tags, key=lambda t: tuple(map(int, CALVER_RE.match(t).groups())), default=None)


def set_pin(entry, ref, sha, kind):
    src = entry["source"]
    src["ref"], src["sha"] = ref, sha
    entry.setdefault("metadata", {}).setdefault("jaix", {})["refKind"] = kind
    if kind == "tag" and CALVER_RE.match(ref):
        entry["version"] = ref[1:]
    else:
        entry.pop("version", None)  # 버전이 없으면 Claude 는 커밋 sha 로 업데이트를 판단한다


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
        # github 소스·owner/repo 축약형·git@ 은 SSH로 클론돼 SSH 키 없는 연구원 PC에서 설치가 실패한다
        if src["source"] not in ("git-subdir", "url") or not src.get("url", "").startswith("https://"):
            print(f"✗ {name}: {src['source']} 소스 대신 url/git-subdir + https:// URL로 적어야 함"); bad += 1; continue
        if not SHA_RE.match(sha):
            print(f"✗ {name}: sha 고정 없음"); bad += 1; continue
        if ref:
            try:
                remote_sha, kind = resolve(git_url(src), ref, ref_kind(p))
            except LookupError as e:
                print(f"✗ {name}: {e}"); bad += 1; continue
            if kind == "tag" and remote_sha != sha:
                print(f"✗ {name}: 태그 {ref}={remote_sha[:12]} 인데 잠금은 {sha[:12]}"); bad += 1; continue
            if kind == "tag" and CALVER_RE.match(ref) and p.get("version") != ref[1:]:
                print(f"✗ {name}: version 은 태그와 같은 {ref[1:]} 이어야 함 (지금 {p.get('version')})"); bad += 1; continue
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
            set_pin(p, ref, sha, kind)
            save(d)
            print(f"{name}: {ref} ({kind}) @ {sha[:12]}")
            return
    sys.exit(f"플러그인 '{name}' 없음")


def update():
    d = load()
    changed = []
    for p in d["plugins"]:
        src = p["source"]
        if isinstance(src, str):
            continue
        url, ref = git_url(src), src.get("ref")
        # 날짜 태그가 있는 도구는 가장 새 태그로(브랜치·semver 고정에서도 옮겨 간다),
        # 아직 날짜 태그가 없는 도구는 고정한 브랜치의 head 를 따라간다
        new_ref = latest_calver(url)
        if new_ref:
            if CALVER_RE.match(ref or "") and CALVER_RE.match(new_ref).groups() <= CALVER_RE.match(ref).groups():
                continue
            sha, new_kind = resolve(url, new_ref, "tag")
        elif ref_kind(p) == "branch":
            new_ref = ref
            sha, new_kind = resolve(url, ref, "branch")
        else:
            continue
        if sha == src.get("sha") and new_ref == ref:
            continue
        changed.append(f"{p['name']}: {ref} @ {src.get('sha', '')[:7]} → {new_ref} @ {sha[:7]}")
        set_pin(p, new_ref, sha, new_kind)
    if changed:
        save(d)
    print("\n".join(changed))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["check"]:
        check()
    elif args[:1] == ["bump"] and len(args) == 3:
        bump(args[1], args[2])
    elif args[:1] == ["update"]:
        update()
    else:
        sys.exit(__doc__)
