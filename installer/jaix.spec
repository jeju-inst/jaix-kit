# PyInstaller 빌드 정의 — jaix.exe(콘솔)·jaixw.exe(창 없음)를 한 폴더(dist\jaix\)에 onedir 로 만든다.
# 실행:  pyinstaller --noconfirm installer\jaix.spec   (저장소 루트에서. 버전은 JAIX_VERSION 환경변수, 없으면 소스 값)
#
# onefile 을 쓰지 않는 까닭(jaix-kit#46): v2026.10.28.5 설치본이 Defender 기계학습 판정(Bearfoos.B!ml)에 걸렸다.
# onefile 은 실행할 때마다 %TEMP%\_MEI* 에 자기를 풀어 DLL·pyd 를 올리는데, 이것이 그런 판정을 부르기 쉬운
# 동작으로 알려져 있다. onedir 는 설치 폴더의 파일을 그대로 쓴다.
# UPX 압축은 끈다(압축된 실행파일은 평판 판정에서 불리하다). 버전 리소스(회사·제품·파일 버전)를 넣는다.
# 두 실행파일은 같은 Analysis 를 나눠 써 _internal 하나를 함께 쓴다 — 다른 것은 부트로더(콘솔 유무)뿐이다.
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 — PyInstaller 가 넣어 주는 이름


def _version():
    v = os.environ.get("JAIX_VERSION")
    if not v:
        src = open(os.path.join(ROOT, "src", "jaix", "__init__.py"), encoding="utf-8").read()
        v = re.search(r'__version__ = "([^"]+)"', src).group(1)
    nums = [int(n) for n in re.findall(r"\d+", v.split("+")[0])][:4]
    return v, tuple(nums + [0] * (4 - len(nums)))


VERSION, VERSION_TUPLE = _version()


def version_info(name, description):
    if sys.platform != "win32":  # 버전 리소스는 Windows PE 에만 있다(맥 시험 빌드는 건너뜀)
        return None
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    text = ".".join(str(n) for n in VERSION_TUPLE)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
        kids=[
            StringFileInfo([StringTable("041204B0", [  # 한국어(0x0412), 유니코드
                StringStruct("CompanyName", "제주연구원"),
                StringStruct("ProductName", "JAIX"),
                StringStruct("FileDescription", description),
                StringStruct("FileVersion", text),
                StringStruct("ProductVersion", VERSION),
                StringStruct("InternalName", name),
                StringStruct("OriginalFilename", f"{name}.exe"),
                StringStruct("LegalCopyright", "© 제주연구원 AI센터"),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0412, 1200])]),
        ],
    )


a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "src", "jaix", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    # 잠금 사본을 묶어 네트워크가 막혀도 doctor가 돈다(평소엔 GitHub의 최신 잠금을 먼저 본다)
    datas=[(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), ".")],
)
pyz = PYZ(a.pure)  # noqa: F821

# hide-early: 콘솔을 혼자 가진 때만 창을 숨긴다. 명령창·바로가기(cmd /K)에선 그대로 보인다
jaix = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="jaix", console=True, hide_console="hide-early",
    upx=False, version=version_info("jaix", "JAIX 도구 설치·점검·갱신"),
)
# 창 없는 빌드: 예약 작업(로그온 갱신·설치 중 setup)이 부른다. hide-early 는 콘솔이 생긴 뒤 숨겨 깜빡임이 남는다
jaixw = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="jaixw", console=False,
    upx=False, version=version_info("jaixw", "JAIX 도구 갱신(창 없음)"),
)
coll = COLLECT(jaix, jaixw, a.binaries, a.datas, upx=False, name="jaix")  # noqa: F821
