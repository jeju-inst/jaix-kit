"""도구가 쓰는 로컬 런타임: 찾기 · 버전 · 설치 · 갱신.

Windows 설치 순서: winget 사용자 범위(--scope user) → 안 되면 포터블 zip을 jaix_home 아래에 풀고 사용자 PATH에 추가.
둘 다 관리자 권한이 필요 없다. winget이 머신 범위 설치기만 있는 패키지(Git, Temurin MSI 등)는 --scope user가
거절되므로 자연히 포터블로 넘어간다. 맥·리눅스는 설치하지 않고 설치 명령만 알려 준다(개발·AI센터용).
"""
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
    windows_only: bool = False
    hint: str = ""                  # 맥·리눅스 설치 안내
    purpose: str = ""

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
            purpose="한컴오피스로 HWP 렌더(PDF)"),
    Runtime("himalaya", "himalaya", "himalaya", ["--version"], False,
            _github("pimalaya/himalaya", r"^himalaya\.x86_64-windows\.zip$"), hint="brew install himalaya",
            purpose="메일 도구(선택)"),
    Runtime("age", "age", "age", ["--version"], False, _github("FiloSottile/age", r"-windows-amd64\.zip$"),
            winget="FiloSottile.age", hint="brew install age", purpose="메일 도구 비밀 암호화(선택)"),
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


def find(rt):
    """jaix가 깐 위치를 먼저 보고, 없으면 PATH에서 찾는다."""
    own = shutil.which(rt.exe, path=str(rt.path_dir()))
    path = own or shutil.which(rt.exe)
    if not path:
        return Found(None, None)
    try:
        out = subprocess.run([path, *rt.version_args], capture_output=True, text=True, timeout=30,
                             encoding="utf-8", errors="replace")
        raw = (out.stdout + out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return Found(path, None, raw=str(e), managed=bool(own))
    m = re.search(r"(\d+)(?:\.\d+)+", raw)
    return Found(path, m.group(0) if m else None, int(m.group(1)) if m else None,
                 raw.splitlines()[0] if raw else "", managed=bool(own))


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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
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
    if ok(rt, found) and not (upgrade and found.managed):
        if upgrade and IS_WIN and rt.winget and not dry_run:
            _winget(["upgrade", "--id", rt.winget, "--scope", "user"], log)  # winget으로 안 깐 것이면 아무 일 없음
            found = find(rt)
        log(f"  {rt.label}: {found.version or '있음'} ({found.path})")
        return found
    if not IS_WIN:
        log(f"  {rt.label}: 없음 → {rt.hint or '수동 설치'}" if not found.path
            else f"  {rt.label}: {found.version} — {rt.min_major} 이상 필요 → {rt.hint}")
        return found
    if dry_run:
        log(f"  {rt.label}: 설치 예정 (winget {rt.winget or '없음'} → 포터블)")
        return found
    if rt.winget and not found.managed:
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
    return found


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


def select(keys):
    """--runtimes 값(쉼표 구분)을 Runtime 목록으로. 비우면 필수 + 맥에서 안 쓰는 것 제외."""
    if not keys:
        return [rt for rt in RUNTIMES if rt.required and rt.applies]
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise SystemExit(f"모르는 런타임: {', '.join(unknown)} (가능: {', '.join(BY_KEY)})")
    return [BY_KEY[k] for k in keys if BY_KEY[k].applies]

