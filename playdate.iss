; playdate.iss — Inno Setup installer script for PlayDate
; Build with Inno Setup 6+: https://jrsoftware.org/isinfo.php
;
; Input:  dist\PlayDate\  (PyInstaller onedir output)
; Output: installer\PlayDate-Setup.exe

#define AppName      "PlayDate"
#define AppVersion   GetVersionNumbersString("dist\PlayDate\PlayDate.exe")
#define AppPublisher "PlayDate"
#define AppURL       "https://github.com/RobbyRatpoison/PlayDate"
#define AppExeName   "PlayDate.exe"
#define AppDataDir   "{userappdata}\PlayDate"

[Setup]
; Basic identity
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; Install location — Program Files by default, user can change
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Output
OutputDir=installer
OutputBaseFilename=PlayDate-Setup
SetupIconFile=static\img\favicon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Appearance
WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no

; Privileges — install per-user so no UAC prompt needed
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Restart
RestartIfNeededByRun=no

; Version info embedded in the setup exe
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Bundle everything from the PyInstaller onedir output
Source: "dist\PlayDate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\{#AppName}";        FileName: "{app}\{#AppExeName}"
Name: "{group}\Uninstall PlayDate"; FileName: "{uninstallexe}"

; Desktop (optional, off by default)
Name: "{autodesktop}\{#AppName}"; FileName: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch after install
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Nothing special needed — Inno Setup handles file removal automatically

[Code]
// ── Custom page: ask user if they want to keep their data on uninstall ────────

function InitializeUninstall(): Boolean;
var
  MsgResult: Integer;
begin
  Result := True;
  MsgResult := MsgBox(
    'Do you want to delete your PlayDate user data?' + #13#10 +
    #13#10 +
    'This includes:' + #13#10 +
    '  - config.json  (Steam API credentials)' + #13#10 +
    '  - state.json   (filters, sort, shelves)' + #13#10 +
    '  - games.db     (your game library)' + #13#10 +
    '  - playdate.log (application log)' + #13#10 +
    #13#10 +
    'Click YES to delete everything.' + #13#10 +
    'Click NO to keep your data (you can re-use it after reinstalling).',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2  // NO is default
  );

  if MsgResult = IDYES then
  begin
    // Delete user data files from the install directory
    DeleteFile(ExpandConstant('{app}\config.json'));
    DeleteFile(ExpandConstant('{app}\state.json'));
    DeleteFile(ExpandConstant('{app}\games.db'));
    DeleteFile(ExpandConstant('{app}\playdate.log'));
  end;
end;
