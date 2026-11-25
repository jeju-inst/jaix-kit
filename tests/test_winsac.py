"""스마트 앱 컨트롤: doctor 한 줄과 업데이트 실패 안내(11/25 연구원 PC WinError 4551)."""
from jaix import doctor, selfupdate, winsac


def test_state_from_registry_value():
    assert winsac.state(lambda: 1) == "on"
    assert winsac.state(lambda: 2) == "eval"
    assert winsac.state(lambda: 0) == "off"

    def missing():
        raise FileNotFoundError
    assert winsac.state(missing) is None


def test_doctor_rows():
    assert winsac.doctor_rows(lambda: 1)[0][0] == "fail" and "끄기" in winsac.doctor_rows(lambda: 1)[0][3]
    assert winsac.doctor_rows(lambda: 2)[0][0] == "warn"
    assert winsac.doctor_rows(lambda: 0)[0][0] == "ok"
    assert winsac.doctor_rows(lambda: 9) == []


def test_doctor_includes_sac(monkeypatch):
    monkeypatch.setattr(winsac, "state", lambda read=None: "on")
    rows = doctor.check_sac()
    assert rows[0].status == "fail" and rows[0].area == winsac.AREA


def test_launch_blocked_by_app_control_explains(tmp_path, monkeypatch):
    monkeypatch.setattr(winsac, "state", lambda read=None: "on")
    monkeypatch.setattr(selfupdate, "verified", lambda st: tmp_path / "jaix-setup.exe")
    monkeypatch.setattr(selfupdate, "save_state", lambda st: None)

    def popen(*a, **kw):
        e = OSError("애플리케이션 제어 정책에서 이 파일을 차단했습니다")
        e.winerror = 4551
        raise e
    out, st = [], {}
    assert selfupdate.launch(st, out.append, popen=popen, close=lambda log: None) is False
    assert "스마트 앱 컨트롤" in st["error"] and "끄기" in out[-1]


def test_launch_other_oserror_keeps_message(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "verified", lambda st: tmp_path / "jaix-setup.exe")
    monkeypatch.setattr(selfupdate, "save_state", lambda st: None)

    def popen(*a, **kw):
        raise PermissionError("거부")
    st = {}
    selfupdate.launch(st, lambda m: None, popen=popen, close=lambda log: None)
    assert st["error"].startswith("설치기 실행 실패")


def test_4551_without_sac_keeps_original_error():
    e = OSError("애플리케이션 제어 정책에서 이 파일을 차단했습니다")
    e.winerror = 4551
    msg = winsac.explain(e, read=lambda: 0)
    assert "스마트 앱 컨트롤" not in msg and "애플리케이션 제어 정책에서" in msg and "기관" in msg
    assert "스마트 앱 컨트롤" in winsac.explain(e, read=lambda: 2)
