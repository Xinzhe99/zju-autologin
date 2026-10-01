# 安全政策

## 支持版本

| 版本 | 状态 |
| --- | --- |
| 最新 Release | ✅ 支持 |
| 更早版本 | ❌ 请先升级再报告 |

## 报告漏洞

**请勿通过公开 Issue 报告安全漏洞。**

通过 GitHub [Security Advisories](https://github.com/Xinzhe99/zju-autologin/security/advisories/new) 私密报告（"Report a vulnerability"），或联系仓库所有者。会在 72 小时内确认收到，修复后公开致谢（除非你要求匿名）。

## 本工具的安全设计（供审计参考）

### 凭据存储

- 密码优先存入**系统凭据管理器**（Windows Credential Locker / macOS Keychain），不出现在任何文件中
- keyring 不可用时退化为 base64 混淆存于配置文件（界面明示），权限收紧
- Linux systemd 服务凭据 `/etc/zju-autologin/config.json`（root:600）；Windows ProgramData 同级 ACL
- 凭据**永不**写入日志、诊断输出、导出文件（导出明确排除密钥字段）

### 网络传输

- 带凭据的认证请求**强制 https**（策略链中带密码的端点跳过 http 降级）
- DNS 故障兜底的 IP 直连场景降级为"加密不验身份"，代码中有明确注释权衡
- 更新包下载后强制 **SHA256 校验**（GitHub 官方 digest），不匹配即删除拒绝执行

### 提权操作

- Windows UAC / macOS osascript / Linux pkexec 三平台的提权脚本均在临时文件执行，随机文件名降低 TOCTOU 面
- 移除路由等操作对配置中的 IP 参数做 `ipaddress` 强校验，防注入
- 脚本内容不含任何凭据

### 潜在攻击面（诚实披露）

- base64 混淆**不是加密**——同机同用户的进程可还原。需要更强保护请确保 keyring 可用
- 心跳 URL / 推送 Webhook 由用户配置，若填入恶意地址，工具会向其发送状态信息（不含密码）；错误信息输出前剥离完整 URL
- Web 配置页仅绑定 127.0.0.1，但本机任意进程可访问；不要在不可信环境使用 `serve`
