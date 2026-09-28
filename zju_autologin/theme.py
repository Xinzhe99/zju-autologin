"""应用 QSS 主题：浙大蓝配色 + 卡片式布局。"""

QSS = """
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
    image: url(none);
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
"""
