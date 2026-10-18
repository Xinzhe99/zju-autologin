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
; 应用更新流程自己 taskkill 并启动独立 relaunch helper。
; 让 Inno 也关闭/重启会与 [Run] 或 helper 形成双开, 加剧 PyInstaller
; onefile 解包竞态(Failed to load Python DLL)。
CloseApplications=no
RestartApplications=no
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
; 静默安装(应用内更新/winget): 不直接拉起 exe, 而是启动一个延迟 helper。
; 安装器退出/杀软扫描结束后再启动, 规避 PyInstaller onefile 解包
; python3xx.dll 的竞态。旧版本应用发起的更新也能自动重启。
Filename: "{sys}\powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\update-relaunch.ps1"""; Flags: nowait runasoriginaluser skipifnotsilent

[UninstallDelete]
Type: files; Name: "{app}\update-relaunch.ps1"

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

// 每次安装写一个安装会话标记: 应用靠它判断"这是新装/覆盖安装", 弹一次引导向导
// (静默安装带 -silent 后缀, 已配置的用户不弹)。
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
    { 静默更新的延迟启动 helper: 等安装器退出/杀软扫描结束后再拉起 exe。 }
    SaveStringToFile(ExpandConstant('{app}\update-relaunch.ps1'),
      '$ErrorActionPreference = "SilentlyContinue"' + #13#10
      + 'Start-Sleep -Seconds 12' + #13#10
      + '$exe = Join-Path (Split-Path -Parent $PSCommandPath) "ZJUAutoLogin.exe"' + #13#10
      + 'if (Test-Path -LiteralPath $exe) {' + #13#10
      + '  Start-Process -FilePath $exe | Out-Null' + #13#10
      + '  Start-Sleep -Seconds 10' + #13#10
      + '  if (-not (Get-Process -Name "ZJUAutoLogin" -ErrorAction SilentlyContinue)) {' + #13#10
      + '    Start-Sleep -Seconds 10' + #13#10
      + '    Start-Process -FilePath $exe | Out-Null' + #13#10
      + '  }' + #13#10
      + '}' + #13#10
      + 'Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue' + #13#10,
      False);

    MarkerPath := ExpandConstant('{app}\.install-session');
    Content := GetDateTimeString('yyyymmddhhnnss', #0, #0);
    { 静默安装(应用内更新/winget)打上 silent 标记: 已配置好的用户升级后不再被
      引导向导拦住(向导是模态的, 不点掉保活就不启动); 手动重装仍会弹引导 }
    if WizardSilent then
      Content := Content + '-silent';
    SaveStringToFile(MarkerPath, Content, False);
  end;
end;

procedure RemoveServiceDataElevated;
var
  Rc: Integer;
begin
  { 系统级保活的计划任务与 ProgramData 配置由 SYSTEM 创建并锁了 ACL,
    普通权限卸载删不掉。这里显式弹一次 UAC, 由管理员进程删除任务与
    含 base64 密码的配置文件; 用户取消则保留, 但至少给出提示。 }
  if not DirExists(ExpandConstant('{commonappdata}\ZJUAutoLogin')) then
    Exit;
  if not ShellExec('runas', ExpandConstant('{sys}\cmd.exe'),
       '/C schtasks /End /TN ZJUAutoLogin & schtasks /Delete /F /TN ZJUAutoLogin'
       + ' & rmdir /S /Q "' + ExpandConstant('{commonappdata}\ZJUAutoLogin') + '"',
       '', SW_HIDE, ewWaitUntilTerminated, Rc) then
    MsgBox('未能获取管理员权限: 系统级保活凭据仍保留在 '
           + ExpandConstant('{commonappdata}\ZJUAutoLogin') + '。'
           + #13#10 + '如需彻底清除, 请以管理员身份运行:'
           + #13#10 + 'schtasks /Delete /F /TN ZJUAutoLogin'
           + #13#10 + 'rmdir /S /Q "'
           + ExpandConstant('{commonappdata}\ZJUAutoLogin') + '"',
           mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    StopOurProcesses;  { 卸载同样要先关程序, 否则又留下"重启后删除"残留 }
    RemoveServiceDataElevated;
  end;
end;
