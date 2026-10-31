; Inno Setup — JAIX 설치 프로그램 (jaix-setup.exe).
; 얇은 껍데기다: jaix(onedir 폴더)를 깔고, 채널 체크박스만 받아 `jaix setup --channels …`에 넘긴다
; (ji-deploy-standards 3.2). 런타임 설치·마켓플레이스 등록·안내문은 전부 jaix CLI가 한다.
; 사용자 범위 설치(관리자 권한·재부팅 없음).
;
; CI(jaix-setup.yml)가 installer\payload\jaix\ (PyInstaller onedir: jaix.exe·jaixw.exe·_internal) 를 놓고
;   ISCC.exe installer\jaix-setup.iss  를 돌린다. {app} 은 런타임(bin·git·jre)도 두는 곳이라 실행파일은 {app}\jaix\ 에 둔다.
; 무인 설치:  jaix-setup.exe /VERYSILENT /CURRENTUSER /CHANNELS=claude,codex[,hermes] [/GWSOURCE=<원내 URL>]
;             Hermes: /HERMESCODEFILE=<연결 코드 파일, jaix가 읽고 지움> [/HERMESMODEL=chatgpt|claude]
; 슬랙 연결 코드는 명령줄·설치 기록에 싣지 않는다 — 사용자 폴더의 파일로 넘기고 jaix가 읽자마자 지운다(docs/design-hermes-unattended.md §3.2)
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
; 코드 서명 자리(jaix-kit#46): 인증서가 생기면 ISCC /Sjaixsign="signtool sign /fd sha256 ... $f" 로 넘기고 아래를 켠다
; SignTool=jaixsign

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[InstallDelete]
; 예전(onefile) 설치본이 {app} 바로 아래 둔 실행파일. 남으면 옛 PATH 항목으로 옛 jaix 가 불린다(jaix-kit#46)
Type: files; Name: "{app}\jaix.exe"
Type: files; Name: "{app}\jaixw.exe"
; onedir 폴더는 판마다 통째로 바꾼다 — 빠진 모듈의 옛 파일이 _internal 에 남지 않게
Type: filesandordirs; Name: "{app}\jaix"

[Files]
; jaix.exe(콘솔)·jaixw.exe(창 없음, 예약 작업이 부름)·_internal(둘이 함께 씀)
Source: "payload\jaix\*"; DestDir: "{app}\jaix"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\JAIX 점검 (jaix doctor)"; Filename: "{cmd}"; Parameters: "/K ""{app}\jaix\jaix.exe"" doctor"; Comment: "도구 설치 상태 점검"
Name: "{autoprograms}\JAIX 업데이트 (jaix update)"; Filename: "{cmd}"; Parameters: "/K ""{app}\jaix\jaix.exe"" update"; Comment: "런타임·도구를 잠금 버전에 맞춤"

[Registry]
; jaix.exe 자체를 사용자 PATH에. 런타임 폴더(bin·git·jre)는 jaix setup이 넣고, 예전 설치본이 넣은 {app} 항목도 뺀다
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}\jaix"; Check: NeedsAddPath(ExpandConstant('{app}\jaix'))

[Run]
; Hermes 를 깔았으면 마지막 화면에서 AI 구독 로그인 창을 연다(브라우저 승인 한 번은 사람이 한다)
Filename: "{cmd}"; Parameters: "/K ""{localappdata}\hermes\bin\hermes.exe"" auth add openai-codex"; \
  Description: "Hermes AI 로그인 창 열기 (ChatGPT)"; Flags: postinstall nowait skipifsilent; Check: HermesLogin('chatgpt')
Filename: "{cmd}"; Parameters: "/K ""{localappdata}\hermes\bin\hermes.exe"" auth add anthropic --type oauth"; \
  Description: "Hermes AI 로그인 창 열기 (Claude)"; Flags: postinstall nowait skipifsilent; Check: HermesLogin('claude')

[UninstallRun]
; 사용자 PATH에서 jaix 폴더들을 뺀다. Claude·Codex 설정과 설치된 플러그인은 그대로 둔다
Filename: "{app}\jaix\jaix.exe"; Parameters: "cleanup"; Flags: runhidden; RunOnceId: "JaixCleanup"

[UninstallDelete]
; jaix setup이 받은 포터블 런타임(bin·git·jre). 기록·상태는 %LOCALAPPDATA%\jaix 에 있어 남긴다
; (Claude·Codex 설정에 넣은 항목도 남기므로, 재설치 때 jaix가 쓴 항목을 알아보게 소유 기록을 같이 둔다)
Type: filesandordirs; Name: "{app}"

[Code]
var
  ChannelPage: TInputOptionWizardPage;
  HermesPage: TInputQueryWizardPage;
  ModelPage: TInputOptionWizardPage;
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
  ChannelPage.Add('슬랙으로도 쓰기 (Hermes) — AI센터에서 받은 연결 코드 필요');
  ChannelPage.Values[0] := True;
  ChannelPage.Values[1] := IsCodexInstalled();
  ChannelPage.Values[2] := False;

  HermesPage := CreateInputQueryPage(
    ChannelPage.ID,
    '슬랙 연결 코드',
    'AI센터에서 받은 연결 코드를 붙여 넣으세요.',
    '코드는 한 번만 쓸 수 있고 72시간 뒤 만료됩니다. 원내망에서 설치해야 합니다. ' +
    '코드가 없으면 비워 두세요(Hermes만 깔고 슬랙 연결은 나중에 합니다).');
  HermesPage.Add('연결 코드 (JX-로 시작):', False);

  ModelPage := CreateInputOptionPage(
    HermesPage.ID,
    'Hermes가 쓸 AI',
    '이미 쓰고 있는 구독을 고르세요.',
    '설치가 끝나면 로그인 창이 열립니다. 브라우저에서 승인하면 됩니다.',
    True, False);
  ModelPage.Add('ChatGPT 구독 — 권장');
  ModelPage.Add('Claude 구독');
  ModelPage.Values[0] := True;

  ProgressPage := CreateOutputProgressPage('도구 설치 중', '런타임을 내려받고 AI에 도구를 등록합니다. 몇 분 걸릴 수 있습니다.');

  GuidePage := CreateOutputMsgMemoPage(
    wpInstalling,
    '설치 완료',
    '이렇게 쓰세요',
    '아래 안내는 시작 메뉴의 "JAIX 점검"으로 언제든 다시 확인할 수 있습니다.',
    '');
end;

function HermesChosen(): Boolean;
begin
  Result := Pos('hermes', ExpandConstant('{param:CHANNELS|}')) > 0;
  if (not Result) and (ExpandConstant('{param:CHANNELS|}') = '') then
    Result := ChannelPage.Values[2];
end;

function HermesModel(): string;
begin
  Result := ExpandConstant('{param:HERMESMODEL|}');
  if Result <> '' then
    exit;
  if ModelPage.Values[1] then
    Result := 'claude'
  else
    Result := 'chatgpt';
end;

function HermesLogin(Model: string): Boolean;
begin
  Result := HermesChosen() and (HermesModel() = Model) and
    FileExists(ExpandConstant('{localappdata}\hermes\bin\hermes.exe'));
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = HermesPage.ID) or (PageID = ModelPage.ID)) and not ChannelPage.Values[2];
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: string;
begin
  Result := True;
  if CurPageID = HermesPage.ID then
  begin
    Code := Uppercase(Trim(HermesPage.Values[0]));
    HermesPage.Values[0] := Code;
    if (Code <> '') and ((Length(Code) <> 29) or (Copy(Code, 1, 3) <> 'JX-')) then
    begin
      MsgBox('연결 코드는 JX-로 시작하는 29자입니다. AI센터에서 받은 코드를 그대로 붙여 넣으세요.', mbError, MB_OK);
      Result := False;
    end;
  end;
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
  if ChannelPage.Values[2] then
  begin
    if Result <> '' then
      Result := Result + ',';
    Result := Result + 'hermes';
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
  Channels, ExePath, GuideFile, LogFile, Params, Guide, CodeFile: string;
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
  ExePath := ExpandConstant('{app}\jaix\jaix.exe');
  GuideFile := ExpandConstant('{localappdata}\jaix\guide.txt');
  LogFile := ExpandConstant('{localappdata}\jaix\setup.log');
  // --via-task: jaix setup 본 실행을 작업 스케줄러로 돌린다. 설치본의 자식으로 돌면 Windows 11 프로세스 완화
  // 정책(RedirectionGuard)을 물려받아 uv 정션 등에서 os error 448 로 죽는다(#27). 진행 줄은 그대로 이 화면에 흐른다
  Params := 'setup --via-task --channels ' + Channels + ' --guide-out "' + GuideFile + '" --log "' + LogFile + '"';
  CodeFile := '';
  if HermesChosen() then
  begin
    Params := Params + ' --hermes-model ' + HermesModel();
    CodeFile := ExpandConstant('{param:HERMESCODEFILE|}');
    if (CodeFile = '') and (HermesPage.Values[0] <> '') then
    begin
      // 사용자 폴더(본인·SYSTEM·Administrators만)에 둔다. 값은 Log 에 넘기지 않는다
      CodeFile := ExpandConstant('{localappdata}\jaix\pending\hermes-code');
      ForceDirectories(ExtractFileDir(CodeFile));
      SaveStringToFile(CodeFile, HermesPage.Values[0], False);
    end;
    if CodeFile <> '' then
      Params := Params + ' --hermes-code-file "' + CodeFile + '"';
  end;
  { gw 런타임 latest.json 주소를 바꿀 때만 /GWSOURCE= (기본은 jaix 의 원내 주소, none 이면 끔) }
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
    // jaix가 읽자마자 지우지만, jaix가 거기까지 못 갔을 때도 코드가 남지 않게
    if CodeFile <> '' then
      DeleteFile(CodeFile);
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
