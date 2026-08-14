; Inno Setup script for noskips — compile with ISCC.exe installer.iss
#define MyAppName "noskips"
#define MyAppVersion "2.0.0"
#define MyAppExeName "noskips.exe"

[Setup]
; NB: a fresh AppId, not Rateify's. This installs *alongside* an old Rateify
; rather than over it — the app copies the old library across on first run
; (see _migrate_from_rateify in app.py) and leaves the old install untouched.
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
