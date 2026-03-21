; playdate.iss - Inno Setup installer script for PlayDate
; Build with Inno Setup 6+: https://jrsoftware.org/isinfo.php

#define AppName      "PlayDate"
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif
#define AppPublisher "PlayDate"
#define AppURL       "https://github.com/RobbyRatpoison/PlayDate"
#define AppExeName   "PlayDate.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

OutputDir=installer
OutputBaseFilename=PlayDate-Setup
SetupIconFile=static\img\favicon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

RestartIfNeededByRun=no

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
Source: "dist\PlayDate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";         FileName: "{app}\{#AppExeName}"
Name: "{group}\Uninstall PlayDate"; FileName: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";   FileName: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
var
  MsgResult: Integer;
  NL: String;
  Msg: String;
begin
  Result := True;
  NL := Chr(13) + Chr(10);
  Msg := 'Do you want to delete your PlayDate user data?' + NL +
         NL +
         'This includes:' + NL +
         '  - config.json  (Steam API credentials)' + NL +
         '  - state.json   (filters, sort, shelves)' + NL +
         '  - games.db     (your game library)' + NL +
         '  - playdate.log (application log)' + NL +
         NL +
         'Click YES to delete everything.' + NL +
         'Click NO to keep your data (you can re-use it after reinstalling).';
  MsgResult := MsgBox(Msg, mbConfirmation, MB_YESNO or MB_DEFBUTTON2);

  if MsgResult = IDYES then
  begin
    DeleteFile(ExpandConstant('{app}\config.json'));
    DeleteFile(ExpandConstant('{app}\state.json'));
    DeleteFile(ExpandConstant('{app}\games.db'));
    DeleteFile(ExpandConstant('{app}\playdate.log'));
  end;
end;
