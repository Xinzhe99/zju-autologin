name: 🐛 Bug 报告
description: 功能异常 / 崩溃 / 行为不符合预期
labels: [bug]
body:
  - type: markdown
    attributes:
      value: |
        感谢反馈！**先试「一键诊断」**：主界面 → 网络诊断 按钮，或命令行 `zju-autologin diagnose`——它经常直接告诉你原因。

  - type: textarea
    id: what-happened
    attributes:
      label: 问题描述
      description: 发生了什么？预期是什么？
    validations:
      required: true

  - type: textarea
    id: diagnostics
    attributes:
      label: 诊断输出（重要）
      description: |
        主界面 → 日志 → 「复制诊断」，把内容粘贴到这里（账号已自动打码）。
        没有图形界面时：`zju-autologin diagnose > diag.txt` 附上文件。
        **没有诊断输出的报告很难定位，大概率被退回。**
    validations:
      required: true

  - type: input
    id: version
    attributes:
      label: 版本
      description: 关于对话框或 `zju-autologin version`，如 1.24.1
    validations:
      required: true

  - type: dropdown
    id: os
    attributes:
      label: 操作系统
      options:
        - Windows
        - macOS
        - Linux 桌面
        - Linux 服务器 / 树莓派
        - OpenWrt / 路由器
    validations:
      required: true

  - type: input
    id: school
    attributes:
      label: 学校（非浙大请注明）
      placeholder: 浙江大学

  - type: textarea
    id: logs
    attributes:
      label: 补充日志（可选）
      description: "%APPDATA%\\ZJUAutoLogin\\app.log（Windows）或 journalctl -u zju-autologin（Linux）的相关片段"
