#!/usr/bin/env python3
"""jaix-kit 잠금 목록(marketplace.json) 점검·갱신.

  jaixlock.py check          모든 외부 소스가 40자 sha로 고정돼 있고, ref가 태그면 그 태그가 sha를 가리키는지 확인
  jaixlock.py bump NAME REF  NAME 플러그인의 ref를 REF(태그·브랜치)로 바꾸고 sha를 원격에서 다시 받아 고정
  jaixlock.py add NAME URL REF 표시이름 설명   새 플러그인을 url 소스(https)로 REF에 고정해 추가.
                             그 커밋에 .claude-plugin/plugin.json 이 없으면 거절
  jaixlock.py update         모든 플러그인을 최신으로: 태그 고정이면 가장 새 날짜 태그(vYYYY.MM.DD.N),
                             브랜치 고정이면 그 브랜치 head. 바뀐 것을 한 줄씩 출력(갱신 봇 PR 본문용)

플러그인이 아닌 커밋은 잠그지 않는다: 태그 커밋에 <path>/.claude-plugin/plugin.json 이 없으면(예: jaix-gw 처럼
자동 생성되는 저장소의 워크플로만 담긴 첫 seed 커밋에 날짜 태그가 붙은 경우) update 는 그 태그를 건너뛰고
직전의 유효한 태그를 쓴다. check 는 잠긴 커밋에 plugin.json 이 없으면 경고한다.

버전은 날짜 버전 하나뿐이다. 태그 고정 entry 는 version 에 태그(v 뺀 것)를 적고, 도구 plugin.json 에는
version 을 두지 않는다 — Claude 는 plugin.json version 을 먼저 보므로 거기 남아 있으면 업데이트를 못 알아챈다.
"""
import json
import re
import subprocess
import sys
import tempfile
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


def calver_key(tag):
    return tuple(map(int, CALVER_RE.match(tag).groups()))  # 문자열 비교면 .10 < .9


def calver_tags(url):
    """날짜 태그를 새것부터."""
    out = subprocess.run(["git", "ls-remote", "--tags", "--refs", url], capture_output=True, text=True, check=True).stdout
    tags = [line.split("\t")[1].removeprefix("refs/tags/") for line in out.splitlines() if line]
    return sorted((t for t in tags if CALVER_RE.match(t)), key=calver_key, reverse=True)


def plugin_manifest(src):
    return "/".join(x for x in (src.get("path", "").strip("/"), ".claude-plugin/plugin.json") if x)


def has_plugin(url, sha, path):
    """그 커밋에 path(plugin.json)가 있는가. 트리만 얕게 받아(blob 없이) 본다 — GitHub 은 sha 로 fetch 를 허용한다."""
    with tempfile.TemporaryDirectory() as d:
        git = ["git", "-C", d]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "fetch", "-q", "--depth", "1", "--filter=blob:none", url, sha],
                       capture_output=True, check=True)
        out = subprocess.run([*git, "ls-tree", "FETCH_HEAD", "--", path], capture_output=True, text=True, check=True)
        return bool(out.stdout.strip())


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
            if not has_plugin(git_url(src), sha, plugin_manifest(src)):
                print(f"△ {name}: 잠긴 커밋 {sha[:12]}에 {plugin_manifest(src)} 없음 — 플러그인이 아닌 커밋(seed 등)일 수 있음")
                continue
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


def add(name, url, ref, display, description):
    d = load()
    if any(p["name"] == name for p in d["plugins"]):
        sys.exit(f"플러그인 '{name}' 이미 있음 — bump 를 쓸 것")
    if not url.startswith("https://"):
        sys.exit("https:// URL 이어야 함 (SSH 키 없는 연구원 PC에서도 받게)")
    try:
        sha, kind = resolve(url, ref)
    except LookupError as e:
        sys.exit(str(e))
    src = {"source": "url", "url": url}
    if not has_plugin(url, sha, plugin_manifest(src)):
        sys.exit(f"{ref} @ {sha[:12]} 에 .claude-plugin/plugin.json 없음 — 플러그인이 아닌 커밋(seed 등)")
    entry = {"name": name, "displayName": display, "description": description, "category": "productivity",
             "source": src, "homepage": url.removesuffix(".git")}
    set_pin(entry, ref, sha, kind)
    d["plugins"].append(entry)
    save(d)
    print(f"{name}: 추가 {ref} ({kind}) @ {sha[:12]}")


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
        new_ref = sha = None
        for tag in calver_tags(url):
            if CALVER_RE.match(ref or "") and calver_key(tag) <= calver_key(ref):
                break  # 지금 것보다 새 유효 태그가 없음 → 그대로 둔다
            tag_sha, _ = resolve(url, tag, "tag")
            if has_plugin(url, tag_sha, plugin_manifest(src)):
                new_ref, sha, new_kind = tag, tag_sha, "tag"
                break
            # stdout 은 PR 본문·커밋 메시지(changes.txt)라 로그로만 남긴다
            print(f"△ {p['name']}: {tag} @ {tag_sha[:7]} 에 {plugin_manifest(src)} 없음 → 건너뜀", file=sys.stderr)
        if not new_ref:
            if ref_kind(p) != "branch":
                continue
            new_ref = ref  # 유효한 날짜 태그가 아직 없으면 고정한 브랜치의 head 를 따라간다
            sha, new_kind = resolve(url, ref, "branch")
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
    elif args[:1] == ["add"] and len(args) == 6:
        add(*args[1:])
    elif args[:1] == ["update"]:
        update()
    else:
        sys.exit(__doc__)
