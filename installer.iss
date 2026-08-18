; Inno Setup script for noskips — compile with ISCC.exe installer.iss
#define MyAppName "noskips"
#define MyAppVersion "2.1.0"
#define MyAppExeName "noskips.exe"

[Setup]
; The AppId is what Windows upgrades in place — never change it between
; releases, or a new version installs alongside the old one instead of over it.
AppId={{7C2E5A19-4B3D-4F86-9A17-D0C8E4B62F31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Kaan
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
; per-user install: no admin prompt, and the app can write its library next to itself
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=noskips-Setup-{#MyAppVersion}
SetupIconFile=noskips.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; NB: uninstall deliberately leaves {app}\data and {app}\covers behind —
; those are the user's ratings, not ours to delete.
