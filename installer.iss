; Inno Setup 脚本：ZJU AutoLogin Windows 安装包（按用户安装，无需管理员）
; 用法: iscc installer.iss /DAppVersion=1.25.4

#define MyAppName "ZJU AutoLogin"
#ifndef AppVersion
; 未传 /DAppVersion 时别再默默产出 1.1.0 的包名与版本号, 直接报错
#error 请传 /DAppVersion=<版本号>, 例如: iscc installer.iss /DAppVersion=1.25.4
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
; 先删用户级 GUI 看护任务(ZJUAutoLogin-Watchdog, 与 GUI 同权限, 无需管理员)。
; 注意任务名不是 ZJUAutoLogin —— 早期卸载脚本删错了名字, 结果看护任务残留,
; 每 5 分钟去拉起一个已经不存在的 exe。
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ZJUAutoLogin-Watchdog"; Flags: runhidden; RunOnceId: "DelWatchdog"
Filename: "{sys}\cmd.exe"; Parameters: "/C del /F /Q ""{userappdata}\ZJUAutoLogin\watchdog.ps1"" ""{userappdata}\ZJUAutoLogin\gui.alive"" ""{userappdata}\ZJUAutoLogin\watchdog.pause"""; Flags: runhidden; RunOnceId: "DelWatchdogFiles"
; 系统级保活(SYSTEM watch 会锁住 exe, 必须先停再删)与服务凭据目录。
; 该任务由 SYSTEM 账户注册, 普通权限删不掉; 若存在请用管理员执行:
;   schtasks /Delete /F /TN ZJUAutoLogin
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ZJUAutoLogin"; Flags: runhidden; RunOnceId: "StopWatch"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ZJUAutoLogin"; Flags: runhidden; RunOnceId: "DelWatch"
Filename: "{sys}\cmd.exe"; Parameters: "/C rmdir /S /Q ""C:\ProgramData\ZJUAutoLogin"""; Flags: runhidden; RunOnceId: "DelSvcData"

[Code]
// 关掉正在运行的 ZJU AutoLogin(托盘 GUI 与无界面 watch 进程同名)。
// 文件被占用时 Inno 无法删除/替换, 只能登记"重启后删除"; 该记录会一直留在系统的
// PendingFileRenameOperations 里, 之后每次安装都会被"上一次安装未完成, 请重启"
// 挡住 —— 而它指向的正是 {app}\ZJUAutoLogin.exe, 只能清注册表才能解(2026-10-08 事故)。
procedure StopOurProcesses;
var
  Rc: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'),
       '/IM ZJUAutoLogin.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Rc);
  { 系统级保活计划任务(如有): 尽力停止, 无管理员权限时失败可忽略 }
  Exec(ExpandConstant('{sys}\schtasks.exe'),
       '/End /TN ZJUAutoLogin', '', SW_HIDE, ewWaitUntilTerminated, Rc);
  Exec(ExpandConstant('{sys}\schtasks.exe'),
       '/End /TN ZJUAutoLogin-Watchdog', '', SW_HIDE, ewWaitUntilTerminated, Rc);
  Sleep(800);  { 等文件句柄释放 }
end;

// 每次安装写一个安装会话标记: 应用靠它判断"这是新装/覆盖安装", 强制弹一次引导向导。
// v1.24.0 起 gui.py 就在读 {app}\.install-session, 但安装器曾长期没写过它,
// "新装必见引导"一度从未生效。
procedure CurStepChanged(CurStep: TSetupStep);
var
  MarkerPath: String;
  Content: String;
begin
  if CurStep = ssInstall then
    StopOurProcesses
  else if CurStep = ssPostInstall then
  begin
    MarkerPath := ExpandConstant('{app}\.install-session');
    Content := GetDateTimeString('yyyymmddhhnnss', #0, #0);
    SaveStringToFile(MarkerPath, Content, False);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopOurProcesses;  { 卸载同样要先关程序, 否则又留下"重启后删除"残留 }
end;
