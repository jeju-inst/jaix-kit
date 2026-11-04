import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "managed_check", Path(__file__).resolve().parent.parent / "scripts" / "managed_check.py")
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)


def test_missing_and_stale():
    m = {"enabledPlugins": {"a@jaix": True, "b@jaix": True, "x@synced": False, "c@jaix": False}}
    assert mc.compare(["a", "b", "c"], m) == (["c"], [])
    assert mc.compare(["a"], m) == ([], ["b"])


def test_repo_files_match():
    assert mc.main() == 0
