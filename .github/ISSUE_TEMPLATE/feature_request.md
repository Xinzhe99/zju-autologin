name: 💡 功能建议
description: 新功能或改进想法
labels: [enhancement]
body:
  - type: textarea
    id: problem
    attributes:
      label: 要解决什么问题？
      description: 先说场景和痛点，而不是方案——也许有更好的实现
    validations:
      required: true

  - type: textarea
    id: solution
    attributes:
      label: 期望的方案
      description: 你希望它怎么工作？

  - type: dropdown
    id: scope
    attributes:
      label: 影响范围
      options:
        - 保活核心
        - 界面
        - 通知
        - 安装/分发
        - 其他
