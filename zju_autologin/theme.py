"""应用 QSS 主题：浙大蓝配色 + 卡片式布局，支持浅色/深色/跟随系统。"""

from __future__ import annotations

import sys

_LIGHT = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
    color: #1c2b41;
}
QMainWindow, QDialog {
    background: #e9eef6;
}
QFrame#card {
    background: #ffffff;
    border: 1px solid #e2e8f2;
    border-radius: 12px;
}
QFrame#header {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #0b377a, stop:1 #1263b8);
    border-radius: 12px;
}
QLabel {
    background: transparent;
}
QLabel#headerHint {
    color: rgba(255, 255, 255, 200);
    font-size: 12px;
}
QLabel#statusText {
    font-size: 22px;
    font-weight: 600;
    color: #10233d;
}
QLabel#statusDetail {
    color: #5c6f8a;
    font-size: 12px;
}
QLabel#fieldKey {
    color: #7a8aa2;
    font-size: 12px;
}
QLabel#fieldValue {
    color: #16273f;
    font-weight: 500;
}
QLabel#cardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #10233d;
}
QPushButton {
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 500;
}
QPushButton#primary {
    background-color: #0e4192;
    color: #ffffff;
    border: none;
}
QPushButton#primary:hover {
    background-color: #1552b3;
}
QPushButton#primary:pressed {
    background-color: #0a3374;
}
QPushButton#primary:disabled {
    background-color: #9db4d4;
}
QPushButton#secondary {
    background-color: #ffffff;
    color: #24456e;
    border: 1px solid #c6d2e4;
}
QPushButton#secondary:hover {
    background-color: #f1f6fd;
    border-color: #9db9dd;
}
QToolButton#eye {
    border: none;
    background: transparent;
    color: #5c6f8a;
    padding: 4px 6px;
    font-size: 14px;
}
QToolButton#eye:hover {
    color: #0e4192;
}
QLineEdit, QSpinBox, QComboBox {
    background: #f7f9fc;
    border: 1px solid #cfd9e8;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: #0e4192;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    background: #ffffff;
    border: 1px solid #0e4192;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    border: none;
    background: transparent;
}
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #b8c6dc;
    border-radius: 5px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #0e4192;
    border-color: #0e4192;
}
QPlainTextEdit#log {
    background: #0d1b2e;
    color: #a8c7f0;
    border: none;
    border-radius: 10px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    padding: 8px;
}
QMenu {
    background: #ffffff;
    border: 1px solid #d8e0ee;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #eaf1fb;
    color: #0e4192;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #35507a;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background: #10233d;
    color: #ffffff;
    border: none;
    padding: 6px 8px;
    border-radius: 6px;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #d8e0ee;
    border-radius: 8px;
    gridline-color: #e2e8f2;
}
QHeaderView::section {
    background: #eef2f9;
    color: #24456e;
    border: none;
    padding: 6px;
}
"""

_DARK = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
    color: #dbe6f5;
}
QMainWindow, QDialog {
    background: #10161f;
}
QFrame#card {
    background: #1a2330;
    border: 1px solid #273344;
    border-radius: 12px;
}
QFrame#header {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #0a2c60, stop:1 #104a8c);
    border-radius: 12px;
}
QLabel {
    background: transparent;
}
QLabel#headerHint {
    color: rgba(255, 255, 255, 190);
    font-size: 12px;
}
QLabel#statusText {
    font-size: 22px;
    font-weight: 600;
    color: #eaf2fd;
}
QLabel#statusDetail {
    color: #8ba1bd;
    font-size: 12px;
}
QLabel#fieldKey {
    color: #7e93af;
    font-size: 12px;
}
QLabel#fieldValue {
    color: #dbe6f5;
    font-weight: 500;
}
QLabel#cardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #eaf2fd;
}
QPushButton {
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 500;
}
QPushButton#primary {
    background-color: #1a5ec4;
    color: #ffffff;
    border: none;
}
QPushButton#primary:hover {
    background-color: #2470dd;
}
QPushButton#primary:pressed {
    background-color: #14479c;
}
QPushButton#primary:disabled {
    background-color: #31517c;
}
QPushButton#secondary {
    background-color: #1f2b3c;
    color: #b9cde8;
    border: 1px solid #33445c;
}
QPushButton#secondary:hover {
    background-color: #26364b;
    border-color: #4d6a90;
}
QToolButton#eye {
    border: none;
    background: transparent;
    color: #8ba1bd;
    padding: 4px 6px;
    font-size: 14px;
}
QToolButton#eye:hover {
    color: #6db2ff;
}
QLineEdit, QSpinBox, QComboBox {
    background: #161f2c;
    border: 1px solid #33445c;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: #1a5ec4;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    background: #1c2836;
    border: 1px solid #1a5ec4;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    border: none;
    background: transparent;
}
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #46586f;
    border-radius: 5px;
    background: #1a2330;
}
QCheckBox::indicator:checked {
    background: #1a5ec4;
    border-color: #1a5ec4;
}
QPlainTextEdit#log {
    background: #0b111a;
    color: #8fb8ea;
    border: none;
    border-radius: 10px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    padding: 8px;
}
QMenu {
    background: #1a2330;
    border: 1px solid #33445c;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #223449;
    color: #6db2ff;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3f5878;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background: #223449;
    color: #eaf2fd;
    border: none;
    padding: 6px 8px;
    border-radius: 6px;
}
QTableWidget {
    background: #1a2330;
    border: 1px solid #33445c;
    border-radius: 8px;
    gridline-color: #273344;
}
QHeaderView::section {
    background: #223449;
    color: #b9cde8;
    border: none;
    padding: 6px;
}
"""


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


def get_qss(mode: str = "auto") -> str:
    """按 mode（auto/light/dark）返回样式表。"""
    dark = system_prefers_dark() if mode == "auto" else mode == "dark"
    return _DARK if dark else _LIGHT
