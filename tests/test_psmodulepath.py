"""PS7 창에서 jaix 를 불러도 자식 Windows PowerShell 5.1 이 PS7 모듈을 읽지 않게(jaix-kit#205)"""
from jaix import winenv

PS7 = ("C:\\Users\\u\\Documents\\PowerShell\\Modules;C:\\Program Files\\PowerShell\\Modules;"
       "c:\\program files\\powershell\\7\\Modules")
PS51 = ("C:\\Users\\u\\Documents\\WindowsPowerShell\\Modules;C:\\Program Files\\WindowsPowerShell\\Modules;"
        "C:\\WINDOWS\\system32\\WindowsPowerShell\\v1.0\\Modules")


def test_drops_ps7_dirs_keeps_others():
    env = {"PSModulePath": f"{PS7};{PS51};D:\\Org\\Modules"}
    assert winenv.clean_psmodulepath(env) is True
    assert env["PSModulePath"] == f"{PS51};D:\\Org\\Modules"


def test_untouched_when_no_ps7():
    env = {"PSModulePath": PS51}
    assert winenv.clean_psmodulepath(env) is False
    assert env["PSModulePath"] == PS51


def test_removes_variable_when_only_ps7():
    env = {"PSModulePath": PS7}
    assert winenv.clean_psmodulepath(env) is True
    assert "PSModulePath" not in env


def test_missing_variable():
    env = {}
    assert winenv.clean_psmodulepath(env) is False
    assert env == {}


def _real_windows_pwsh():
    import shutil
    return winenv.IS_WIN and shutil.which("pwsh") and shutil.which("powershell")


def test_real_pwsh_child_ps51_loads_security_module():
    """Windows CI(pwsh 있음): PS7 이 넘기는 PSModulePath 를 정리하면 5.1 의 ConvertTo-SecureString 이 된다."""
    import os
    import subprocess

    import pytest
    if not _real_windows_pwsh():
        pytest.skip("Windows + pwsh 에서만")
    inherited = subprocess.run(["pwsh", "-NoProfile", "-Command", "$env:PSModulePath"],
                               capture_output=True, text=True, timeout=120).stdout.strip()
    env = {**os.environ, "PSModulePath": inherited}
    winenv.clean_psmodulepath(env)
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$null = ConvertTo-SecureString 'x' -AsPlainText -Force; 'ok'"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.stdout.strip() == "ok", r.stderr
