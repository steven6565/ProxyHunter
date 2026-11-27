; Inno Setup script for ProxyHunter v3.0 Windows installer (64-bit)
#define MyAppName "ProxyHunter"
#define MyAppVersion "3.0.0"
#define MyAppPublisher "ProxyHunter Project"
#define MyAppExeName "ProxyHunter.exe"

[Setup]
AppId={{6B0E6A9E-3B47-4E1C-9D32-0D5A64A6D3F1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\builds
OutputBaseFilename=ProxyHunter_v3.0_Setup
SetupIconFile=ProxyHunter.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Launch ProxyHunter when Windows starts"; GroupDescription: "Startup"; Flags: unchecked

[Files]
Source: "..\builds\ProxyHunter_portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--startup"; Tasks: startup; Flags: nowait postinstall skipifsilent
