; WvW Analyzer - Inno Setup 6 script (built by scripts/build_windows.ps1).
;   iscc /DAppVersion=0.2.0 packaging\installer.iss
; Per-user install (no admin), private .NET runtime included in the app folder, data kept on
; upgrade, uninstall asks whether to delete analyzed fights.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "WvW Analyzer"
#define AppExe "WvWAnalyzer.exe"
#define DataDirName "WvWAnalyzer"

[Setup]
; Fixed AppId: a newer setup upgrades the existing install in place.
AppId={{8F3C6B1E-4A7D-4C2B-9E51-7D0A6B2F9C43}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=WvW Analyzer
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
; Close a running app (and its worker / Elite Insights processes) before replacing files.
; "force" also handles a window-less or hung app that ignores the polite close request.
CloseApplications=force
RestartApplications=no
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
OutputDir=..\dist
OutputBaseFilename=WvWAnalyzer-Setup-{#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Old program files are replaced completely on upgrade (user data lives elsewhere).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\WvWAnalyzer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\redist\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
  StatusMsg: "Installing Microsoft Edge WebView2 (needed for the app window)..."; Check: NeedsWebView2
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent
; The app's own updater runs this setup silently with /RELAUNCH=1 and closes itself; start it
; again afterwards. {param:} only sees the /Name=Value form. runasoriginaluser: after an
; all-users (elevated) install the app must not restart as the admin account.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: ShouldRelaunch

[Code]
const
  WebView2Key = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2KeyUser = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWebView2Version(Root: Integer; Key: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

{ WebView2 ships with Windows 10 (recent updates) and 11; only very old systems need it. }
function NeedsWebView2: Boolean;
begin
  Result := not (HasWebView2Version(HKLM, WebView2Key) or HasWebView2Version(HKCU, WebView2KeyUser));
end;

{ Set by the in-app updater (plan 17): restart the app after a silent update. }
function ShouldRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

{ Stop processes that would block replacing or removing files: anything running from the
  program folder (the app, its analysis workers, Elite Insights on the bundled .NET) and a
  llama-server started from the user's data folder. Nothing outside those folders is touched. }
procedure StopAppProcesses;
var
  ResultCode: Integer;
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-Process -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -and ($_.Path -like ''' + AppDir + '\*'' -or ' +
    '($_.ProcessName -eq ''llama-server'' -and $_.Path -like ''*\{#DataDirName}\*'')) } | ' +
    'Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1000);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // On a first install nothing runs from the app folder yet; on upgrade this closes the old app.
  if DirExists(ExpandConstant('{app}')) then
    StopAppProcesses;
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
    StopAppProcesses;
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\{#DataDirName}');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your analyzed fights, settings and the downloaded AI model?' + #13#10#13#10 +
                'Folder: ' + DataDir + #13#10 +
                'Your arcdps log files are NOT affected either way.' + #13#10#13#10 +
                'Choose No to keep them for a later reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
