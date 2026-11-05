"""도구가 쓰는 로컬 런타임: 찾기 · 버전 · 설치 · 갱신.

Windows 설치 순서: winget 사용자 범위(--scope user) → 안 되면 포터블 zip을 jaix_home 아래에 풀고 사용자 PATH에 추가.
둘 다 관리자 권한이 필요 없다. winget이 머신 범위 설치기만 있는 패키지(Git, Temurin MSI 등)는 --scope user가
거절되므로 자연히 포터블로 넘어간다. 맥·리눅스는 설치하지 않고 설치 명령만 알려 준다(개발·AI센터용).
"""
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from jaix import net, paths, winenv
from jaix.paths import IS_WIN

ADOPTIUM_API = "https://api.adoptium.net/v3/assets/latest/21/hotspot?os=windows&architecture=x64&image_type=jre"


def _github(repo, pattern):
    return lambda: net.latest_release_asset(repo, pattern)


def _nodejs():
    """nodejs.org 의 최신 LTS Windows x64 zip. (jaix-works 의 nworks 가 쓴다)"""
    rel = next(r for r in net.get_json("https://nodejs.org/dist/index.json") if r.get("lts") and "win-x64-zip" in r["files"])
    name = f"node-{rel['version']}-win-x64.zip"
    return name, f"https://nodejs.org/dist/{rel['version']}/{name}"


def _adoptium():
    rel = net.get_json(ADOPTIUM_API)[0]
    pkg = rel["binary"]["package"]
    return pkg["name"], pkg["link"]


@dataclass
class Runtime:
    key: str
    label: str
    exe: str
    version_args: list
    required: bool
    resolve: object = None          # () -> (파일 이름, URL). 포터블 설치용
    tree: str | None = None         # zip을 통째로 풀 폴더(jaix_home/<tree>). None이면 실행파일만 bin에
    path_subdir: str = ""           # tree 안에서 PATH에 넣을 하위 폴더
    winget: str | None = None
    min_major: int | None = None
    min_version: str | None = None  # 이보다 낮으면 doctor가 "업데이트 필요"(동작은 함 → 주의)
    min_reason: str = ""            # 그 버전이 필요한 이유(doctor 메시지)
    windows_only: bool = False
    needed_by: str = ""             # 이 플러그인이 잠금에 있으면 필수(없으면 선택). 잠금이 곧 켜진 플러그인 목록이다
    hint: str = ""                  # 맥·리눅스 설치 안내
    purpose: str = ""
    # 다른 곳(예: 관리자 설치 C:\\Program Files, 시스템 PATH 가 사용자 PATH 보다 앞)에 있어도 jaix 사본을 따로 두고
    # 갱신한다. 그 사본 경로를 env_var(사용자 환경변수)에 적어 도구가 PATH 순서와 상관없이 그것을 쓰게 한다
    own_copy: bool = False
    env_var: str = ""

    @property
    def applies(self):
        return IS_WIN or not self.windows_only

    def path_dir(self):
        if self.tree:
            return paths.jaix_home() / self.tree / self.path_subdir
        return paths.bin_dir()


RUNTIMES = [
    Runtime("uv", "uv", "uv", ["--version"], True, _github("astral-sh/uv", r"^uv-x86_64-pc-windows-msvc\.zip$"),
            winget="astral-sh.uv", hint="brew install uv", purpose="hwp-agent 등 플러그인 MCP 서버 실행(uvx)"),
    Runtime("git", "Git", "git", ["--version"], True, _github("git-for-windows/git", r"^MinGit-[\d.]+-64-bit\.zip$"),
            tree="git", path_subdir="cmd", winget="Git.Git", hint="xcode-select --install",
            purpose="플러그인 내려받기"),
    Runtime("java", "Java (Temurin JRE 21)", "java", ["-version"], True, _adoptium, tree="jre", path_subdir="bin",
            winget="EclipseAdoptium.Temurin.21.JRE", min_major=21, hint="brew install --cask temurin@21",
            purpose="hwp → hwpx 변환"),
    Runtime("hwp2pdf", "hwp2pdf-cli", "hwp2pdf-cli", ["--version"], True,
            _github("z0nam/hwp2pdf", r"^hwp2pdf-cli-[\d.]+\.exe$"), windows_only=True,
            # hwp-agent가 HWP2PDF_LOCAL=1(저장된 서버 무시, 이 PC 한컴으로 변환)을 넘긴다. 이 첫 지원판보다
            # 낮으면 그 값을 몰라 서버 설정이 있는 PC에서 로컬 렌더가 원격으로 샌다(z0nam/hwp2pdf#5)
            min_version="2026.10.30.1", min_reason="HWP2PDF_LOCAL 지원",
            # 관리자가 깐 hwp2pdf 앱(HKLM PATH)이 있으면 그것이 먼저 잡혀 jaix 사본이 가려지고 낡은 판에 묶였다
            # (namun-ji 실측 2026-11-05). hwp-agent 는 $HWP2PDF_CLI → PATH 순으로 찾는다(docs/handoff "hwp2pdf 위치")
            own_copy=True, env_var="HWP2PDF_CLI",
            purpose="한컴오피스로 HWP 렌더(PDF)"),
    # 웍스 도구(nworks, npm 패키지)만 쓴다. 잠금에 jaix-works 가 있으면 works.ensure 가 부른다
    Runtime("node", "Node.js (LTS)", "node", ["--version"], False, _nodejs, tree="node",
            winget="OpenJS.NodeJS.LTS", min_major=18, hint="brew install node", purpose="웍스 도구(nworks)"),
    Runtime("himalaya", "himalaya", "himalaya", ["--version"], False,
            _github("pimalaya/himalaya", r"^himalaya\.x86_64-windows\.zip$"), hint="brew install himalaya",
            needed_by="mail-skill", purpose="메일 도구(mail-skill 플러그인)"),
    Runtime("age", "age", "age", ["--version"], False, _github("FiloSottile/age", r"-windows-amd64\.zip$"),
            winget="FiloSottile.age", hint="brew install age", needed_by="mail-skill",
            purpose="메일 도구 비밀 암호화(mail-skill 플러그인)"),
]
BY_KEY = {rt.key: rt for rt in RUNTIMES}


@dataclass
class Found:
    path: str | None
    version: str | None
    major: int | None = None
    raw: str = ""
    managed: bool = False           # jaix가 포터블로 깐 것(갱신 대상)
    notes: list = field(default_factory=list)
    stale: bool = False             # 이 프로세스의 PATH 엔 없고 새 창(레지스트리 PATH)·winget 바로가기에서만 보임


def _probe(rt, path, managed=False):
    try:
        out = subprocess.run([path, *rt.version_args], capture_output=True, creationflags=paths.NO_WINDOW, text=True, timeout=30,
                             encoding="utf-8", errors="replace")
        raw = (out.stdout + out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return Found(path, None, raw=str(e), managed=managed)
    m = re.search(r"(\d+)(?:\.\d+)+", raw)
    return Found(path, m.group(0) if m else None, int(m.group(1)) if m else None,
                 raw.splitlines()[0] if raw else "", managed=managed)


def copies(rt):
    """PATH(이 프로세스의 순서: Windows 는 시스템 → 사용자) 와 jaix 설치 위치에 있는 rt 실행파일 전부, 잡히는 순서대로.
    jaix 사본이 PATH 에 없거나 뒤에 있으면 마지막에 붙는다."""
    seen, out = set(), []
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d] + [str(rt.path_dir())]
    for d in dirs:
        hit = shutil.which(rt.exe, path=d)
        if not hit:
            continue
        key = os.path.normcase(os.path.realpath(hit))
        if key in seen:
            continue
        seen.add(key)
        own = shutil.which(rt.exe, path=str(rt.path_dir()))
        out.append(_probe(rt, hit, managed=bool(own) and os.path.normcase(os.path.realpath(own)) == key))
    return out


def find(rt):
    """jaix가 깐 위치 → PATH → winget 바로가기 폴더 → 새 창의 PATH(레지스트리) 순. 뒤의 둘은 winget 이 깔아
    사용자 PATH 에는 넣었지만 이 프로세스(설치 전부터 열린 명령창·Claude 앱)의 PATH 에는 아직 없는 경우다.
    winget 사용자 범위 Git(Programs 폴더)과 개발자 모드가 꺼진 PC의 uv·age 는 바로가기 폴더에 없어 마지막에만
    잡힌다 — 이것을 못 보면 doctor 가 깔린 것을 "없음"으로 보였다(소모임 11/5)."""
    own = shutil.which(rt.exe, path=str(rt.path_dir()))
    here = None if own else shutil.which(rt.exe)
    path = own or here or (IS_WIN and (shutil.which(rt.exe, path=str(paths.winget_links()))
                                      or shutil.which(rt.exe, path=winenv.fresh_path())))
    if not path:
        return Found(None, None)
    found = _probe(rt, path, managed=bool(own))
    found.stale = bool(IS_WIN and not own and not here)
    return found


def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def outdated(rt, found):
    """min_version이 있고 찾은 버전이 그보다 낮으면 True. 버전을 못 읽으면 판정하지 않는다(False)."""
    if not (rt.min_version and found.path and found.version):
        return False
    return _vtuple(found.version) < _vtuple(rt.min_version)


def ok(rt, found):
    if not found.path:
        return False
    return rt.min_major is None or (found.major or 0) >= rt.min_major


def _marker(rt):
    return paths.jaix_home() / f".{rt.key}.asset"


def _extract(archive, rt):
    """zip을 설치 위치에 푼다. tree면 맨 위 폴더 하나를 벗겨 통째로, 아니면 .exe/.dll만 bin에."""
    with zipfile.ZipFile(archive) as z:
        if rt.tree:
            dest = paths.jaix_home() / rt.tree
            with tempfile.TemporaryDirectory(dir=paths.jaix_home()) as tmp:
                z.extractall(tmp)
                top = [p for p in Path(tmp).iterdir()]
                root = top[0] if len(top) == 1 and top[0].is_dir() else Path(tmp)
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(root), dest)
            return
        bindir = paths.bin_dir()
        bindir.mkdir(parents=True, exist_ok=True)
        for info in z.infolist():
            name = Path(info.filename).name
            if not info.is_dir() and name.lower().endswith((".exe", ".dll")):
                with z.open(info) as src, open(bindir / name, "wb") as out:
                    shutil.copyfileobj(src, out)


def install_portable(rt, log):
    """최신 포터블을 받아 깐다. 지난번과 같은 파일이면 건너뛴다. PATH에 넣을 폴더를 돌려준다."""
    name, url = rt.resolve()
    marker = _marker(rt)
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == name and find(rt).managed:
        log(f"  {rt.label}: 최신({name}) — 그대로 둠")
        return rt.path_dir()
    log(f"  {rt.label}: {name} 내려받는 중…")
    paths.jaix_home().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.jaix_home()) as tmp:
        file = net.download(url, Path(tmp) / name)
        if name.lower().endswith(".zip"):
            _extract(file, rt)
        else:  # 단일 exe (hwp2pdf-cli-<버전>.exe → hwp2pdf-cli.exe)
            paths.bin_dir().mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, paths.bin_dir() / f"{rt.exe}.exe")
    marker.write_text(name, encoding="utf-8")
    return rt.path_dir()


def _winget(args, log):
    exe = shutil.which("winget")
    if not exe:
        return False
    cmd = [exe, *args, "--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements",
           "--disable-interactivity"]
    try:
        r = subprocess.run(cmd, capture_output=True, creationflags=paths.NO_WINDOW, text=True, timeout=900, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"    winget 실패: {e}")
        return False
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        log(f"    winget 안 됨(코드 {r.returncode}): {tail[0][:160]}")
        return False
    winenv.refresh_process_path()
    return True


def ensure(rt, log, dry_run=False, upgrade=False):
    """rt가 쓸 수 있는 상태가 되게 한다. 결과 Found를 돌려준다."""
    found = find(rt)
    # jaix 사본을 따로 두는 런타임: 밖의 사본이 쓸 만해도 jaix 사본이 없으면 깐다(밖의 것은 건드리지 않는다)
    foreign = rt.own_copy and IS_WIN and found.path and not found.managed
    if foreign:
        log(f"  {rt.label}: jaix 밖의 사본 {found.version or '?'} ({found.path}) — 그대로 두고 jaix 사본을 따로 둠")
    if ok(rt, found) and not (upgrade and found.managed) and not foreign:
        if upgrade and IS_WIN and rt.winget and not dry_run:
            _winget(["upgrade", "--id", rt.winget, "--scope", "user"], log)  # winget으로 안 깐 것이면 아무 일 없음
            found = find(rt)
        if found.managed:  # 파일은 있는데 사용자 PATH에서 빠졌을 수 있다(doctor가 setup 재실행을 권하는 경우)
            winenv.add_to_path([rt.path_dir()], dry_run=dry_run)
        if found.stale and not dry_run:  # 설치 전에 연 창에서 돈 setup: 뒤에 부르는 claude·uvx 가 Git·uv 를 찾게
            winenv.refresh_process_path()
            _process_path_add(Path(found.path).parent)
        log(f"  {rt.label}: {found.version or '있음'} ({found.path})")
        _export(rt, found, log, dry_run)
        return found
    if not IS_WIN:
        log(f"  {rt.label}: 없음 → {rt.hint or '수동 설치'}" if not found.path
            else f"  {rt.label}: {found.version} — {rt.min_major} 이상 필요 → {rt.hint}")
        return found
    if dry_run:
        log(f"  {rt.label}: 설치 예정 (winget {rt.winget or '없음'} → 포터블)")
        return found
    if rt.winget and not found.managed and not rt.own_copy:
        log(f"  {rt.label}: winget({rt.winget}) 사용자 범위로 설치 시도")
        if _winget(["install", "--id", rt.winget, "--scope", "user"], log):
            found = find(rt)
            if ok(rt, found):
                log(f"  {rt.label}: {found.version} 설치됨 ({found.path})")
                return found
    try:
        winenv.add_to_path([install_portable(rt, log)])
    except Exception as e:  # 한 런타임이 막혀도 나머지는 계속 깐다. doctor가 남은 것을 알려 준다
        log(f"  {rt.label}: 설치 실패 — {e}")
        return find(rt)
    found = find(rt)
    log(f"  {rt.label}: {found.version or '?'} ({found.path})")
    _export(rt, found, log, dry_run)
    return found


def _process_path_add(folder):
    """이 프로세스(와 자식)의 PATH 에만 folder 를 붙인다. 사용자 PATH 는 건드리지 않는다."""
    cur = os.environ.get("PATH", "").split(os.pathsep)
    norm = lambda p: os.path.normcase(os.path.normpath(p))  # noqa: E731
    if norm(str(folder)) not in {norm(p) for p in cur if p}:
        os.environ["PATH"] = os.pathsep.join([*cur, str(folder)])


def _export(rt, found, log, dry_run=False):
    """jaix 사본 경로를 사용자 환경변수에 적는다(PATH 에서 다른 사본이 먼저 잡혀도 도구가 이것을 쓰게)."""
    if not (rt.env_var and IS_WIN and found.managed and found.path) or dry_run:
        return
    if winenv.set_user_env(rt.env_var, found.path):
        log(f"  {rt.label}: {rt.env_var}={found.path} (새로 연 앱·창부터 적용)")


def hancom_installed():
    """한컴오피스(HWP COM 서버 HWPFrame.HwpObject) 등록 여부. hwp2pdf가 이 COM으로 렌더한다."""
    if not IS_WIN:
        return False
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "HWPFrame.HwpObject"))
        return True
    except OSError:
        return False


def required(rt, lock=None):
    """필수인지: 늘 필수이거나, 이 런타임을 쓰는 플러그인(needed_by)이 잠금에 있을 때."""
    return rt.required or bool(rt.needed_by and lock and any(p.name == rt.needed_by for p in lock.plugins))


def select(keys, lock=None):
    """--runtimes 값(쉼표 구분)을 Runtime 목록으로. 비우면 필수(잠금의 플러그인이 쓰는 것 포함) + 맥에서 안 쓰는 것 제외."""
    if not keys:
        return [rt for rt in RUNTIMES if required(rt, lock) and rt.applies]
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise SystemExit(f"모르는 런타임: {', '.join(unknown)} (가능: {', '.join(BY_KEY)})")
    return [BY_KEY[k] for k in keys if BY_KEY[k].applies]

