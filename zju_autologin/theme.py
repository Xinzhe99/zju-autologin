"""应用 QSS 主题：Codex 风格设计语言（近黑白灰、细边框、扁平克制），浅/深双主题。

- 控件箭头/勾选使用自绘图标（resources/icon_*.png），与整体风格一致
- 主按钮：浅色主题黑底白字，深色主题白底黑字（OpenAI 风格）
- 通过 __ICON_DIR__ 占位符在运行时注入图标目录
"""

from __future__ import annotations

import os
import sys


def _icon_dir() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, "resources")
    return path.replace("\\", "/")


def system_prefers_dark() -> bool:
    """探测系统是否为深色模式（Windows 注册表 / Qt styleHints）。"""
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            scheme = app.styleHints().colorScheme()
            if scheme is not None:
                return scheme.name().endswith("Dark")
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return val == 0
        except (OSError, ImportError):
            pass
    return False


_LIGHT = """
* {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: #0d0d0d;
}
QMainWindow {
    background: #ffffff;
}
QDialog {
    background: #f9f9f9;
}
QFrame#sidebar {
    background: #f7f7f8;
    border: none;
    border-right: 1px solid #ececec;
}
QLabel#sidebarTitle { font-size: 13px; font-weight: 600; color: #0d0d0d; }
QLabel#sidebarSub { font-size: 10px; color: #8f8f8f; }
QLabel#sidebarHint { font-size: 11px; color: #9a9a9a; }
QPushButton#nav {
    text-align: left;
    border: none;
    border-radius: 8px;
    padding: 9px 12px;
    color: #4b4b4b;
    background: transparent;
    font-size: 13px;
}
QPushButton#nav:hover { background: #efefef; color: #0d0d0d; }
QPushButton#nav:checked { background: #e9e9e9; color: #0d0d0d; font-weight: 600; }
QFrame#segHost { background: #f1f1f3; border-radius: 9px; }
QPushButton#seg {
    border: 1px solid transparent;
    background: transparent;
    padding: 5px 14px;
    border-radius: 7px;
    color: #6b6b6b;
    font-size: 12px;
}
QPushButton#seg:checked {
    background: #ffffff;
    color: #0d0d0d;
    border-color: #e0e0e0;
    font-weight: 500;
}
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#card {
    background: #ffffff;
    border: 1px solid #e4e4e4;
    border-radius: 10px;
}
QLabel { background: transparent; }
QLabel#statusText { font-size: 20px; font-weight: 600; color: #0d0d0d; }
QLabel#statusDetail { color: #757575; font-size: 12px; }
QLabel#fieldKey { color: #8f8f8f; font-size: 12px; }
QLabel#fieldValue { color: #0d0d0d; font-weight: 500; }
QLabel#cardTitle { font-size: 13px; font-weight: 600; color: #0d0d0d; }

QPushButton {
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
    font-size: 12.5px;
}
QPushButton#primary {
    background-color: #0d0d0d;
    color: #ffffff;
    border: 1px solid #0d0d0d;
}
QPushButton#primary:hover { background-color: #2b2b2b; }
QPushButton#primary:pressed { background-color: #000000; }
QPushButton#primary:disabled { background-color: #c9c9c9; border-color: #c9c9c9; }
QPushButton#secondary {
    background-color: #ffffff;
    color: #0d0d0d;
    border: 1px solid #d9d9d9;
}
QPushButton#secondary:hover { background-color: #f2f2f2; }
QPushButton#secondary:pressed { background-color: #e8e8e8; }

QToolButton#eye {
    border: none;
    background: transparent;
    padding: 4px 6px;
}

QLineEdit, QSpinBox, QComboBox {
    background: #ffffff;
    border: 1px solid #d9d9d9;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: #0d0d0d;
    selection-color: #ffffff;
}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: #bdbdbd; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #0d0d0d;
    padding: 6.5px 9.5px;
    background: #ffffff;
}
QLineEdit:disabled, QComboBox:disabled { background: #f5f5f5; color: #9a9a9a; }

QComboBox { padding-right: 30px; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url(__ICON_DIR__/icon_chevron.png);
    width: 16px;
    height: 16px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #e4e4e4;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: #f0f0f0;
    selection-color: #0d0d0d;
    outline: none;
}

QSpinBox { padding-right: 10px; }
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }
QSpinBox::up-arrow, QSpinBox::down-arrow { image: none; width: 0; height: 0; }

QCheckBox { spacing: 7px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #c9c9c9;
    border-radius: 5px;
    background: #ffffff;
}
QCheckBox::indicator:hover { border-color: #8f8f8f; }
QCheckBox::indicator:checked {
    background: #0d0d0d;
    border-color: #0d0d0d;
    image: url(__ICON_DIR__/icon_check.png);
}

QPlainTextEdit#log {
    background: #1f1f1f;
    color: #d6d6d6;
    border: 1px solid #e4e4e4;
    border-radius: 8px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    padding: 8px;
}
QMenu {
    background: #ffffff;
    border: 1px solid #e4e4e4;
    border-radius: 10px;
    padding: 5px;
}
QMenu::item { padding: 7px 22px; border-radius: 7px; }
QMenu::item:selected { background: #f0f0f0; color: #0d0d0d; }
QMenu::separator { height: 1px; background: #ececec; margin: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #d4d4d4; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #bdbdbd; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QToolTip {
    background: #0d0d0d;
    color: #ffffff;
    border: none;
    padding: 6px 9px;
    border-radius: 6px;
    font-size: 12px;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #e4e4e4;
    border-radius: 8px;
    gridline-color: #efefef;
}
QHeaderView::section {
    background: #fafafa;
    color: #757575;
    border: none;
    border-bottom: 1px solid #e4e4e4;
    padding: 7px;
    font-size: 12px;
}
"""

_DARK = """
* {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: #ececec;
}
QMainWindow {
    background: #141414;
}
QDialog {
    background: #191919;
}
QFrame#sidebar {
    background: #191919;
    border: none;
    border-right: 1px solid #282828;
}
QLabel#sidebarTitle { font-size: 13px; font-weight: 600; color: #ececec; }
QLabel#sidebarSub { font-size: 10px; color: #8d8d8d; }
QLabel#sidebarHint { font-size: 11px; color: #8d8d8d; }
QPushButton#nav {
    text-align: left;
    border: none;
    border-radius: 8px;
    padding: 9px 12px;
    color: #a8a8a8;
    background: transparent;
    font-size: 13px;
}
QPushButton#nav:hover { background: #242424; color: #ffffff; }
QPushButton#nav:checked { background: #2c2c2c; color: #ffffff; font-weight: 600; }
QFrame#segHost { background: #242424; border-radius: 9px; }
QPushButton#seg {
    border: 1px solid transparent;
    background: transparent;
    padding: 5px 14px;
    border-radius: 7px;
    color: #9b9b9b;
    font-size: 12px;
}
QPushButton#seg:checked {
    background: #3a3a3a;
    color: #ffffff;
    border-color: #4a4a4a;
    font-weight: 500;
}
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#card {
    background: #1f1f1f;
    border: 1px solid #2c2c2c;
    border-radius: 10px;
}
QLabel { background: transparent; }
QLabel#statusText { font-size: 20px; font-weight: 600; color: #f2f2f2; }
QLabel#statusDetail { color: #9b9b9b; font-size: 12px; }
QLabel#fieldKey { color: #8d8d8d; font-size: 12px; }
QLabel#fieldValue { color: #ececec; font-weight: 500; }
QLabel#cardTitle { font-size: 13px; font-weight: 600; color: #f2f2f2; }

QPushButton {
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
    font-size: 12.5px;
}
QPushButton#primary {
    background-color: #f2f2f2;
    color: #0d0d0d;
    border: 1px solid #f2f2f2;
}
QPushButton#primary:hover { background-color: #d9d9d9; }
QPushButton#primary:pressed { background-color: #c4c4c4; }
QPushButton#primary:disabled { background-color: #3d3d3d; border-color: #3d3d3d; color: #7a7a7a; }
QPushButton#secondary {
    background-color: transparent;
    color: #ececec;
    border: 1px solid #3a3a3a;
}
QPushButton#secondary:hover { background-color: #262626; }
QPushButton#secondary:pressed { background-color: #303030; }

QToolButton#eye {
    border: none;
    background: transparent;
    padding: 4px 6px;
}

QLineEdit, QSpinBox, QComboBox {
    background: #191919;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: #f2f2f2;
    selection-color: #0d0d0d;
}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: #5a5a5a; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #f2f2f2;
    padding: 6.5px 9.5px;
    background: #1c1c1c;
}
QLineEdit:disabled, QComboBox:disabled { background: #1a1a1a; color: #6a6a6a; }

QComboBox { padding-right: 30px; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url(__ICON_DIR__/icon_chevron_dark.png);
    width: 16px;
    height: 16px;
}
QComboBox QAbstractItemView {
    background: #1f1f1f;
    border: 1px solid #333333;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: #303030;
    selection-color: #ffffff;
    outline: none;
}

QSpinBox { padding-right: 10px; }
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }
QSpinBox::up-arrow, QSpinBox::down-arrow { image: none; width: 0; height: 0; }

QCheckBox { spacing: 7px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4d4d4d;
    border-radius: 5px;
    background: #191919;
}
QCheckBox::indicator:hover { border-color: #8d8d8d; }
QCheckBox::indicator:checked {
    background: #f2f2f2;
    border-color: #f2f2f2;
    image: url(__ICON_DIR__/icon_check_dark.png);
}

QPlainTextEdit#log {
    background: #0c0c0c;
    color: #b8b8b8;
    border: 1px solid #2c2c2c;
    border-radius: 8px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    padding: 8px;
}
QMenu {
    background: #1f1f1f;
    border: 1px solid #333333;
    border-radius: 10px;
    padding: 5px;
}
QMenu::item { padding: 7px 22px; border-radius: 7px; }
QMenu::item:selected { background: #2e2e2e; color: #ffffff; }
QMenu::separator { height: 1px; background: #2c2c2c; margin: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #3d3d3d; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #4d4d4d; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QToolTip {
    background: #2e2e2e;
    color: #f2f2f2;
    border: none;
    padding: 6px 9px;
    border-radius: 6px;
    font-size: 12px;
}
QTableWidget {
    background: #1f1f1f;
    border: 1px solid #2c2c2c;
    border-radius: 8px;
    gridline-color: #2a2a2a;
}
QHeaderView::section {
    background: #191919;
    color: #9b9b9b;
    border: none;
    border-bottom: 1px solid #2c2c2c;
    padding: 7px;
    font-size: 12px;
}
"""


def get_qss(mode: str = "auto") -> str:
    """按 mode（auto/light/dark）返回样式表，并注入图标目录。"""
    dark = system_prefers_dark() if mode == "auto" else mode == "dark"
    qss = _DARK if dark else _LIGHT
    return qss.replace("__ICON_DIR__", _icon_dir())
