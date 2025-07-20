import requests
from typing import Dict
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QCheckBox, QSpinBox, QComboBox, QMessageBox
)


class ProxyConfigWidget(QWidget):
    """代理配置组件"""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 代理启用
        self.proxy_enabled = QCheckBox("启用代理")
        layout.addWidget(self.proxy_enabled)

        # 代理配置组
        proxy_group = QGroupBox("代理设置")
        proxy_layout = QVBoxLayout()

        # 代理类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("代理类型:"))
        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["HTTP", "HTTPS", "SOCKS5"])
        type_layout.addWidget(self.proxy_type)
        type_layout.addStretch()
        proxy_layout.addLayout(type_layout)

        # 代理地址
        addr_layout = QHBoxLayout()
        addr_layout.addWidget(QLabel("代理地址:"))
        self.proxy_host = QLineEdit()
        self.proxy_host.setPlaceholderText("127.0.0.1")
        addr_layout.addWidget(self.proxy_host)
        addr_layout.addWidget(QLabel("端口:"))
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(7890)
        addr_layout.addWidget(self.proxy_port)
        proxy_layout.addLayout(addr_layout)

        # 认证
        auth_layout = QHBoxLayout()
        self.auth_enabled = QCheckBox("需要认证")
        auth_layout.addWidget(self.auth_enabled)
        auth_layout.addStretch()
        proxy_layout.addLayout(auth_layout)

        user_layout = QHBoxLayout()
        user_layout.addWidget(QLabel("用户名:"))
        self.username = QLineEdit()
        user_layout.addWidget(self.username)
        user_layout.addWidget(QLabel("密码:"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        user_layout.addWidget(self.password)
        proxy_layout.addLayout(user_layout)

        # 测试按钮
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.test_proxy)
        proxy_layout.addWidget(self.test_btn)

        proxy_group.setLayout(proxy_layout)
        layout.addWidget(proxy_group)

        # 启用状态控制
        self.proxy_enabled.toggled.connect(proxy_group.setEnabled)
        proxy_group.setEnabled(False)

        layout.addStretch()
        self.setLayout(layout)

    def test_proxy(self):
        try:
            proxy_url = self.get_proxy_url()
            if proxy_url:
                proxies = {'http': proxy_url, 'https': proxy_url}
                response = requests.get('https://httpbin.org/ip',
                                        proxies=proxies, timeout=10)
                if response.status_code == 200:
                    QMessageBox.information(self, "测试结果", "代理连接成功！")
                else:
                    QMessageBox.warning(self, "测试结果", "代理连接失败！")
            else:
                QMessageBox.warning(self, "测试结果", "请配置代理地址！")
        except Exception as e:
            QMessageBox.critical(self, "测试结果", f"代理测试失败: {str(e)}")

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

    def get_config(self) -> Dict:
        return {
            'enabled': self.proxy_enabled.isChecked(),
            'proxy_host': self.proxy_host.text().strip(),
            'proxy_port': self.proxy_port.value(),
            'url': self.get_proxy_url(),
        }