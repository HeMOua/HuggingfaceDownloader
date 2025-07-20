import os
import requests
import re
from urllib.parse import urlparse
from typing import Dict
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QCheckBox, QSpinBox, QComboBox, QMessageBox
)


def is_well_formed_proxy_url(url: str) -> bool:
    """
    仅判断代理 URL 格式是否合理，不判断是否能连接。
    示例格式:
        - http://host:port
        - http://user:pass@host:port
        - socks5://host:port
    """
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https", "socks5"}:
        return False

    if not parsed.hostname or not parsed.port:
        return False

    # 额外可选：校验主机名和端口范围
    hostname_pattern = re.compile(
        r"^([a-zA-Z0-9.-]+|\d{1,3}(\.\d{1,3}){3})$"  # 支持域名或 IPv4
    )
    if not hostname_pattern.match(parsed.hostname):
        return False

    if not (0 < parsed.port <= 65535):
        return False

    return True


def is_valid_proxy_url(url: str) -> bool:
    """验证代理 URL 是否可用"""
    try:
        proxies = {'http': url, 'https': url}
        response = requests.get('https://httpbin.org/ip', proxies=proxies, timeout=5)
        return response.status_code == 200
    except Exception:
        return False


class ProxyConfigWidget(QWidget):
    """代理配置组件"""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 启用代理
        self.proxy_enabled = QCheckBox("启用代理")
        self.proxy_enabled.toggled.connect(self.on_proxy_enabled_changed)
        layout.addWidget(self.proxy_enabled)

        # 代理配置组
        self.proxy_group = QGroupBox("代理设置")
        proxy_layout = QVBoxLayout()

        # 代理类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("代理类型:"))
        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["HTTP", "HTTPS", "SOCKS5"])
        self.proxy_type.currentIndexChanged.connect(self.on_proxy_config_changed)
        type_layout.addWidget(self.proxy_type)
        proxy_layout.addLayout(type_layout)

        # 地址和端口
        addr_layout = QHBoxLayout()
        addr_layout.addWidget(QLabel("代理地址:"))
        self.proxy_host = QLineEdit()
        self.proxy_host.setPlaceholderText("127.0.0.1")
        self.proxy_host.textChanged.connect(self.on_proxy_config_changed)
        addr_layout.addWidget(self.proxy_host)
        addr_layout.addWidget(QLabel("端口:"))
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(7890)
        self.proxy_port.valueChanged.connect(self.on_proxy_config_changed)
        addr_layout.addWidget(self.proxy_port)
        proxy_layout.addLayout(addr_layout)

        # 认证
        auth_layout = QHBoxLayout()
        self.auth_enabled = QCheckBox("需要认证")
        self.auth_enabled.toggled.connect(self.on_proxy_config_changed)
        auth_layout.addWidget(self.auth_enabled)
        proxy_layout.addLayout(auth_layout)

        user_layout = QHBoxLayout()
        user_layout.addWidget(QLabel("用户名:"))
        self.username = QLineEdit()
        self.username.textChanged.connect(self.on_proxy_config_changed)
        user_layout.addWidget(self.username)
        user_layout.addWidget(QLabel("密码:"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.textChanged.connect(self.on_proxy_config_changed)
        user_layout.addWidget(self.password)
        proxy_layout.addLayout(user_layout)

        # 测试按钮
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.test_proxy)
        proxy_layout.addWidget(self.test_btn)

        self.proxy_group.setLayout(proxy_layout)
        layout.addWidget(self.proxy_group)
        layout.addStretch()
        self.setLayout(layout)

        # 初始禁用代理设置组
        self.proxy_group.setEnabled(False)

    def on_proxy_enabled_changed(self, enabled: bool):
        self.proxy_group.setEnabled(enabled)
        self.on_proxy_config_changed()  # 立即触发一次检查

    def on_proxy_config_changed(self):
        if not self.proxy_enabled.isChecked():
            self.clear_proxy_env()
            return

        proxy_url = self.get_proxy_url()
        if proxy_url and is_well_formed_proxy_url(proxy_url):
            self.set_proxy_env(proxy_url)
        else:
            self.clear_proxy_env()

    def test_proxy(self):
        proxy_url = self.get_proxy_url()
        if not proxy_url:
            QMessageBox.warning(self, "测试结果", "请填写完整的代理地址")
            return

        if is_valid_proxy_url(proxy_url):
            QMessageBox.information(self, "测试结果", "代理连接成功！")
        else:
            QMessageBox.critical(self, "测试结果", "代理连接失败，请检查配置")

    def get_proxy_url(self) -> str:
        if not self.proxy_enabled.isChecked():
            return ""

        protocol = self.proxy_type.currentText().lower()
        host = self.proxy_host.text().strip()
        port = self.proxy_port.value()

        if not host:
            return ""

        if self.auth_enabled.isChecked():
            username = self.username.text().strip()
            password = self.password.text().strip()
            if username and password:
                return f"{protocol}://{username}:{password}@{host}:{port}"

        return f"{protocol}://{host}:{port}"

    def set_proxy_env(self, proxy_url: str):
        os.environ["http_proxy"] = proxy_url
        os.environ["https_proxy"] = proxy_url

    def clear_proxy_env(self):
        os.environ.pop("http_proxy", None)
        os.environ.pop("https_proxy", None)

    def get_config(self) -> Dict:
        return {
            'enabled': self.proxy_enabled.isChecked(),
            'proxy_host': self.proxy_host.text().strip(),
            'proxy_port': self.proxy_port.value(),
            'url': self.get_proxy_url(),
        }
