[Setup]
#define AppVersion GetEnv("APP_VERSION")
#ifndef AppVersion
#define AppVersion "1.0.0"
#endif

AppName=LabSync
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={pf}\LabSync
DefaultGroupName=LabSync
OutputDir=..\..\dist
OutputBaseFilename=LabSync-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
SetupIconFile=..\..\src\gui\resources\icon.ico
UninstallDisplayIcon={app}\LabSync.exe
AllowNoIcons=yes
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\LabSync.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\src\gui\resources\icon.ico"; DestDir: "{app}\resources"; Flags: ignoreversion

[Icons]
Name: "{group}\LabSync"; Filename: "{app}\LabSync.exe"; IconFilename: "{app}\resources\icon.ico"
Name: "{group}\Uninstall LabSync"; Filename: "{uninstallexe}"
Name: "{commondesktop}\LabSync"; Filename: "{app}\LabSync.exe"; IconFilename: "{app}\resources\icon.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\LabSync"; Filename: "{app}\LabSync.exe"; IconFilename: "{app}\resources\icon.ico"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\LabSync.exe"; Description: "{cm:LaunchProgram,LabSync}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\LabSync.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\LabSync.exe"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\LabSync.exe"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Applications\LabSync.exe\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\resources\icon.ico"; Flags: uninsdeletekey