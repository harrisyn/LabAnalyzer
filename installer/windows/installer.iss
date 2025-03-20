[Setup]
AppName=LabSync
AppVersion=1.0
DefaultDirName={pf}\LabSync
DefaultGroupName=LabSync
OutputDir=..\..\dist
OutputBaseFilename=LabSync-Setup
Compression=lzma
SolidCompression=yes
SetupIconFile=..\..\src\gui\resources\icon.ico

[Files]
Source: "..\..\dist\LabSync.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\src\gui\resources\icon.ico"; DestDir: "{app}\resources"; Flags: ignoreversion

[Icons]
Name: "{group}\LabSync"; Filename: "{app}\LabSync.exe"; IconFilename: "{app}\resources\icon.ico"; IconIndex: 0
Name: "{commondesktop}\LabSync"; Filename: "{app}\LabSync.exe"; IconFilename: "{app}\resources\icon.ico"; IconIndex: 0
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\LabSync"; Filename: "{app}\LabSync.exe"; IconFilename: "{app}\resources\icon.ico"; IconIndex: 0

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\LabSync.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\LabSync.exe"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\LabSync.exe"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Applications\LabSync.exe\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\resources\icon.ico"; Flags: uninsdeletekey