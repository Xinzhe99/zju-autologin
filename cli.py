"""无界面的命令行模式（薄壳，实现见 zju_autologin.cli）。

用法：
    python cli.py check                      查询当前在线状态
    python cli.py login                      立即登录一次
    python cli.py watch [秒] [--config 路径]  常驻守护
    sudo python cli.py enable -u 学号 -p 密码  Linux: 一行启用系统级保活
    sudo python cli.py disable                停用并卸载系统服务
    python cli.py status                     服务与网络状态
"""

import sys

from zju_autologin.cli import main

if __name__ == "__main__":
    sys.exit(main())
