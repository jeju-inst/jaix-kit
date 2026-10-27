#!/usr/bin/env python3
"""jaix 플러그인 표준 검사기 (plugin_lint.py).

.claude-plugin/marketplace.json 에 잠긴 각 플러그인을 sha 로 얕게 받아 다음을 검사:
  ① <path>/.claude-plugin/plugin.json 존재, JSON 파싱, "version" 필드 없음 (TS-FORMAT-1, TS-FORMAT-2)
  ② 저장소 루트에 .github/workflows/calver.yml 존재하고 jeju-inst/jaix-kit 의 calver-tag.yml 을 40자 SHA 로 호출 (TS-VER-2, TS-VER-3)
  ③ .mcp.json 이 있으면 command 가 uvx 인 서버는 args 에 "--python" 다음 "3.12" 가 있음 (TS-MCP-1)
  ④ skills/*/SKILL.md 존재, 본문에 'path/to' 문자열 없음 (TS-FORMAT-3, TS-SKILL-2)
  ⑤ SKILL.md 크기 근사(바이트/3)가 10,000 토큰 초과면 경고 (TS-TOKEN-2)

출력은 플러그인별 ✓/△ 목록이며, 기본은 전부 경고 모드(종료 코드 0)이다.
--strict 옵션 지정 시 위반(①~④)이 1건이라도 있으면 종료 코드 1로 종료한다.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# 한국어 Windows 콘솔(cp949)·CI(cp1252)에서도 한글·기호가 깨지지 않게 설정
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")

MARKET = Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
CALVER_TAG_SHA_RE = re.compile(r"^jeju-inst/jaix-kit/\.github/workflows/calver-tag\.yml@[0-9a-fA-F]{40}$")


def check_calver_workflow(text):
    """calver.yml 내용에서 주석을 제외한 실제 uses 호출이 calver-tag.yml을 40자 SHA로 호출하는지 검사한다."""
    has_valid_call = False
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        if not code:
            continue
        m_uses = re.search(r"uses:\s*(\S+)", code)
        if m_uses:
            target = m_uses.group(1).strip("'\"")
            if "jeju-inst/jaix-kit/.github/workflows/calver-tag.yml" in target:
                if CALVER_TAG_SHA_RE.fullmatch(target):
                    has_valid_call = True
                else:
                    return False
    return has_valid_call


def git_url(src):
    url = src.get("url") or src.get("repo")
    if src.get("source") == "github" or re.fullmatch(r"[\w.-]+/[\w.-]+", url or ""):
        return f"https://github.com/{url}.git"
    return url


def inspect_plugin(plugin_entry):
    """원격 저장소에서 커밋 sha를 blob 없이 얕게 fetch하여 표준 검사를 수행한다."""
    src = plugin_entry.get("source", {})
    url = git_url(src)
    sha = src.get("sha")
    if not sha:
        return [f"sha 고정 없음"], []

    with tempfile.TemporaryDirectory() as d:
        git = ["git", "-C", d]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run(
            [*git, "fetch", "-q", "--depth", "1", "--filter=blob:none", url, sha],
            capture_output=True,
            check=True,
        )
        ls_out = subprocess.run(
            [*git, "ls-tree", "-r", "--name-only", "FETCH_HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = set(ls_out.stdout.splitlines())

        def read_file(path):
            res = subprocess.run(
                [*git, "show", f"FETCH_HEAD:{path}"],
                capture_output=True,
                check=True,
            )
            raw = res.stdout
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            return text, raw

        return lint_plugin(plugin_entry, files, read_file)


def lint_plugin(plugin_entry, files, read_func):
    """단일 플러그인 대상 표준 검사 수행. (issues, warnings) 반환."""
    issues = []
    warnings = []

    src = plugin_entry.get("source", {})
    path = src.get("path", "").strip("/")
    prefix = f"{path}/" if path else ""

    # ① <path>/.claude-plugin/plugin.json 존재, JSON 파싱, "version" 필드 없음
    manifest_path = f"{prefix}.claude-plugin/plugin.json"
    if manifest_path not in files:
        issues.append(f"TS-FORMAT-1: {manifest_path} 없음")
    else:
        try:
            text, _ = read_func(manifest_path)
            data = json.loads(text)
            if not isinstance(data, dict):
                issues.append(f"TS-FORMAT-1: {manifest_path} JSON 루트가 객체가 아님")
            elif "version" in data:
                issues.append(f"TS-FORMAT-2: {manifest_path} 에 'version' 필드 있음 (버전은 marketplace.json 에서 관리)")
        except Exception as e:
            issues.append(f"TS-FORMAT-1: {manifest_path} JSON 파싱 실패: {e}")

    # ② 저장소 루트에 .github/workflows/calver.yml 존재하고 jeju-inst/jaix-kit 의 calver-tag.yml 을 40자 SHA 로 호출
    calver_path = ".github/workflows/calver.yml"
    if calver_path not in files:
        issues.append(f"TS-VER-2: {calver_path} 없음")
    else:
        try:
            text, _ = read_func(calver_path)
            if not check_calver_workflow(text):
                issues.append(f"TS-VER-3: {calver_path} 에서 jeju-inst/jaix-kit/.github/workflows/calver-tag.yml 을 40자 SHA 로 호출하지 않음")
        except Exception as e:
            issues.append(f"TS-VER-2: {calver_path} 읽기 실패: {e}")

    # ③ .mcp.json 이 있으면 command 가 uvx 인 서버는 args 에 "--python" 다음 "3.12" 가 있음
    mcp_path = None
    if f"{prefix}.mcp.json" in files:
        mcp_path = f"{prefix}.mcp.json"
    elif ".mcp.json" in files:
        mcp_path = ".mcp.json"

    if mcp_path:
        try:
            text, _ = read_func(mcp_path)
            data = json.loads(text)
            servers = data.get("mcpServers", {})
            if isinstance(servers, dict):
                for s_name, s_conf in servers.items():
                    if isinstance(s_conf, dict) and s_conf.get("command") == "uvx":
                        args = s_conf.get("args", [])
                        has_py312 = False
                        if isinstance(args, list):
                            for i in range(len(args) - 1):
                                if str(args[i]) == "--python" and str(args[i + 1]) == "3.12":
                                    has_py312 = True
                                    break
                            if not has_py312:
                                for a in args:
                                    if str(a) == "--python=3.12":
                                        has_py312 = True
                                        break
                        if not has_py312:
                            issues.append(f"TS-MCP-1: {mcp_path}: 서버 '{s_name}' uvx args 에 '--python 3.12' 없음")
        except Exception as e:
            issues.append(f"TS-MCP-1: {mcp_path} JSON 파싱 실패: {e}")

    # ④ skills/*/SKILL.md 존재, 본문에 'path/to' 문자열 없음
    skill_re = re.compile(rf"^{re.escape(prefix)}skills/[^/]+/SKILL\.md$")
    skill_files = sorted([f for f in files if skill_re.match(f)])
    if not skill_files:
        issues.append(f"TS-FORMAT-3: {prefix}skills/*/SKILL.md 없음")
    else:
        for sf in skill_files:
            try:
                text, raw = read_func(sf)
                if "path/to" in text:
                    issues.append(f"TS-SKILL-2: {sf} 본문에 'path/to' 문자열 포함")

                # ⑤ SKILL.md 크기 근사(바이트/3 을 토큰 근사로) 10000 초과면 경고
                tokens = len(raw) / 3
                if tokens > 10000:
                    warnings.append(f"TS-TOKEN-2: {sf} 크기({len(raw):,} B, 약 {int(tokens):,} 토큰)가 10,000 토큰 초과")
            except Exception as e:
                issues.append(f"TS-FORMAT-3: {sf} 읽기 실패: {e}")

    return issues, warnings


def main():
    parser = argparse.ArgumentParser(description="jaix 플러그인 표준 검사기")
    parser.add_argument("--market", default=str(MARKET), help="marketplace.json 경로")
    parser.add_argument("--strict", action="store_true", help="위반 발생 시 종료 코드 1 반환 (기본은 전부 경고)")
    parser.add_argument("plugins", nargs="*", help="점검할 플러그인 이름 (생략 시 전체)")
    args = parser.parse_args()

    market_path = Path(args.market)
    if not market_path.exists():
        sys.exit(f"오류: {market_path} 파일이 존재하지 않습니다.")

    market_data = json.loads(market_path.read_text(encoding="utf-8"))
    all_plugins = market_data.get("plugins", [])

    targets = args.plugins
    if targets:
        plugins_to_check = [p for p in all_plugins if p.get("name") in targets]
    else:
        plugins_to_check = all_plugins

    total_plugins = len(plugins_to_check)
    passed_count = 0
    total_issues = 0
    total_warnings = 0

    for p in plugins_to_check:
        name = p.get("name", "<unnamed>")
        src = p.get("source", {})
        if isinstance(src, str):
            continue

        url = git_url(src)
        sha = src.get("sha")
        if not sha:
            print(f"△ {name}")
            print(f"  - sha 고정 없음")
            total_issues += 1
            continue

        try:
            issues, warnings = inspect_plugin(p)
        except Exception as e:
            print(f"△ {name}")
            print(f"  - 저장소 fetch/검사 실패: {e}")
            total_issues += 1
            continue

        total_issues += len(issues)
        total_warnings += len(warnings)

        if not issues and not warnings:
            passed_count += 1
            print(f"✓ {name}")
        else:
            print(f"△ {name}")
            for item in issues:
                print(f"  - [위반] {item}")
            for item in warnings:
                print(f"  - [경고] {item}")

    print(
        f"\n검사 완료: 총 {total_plugins}개 중 {passed_count}개 통과, "
        f"{total_plugins - passed_count}개 주의 (위반 {total_issues}건, 경고 {total_warnings}건)"
    )

    if args.strict and total_issues > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
