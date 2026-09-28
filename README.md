# ZJU-AutoLogin · 浙江大学校园网自动登录

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)](https://www.riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

一个挂在 Windows 桌面托盘的后台小程序：**自动检测浙江大学校园网认证状态，掉线/过期后用保存的学号密码自动重新登录**，保证远程桌面、SSH 等连接不会因为认证过期而失联。

![主界面](docs/screenshot_online.png)

## 为什么需要它

浙江大学校园网（有线 + ZJUWLAN）采用深澜（Srun）Web 门户认证，并有如下机制（来自认证页官方说明）：

> 为了您的账号安全，**无感知认证周期设定为 14 天**，到期后需重新登录。

也就是说：即使勾选了门户的免认证（MacAuth），**每 14 天也必须手动在网页里输入一次学号密码**；此外 IP 变化、无线重连、断电重启等都可能导致认证失效。如果这时人不在电脑旁（例如人在校外用远程桌面连实验室电脑），机器就掉网了——**远程直接失联，只能跑回去重新登录**。

本工具把"重新登录"这件事交给后台：掉线自动重登，远程永不失联。

## 功能

- ✅ **自动保活**：按可配置间隔（默认 60 秒）检测在线状态，掉线自动重登，失败指数退避（60s → 10min）
- ✅ **托盘常驻**：关闭窗口即最小化到托盘，托盘图标实时反映网络状态（绿=在线 / 红=掉线 / 蓝=检测中 / 灰=无校园网）
- ✅ **账号设置**：图形界面填入学号密码，密码默认存入 **Windows 凭据管理器**（不明文落盘）
- ✅ **开机自启**：一键开关（写入 HKCU 注册表，无需管理员权限）
- ✅ **认证失败提醒**：密码错误等不可自动恢复的错误会弹托盘通知，并停止重试避免锁号
- ✅ **CLI 模式**：无界面运行，可配合 Windows 任务计划或 SSH 使用
- ✅ **在线状态面板**：认证账号、本机 IP、上线时间一目了然

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

## 安装使用

### 方式一：直接运行（需要 Python ≥ 3.10）

```bash
pip install -r requirements.txt
python main.py          # 打开主窗口
pythonw main.py --minimized   # 静默启动到托盘（开机自启即用此方式）
```

### 方式二：打包为 exe（免 Python 环境）

```bash
pip install pyinstaller
build_exe.bat           # 产物: dist/ZJUAutoLogin.exe
```

### 命令行模式

```bash
python cli.py check     # 查询当前在线状态
python cli.py login     # 立即登录一次
python cli.py watch 30  # 常驻守护（每 30 秒检测，可配合任务计划）
```

## 配置与密码存储

- 配置文件：`%APPDATA%\ZJUAutoLogin\config.json`（账号、间隔、开关等）
- 密码：优先写入 **Windows 凭据管理器**（凭据名 `ZJUAutoLogin`）；若 keyring 不可用则退化为 base64 混淆存储在配置文件中（界面上会显示实际存储方式）
- 配置文件仅存本机，请勿提交到任何仓库

## 常见问题

**Q: 会不会把我的账号顶下线？**
不会。登录请求只针对本机当前 IP。本机已在线时服务器返回"IP 已在线"，不会影响现有会话。

**Q: 在校外能用吗？**
门户 `net.zju.edu.cn` 仅校园网内可达。在校外时程序显示"无校园网连接"并持续等待，回校后自动恢复。

**Q: 提示"在线数已达上限"？**
账号同时在在线设备数超限（或本机 IP 已被其他方式登录）。请到自助服务 [myvpn.zju.edu.cn](https://myvpn.zju.edu.cn) 下线其他设备。

**Q: 密码改了怎么办？**
在设置里重新输入密码保存即可，程序会自动清除错误锁存并重试。

## 项目结构

```
zju-autologin/
├── main.py                    # GUI 入口
├── cli.py                     # 命令行入口（check / login / watch）
├── zju_autologin/
│   ├── srun.py                # 深澜 Srun 协议实现（get_challenge / srun_portal / rad_user_info）
│   ├── monitor.py             # 后台监控线程（定时检测 + 自动重登 + 退避）
│   ├── config.py              # 配置持久化 + Windows 凭据管理器
│   ├── autostart.py           # 开机自启（注册表 HKCU\...\Run）
│   ├── ui.py                  # PyQt6 主窗口 + 托盘
│   └── theme.py               # 浙大蓝 QSS 主题
├── resources/                 # 校徽 logo、图标
├── tools/                     # 开发工具（资源生成、JS 交叉验证、UI 截图）
└── build_exe.bat              # PyInstaller 打包脚本
```

## 开发说明

- `tools/cross_check_js.py`：用 QJSEngine 执行门户原版加密 JS，与 Python 实现逐字节对比（防止逆向转写出错）
- `tools/render_ui.py`：离屏渲染 UI 截图，用于自检与文档
- `tools/generate_assets.py`：从门户原始 logo 生成各尺寸图标

## 免责声明

本项目仅供浙江大学师生便利性使用，认证协议的实现来源于公开可访问的门户前端代码。请遵守学校《网络安全管理办法》相关规定，勿用于破坏认证体系或他人账号的用途。校徽版权归浙江大学所有，此处仅作标识用途。

## License

[MIT](LICENSE)
