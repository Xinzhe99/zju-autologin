# ZJU-AutoLogin · 浙江大学校园网自动登录

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey)](releases)
[![Release](https://img.shields.io/github/v/release/Xinzhe99/zju-autologin)](releases)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)


一个挂在桌面托盘的后台小程序：**自动检测浙江大学校园网认证状态，掉线/过期后用保存的学号密码自动重新登录**，保证远程桌面、SSH 等连接不会因为认证过期而失联。

| 主界面 | 首次引导 |
| --- | --- |
| ![主界面](docs/screenshot_online.png) | ![首次引导](docs/wizard_welcome.png) |

## 为什么需要它

浙江大学校园网（有线 + ZJUWLAN）采用深澜（Srun）Web 门户认证，并有如下机制（来自认证页官方说明）：

> 为了您的账号安全，**无感知认证周期设定为 14 天**，到期后需重新登录。

也就是说：即使勾选了门户的免认证（MacAuth），**每 14 天也必须手动在网页里输入一次学号密码**；此外 IP 变化、无线重连、断电重启等都可能导致认证失效。如果这时人不在电脑旁（例如人在校外用远程桌面连实验室电脑），机器就掉网了——**远程直接失联，只能跑回去重新登录**。

本工具把"重新登录"这件事交给后台：掉线自动重登，远程永不失联。

## 下载安装

到 [Releases](https://github.com/Xinzhe99/zju-autologin/releases/latest) 下载最新版（由 GitHub Actions 自动构建）：

| 平台 | 安装版（推荐） | 便携版 |
| --- | --- | --- |
| Windows | `ZJUAutoLogin-*-windows-setup.exe` | `ZJUAutoLogin-*-windows-portable.zip` |
| macOS | `ZJUAutoLogin-*-macos.dmg` | `ZJUAutoLogin-*-macos-portable.zip` |

- Windows 安装包按用户安装（无需管理员权限），可选创建桌面图标与开机自启
- 便携版解压即用，不写注册表
- 已安装的旧版本会在检测到新版本时于界面顶部提示**一键更新**
- macOS 未做代码签名：首次打开若被 Gatekeeper 拦截，请右键 App →"打开"，或到"系统设置 → 隐私与安全性"放行

## 快速上手

**第 1 步 · 安装并打开**：双击安装包完成安装（或解压便携版直接运行 `ZJUAutoLogin.exe`）。

**第 2 步 · 首次引导**：首次打开会进入引导向导——

1. 程序自动检测当前网络。如果你已经登录着校园网，会**自动带出当前账号**，确认无误即可
2. 输入一次校园网密码（与信息门户一致；密码只保存在本机）
3. 勾选"开机自启"（远程场景强烈推荐），点"完成并保存"

**第 3 步 · 完成**：到此结束，之后全自动——程序驻留托盘，掉线/14 天到期时自动重新登录，恢复后会弹通知。

**推荐的远程使用配置**（人在校外连实验室电脑的场景）：

- 设置页勾选 **系统级保活**：重启/停电后无需登录 Windows 即可自动认证（需 UAC 确认一次）
- 配置 **掉线通知**（设置 → 掉线通知）：自动重登也有救不回来时（如密码被改），第一时间手机收到提醒
- 填写 **心跳 URL**（设置 → 高级选项）：机器彻底失联时由外部服务通知你

**日常使用**：

- 托盘图标即状态（绿=在线 / 红=掉线 / 蓝=检测中 / 灰=无校园网），悬停可看 IP 与本月流量
- 右键托盘图标：立即检测 / 立即登录 / 打开登录页 / 临时关闭自动登录 / 退出
- 状态页可看认证账号、IP、上线时间、套餐与本月流量；「运行日志」页可查历史与统计

界面支持简体中文 / English，默认跟随系统语言。

## 功能

- ✅ **首次引导**：初次打开自动检测网络；若已登录校园网，**自动带出当前账号**让你确认，只需再补一次密码（密码在门户侧不可获取）
- ✅ **自动保活**：按可配置间隔（默认 60 秒）检测在线状态，掉线自动重登，失败指数退避（60s → 10min）
- ✅ **系统级保活**：可选"无需登录桌面即可认证"（Windows SYSTEM 计划任务），停电重启后远程照样可达
- ✅ **掉线推送**：连续登录失败时推送 Bark / Server酱 / 企业微信 / 钉钉 / 飞书 / 邮件通知，恢复后也提醒
- ✅ **心跳死信开关**：本机在线时每 5 分钟上报 healthchecks.io 等 URL；机器彻底失联时由外部服务通知你
- ✅ **设备管理**：遇到"在线数已达上限"时，应用内列出其他在线设备、一键踢下线并重登（本机受保护）
- ✅ **更新检查**：发现新版本托盘提醒，Windows 版一键下载（校验 SHA256）并安装
- ✅ **多语言**：简体中文 / English，跟随系统语言，可随时切换；深色模式跟随系统
- ✅ **CLI 模式**：无界面运行，可配合任务计划或 SSH 使用
- 其他：流量/套餐展示与月度超额提醒、定时主动重登、网络事件统计、一键复制诊断、配置导出/导入、笔记本电池降频、崩溃自报告、多校门户接入向导、托盘快速开关、打开登录页

## 校园网认证机制解析

`net.zju.edu.cn` 是深澜 Srun 门户（`SRunCGIAuthIntfSvr V1.18`），登录页为
`https://net.zju.edu.cn/srun_portal_pc?ac_id=80&theme=zju`。本项目的协议实现（[zju_autologin/srun.py](zju_autologin/srun.py)）直接逆向自门户登录页 JS，全流程如下：

### 1. 获取挑战值（challenge）

```
GET /cgi-bin/get_challenge?callback=cb&username={学号}&ip={本机IP}
→ {"challenge": "<64位hex，用作加密token>", "error": "ok"}
```

### 2. 构造加密参数

| 参数 | 算法 |
| --- | --- |
| `hmd5` | `HMAC-MD5(key=challenge, msg=密码)` |
| `info` | `"{SRBX1}" + 自定义Base64( XXTEA( JSON{username,password,ip,acid,enc_ver}, challenge ) )` |
| `chksum` | `SHA1(challenge+username ‖ challenge+hmd5 ‖ challenge+acid ‖ challenge+ip ‖ challenge+"200" ‖ challenge+"1" ‖ challenge+info)` |

固定常量：`acid=80`、`enc_ver=srun_bx1`、`n=200`、`type=1`、`double_stack=0`。

其中"自定义 Base64"把标准字母表替换为
`LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA`（保留 `=` 填充）；
XXTEA 按 UTF-16 码元打包输入（ASCII 场景等同字节），delta 为标准 `0x9E3779B9`。

### 3. 发起认证

```
GET /cgi-bin/srun_portal?callback=cb&action=login
    &username={学号}&password={MD5}+{hmd5}&os=Windows NT&name=Windows
    &double_stack=0&chksum={chksum}&info={info}&ac_id=80&ip={本机IP}&n=200&type=1
→ {"error": "ok"}            认证成功
→ {"error": "sign_error"}    校验码错误（chksum 不对）
→ {"error": "auth_info_error"} info 参数无法解密/不合法
→ {"suc_msg": "ip_already_online_error"}  IP 已在线（无需重复登录）
```

### 4. 查询在线状态

```
GET /cgi-bin/rad_user_info
→ 未认证: "not_online"
→ 在线:   "学号,上线时间戳,…,本机IP,…,版本"（逗号分隔）
```

运营商用户（电信/移动/联通套餐）登录时用户名需带服务后缀（如 `@cmcc`），可在设置的"服务后缀"中填写；普通校园网账号留空即可。

## 进阶用法

**命令行模式**（可配合任务计划 / SSH；系统级保活任务即以 `watch` 方式运行）：

```bash
python cli.py check     # 查询当前在线状态
python cli.py login     # 立即登录一次
python cli.py watch 30  # 常驻守护（每 30 秒检测）
```

**代理/VPN 用户**：门户认证始终直连（不走代理），不受 Clash 等工具影响；HTTPS 被掐断时自动降级 HTTP 重试，瞬断自动快速重试。外网探测 / 更新检查 / 消息推送的路由可在 设置 → 高级选项 → 网络代理 中选择（跟随系统 / 强制直连 / 自定义地址）。

若开启 **TUN/全局模式 VPN**（在路由层接管流量），程序会自动尝试**绑定校园网网卡直发**；仍不通时可点 高级选项 → 「门户直连路由(绕过VPN)」，以管理员权限为门户 IP 添加持久化直连路由（可一键移除）——这是 Windows 上确保级绕过手段。

**推送渠道**：设置 → 掉线通知，支持 Bark（iOS）、Server酱（微信）、企业微信、钉钉、飞书、邮件。钉钉/飞书机器人若启用关键词安全设置，关键词填「校园网」即可（所有推送标题均含此词）。配置后点"发送测试"验证。

每个渠道如何获取 Key/Webhook、每项该填什么，见 **[通知渠道配置指南](docs/notifications.md)**。

**其他学校使用**：设置 → 高级选项 → 接入其他高校门户，填入深澜门户地址自动探测；或手动修改门户地址与 ac_id（支持 auto 自动探测）。

## 配置与密码存储

- 配置文件：`%APPDATA%\ZJUAutoLogin\config.json`（账号、间隔、开关等）
- 密码：优先写入 **Windows 凭据管理器**（凭据名 `ZJUAutoLogin`；macOS 为 Keychain）；若不可用则退化为 base64 混淆存储（界面上会显示实际存储方式）
- 所有凭据仅存本机，不上传不同步
- 配置导出不包含任何密钥（通知 Key / 邮件授权码需导入后重新填写）

## 常见问题

**Q: 会不会把我的账号顶下线？**
不会。登录请求只针对本机当前 IP。本机已在线时服务器返回"IP 已在线"，不会影响现有会话。

**Q: 在校外能用吗？**
门户 `net.zju.edu.cn` 仅校园网内可达。在校外时程序显示"无校园网连接"并持续等待，回校后自动恢复。

**Q: 提示"在线数已达上限"？**
账号同时在在线设备数超限。程序会在状态页显示"设备管理"按钮，应用内一键踢掉其他设备并重登；也可到自助服务 [myvpn.zju.edu.cn](https://myvpn.zju.edu.cn) 操作。

**Q: 密码改了怎么办？**
在设置里重新输入密码保存即可，程序会自动清除错误锁存并重试。

**Q: 已在线时打开，为什么账号被自动填上了？**
程序从门户在线状态接口读出当前会话的账号（仅限本机），方便你确认。密码任何工具都无法获取，需要你自己输入一次。

**Q: 开了 Clash 等代理后提示"无校园网连接"？**
旧版本会受系统代理影响，现版本门户请求已强制直连。若仍异常可在 设置 → 高级选项 → 网络代理 中检查路由设置。

**Q: macOS 提示"已损坏，无法打开"？**
未签名应用在部分 macOS 上会这样提示。终端执行 `xattr -cr /Applications/ZJU\ AutoLogin.app` 后再打开。

## 项目结构

```
zju-autologin/
├── main.py                    # GUI 入口
├── cli.py                     # 命令行入口（check / login / watch）
├── zju_autologin/
│   ├── srun.py                # 深澜 Srun 协议实现（认证/状态/设备管理/参数探测）
│   ├── monitor.py             # 后台监控线程（自动重登 + 退避 + 推送 + 事件记录）
│   ├── notify.py              # 掉线推送（Bark/Server酱/企业微信/钉钉/飞书/SMTP）
│   ├── net.py                 # 网络出口选择（门户直连 / 按代理设置路由 / 网卡绑定）
│   ├── routes.py              # 门户直连路由（绕过 TUN/VPN，需管理员确认）
│   ├── service.py             # 系统级保活（Windows SYSTEM 计划任务 + ProgramData 配置）
│   ├── wizard.py              # 首次引导向导（自动检测在线账号）
│   ├── i18n.py + i18n/        # 多语言模块与翻译文件（zh-CN / en-US）
│   ├── config.py              # 配置持久化（跨平台路径）+ 系统凭据管理器
│   ├── autostart.py           # 开机自启（Windows 注册表 / macOS LaunchAgent）
│   ├── updates.py             # GitHub Releases 更新检查
│   ├── power.py               # 电源状态（笔记本电池智能降频）
│   ├── crash.py               # 全局崩溃捕获
│   ├── ui.py                  # PyQt6 主窗口（侧边栏导航）+ 托盘
│   └── theme.py               # 极简双主题（Codex 风格，浅/深，自绘控件图标）
├── .github/workflows/release.yml  # 打 tag 自动构建安装包/便携包并发布 Release
├── .github/workflows/test.yml     # push/PR 自动跑 pytest
├── tests/                         # 协议加密基准向量（门户 JS 生成）、状态机、推送渠道测试
├── README.en.md                   # English readme
├── CONTRIBUTING.md                # 贡献指南（含新语言接入步骤）
├── installer.iss              # Inno Setup 安装包脚本（Windows）
├── resources/                 # 校徽 logo、自绘控件图标
├── tools/                     # 开发工具（资源生成、JS 交叉验证、UI 截图）
└── build_exe.bat              # PyInstaller 打包脚本
```

## 开发说明

从源码运行（开发者；普通用户请直接[下载安装](#下载安装)）：

```bash
git clone https://github.com/Xinzhe99/zju-autologin.git
cd zju-autologin
pip install -r requirements.txt pytest
python main.py               # 运行
python -m pytest tests/ -q   # 测试
build_exe.bat                # 打包（产物: dist/ZJUAutoLogin.exe）
```

开发工具：

- `tools/cross_check_js.py`：用 QJSEngine 执行门户原版加密 JS，与 Python 实现逐字节对比（防止逆向转写出错）
- `tools/render_ui.py` / `tools/render_wizard.py`：离屏渲染 UI 截图（使用占位账号数据），用于自检与文档
- `tools/generate_assets.py`：从门户原始 logo 生成各尺寸图标与控件图标

参与贡献见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 免责声明

本项目仅供浙江大学师生便利性使用，认证协议的实现来源于公开可访问的门户前端代码。请遵守学校《网络安全管理办法》相关规定，勿用于破坏认证体系或他人账号的用途。校徽版权归浙江大学所有，此处仅作标识用途。

## License

[MIT](LICENSE)
