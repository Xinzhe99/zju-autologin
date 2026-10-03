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
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=yes
SetupIconFile=resources\zju.ico
UninstallDisplayIcon={app}\ZJUAutoLogin.exe

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Launch at Windows startup / 开机自启（推荐）"; GroupDescription: "Options / 选项:"

[Files]
Source: "dist\ZJUAutoLogin.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\ZJUAutoLogin.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\ZJUAutoLogin.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ZJUAutoLogin"; ValueData: """{app}\ZJUAutoLogin.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; 可见安装: 完成页「启动程序」复选框(默认勾选)
Filename: "{app}\ZJUAutoLogin.exe"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
; 静默安装(应用内更新以 /SILENT 拉起): 完成后直接启动, 更新闭环的"最后一拉"
; (RESTARTAPPLICATIONS 救不了自退出的进程, 必须由安装器主动拉起)
Filename: "{app}\ZJUAutoLogin.exe"; Flags: nowait runasoriginaluser skipifnotsilent

[UninstallRun]
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v ZJUAutoLogin /f"; Flags: runhidden; RunOnceId: "DelAutoStart"
; 卸载时清理系统级保活(SYSTEM watch 会锁住 exe, 必须先停再删)与服务凭据目录
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ZJUAutoLogin"; Flags: runhidden; RunOnceId: "StopWatch"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ZJUAutoLogin"; Flags: runhidden; RunOnceId: "DelWatch"
Filename: "{sys}\cmd.exe"; Parameters: "/C rmdir /S /Q ""C:\ProgramData\ZJUAutoLogin"""; Flags: runhidden; RunOnceId: "DelSvcData"
