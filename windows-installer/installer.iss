; Inno Setup script for the MaeWang SmartPay print server.
; Compiled by build_windows.py:  ISCC.exe /DAppVersion=1.0.0 installer.iss
; (ASCII only on purpose - avoids encoding problems with the Inno compiler.)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "MaeWang SmartPay"
#define AppExe "MaeWang-SmartPay.exe"

[Setup]
; AppId identifies the app for upgrades/uninstall - never change it.
AppId={{6F0C3B1E-6B0B-4C0E-9C55-7D1B4E2A9A31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=MaeWang SmartPay
; Per-user install (no admin prompt). The install folder stays writable, which the
; app needs for its .env file and the previews\ folder.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=output
OutputBaseFilename=MaeWang-SmartPay-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "autostart"; Description: "Start the print server automatically when Windows starts"; Flags: unchecked

[InstallDelete]
; Remove the previous version's bundled libraries so stale files do not linger.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "build\dist\MaeWang-SmartPay\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "README-Windows.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
; Written by build_windows.py when SMARTPAY_PRINT_KEY is available at build time.
Source: "build\default.env"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\README"; Filename: "{app}\README-Windows.txt"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--no-browser"; Tasks: autostart

[Run]
; Silent install = the app updating itself: bring the print server back up afterwards.
Filename: "{app}\{#AppExe}"; Parameters: "--no-browser"; Flags: nowait; Check: WizardSilent
Filename: "{app}\README-Windows.txt"; Description: "Open the setup guide (USB driver step)"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: postinstall nowait skipifsilent

[Code]
// Stop a running print server before files are replaced (upgrade) or removed.
procedure StopRunningApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp();
  Result := True;
end;
