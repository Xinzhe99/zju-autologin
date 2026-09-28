# 贡献指南 / Contributing

感谢关注本项目！以下是开发环境的搭建方式和一些约定。

## 开发环境

```bash
git clone https://github.com/Xinzhe99/zju-autologin.git
cd zju-autologin
pip install -r requirements.txt pytest
python main.py          # GUI
python cli.py check     # CLI 验证
python -m pytest tests/ -q   # 测试
```

要求 Python ≥ 3.10。UI 为 PyQt6；协议实现不依赖 Qt，可在无界面环境运行。

## 项目结构

- `zju_autologin/srun.py` — 深澜 Srun 门户协议（challenge / login / 状态 / 设备管理），逆向自门户前端 JS
- `zju_autologin/monitor.py` — 后台监控线程（检测 / 自动重登 / 推送 / 心跳 / 事件记录）
- `zju_autologin/ui.py` + `wizard.py` — PyQt6 界面与首次引导
- `zju_autologin/i18n/` — 翻译文件（zh-CN / en-US）

## 添加新语言

1. 复制 `zju_autologin/i18n/en-US.json` 为 `{lang}.json`（如 `ja-JP.json`）
2. 翻译全部 value（**保留 `{placeholder}` 占位符**）
3. 在 `zju_autologin/i18n.py` 的 `SUPPORTED_LANGS` / `LANG_LABELS` 中注册
4. 在 `zju_autologin/ui.py` 的语言下拉框和 `_provider_label` 等处补充映射
5. 运行 `python -m pytest tests/test_i18n.py -q` 确保键集合与占位符一致

## 测试

- `tests/test_srun_crypto.py` 的加密基准向量由 QJSEngine 执行门户原版 JS 生成（`tools/cross_check_js.py`），修改加密实现前请先跑一遍确认
- 提交前请确保 `python -m pytest tests/ -q` 全绿

## 发布流程

1. 修改 `zju_autologin/__init__.py` 中的 `__version__`
2. 提交并打 tag：`git tag vX.Y.Z && git push origin vX.Y.Z`
3. GitHub Actions 会自动构建 Windows（exe + Inno Setup 安装包）与 macOS（dmg + zip）并创建 Release

## 协议参考

深澜 Srun 门户的认证细节（XXTEA + 自定义 base64 + HMAC-MD5 + SHA1 校验链）记录在 [README.md](README.md) 的"校园网认证机制解析"一节。请勿利用本项目做超出校园网自助认证范围的事情。
