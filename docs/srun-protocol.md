# 深澜（Srun）门户认证协议规范

> 本文档来自 ZJU-AutoLogin 项目对深澜门户前端的逆向分析，供任何校园的开发者复用。
> 不依赖本项目代码，任何语言均可按此实现。协议有变体时欢迎 PR 更新。

## 概述

深澜（Srun）是国内部署最广的校园网 Web 认证系统之一。认证流程为四次 HTTP GET（JSONP 风格）：

```
客户端                         门户
  │ 1. get_challenge ───────────▶  返回一次性 token
  │ 2. 本地构造加密参数
  │ 3. srun_portal?action=login ─▶  返回认证结果
  │ 4. rad_user_info ───────────▶  查询在线状态（周期性）
```

## 1. 获取挑战值

```
GET /cgi-bin/get_challenge?callback=<cb>&username={学号}&ip={本机IP}
→ <cb>({"challenge":"<64位hex>","error":"ok","expire":"60",...})
```

- `challenge` 即 token，60 秒有效，仅供一次登录使用
- `ip` 建议用门户识别的 IP（从登录页 HTML 的 `CONFIG.ip` 解析最可靠）

## 2. 构造加密参数

| 参数 | 算法 |
| --- | --- |
| `hmd5` | `HMAC-MD5(key=challenge, msg=密码)` |
| `info` | `"{SRBX1}" + CustomBase64(XXTEA(json, challenge))` |
| `chksum` | `SHA1(T+username ‖ T+hmd5 ‖ T+acid ‖ T+ip ‖ T+"200" ‖ T+"1" ‖ T+info)`（T=challenge） |

固定常量：`n=200`、`type=1`、`double_stack=0`（双栈部署另论）。

`json` 为紧凑序列化（键序不可变）：

```json
{"username":"...","password":"...","ip":"...","acid":"80","enc_ver":"srun_bx1"}
```

**CustomBase64**：标准 Base64 算法 + `=` 填充，但字母表替换为：

```
LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA
```

**XXTEA**：标准 XXTEA（delta=0x9E3779B9），要点：
- 输入按 **UTF-16 码元**小端打包为 32 位字（JS `charCodeAt` 语义；纯 ASCII 时等同字节）
- 末尾追加明文长度（码元数）
- JS 实现的 `for(p=0;p<n;p++)` 循环结束后 `p==n`，最后一轮的 `k[p&3^e]` 必须用 `n` 而非 `n-1`（常见转写错误）
- 密钥为 challenge 字符串按同法打包，不足 4 字补零

## 3. 发起认证

```
GET /cgi-bin/srun_portal?callback=<cb>&action=login
    &username={学号}&password={MD5}+{hmd5}
    &os=Windows NT&name=Windows&double_stack=0
    &chksum={chksum}&info={info}&ac_id={acid}&ip={本机IP}&n=200&type=1
```

响应语义：

| 返回 | 含义 |
| --- | --- |
| `{"error":"ok"}` | 成功 |
| `{"error":"ok","suc_msg":"ip_already_online_error"}` | 本机已在线（幂等） |
| `sign_error` | chksum 构造错误 |
| `auth_info_error` | info 解密失败（XXTEA/编码有误） |
| `password_error` / `E1002` | 凭据错误 |
| `E2620` | 在线设备数超限 |

## 4. 在线状态查询

```
GET /cgi-bin/rad_user_info            → 纯文本: "not_online_error" 或逗号分隔字段
GET /cgi-bin/rad_user_info?callback=x → JSON 富形态(含套餐/流量/账号)
```

纯文本字段序（0 起）：0=学号，1=上线时间戳，8=本机 IP。**务必做形状校验**——任意含 ≥10 个逗号的页面会被误判为在线。

## 5. 设备管理（部分部署启用）

```
GET /v1/srun_portal_online?user_name={学号}&password=md5(密码)   → 在线设备列表
GET /cgi-bin/rad_user_dm?ip={目标}&username={学号}&time={unix秒}&unbind=1
    &sign=sha1(time+username+ip+unbind+time)                    → 踢指定设备下线
```

## 6. 校园差异清单（接入新学校时核对）

- `ac_id`：登录页 URL 的 `ac_id` 参数（各校不同；首页可能是跳转壳，需跟到 `srun_portal_pc` 页解析）
- 门户域名与协议（HTTPS 可能被代理干扰，准备 HTTP 回退）
- 运营商后缀（如 `@cmcc`）拼在用户名后
- `double_stack`（IPv4/IPv6 双栈部署）
- 设备管理接口是否启用
- 无感知认证周期（ZJU 为 14 天强制重登）

## 参考实现

- Python（零依赖）：[zju_autologin/srun.py](../zju_autologin/srun.py)
- 与门户原版 JS 的逐字节交叉验证工具：[tools/cross_check_js.py](../tools/cross_check_js.py)
