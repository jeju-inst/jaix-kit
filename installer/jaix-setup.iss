; Inno Setup — JAIX 설치 프로그램 (jaix-setup.exe).
; 얇은 껍데기다: jaix.exe를 깔고, 채널 체크박스만 받아 `jaix setup --channels …`에 넘긴다
; (ji-deploy-standards 3.2). 런타임 설치·마켓플레이스 등록·안내문은 전부 jaix CLI가 한다.
; 사용자 범위 설치(관리자 권한·재부팅 없음).
;
; CI(jaix-setup.yml)가 installer\payload\jaix.exe 를 놓고  ISCC.exe installer\jaix-setup.iss  를 돌린다.
; 무인 설치:  jaix-setup.exe /VERYSILENT /CURRENTUSER /CHANNELS=claude,codex [/GWSOURCE=<원내 URL>]
; jaix setup이 실패하면 설치기는 종료 코드 10으로 끝난다(설치 자체는 남아 jaix doctor로 볼 수 있다).

#define AppName "JAIX 원내 AI 도구"
; AppVer 는 릴리스 빌드가 jaix-kit 묶음 태그 값으로 바꿔 찍는다
#define AppVer "0.0.0"

[Setup]
AppId={{5B7A2E1C-6D3F-4C8B-9A41-7E2D0F3C1A90}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher=제주연구원 AI센터
AppPublisherURL=https://github.com/jeju-inst/jaix-kit
DefaultDirName={localappdata}\Programs\jaix
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=jaix-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
RestartIfNeededByRun=no
UninstallDisplayName={#AppName}
SetupLogging=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "payload\jaix.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\JAIX 점검 (jaix doctor)"; Filename: "{cmd}"; Parameters: "/K ""{app}\jaix.exe"" doctor"; Comment: "도구 설치 상태 점검"
Name: "{autoprograms}\JAIX 업데이트 (jaix update)"; Filename: "{cmd}"; Parameters: "/K ""{app}\jaix.exe"" update"; Comment: "런타임·도구를 잠금 버전에 맞춤"

[Registry]
; jaix.exe 자체를 사용자 PATH에. 런타임 폴더(bin·git·jre)는 jaix setup이 넣는다
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[UninstallRun]
; 사용자 PATH에서 jaix 폴더들을 뺀다. Claude·Codex 설정과 설치된 플러그인은 그대로 둔다
Filename: "{app}\jaix.exe"; Parameters: "cleanup"; Flags: runhidden; RunOnceId: "JaixCleanup"

[UninstallDelete]
; jaix setup이 받은 포터블 런타임(bin·git·jre)과 기록 파일
Type: filesandordirs; Name: "{app}"

[Code]
var
  ChannelPage: TInputOptionWizardPage;
  GuidePage: TOutputMsgMemoWizardPage;
  ProgressPage: TOutputProgressWizardPage;
  SetupLines: Integer;
  SetupFailed: Boolean;

function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

function IsCodexInstalled(): boolean;
begin
  Result :=
    // userprofile 은 Inno 상수가 아니다(ExpandConstant에 쓰면 런타임 오류) — 환경변수로
    DirExists(GetEnv('USERPROFILE') + '\.codex') or
    FileExists(ExpandConstant('{userappdata}\npm\codex.cmd'));
end;

procedure InitializeWizard();
begin
  ChannelPage := CreateInputOptionPage(
    wpWelcome,
    '어디에서 쓰시나요?',
    'JAIX 도구(HWP 편집 · 업무일지 · 보고서 작성 표준)를 연결할 AI를 고르세요.',
    '고른 곳에 도구를 등록합니다. 기존 설정은 지우지 않고, 바꾸기 전에 백업합니다.',
    False, False);
  ChannelPage.Add('Claude (데스크톱 앱 · Claude Code) — 권장');
  ChannelPage.Add('Codex (데스크톱 앱 · CLI)');
  ChannelPage.Add('슬랙으로도 쓰기 (Hermes) — 다음 버전');
  ChannelPage.Values[0] := True;
  ChannelPage.Values[1] := IsCodexInstalled();
  ChannelPage.Values[2] := False;
  ChannelPage.CheckListBox.ItemEnabled[2] := False;

  ProgressPage := CreateOutputProgressPage('도구 설치 중', '런타임을 내려받고 AI에 도구를 등록합니다. 몇 분 걸릴 수 있습니다.');

  GuidePage := CreateOutputMsgMemoPage(
    wpInstalling,
    '설치 완료',
    '이렇게 쓰세요',
    '아래 안내는 시작 메뉴의 "JAIX 점검"으로 언제든 다시 확인할 수 있습니다.',
    '');
end;

function SelectedChannels(): string;
begin
  { 무인 설치는 /CHANNELS=claude,codex 로 고른다 }
  Result := ExpandConstant('{param:CHANNELS|}');
  if Result <> '' then
    exit;
  if ChannelPage.Values[0] then
    Result := 'claude';
  if ChannelPage.Values[1] then
  begin
    if Result <> '' then
      Result := Result + ',';
    Result := Result + 'codex';
  end;
end;

procedure OnSetupLog(const S: String; const Error, FirstLine: Boolean);
begin
  SetupLines := SetupLines + 1;
  ProgressPage.SetText(S, '');
  ProgressPage.SetProgress(SetupLines mod 40, 40);
  Log('jaix: ' + S);
end;

function LoadGuide(const FileName: string): string;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if not LoadStringsFromFile(FileName, Lines) then
    exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    if I > 0 then
      Result := Result + #13#10;
    Result := Result + Lines[I];
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Channels, ExePath, GuideFile, LogFile, Params, Guide: string;
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then
    exit;
  Channels := SelectedChannels();
  if Channels = '' then
  begin
    GuidePage.RichEditViewer.Lines.Text :=
      '연결할 AI를 고르지 않아 도구 등록을 건너뛰었습니다.' + #13#10 +
      '나중에 명령창에서 다음을 실행하면 됩니다:' + #13#10 + '  jaix setup';
    exit;
  end;
  ExePath := ExpandConstant('{app}\jaix.exe');
  GuideFile := ExpandConstant('{app}\guide.txt');
  LogFile := ExpandConstant('{app}\setup.log');
  Params := 'setup --channels ' + Channels + ' --guide-out "' + GuideFile + '" --log "' + LogFile + '"';
  { gw 런타임 원내 위치(정해지면 배포 스크립트가 /GWSOURCE= 로 넘김) }
  if ExpandConstant('{param:GWSOURCE|}') <> '' then
    Params := Params + ' --gw-source "' + ExpandConstant('{param:GWSOURCE|}') + '"';
  Log('실행: ' + ExePath + ' ' + Params);
  SetupLines := 0;
  ProgressPage.Show;
  try
    if not ExecAndLogOutput(ExePath, Params, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode, @OnSetupLog) then
      ResultCode := -1;
  finally
    ProgressPage.Hide;
  end;
  Guide := LoadGuide(GuideFile);
  if (ResultCode = 0) and (Guide <> '') then
    GuidePage.RichEditViewer.Lines.Text := Guide
  else
    GuidePage.RichEditViewer.Lines.Text :=
      '도구 등록 중 문제가 있었습니다 (코드 ' + IntToStr(ResultCode) + ').' + #13#10 +
      '명령창에서 jaix doctor 를 실행해 결과를 AI센터에 보내 주세요.' + #13#10 +
      '기록: ' + LogFile + #13#10 + #13#10 + Guide;
  if ResultCode <> 0 then
  begin
    SetupFailed := True;
    Log('jaix setup 종료 코드 ' + IntToStr(ResultCode));
  end;
end;

// 무인 설치(/VERYSILENT)를 부르는 배포 스크립트가 jaix setup 실패를 알아채게 종료 코드로 알린다.
// 1-8은 Inno가 쓰므로 10.
function GetCustomSetupExitCode: Integer;
begin
  if SetupFailed then
    Result := 10
  else
    Result := 0;
end;
