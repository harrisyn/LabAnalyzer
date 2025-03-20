[Setup]
AppName=LabSync
AppVersion={#GetEnv('GITHUB_REF_NAME')}
DefaultDirName={autopf}\LabSync
DefaultGroupName=LabSync Analyzer
OutputBaseFilename=LabSync-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\..\dist\labSync.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\src\gui\resources\*"; DestDir: "{app}\gui\resources"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\Basic Analyzer"; Filename: "{app}\labSync.exe"
Name: "{commondesktop}\Basic Analyzer"; Filename: "{app}\labSync.exe"