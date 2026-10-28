"""scripts/jaixlock.py: 플러그인이 아닌 태그 커밋(seed 등)을 잠그지 않는지."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jaixlock.py"
spec = importlib.util.spec_from_file_location("jaixlock", SCRIPT)
jaixlock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jaixlock)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, files, tag):
    for name, text in files.items():
        f = repo / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", tag)
    _git(repo, "tag", "-a", tag, "-m", tag)  # 주석 태그: resolve 가 peel 한 커밋을 써야 한다
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def gen_repo(tmp_path):
    """jaix-gw 처럼 자동 생성되는 저장소: 첫 커밋은 워크플로만 담은 seed."""
    repo = tmp_path / "jaix-gw"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "t")  # CI 러너엔 git 사용자 정보가 없다(주석 태그가 요구함)
    _git(repo, "config", "user.email", "t@t")
    # 로컬 file:// 원격에서도 GitHub 처럼 sha 로 얕게·blob 없이 받을 수 있게
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    _git(repo, "config", "uploadpack.allowFilter", "true")
    seed = _commit(repo, {".github/workflows/calver.yml": "on: push\n"}, "v2026.10.27.1")
    return repo, seed


def _lock(tmp_path, monkeypatch, url, ref, sha, kind):
    market = tmp_path / "marketplace.json"
    entry = {"name": "jaix-gw", "source": {"source": "url", "url": url, "ref": ref, "sha": sha},
             "metadata": {"jaix": {"refKind": kind}}}
    market.write_text(json.dumps({"plugins": [entry]}), encoding="utf-8")
    monkeypatch.setattr(jaixlock, "MARKET", market)
    return market


def test_update_skips_seed_tag_without_plugin_json(tmp_path, monkeypatch, gen_repo, capsys):
    repo, seed = gen_repo
    url = repo.as_uri()
    _lock(tmp_path, monkeypatch, url, "main", "0" * 40, "branch")
    jaixlock.update()
    out = capsys.readouterr()
    assert "건너뜀" in out.err and "v2026.10.27.1" in out.err
    entry = jaixlock.load()["plugins"][0]
    # 유효한 태그가 없으니 브랜치 head(=seed)를 따라가되 태그로 옮기지는 않는다
    assert entry["source"]["ref"] == "main" and entry["metadata"]["jaix"]["refKind"] == "branch"


def test_update_uses_last_valid_tag(tmp_path, monkeypatch, gen_repo, capsys):
    repo, seed = gen_repo
    good = _commit(repo, {".claude-plugin/plugin.json": "{}", "skills/gw/SKILL.md": "x"}, "v2026.10.27.2")
    _commit(repo, {"README.md": "plugin.json 을 지운 잘못된 생성"}, "v2026.10.27.3")
    _git(repo, "rm", "-q", ".claude-plugin/plugin.json")
    _git(repo, "commit", "-q", "-m", "broken")
    _git(repo, "tag", "-a", "v2026.10.28.1", "-m", "broken")
    url = repo.as_uri()
    _lock(tmp_path, monkeypatch, url, "v2026.10.27.1", seed, "tag")
    jaixlock.update()
    out = capsys.readouterr()
    assert "v2026.10.28.1" in out.err  # 최신이 무효라 건너뛰고
    entry = jaixlock.load()["plugins"][0]
    assert entry["source"]["ref"] == "v2026.10.27.3"  # 그다음 유효한 태그(plugin.json 있음)
    assert entry["version"] == "2026.10.27.3"
    assert "v2026.10.27.3" in out.out and good  # changes 줄은 stdout 에만


def test_update_keeps_current_when_newer_tags_invalid(tmp_path, monkeypatch, gen_repo):
    repo, seed = gen_repo
    good = _commit(repo, {".claude-plugin/plugin.json": "{}"}, "v2026.10.27.2")
    _git(repo, "rm", "-q", ".claude-plugin/plugin.json")
    _git(repo, "commit", "-q", "-m", "broken")
    _git(repo, "tag", "-a", "v2026.10.27.3", "-m", "broken")
    _lock(tmp_path, monkeypatch, repo.as_uri(), "v2026.10.27.2", good, "tag")
    jaixlock.update()
    assert jaixlock.load()["plugins"][0]["source"]["ref"] == "v2026.10.27.2"


def test_check_warns_on_pluginless_commit(tmp_path, monkeypatch, gen_repo, capsys):
    repo, seed = gen_repo
    # check 는 https 소스만 받으므로 주소는 https 로 두고 실제 조회만 로컬 저장소로 돌린다
    market = _lock(tmp_path, monkeypatch, "https://github.com/jeju-inst/jaix-gw.git", "v2026.10.27.1", seed, "tag")
    data = json.loads(market.read_text(encoding="utf-8"))
    data["plugins"][0]["version"] = "2026.10.27.1"
    market.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(jaixlock, "git_url", lambda src: repo.as_uri())
    with pytest.raises(SystemExit) as e:
        jaixlock.check()
    assert e.value.code == 0  # 경고만
    assert "plugin.json 없음" in capsys.readouterr().out


def test_add_refuses_seed_and_pins_valid_tag(tmp_path, monkeypatch, gen_repo):
    repo, seed = gen_repo
    good = _commit(repo, {".claude-plugin/plugin.json": "{}", "skills/gw/SKILL.md": "x"}, "v2026.10.27.2")
    market = tmp_path / "marketplace.json"
    market.write_text(json.dumps({"plugins": []}), encoding="utf-8")
    monkeypatch.setattr(jaixlock, "MARKET", market)
    url = "https://github.com/jeju-inst/jaix-gw.git"  # add 는 https 만 받으므로 조회만 로컬로 돌린다
    real_resolve, real_has = jaixlock.resolve, jaixlock.has_plugin
    monkeypatch.setattr(jaixlock, "resolve", lambda u, ref, kind=None: real_resolve(repo.as_uri(), ref, kind))
    monkeypatch.setattr(jaixlock, "has_plugin", lambda u, sha, path: real_has(repo.as_uri(), sha, path))
    with pytest.raises(SystemExit):
        jaixlock.add("gw", url, "v2026.10.27.1", "그룹웨어 (gw)", "설명")
    jaixlock.add("gw", url, "v2026.10.27.2", "그룹웨어 (gw)", "설명")
    entry = jaixlock.load()["plugins"][0]
    assert entry["source"] == {"source": "url", "url": url, "ref": "v2026.10.27.2", "sha": good}
    assert entry["version"] == "2026.10.27.2" and entry["metadata"]["jaix"]["refKind"] == "tag"
