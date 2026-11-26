"""사용자 PATH 가 너무 길면 새 창이 통째로 못 받는다(11/26) — 줄이는 계획."""
from jaix import winenv

ENV = {"LOCALAPPDATA": r"C:\Users\user\AppData\Local", "APPDATA": r"C:\Users\user\AppData\Roaming",
       "USERPROFILE": r"C:\Users\user"}


def test_short_path_untouched():
    entries = [r"C:\a", r"C:\b"]
    keep, removed = winenv.plan_shrink(entries, [], lambda p: True, env=ENV)
    assert keep == entries and removed == []


def test_duplicates_and_system_entries_go_first():
    entries = [r"C:\a", r"C:\a", r"C:\Windows\system32", "", r"C:\b"]
    keep, removed = winenv.plan_shrink(entries, [r"C:\Windows\system32"], lambda p: True, env=ENV)
    assert keep == [r"C:\a", r"C:\b"]
    assert [why for _, why in removed] == ["중복", "시스템 PATH 에 이미 있음"]


def test_missing_local_dirs_only_when_still_long():
    real = [rf"C:\tools\t{i:03d}\bin\really\long\folder\name" for i in range(50)]  # 50 × 40자 ≈ 2000자
    gone = [rf"C:\old\gone{i}" for i in range(10)]
    usb, net = r"E:\portable", r"\\server\share\bin"
    entries = real + gone + [usb, net]
    exists = lambda p: p == "C:\\" or not p.startswith(("C:\\old", "E:"))  # E: 드라이브는 빠져 있음
    keep, removed = winenv.plan_shrink(entries, [], exists, env=ENV)
    assert all(g not in keep for g in gone) and real[0] in keep and usb in keep and net in keep  # 빠진 USB 항목은 둔다
    keep2, _ = winenv.plan_shrink(entries, [], lambda p: False, env=ENV)
    assert net in keep2  # 네트워크 경로는 존재 확인 없이 둔다(지금 안 닿을 뿐일 수 있다)


def test_shortens_with_variables_when_still_long():
    entries = [ENV["LOCALAPPDATA"] + rf"\Programs\tool{i:03d}\bin" for i in range(70)]  # 70 × 47자 > 2047
    keep, removed = winenv.plan_shrink(entries, [], lambda p: True, env=ENV)
    assert removed == [] and keep[0] == r"%LOCALAPPDATA%\Programs\tool000\bin"
    assert len(";".join(keep)) < len(";".join(entries))


def test_unexpanded_variables_are_kept():
    entries = [r"%NOPE%\x"] + ["C:\\t%03d\\" % i + "x" * 40 for i in range(50)]
    keep, _ = winenv.plan_shrink(entries, [], lambda p: False, env=ENV)
    assert r"%NOPE%\x" in keep


def test_entries_already_using_variables_are_not_cut():
    """%USERPROFILE%\\AppData\\Local\\… 를 %LOCALAPPDATA% 로 바꾸며 원문을 펼친 길이로 자르면 경로가 깨진다(Codex P1)."""
    entries = ["%USERPROFILE%" + rf"\AppData\Local\Programs\tool{i:03d}\bin" for i in range(70)]
    keep, _ = winenv.plan_shrink(entries, [], lambda p: True, env=ENV)
    assert keep == entries


def test_expanded_length_is_case_insensitive_and_covers_all_variables():
    env = dict(ENV, TOOLS="C:\\" + "t" * 3000)
    assert winenv._expanded_len([r"%localappdata%\x"], env) == len(ENV["LOCALAPPDATA"] + r"\x")
    assert winenv._expanded_len([r"%Tools%\bin"], env) > 3000
    assert winenv._expand(r"%NOPE%\x", env) == r"%NOPE%\x"
