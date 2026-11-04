"""플러그인 `bin/` 의 셸 명령을 PATH 에 올린다(TS-RUNTIME-4). 예: mail-skill 의 `mailskill`·`mail-secret`.

왜: 스킬이 "PATH의 셸 명령"을 부르는데(TS-SKILL-1), 플러그인 `bin/` 을 PATH 에 넣어 주는 호스트는 Claude Code 뿐이다
(켜진 플러그인의 bin 을 Bash 도구 PATH 에 붙인다. 2.1.318 실측). Codex(0.160.0 실측)는 넣지 않고, Hermes 는 jaix 가
SKILL.md 폴더만 복사하므로 `bin/` 자체가 없다. 연구원은 clone·PATH 편집을 못 하므로 jaix 가 맡는다.

방법: 잠금 커밋의 플러그인 루트를 jaix_home/plugins/<이름> 에 통째로 받아 두고(bin 스크립트가 자기 위치에서
`../scripts` 를 찾는다), 거기 bin 의 명령을 PATH 의 폴더에 올린다.
- Windows: jaix 실행 폴더(paths.bin_dir, setup 이 사용자 PATH 에 넣음)에 `<이름>.cmd` 심. 확장자 없는 스크립트는
  Git Bash 용 sh 심도 둔다(`.cmd` 는 bash 가 이름만으로 찾지 못한다).
- 맥·리눅스: link_dir(기본 ~/.local/bin)에 심볼릭 링크. `.cmd`·`.ps1`·`.bat` 는 건너뛴다.
jaix 가 만들지 않은 같은 이름의 파일은 덮지 않는다. 기록(data_dir/plugin-bin.json)에 플러그인별 커밋과 만든 명령을
적어 두고, 잠금 커밋이 같으면 다시 받지 않는다. 잠금에서 빠진 플러그인의 명령은 지운다.
"""
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from jaix import net, paths
from jaix.paths import IS_WIN

WIN_SCRIPT = {".cmd", ".bat", ".exe"}  # Windows 가 PATHEXT 로 이름만으로 찾는 것
SKIP_POSIX = {".cmd", ".bat", ".ps1", ".exe"}
SHIM_MARK = "jaix plugin-bin shim"


def codeload(url, sha):
    repo = url.removeprefix("https://github.com/").removesuffix(".git")
    return f"https://codeload.github.com/{repo}/tar.gz/{sha}"


def fetch_root(plugin, workdir):
    """잠금 커밋의 소스를 받아 풀고 플러그인 루트(git-subdir 면 그 하위 폴더)를 돌려준다."""
    archive = net.download(codeload(plugin.url, plugin.sha), Path(workdir) / f"{plugin.name}.tar.gz")
    out = Path(workdir) / plugin.name
    with tarfile.open(archive) as t:
        t.extractall(out, filter="data")
    top = next(out.iterdir())  # codeload는 <repo>-<sha>/ 하나로 묶는다
    return top / plugin.subdir if plugin.subdir else top


def plugins_dir():
    return paths.jaix_home() / "plugins"


def link_dir():
    """명령을 올릴 PATH 의 폴더. Windows 는 jaix 실행 폴더, 그 밖은 ~/.local/bin(works 와 같은 곳)."""
    if IS_WIN:
        return paths.bin_dir()
    return Path(os.environ.get("JAIX_LINK_DIR") or Path.home() / ".local" / "bin")


def _record_file():
    return paths.data_dir() / "plugin-bin.json"


def recorded():
    """{플러그인 이름: {"sha": 커밋, "commands": [만든 파일 경로]}}. bin 이 없는 플러그인도 commands=[] 로 적힌다."""
    try:
        return json.loads(_record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(rec):
    _record_file().parent.mkdir(parents=True, exist_ok=True)
    _record_file().write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def _commands(bin_dir):
    """bin 폴더에서 이 OS 에서 이름으로 부를 파일들."""
    if not bin_dir.is_dir():
        return []
    files = sorted(f for f in bin_dir.iterdir() if f.is_file())
    if IS_WIN:
        return [f for f in files if f.suffix.lower() in WIN_SCRIPT or not f.suffix]
    return [f for f in files if f.suffix.lower() not in SKIP_POSIX]


def _shim_text(target):
    """Windows 심 내용. .cmd 는 call 로 넘겨 원본의 %~dp0 가 원래 bin 을 가리키게 한다."""
    if target.suffix:
        return f'@rem {SHIM_MARK}\r\n@call "{target}" %*\r\n@exit /b %ERRORLEVEL%\r\n'
    posix = str(target).replace("\\", "/")  # Git Bash 는 C:/... 형태를 받는다
    return f'#!/bin/sh\n# {SHIM_MARK}\nexec "{posix}" "$@"\n'


def _ours(path):
    """jaix 가 만든 명령인가(우리 플러그인 사본을 가리키는 링크, 또는 표시가 든 심)."""
    try:
        if path.is_symlink():
            return Path(os.readlink(path)).is_relative_to(plugins_dir())
        return path.is_file() and SHIM_MARK in path.read_text(encoding="utf-8", errors="replace")[:200]
    except OSError:
        return False


def _place(target, log):
    """target(사본 bin 안의 파일)을 link_dir 에 올린다. 만든 경로, 못 만들었으면 None."""
    dst = link_dir() / (target.stem + ".cmd" if IS_WIN and target.suffix else target.name)
    if (dst.exists() or dst.is_symlink()) and not _ours(dst):
        log(f"    {dst} 에 jaix 가 만들지 않은 파일이 있어 그대로 둠")
        return None
    try:
        link_dir().mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        if IS_WIN:
            dst.write_text(_shim_text(target), encoding="utf-8", newline="")
        else:
            dst.symlink_to(target)
    except OSError as e:
        log(f"    {dst} 를 만들지 못함 — {e}")
        return None
    return dst


def _remove(cmds):
    for c in cmds:
        p = Path(c)
        if _ours(p):
            p.unlink(missing_ok=True)


def _install_one(plugin, workdir, log):
    """사본을 바꿔 넣고 명령을 올린다. 만든 명령 경로 목록."""
    root = fetch_root(plugin, workdir)
    if not (root / "bin").is_dir():
        shutil.rmtree(plugins_dir() / plugin.name, ignore_errors=True)
        return []
    dst = plugins_dir() / plugin.name
    tmp = dst.with_name(dst.name + ".jaix-new")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(root, tmp, symlinks=False)
    if not IS_WIN:
        for f in (tmp / "bin").iterdir():  # tar 의 실행 비트가 빠졌어도 부를 수 있게
            if f.is_file() and f.suffix.lower() not in SKIP_POSIX:
                f.chmod(f.stat().st_mode | 0o755)
    shutil.rmtree(dst, ignore_errors=True)
    tmp.rename(dst)
    made = [_place(f, log) for f in _commands(dst / "bin")]
    return [str(m) for m in made if m]


def stale(lock):
    """다시 받아야 할 플러그인: 기록이 없거나 커밋이 다르거나, 만든 명령이 사라진 것."""
    rec = recorded()
    out = []
    for p in lock.plugins:
        r = rec.get(p.name)
        cmds = r.get("commands", []) if r else []
        if (not r or r.get("sha") != p.sha or (cmds and not (plugins_dir() / p.name).is_dir())
                or any(not (Path(c).exists() or Path(c).is_symlink()) for c in cmds)):
            out.append(p)
    return out


def ensure(lock, log, dry_run=False, offline=False):
    """잠금에 맞춘다. 돌려주는 값: {"status": ok|failed|offline, "commands": [이름], "failed": [플러그인]}."""
    rec = recorded()
    todo = stale(lock)
    gone = [n for n in rec if n not in {p.name for p in lock.plugins}]
    if dry_run:
        for p in todo:
            log(f"  플러그인 명령 {p.name}: 확인 예정")
        return {"status": "ok", "commands": [], "failed": []}
    for name in gone:
        _remove(rec.pop(name).get("commands", []))
        shutil.rmtree(plugins_dir() / name, ignore_errors=True)
        log(f"  플러그인 명령 {name}: 잠금에서 빠져 지움")
    failed = []
    if todo and offline:
        _save(rec)
        return {"status": "offline", "commands": [], "failed": []}
    with tempfile.TemporaryDirectory() as tmp:
        for p in todo:
            old = rec.get(p.name, {}).get("commands", [])
            try:
                made = _install_one(p, tmp, log)
            except Exception as e:  # 한 플러그인이 못 받아도 나머지는 한다
                log(f"  플러그인 명령 {p.name}: 받지 못함 — {e}")
                failed.append(p.name)
                continue
            _remove([c for c in old if c not in made])
            rec[p.name] = {"sha": p.sha, "commands": made}
            if made:
                log(f"  플러그인 명령 {p.name}: {', '.join(Path(m).name for m in made)} → {link_dir()}")
    _save(rec)
    names = sorted(Path(c).name for r in rec.values() for c in r.get("commands", []))
    return {"status": "failed" if failed else "ok", "commands": names, "failed": failed}
