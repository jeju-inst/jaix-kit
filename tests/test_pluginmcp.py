"""플러그인 MCP 정의: .mcp.json 과 plugin.json mcpServers 를 함께 읽는다(korea-rio-mcp v2026.11.21.1 은 plugin.json 만 씀)."""
import json
import urllib.error
from types import SimpleNamespace

from jaix import pluginmcp

RIO = {"korea-rio": {"command": "uvx", "args": ["--python", "3.12", "--from", "${CLAUDE_PLUGIN_ROOT}", "korea-rio-mcp"]}}
CAL = {"ji-calendar": {"type": "http", "url": "https://example.invalid/mcp"}}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_local_plugin_json_only(tmp_path):
    _write(tmp_path / ".claude-plugin" / "plugin.json", {"name": "korea-rio-mcp", "mcpServers": RIO})
    assert pluginmcp.local(tmp_path)["mcpServers"] == RIO


def test_local_mcp_json_and_plugin_json_merge(tmp_path):
    _write(tmp_path / ".mcp.json", {"mcpServers": CAL})
    _write(tmp_path / ".claude-plugin" / "plugin.json", {"mcpServers": RIO})
    assert set(pluginmcp.local(tmp_path)["mcpServers"]) == {"korea-rio", "ji-calendar"}


def test_local_plugin_json_points_to_file(tmp_path):
    _write(tmp_path / "mcp" / "servers.json", {"mcpServers": RIO})
    _write(tmp_path / ".claude-plugin" / "plugin.json", {"mcpServers": "./mcp/servers.json"})
    assert pluginmcp.local(tmp_path)["mcpServers"] == RIO


def test_local_nothing(tmp_path):
    assert pluginmcp.local(tmp_path) == {"mcpServers": {}}
    assert pluginmcp.local(None) == {"mcpServers": {}}


def _plugin():
    return SimpleNamespace(url="https://github.com/o/r.git", sha="abc", subdir="")


def _fetcher(files, fail=()):
    def fetch(url):
        name = url.split("/abc/", 1)[1]
        if name in fail:
            raise urllib.error.URLError("offline")
        if name not in files:
            raise urllib.error.HTTPError(url, 404, "nf", None, None)
        return files[name]
    return fetch


def test_remote_reads_plugin_json_404_is_not_failure():
    cfg, failed = pluginmcp.remote(_plugin(), _fetcher({".claude-plugin/plugin.json": {"mcpServers": RIO}}))
    assert cfg["mcpServers"] == RIO and failed is False


def test_remote_network_failure_flagged():
    cfg, failed = pluginmcp.remote(_plugin(), _fetcher({}, fail={".mcp.json"}))
    assert cfg["mcpServers"] == {} and failed is True


def test_local_plugin_json_points_to_hidden_dir(tmp_path):
    _write(tmp_path / ".config" / "servers.json", {"mcpServers": RIO})
    _write(tmp_path / ".claude-plugin" / "plugin.json", {"mcpServers": "./.config/servers.json"})
    assert pluginmcp.local(tmp_path)["mcpServers"] == RIO
