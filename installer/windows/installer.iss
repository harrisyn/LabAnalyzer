[Setup]
AppName=XN-L Interface
AppVersion=1.0
DefaultDirName={pf}\XN-L Interface
DefaultGroupName=XN-L Interface
OutputDir=..\..\dist
OutputBaseFilename=XN-L-Interface-Setup
Compression=lzma
SolidCompression=yes
SetupIconFile=..\..\src\gui\resources\icon.ico

[Files]
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\src\gui\resources\icon.ico"; DestDir: "{app}\resources"; Flags: ignoreversion

[Icons]
Name: "{group}\XN-L Interface"; Filename: "{app}\XN-L Interface.exe"; IconFilename: "{app}\resources\icon.ico"; IconIndex: 0
Name: "{commondesktop}\XN-L Interface"; Filename: "{app}\XN-L Interface.exe"; IconFilename: "{app}\resources\icon.ico"; IconIndex: 0
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\XN-L Interface"; Filename: "{app}\XN-L Interface.exe"; IconFilename: "{app}\resources\icon.ico"; IconIndex: 0

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\XN-L Interface.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\XN-L Interface.exe"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\XN-L Interface.exe"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Applications\XN-L Interface.exe\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\resources\icon.ico"; Flags: uninsdeletekey