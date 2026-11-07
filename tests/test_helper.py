"""jaix helper(시작 메뉴 'JAIX 도우미')와 jaix-help 플러그인. 진짜 claude 는 부르지 않는다."""
import json
import re
import subprocess
from pathlib import Path

import pytest

import sys

from jaix import cli, claude, helper, hermesbot, lock, paths, selftest

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "jaix-help"
SKILL = PLUGIN / "skills" / "jaix-help" / "SKILL.md"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    real_popen = subprocess.Popen

    class GuardedPopen(real_popen):
        def __init__(self, args, *a, **kw):
            exe = args[0] if isinstance(args, (list, tuple)) and args else str(args)
            if Path(str(exe)).stem.lower() in ("claude", "hermes", "gw", "mailskill") or "claude" in str(args):
                raise AssertionError(f"시험이 외부 명령을 부름: {args}")
            super().__init__(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(hermesbot, "show_console", lambda: False)
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "JAIX_HOME", "JAIX_DATA", "HERMES_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("JAIX_LOCK", str(LOCK_FILE))


def test_command_puts_prompt_first_and_appends_skill(monkeypatch):
    monkeypatch.setattr(helper, "IS_WIN", False)
    cmd = helper.command("/x/claude", SKILL)
    assert cmd[:2] == ["/x/claude", helper.FIRST_PROMPT]  # --allowedTools 가 프롬프트를 삼키지 않게
    assert cmd[cmd.index("--append-system-prompt-file") + 1] == str(SKILL)
    assert cmd[cmd.index("--allowedTools") + 1] == "Bash(jaix selftest:*),Bash(jaix connect:*)"


def test_skill_file_prefers_installed_plugin(monkeypatch, tmp_path):
    root = tmp_path / "inst"
    (root / helper.SKILL_REL).parent.mkdir(parents=True)
    (root / helper.SKILL_REL).write_text("x", encoding="utf-8")
    monkeypatch.setattr(selftest, "plugin_root", lambda name: root if name == "jaix-help" else None)
    assert helper.skill_file() == root / helper.SKILL_REL


def test_skill_file_falls_back_to_bundled_copy(monkeypatch):
    monkeypatch.setattr(selftest, "plugin_root", lambda name: None)
    assert helper.skill_file() == SKILL  # 소스 체크아웃의 사본


def test_run_launches_claude(monkeypatch):
    monkeypatch.setattr(claude, "find_cli", lambda: "/x/claude")
    monkeypatch.setattr(selftest, "plugin_root", lambda name: None)
    seen = []
    assert helper.run(print, call=lambda c, cwd=None: seen.append(c) or 0) == 0
    assert seen and helper.FIRST_PROMPT in seen[0]


def test_run_uses_empty_helper_dir_not_install_dir(monkeypatch, tmp_path):
    # 설치 폴더(실행 파일들)를 작업 폴더로 열면 신뢰 화면에서 'Yes' 를 고를 때 Claude 가 그것을 고칠 수 있게 된다(실기 11/7)
    install = tmp_path / "Programs" / "jaix" / "jaix"
    install.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "jaix.exe"))
    monkeypatch.chdir(install)  # 시작 메뉴 바로가기의 작업 폴더가 설치 폴더여도
    monkeypatch.setattr(claude, "find_cli", lambda: "/x/claude")
    monkeypatch.setattr(selftest, "plugin_root", lambda name: None)
    seen, lines = [], []
    assert helper.run(lines.append, call=lambda c, cwd=None: seen.append(cwd) or 0) == 0
    cwd = Path(seen[0])
    assert cwd == paths.data_dir() / "helper" and cwd.is_dir() and not any(cwd.iterdir())
    for d in (install, paths.exe_dir(), paths.jaix_home()):
        assert cwd != d and not cwd.is_relative_to(d) and not Path(d).is_relative_to(cwd)
    assert any("Yes, I trust this folder" in line for line in lines)  # 기본 'No, exit' 를 피하는 법을 알린다


def test_run_without_claude(monkeypatch):
    monkeypatch.setattr(claude, "find_cli", lambda: None)
    monkeypatch.setattr(helper, "IS_WIN", True)
    lines, paused = [], []
    assert helper.run(lines.append, call=lambda c: 0, pause=paused.append) == 1
    assert "jaix-setup" in lines[0] and paused  # 창이 바로 닫히지 않게


def test_cli_helper(monkeypatch):
    monkeypatch.setattr(helper, "run", lambda log: 7)
    assert cli.main(["helper"]) == 7


def test_guide_mentions_helper():
    assert "jaix 점검" in cli.guide(["claude"], {})
    assert "JAIX 도우미" not in cli.guide(["codex"], {"codex": {}})


# --- 플러그인 ------------------------------------------------------------------------------------
def test_plugin_manifest_has_no_version():
    data = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["name"] == "jaix-help" and "version" not in data  # 버전은 잠금이 정한다(TS-FORMAT-2)


def test_skill_frontmatter_and_triggers():
    text = SKILL.read_text(encoding="utf-8")
    m = re.match(r"---\nname: jaix-help\ndescription: (.+?)\n---\n", text, re.S)
    assert m
    desc = m.group(1)
    for word in ("jaix 점검", "안 돼요", "이상해", "고장", "설정", "도와줘", "설치 확인", "로그인 안 됨", "메일 연결",
                 "그룹웨어 연결"):
        assert word in desc, word
    assert "path/to" not in text
    assert "jaix selftest --json" in text and "jaix connect" in text


def test_skill_stays_small():
    """상시 분량(설명)과 호출당 분량(본문)을 작게 — plugin_lint 와 같은 근사."""
    text = SKILL.read_text(encoding="utf-8")

    def approx(t):
        h = len(re.findall(r"[가-힣ㄱ-ㆎ]", t))
        return 1.5 * h + (len(t.encode("utf-8")) - 3 * h) / 2.5
    desc = re.search(r"^description: (.+)$", text, re.M).group(1)
    assert approx(desc) < 300
    assert approx(text) < 2500


def test_lock_pins_self_plugin():
    entry = next(p for p in json.loads(LOCK_FILE.read_text(encoding="utf-8"))["plugins"] if p["name"] == "jaix-help")
    src = entry["source"]
    assert src["source"] == "git-subdir" and src["url"] == "https://github.com/jeju-inst/jaix-kit.git"
    assert src["path"] == "plugins/jaix-help" and re.fullmatch(r"[0-9a-f]{40}", src["sha"])
    p = next(p for p in lock.load(str(LOCK_FILE)).plugins if p.name == "jaix-help")
    assert p.subdir == "plugins/jaix-help"  # Hermes 스킬 복사(plugbin.fetch_root)가 하위 폴더를 쓴다
