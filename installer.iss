; Inno Setup 脚本：ZJU AutoLogin Windows 安装包（按用户安装，无需管理员）
; 用法: iscc installer.iss /DAppVersion=1.1.0

#define MyAppName "ZJU AutoLogin"
#ifndef AppVersion
#define AppVersion "1.1.0"
#endif

[Setup]
AppId={{7C1E2A64-8D25-4E11-9E7C-3F5B90A2D611}}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher=ZJU-AutoLogin contributors
AppPublisherURL=https://github.com/Xinzhe99/zju-autologin
DefaultDirName={localappdata}\Programs\ZJUAutoLogin
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=ZJUAutoLogin-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=resources\zju.ico
UninstallDisplayIcon={app}\ZJUAutoLogin.exe

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Launch at Windows startup (recommended)"; GroupDescription: "Options:"

[Files]
Source: "dist\ZJUAutoLogin.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\ZJUAutoLogin.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\ZJUAutoLogin.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ZJUAutoLogin"; ValueData: """{app}\ZJUAutoLogin.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\ZJUAutoLogin.exe"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v ZJUAutoLogin /f"; Flags: runhidden; RunOnceId: "DelAutoStart"
