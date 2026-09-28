"""无界面的命令行模式（薄壳，实现见 zju_autologin.cli）。

用法：
    python cli.py check                      查询当前在线状态
    python cli.py login                      立即登录一次
    python cli.py watch [秒] [--config 路径]  常驻守护
"""

import sys

from zju_autologin.cli import main

if __name__ == "__main__":
    sys.exit(main())
