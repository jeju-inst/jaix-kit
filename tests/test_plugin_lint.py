"""scripts/plugin_lint.py: 플러그인 표준 검사기 단위 및 통합(로컬 git) 시험."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "plugin_lint.py"
spec = importlib.util.spec_from_file_location("plugin_lint", SCRIPT)
plugin_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin_lint)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(repo, files, msg="commit"):
    for name, content in files.items():
        f = repo / name
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            f.write_bytes(content)
        else:
            f.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def make_local_repo(tmp_path):
    """로컬 git 저장소를 초기화하고 얕은 fetch/filter 를 허용하도록 설정하는 팩토리."""
    counter = 0

    def _factory():
        nonlocal counter
        counter += 1
        repo = tmp_path / f"repo_{counter}"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.name", "tester")
        _git(repo, "config", "user.email", "tester@example.com")
        _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
        _git(repo, "config", "uploadpack.allowFilter", "true")
        return repo

    return _factory


def test_lint_plugin_pass_repo(make_local_repo, tmp_path, monkeypatch, capsys):
    """규칙 ①~⑤를 모두 만족하는 정상 플러그인 git 저장소 통과 시험."""
    repo = make_local_repo()
    calver_content = (
        "name: calver\n"
        "jobs:\n"
        "  tag:\n"
        "    uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@1111222233334444555566667777888899990000\n"
    )
    mcp_content = json.dumps({
        "mcpServers": {
            "good-mcp": {
                "command": "uvx",
                "args": ["--python", "3.12", "--from", "good-pkg", "good-mcp"]
            }
        }
    })
    plugin_content = json.dumps({
        "name": "good-plugin",
        "description": "완벽한 플러그인"
    })
    skill_content = "# Good Skill\n이 스킬은 표준을 준수합니다.\n"

    sha = _commit(repo, {
        ".claude-plugin/plugin.json": plugin_content,
        ".github/workflows/calver.yml": calver_content,
        ".mcp.json": mcp_content,
        "skills/good-tool/SKILL.md": skill_content,
    })

    market = tmp_path / "marketplace.json"
    market.write_text(json.dumps({
        "plugins": [{
            "name": "good-plugin",
            "source": {
                "source": "url",
                "url": repo.as_uri(),
                "sha": sha
            }
        }]
    }), encoding="utf-8")

    monkeypatch.setattr(plugin_lint, "MARKET", market)
    monkeypatch.setattr("sys.argv", ["plugin_lint.py", "--market", str(market)])

    # 기본 모드: exit 0, ✓ good-plugin 출력
    with pytest.raises(SystemExit) as exc_info:
        plugin_lint.main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "✓ good-plugin" in out
    assert "1개 통과" in out

    # --strict 모드: exit 0
    monkeypatch.setattr("sys.argv", ["plugin_lint.py", "--market", str(market), "--strict"])
    with pytest.raises(SystemExit) as exc_info:
        plugin_lint.main()
    assert exc_info.value.code == 0


def test_lint_plugin_violations_repo(make_local_repo, tmp_path, monkeypatch, capsys):
    """규칙 ①~⑤를 위반하는 플러그인 git 저장소 위반·경고 검출 시험."""
    repo = make_local_repo()

    # ① "version" 필드 포함
    plugin_content = json.dumps({
        "name": "bad-plugin",
        "version": "1.0.0"
    })
    # ② calver.yml 누락 (생성하지 않음)
    # ③ uvx command에 --python 3.12 누락
    mcp_content = json.dumps({
        "mcpServers": {
            "bad-mcp": {
                "command": "uvx",
                "args": ["bad-mcp-pkg"]
            }
        }
    })
    # ④ 'path/to' 문자열 포함 및 ⑤ 10,000 토큰 초과 (30,001 바이트 이상)
    big_skill_text = "# Bad Skill\n" + "path/to/something\n" + ("x" * 30050)

    sha = _commit(repo, {
        ".claude-plugin/plugin.json": plugin_content,
        ".mcp.json": mcp_content,
        "skills/bad-tool/SKILL.md": big_skill_text,
    })

    market = tmp_path / "marketplace.json"
    market.write_text(json.dumps({
        "plugins": [{
            "name": "bad-plugin",
            "source": {
                "source": "url",
                "url": repo.as_uri(),
                "sha": sha
            }
        }]
    }), encoding="utf-8")

    monkeypatch.setattr(plugin_lint, "MARKET", market)

    # 1. 일반(경고) 모드: exit 0, 위반 및 경고 내용 출력
    monkeypatch.setattr("sys.argv", ["plugin_lint.py", "--market", str(market)])
    with pytest.raises(SystemExit) as exc_info:
        plugin_lint.main()
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "△ bad-plugin" in out
    assert "TS-FORMAT-2" in out
    assert "version" in out
    assert "TS-VER-2" in out
    assert ".github/workflows/calver.yml 없음" in out
    assert "TS-MCP-1" in out
    assert "--python 3.12" in out
    assert "TS-SKILL-2" in out
    assert "path/to" in out
    assert "TS-TOKEN-2" in out
    assert "10,000 토큰 초과" in out
    assert "위반 4건, 경고 1건" in out

    # 2. --strict 모드: exit 1
    monkeypatch.setattr("sys.argv", ["plugin_lint.py", "--market", str(market), "--strict"])
    with pytest.raises(SystemExit) as exc_info:
        plugin_lint.main()
    assert exc_info.value.code == 1


def test_lint_plugin_subdir_and_unit_checks():
    """path 지정된 서브디렉터리 플러그인 및 개별 엣지 케이스 단위 점검."""
    # 1. 서브디렉터리 플러그인 (path: "plugin")
    entry = {"name": "sub-plugin", "source": {"path": "plugin"}}
    files = {
        "plugin/.claude-plugin/plugin.json",
        ".github/workflows/calver.yml",
        "plugin/.mcp.json",
        "plugin/skills/sub-tool/SKILL.md"
    }

    def dummy_read(p):
        if p == "plugin/.claude-plugin/plugin.json":
            return '{"name": "sub"}', b'{"name": "sub"}'
        if p == ".github/workflows/calver.yml":
            return "uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@abcdef0123456789abcdef0123456789abcdef01", b""
        if p == "plugin/.mcp.json":
            return '{"mcpServers": {"s": {"command": "uvx", "args": ["--python=3.12"]}}}', b""
        if p == "plugin/skills/sub-tool/SKILL.md":
            return "Valid markdown skill content", b"Valid markdown skill content"
        raise FileNotFoundError(p)

    issues, warnings = plugin_lint.lint_plugin(entry, files, dummy_read)
    assert not issues
    assert not warnings

    # 2. calver.yml 이 40자 SHA가 아닌 브랜치/태그인 경우 위반
    def dummy_read_bad_calver(p):
        if p == ".github/workflows/calver.yml":
            return "uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@main", b""
        return dummy_read(p)

    issues, _ = plugin_lint.lint_plugin(entry, files, dummy_read_bad_calver)
    assert any("TS-VER-3" in i and "40자 SHA" in i for i in issues)

    # 2-1. calver.yml 주석에 40자 SHA가 적혀 있어도 실제 호출이 @main 이면 위반
    def dummy_read_commented_sha(p):
        if p == ".github/workflows/calver.yml":
            return (
                "# example: uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@1111222233334444555566667777888899990000\n"
                "uses: jeju-inst/jaix-kit/.github/workflows/calver-tag.yml@main\n"
            ), b""
        return dummy_read(p)

    issues, _ = plugin_lint.lint_plugin(entry, files, dummy_read_commented_sha)
    assert any("TS-VER-3" in i and "40자 SHA" in i for i in issues)

    # 3. skills/*/SKILL.md 가 아예 없는 경우
    files_no_skill = {f for f in files if "SKILL.md" not in f}
    issues, _ = plugin_lint.lint_plugin(entry, files_no_skill, dummy_read)
    assert any("TS-FORMAT-3" in i and "SKILL.md 없음" in i for i in issues)
