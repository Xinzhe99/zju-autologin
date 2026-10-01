<!-- 感谢贡献！先过一遍清单： -->

- [ ] `python -m pytest tests/ -q` 全绿
- [ ] `python -m ruff check zju_autologin --select F,E9` 通过
- [ ] 涉及 UI：附离屏截图（`tools/render_ui.py`）
- [ ] 涉及新文案：zh-CN 与 en-US 词典同改（`tests/test_i18n.py` 会校验键一致性）
- [ ] 涉及协议：先跑 `tools/cross_check_js.py` 确认与门户 JS 逐字节一致
- [ ] 改动描述写明动机（是什么/为什么，而非罗列文件）

**改动说明**：
