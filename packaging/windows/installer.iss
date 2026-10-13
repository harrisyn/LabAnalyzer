; Inno Setup script for LabSync. Build after PyInstaller:
;   iscc /DAppVersion=2.0.0 packaging\windows\installer.iss
; AppId stays "LabSync" (the 1.x default) so this upgrades existing installs in place.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId=LabSync
AppName=LabSync
AppVersion={#AppVersion}
AppVerName=LabSync {#AppVersion}
AppPublisher=LabSync
AppPublisherURL=https://github.com/harrisyn/LabAnalyzer
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\LabSync
DefaultGroupName=LabSync
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=LabSync-Setup-{#AppVersion}
SetupIconFile=..\..\src\labsync\resources\icon.ico
UninstallDisplayIcon={app}\LabSync.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
MinVersion=10.0

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start LabSync when I sign in (minimised)"; GroupDescription: "Startup:"
Name: "firewall"; Description: "Allow analyzers on the local network to connect (Windows Firewall rule)"; GroupDescription: "Network:"

[InstallDelete]
; 1.x shipped a single-file exe plus a resources folder; remove leftovers before laying down the new build.
Type: filesandordirs; Name: "{app}\resources"
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\LabSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LabSync"; Filename: "{app}\LabSync.exe"
Name: "{group}\Uninstall LabSync"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LabSync"; Filename: "{app}\LabSync.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LabSync"; \
  ValueData: """{app}\LabSync.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""LabSync"""; Flags: runhidden waituntilterminated; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""LabSync"" dir=in action=allow program=""{app}\LabSync.exe"" enable=yes profile=domain,private"; Flags: runhidden waituntilterminated; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""LabSync"" dir=in action=allow program=""{app}\labsync-cli.exe"" enable=yes profile=domain,private"; Flags: runhidden waituntilterminated; Tasks: firewall
Filename: "{app}\LabSync.exe"; Description: "{cm:LaunchProgram,LabSync}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""LabSync"""; Flags: runhidden; RunOnceId: "DelFirewall"
