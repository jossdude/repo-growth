; Inno Setup script for the Repo Growth Windows installer.
;
; Build (from the repo root, after `pyinstaller repo_growth.spec`):
;
;     iscc /DAppVersion=0.2.0 installer\repo_growth.iss
;
; Produces installer\Output\RepoGrowth-Setup.exe.
;
; Deliberately a per-user install: PrivilegesRequired=lowest means no UAC
; prompt and {autopf} resolves to %LOCALAPPDATA%\Programs, a folder the app
; can write to. That's what lets Help > Check for Updates replace the build
; in place without asking for administrator rights.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Repo Growth"
#define AppExe "RepoGrowth.exe"
#define AppPublisher "jossdude"
#define AppUrl "https://github.com/jossdude/repo-growth"

[Setup]
; Never change AppId — it's how Windows recognises an upgrade of an existing
; install rather than a second copy.
AppId={{6F3C1E58-8B27-4B0E-9A3D-2E7C5D9A41B6}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}

PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}

; Shut down a running copy so an update can overwrite the program, and don't
; drag the machine into a reboot over it.
CloseApplications=yes
RestartApplications=no
RestartIfNeededByRun=no

OutputDir=Output
OutputBaseFilename=RepoGrowth-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; No skipifsilent: a silent run is how the in-app updater installs, and it
; needs the app to come back up afterwards.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall

[UninstallDelete]
; Left behind if an in-app update was interrupted between the rename and the
; move; harmless, but no reason to leave it on disk after uninstalling.
Type: files; Name: "{app}\{#AppExe}.old"
