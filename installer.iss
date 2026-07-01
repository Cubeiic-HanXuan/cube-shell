; installer.iss

[Setup]
AppName=cube-shell
#ifndef MyAppVersion
  #define MyAppVersion "2.8.0"
#endif
AppVersion={#MyAppVersion}
DefaultDirName={commonpf}\cube-shell
DefaultGroupName=寒暄
OutputDir=Output
OutputBaseFilename=cube-shell

[Files]
Source: "deploy\cube-shell.dist\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\cube-shell"; Filename: "{app}\cube-shell.exe"
Name: "{commondesktop}\cube-shell"; Filename: "{app}\cube-shell.exe"

[Run]
Filename: "{app}\cube-shell.exe"; Description: "Launch cube-shell"; Flags: postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"