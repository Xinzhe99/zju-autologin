# ZJU-AutoLogin · 浙江大学校园网自动登录

[![Tests](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml/badge.svg)](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Downloads](https://img.shields.io/github/downloads/Xinzhe99/zju-autologin/total)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Stars](https://img.shields.io/github/stars/Xinzhe99/zju-autologin?style=social)](https://github.com/Xinzhe99/zju-autologin/stargazers)
[![Issues](https://img.shields.io/github/issues/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/issues)
[![Last Commit](https://img.shields.io/github/last-commit/Xinzhe99/zju-autologin/main)](https://github.com/Xinzhe99/zju-autologin/commits)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Win%20%7C%20macOS%20%7C%20Linux-lightgrey?logo=linux&logoColor=white)](https://github.com/Xinzhe99/zju-autologin/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**简体中文** | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

一个挂在桌面托盘的后台小程序：**自动检测浙江大学校园网认证状态，掉线/过期后用保存的学号密码自动重新登录**，保证远程桌面、SSH 等连接不会因为认证过期而失联。

| 主界面 | 首次引导 |
| --- | --- |
| ![主界面](docs/screenshot_online.png) | ![首次引导](docs/wizard_welcome.png) |

## 目录

- [为什么需要它](#为什么需要它)
- [下载安装](#下载安装)
- [快速上手](#快速上手)
- [功能一览](#功能)
- [校园网认证机制解析](#校园网认证机制解析)
- [进阶用法](#进阶用法)
- [配置与密码存储](#配置与密码存储)
- [常见问题](#常见问题)
- [项目结构](#项目结构)
- [开发说明](#开发说明)
- [支持与贡献](#支持与贡献)

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
| Windows 仅保活（8MB） | — | `zju-autologin-windows-cli.exe` |
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
- ✅ **系统级保活**：可选"无需登录桌面即可认证"——Windows 计划任务 / macOS LaunchDaemon，停电重启后远程照样可达
- ✅ **掉线推送**：连续登录失败时推送 Bark / Server酱 / 企业微信 / 钉钉 / 飞书 / 邮件通知，恢复后也提醒
- ✅ **验证码支持**：贵校开启登录验证码时自动弹窗（图片+输入），输入即完成登录——验证码学校也能自动保活
- ✅ **DNS 故障兜底**：校园 DNS 挂掉时按缓存门户 IP 直连，最后一类断网原因也兜住
- ✅ **掉线回放**：把事件时间线讲成人话（"14:03 网络变化 → 14:04 重登成功，中断 8 秒"），日志页一键查看
- ✅ **GUI 崩溃自愈**：随系统级保活安装看护任务，GUI 静默消失 10 分钟内自动拉回
- ✅ **无头设备 Web 配置页**：`zju-autologin serve` 浏览器配置（仅 127.0.0.1），NAS/树莓派免 SSH 改配置
- ✅ **Windows CLI 瘦身包**：~8MB 纯保活二进制（无 GUI 依赖），老旧机器/服务器友好
- ✅ **事件驱动网络响应**：Wi-Fi 切换/插拔网线/VPN 起落 2 秒内立即重检（网卡监视器，本地调用零流量）
- ✅ **一键网络诊断**：`zju-autologin diagnose` 或界面按钮，自动区分 不在校园网/密码被改/设备超限/已认证无外网/代理干扰 并给出建议
- ✅ **设备超限自动踢号**（可选）：E2620 时自动踢掉最旧的其他设备并重登，本机永不误踢
- ✅ **心跳死信开关**：本机在线时每 5 分钟上报 healthchecks.io 等 URL；机器彻底失联时由外部服务通知你
- ✅ **设备管理**：遇到"在线数已达上限"时，应用内列出其他在线设备、一键踢下线并重登（本机受保护）
- ✅ **更新检查**：发现新版本托盘提醒，Windows 版一键下载（校验 SHA256）并安装
- ✅ **多语言**：简体中文 / English，跟随系统语言，可随时切换；深色模式跟随系统
- ✅ **CLI 模式**：无界面运行，可配合任务计划或 SSH 使用
- 其他：流量/套餐展示与月度超额提醒、定时主动重登、网络事件统计（掉线回放）、一键复制诊断、配置导出/导入、笔记本电池降频、崩溃自报告+看护自愈、多校门户接入向导、托盘快速开关、打开登录页、门户新装会话强制引导


## Linux / 嵌入式设备（一行命令启用）

适用于树莓派、实验室服务器、任何有 Python ≥3.10 的 Linux 设备（协议层零第三方依赖）：

```bash
# 安装
pip install zju-autologin          # PyPI（推荐）
# pip install git+https://github.com/Xinzhe99/zju-autologin   # 从 GitHub 直装最新

# 一行启用：装 systemd 服务 + 写凭据(root:600) + 立即启动
sudo zju-autologin enable -u 学号 -p 密码

# 完成。开机自启 + 崩溃自动重启，无需登录桌面
zju-autologin status                # 查看服务与网络状态
journalctl -u zju-autologin -f      # 跟踪日志
sudo zju-autologin disable          # 停止并卸载（凭据一并删除）
```

**密码安全**：`-p` 参数会短暂出现在 `ps` 输出里，更安全的写法：

```bash
echo '密码' | sudo zju-autologin enable -u 学号 --pass-stdin   # stdin
ZJU_PASS='密码' sudo -E zju-autologin enable -u 学号            # 环境变量
sudo zju-autologin enable -u 学号                               # 交互式输入(推荐)
```

**Linux 桌面版（GUI）**：

```bash
pip install "zju-autologin[gui]"     # 多装 PyQt6 桌面依赖
zju-autologin-gui                     # 启动图形界面（托盘/设置/向导, 同 Windows/macOS）
```

- 「开机自启」勾选即写 XDG autostart（`~/.config/autostart/`，免 root）
- GUI 内勾选「系统级保活」会通过 **pkexec** 弹系统密码框授权安装 systemd 服务（GNOME/KDE 标准授权方式，无需终端）

**OpenWrt / Alpine 路由器（一机保全网）**：从 Releases 下载 `zju-autologin-linux-musl`（musl 静态二进制），用 [tools/install-openwrt.sh](tools/install-openwrt.sh) 一键安装 procd/systemd 服务——路由器级保活，全宿舍/实验室共享不掉线。

**无 Python 的设备**：从 [Releases](releases) 下载静态二进制 `zju-autologin-linux-x86_64` / `-aarch64`（glibc 环境；Alpine/OpenWrt 等 musl 系统请用 pip 路线），`sudo ./zju-autologin-linux-* enable -u 学号` 同样一行启用。

**服务机制**：systemd 单元（`/etc/systemd/system/zju-autologin.service`），`Restart=always` 崩溃自动拉起、`After=network-online.target` 等网络就绪、凭据存 `/etc/zju-autologin/config.json`（root:600、base64 混淆，与 Windows SYSTEM 任务/macOS LaunchDaemon 同级）。

## 学校兼容性

<!-- COMPAT-MATRIX -->
| 学校 / University | 门户 | 状态 |
| --- | --- | --- |
| 浙江大学 / Zhejiang University | `https://net.zju.edu.cn` | ✅ 2026-09 验证 |
| 为你的学校添加一行 → [portals.json](zju_autologin/portals.json) | | |

## 校园网认证机制解析

> 📖 完整协议规范（供所有深澜高校开发者复用）：[docs/srun-protocol.md](docs/srun-protocol.md)

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
zju-autologin check     # 查询当前在线状态
zju-autologin login     # 立即登录一次
zju-autologin watch 30  # 常驻守护（每 30 秒检测）
zju-autologin diagnose  # 一键网络自诊断
zju-autologin serve     # 无头设备 Web 配置页（仅 127.0.0.1，浏览器改配置）
```

**代理/VPN 用户**：门户认证始终直连（不走代理），不受 Clash 等工具影响；HTTPS 被掐断时自动降级 HTTP 重试，瞬断自动快速重试。外网探测 / 更新检查 / 消息推送的路由可在 设置 → 高级选项 → 网络代理 中选择（跟随系统 / 强制直连 / 自定义地址）。

若开启 **TUN/全局模式 VPN**（在路由层接管流量），程序会自动尝试**绑定校园网网卡直发**；仍不通时可点 高级选项 → 「门户直连路由(绕过VPN)」，以管理员权限为门户 IP 添加持久化直连路由（可一键移除）——这是 Windows 上确保级绕过手段。

**推送渠道**：设置 → 掉线通知，支持 Bark（iOS）、Server酱（微信）、企业微信、钉钉、飞书、邮件。钉钉/飞书机器人若启用关键词安全设置，关键词填「校园网」即可（所有推送标题均含此词）。配置后点"发送测试"验证。

每个渠道如何获取 Key/Webhook、每项该填什么，见 **[通知渠道配置指南](docs/notifications.md)**。

**其他深澜高校（通用工具）**：本项目协议为标准深澜（Srun）实现，适用于所有 srun 高校。引导向导内置**学校识别页**（三层漏斗）：

1. **零输入自动识别**——连上未认证的校园网后打开向导，自动捕获 captive portal 重定向拿到门户地址 + ac_id，直接下一步（约 80% 深澜学校无需任何配置）
2. **预设选择**——社区共建的 [portals.json](zju_autologin/portals.json) 高校列表（欢迎为你的学校提 PR 一行）
3. **手动粘贴**——浏览器登录页网址贴入，一键探测（解析 ac_id + 实测 challenge + **验证码预检**）

探测成功即提示接入就绪；贵校若开启登录验证码会明确告知。首次登录后自动回读运营商后缀（@cmcc 等下次免填）。完整协议规范见 **[docs/srun-protocol.md](docs/srun-protocol.md)**（任何语言可据此实现）。

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

## 支持与贡献

> 💬 建议仓库主人到 Settings → General → Features 开启 **Discussions**（使用问答与学校适配讨论），让 issue 区专注 bug 与 PR。

如果这个工具帮到了你，欢迎点一个 ⭐ Star——是对作者最大的鼓励，也能让更多需要的同学看到：

[![Star History Chart](https://api.star-history.com/svg?repos=Xinzhe99/zju-autologin&type=Date)](https://star-history.com/#Xinzhe99/zju-autologin&Date)

- 🐛 遇到问题欢迎提 [Issue](https://github.com/Xinzhe99/zju-autologin/issues)，「复制诊断」的内容附上能更快定位
- 💡 有功能建议或想法，欢迎开 Issue 讨论
- 🔧 欢迎提交 PR：开发环境搭建、测试要求与新增翻译语言的步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)

## 免责声明

本项目仅供浙江大学师生便利性使用，认证协议的实现来源于公开可访问的门户前端代码。请遵守学校《网络安全管理办法》相关规定，勿用于破坏认证体系或他人账号的用途。校徽版权归浙江大学所有，此处仅作标识用途。

## License

[MIT](LICENSE)
