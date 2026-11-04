"""admin/managed-settings.json 의 jaix 플러그인 목록이 잠금(marketplace.json)과 맞는지 본다.

콘솔의 Managed settings 는 사람이 붙여 넣는 값이라 잠금에 플러그인이 늘거나 빠져도 저절로 따라가지 않는다
(docs/org-defaults.md 3절). 그래서 이 파일을 잠금과 맞춰 두고, 바뀌면 콘솔에도 다시 붙여 넣는다.

- 잠금에 있는데 managed 에 없음 → 경고(::warning::). CLI 에서만 그 플러그인이 강제로 켜지지 않을 뿐이라 막지는 않는다.
  잠금 갱신 봇 PR 을 세우지 않기 위해서다. 사람이 이 파일과 콘솔을 함께 고친다.
- managed 에는 있는데 잠금에 없음 → 실패. 없는 플러그인을 전원에게 켜라고 하는 값이다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKET = "jaix"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def compare(lock_names, managed):
    enabled = managed.get("enabledPlugins") or {}
    on = {k.rsplit("@", 1)[0] for k, v in enabled.items() if k.endswith("@" + MARKET) and v is True}
    return sorted(set(lock_names) - on), sorted(on - set(lock_names))


def main():
    lock = [p["name"] for p in load(".claude-plugin/marketplace.json")["plugins"]]
    missing, stale = compare(lock, load("admin/managed-settings.json"))
    for name in missing:
        print(f"::warning file=admin/managed-settings.json::잠금에 있는 {name} 이 managed enabledPlugins 에 없음 — "
              f'"{name}@{MARKET}": true 를 넣고 콘솔 Managed settings 에도 다시 붙여 넣을 것 (docs/org-defaults.md 3절)')
    for name in stale:
        print(f"::error file=admin/managed-settings.json::{name}@{MARKET} 이 잠금에 없음 — managed enabledPlugins 에서 뺄 것")
    if not missing and not stale:
        print(f"managed-settings 와 잠금 일치 ({len(lock)}종)")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
