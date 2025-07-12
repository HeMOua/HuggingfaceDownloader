import sys
import os
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from urllib.parse import urlparse

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QGroupBox, QCheckBox, QSpinBox, QComboBox, QFileDialog,
    QMessageBox, QSplitter, QFrame, QScrollArea, QListWidget,
    QListWidgetItem, QDialog, QGridLayout
)
from PyQt6.QtCore import (
    QThread, pyqtSignal, QTimer, Qt, QSettings, QSize
)
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPalette, QColor

try:
    from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download
    from huggingface_hub.utils import RepositoryNotFoundError, RevisionNotFoundError
    import requests
except ImportError:
    print("请安装依赖: pip install huggingface_hub requests")
    sys.exit(1)


@dataclass
class DownloadTask:
    repo_id: str
    filename: str
    local_dir: str
    revision: str = "main"
    status: str = "待下载"
    progress: float = 0.0
    size: int = 0
    downloaded: int = 0
    speed: str = "0 B/s"


class DownloadWorker(QThread):
    progress_updated = pyqtSignal(int, float, str, str)  # task_index, progress, speed, status
    task_completed = pyqtSignal(int, bool, str)  # task_index, success, message

    def __init__(self, tasks: List[DownloadTask], proxy_config: Dict):
        super().__init__()
        self.tasks = tasks
        self.proxy_config = proxy_config
        self.is_cancelled = False

    def run(self):
        for i, task in enumerate(self.tasks):
            if self.is_cancelled:
                break

            try:
                self.progress_updated.emit(i, 0, "0 B/s", "下载中")

                # 设置代理
                if self.proxy_config.get('enabled', False):
                    proxy_url = self.proxy_config.get('url', '')
                    if proxy_url:
                        os.environ['HTTP_PROXY'] = proxy_url
                        os.environ['HTTPS_PROXY'] = proxy_url

                # 下载文件
                local_path = hf_hub_download(
                    repo_id=task.repo_id,
                    filename=task.filename,
                    local_dir=task.local_dir,
                    revision=task.revision,
                    resume_download=True
                )

                self.progress_updated.emit(i, 100, "完成", "已完成")
                self.task_completed.emit(i, True, f"下载完成: {local_path}")

            except Exception as e:
                self.progress_updated.emit(i, 0, "错误", "失败")
                self.task_completed.emit(i, False, f"下载失败: {str(e)}")

    def cancel(self):
        self.is_cancelled = True


class ProxyConfigWidget(QWidget):
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

        self.setLayout(layout)

    def test_proxy(self):
        # 测试代理连接
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
            'url': self.get_proxy_url()
        }


class AdvancedFileSelectionDialog(QDialog):
    def __init__(self, files: List[str], parent=None):
        super().__init__(parent)
        self.all_files = files
        self.filtered_files = files.copy()
        self.selected_files = []
        self.current_page = 0
        self.files_per_page = 100  # 默认每页显示100个文件
        self.init_ui()
        self.update_file_list()

    def init_ui(self):
        self.setWindowTitle("选择文件")
        self.setGeometry(200, 200, 800, 600)

        layout = QVBoxLayout()

        # 顶部控制区域
        control_layout = QVBoxLayout()

        # 搜索和过滤区域
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索文件:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入文件名或扩展名进行搜索...")
        self.search_input.textChanged.connect(self.filter_files)
        search_layout.addWidget(self.search_input)

        # 清除搜索按钮
        clear_search_btn = QPushButton("清除")
        clear_search_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(clear_search_btn)

        control_layout.addLayout(search_layout)

        # 文件类型过滤
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("文件类型:"))

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "所有文件", "模型文件 (.bin, .safetensors)", "配置文件 (.json, .yaml)",
            "分词器 (tokenizer)", "权重文件 (.pth, .ckpt)", "其他"
        ])
        self.filter_combo.currentTextChanged.connect(self.filter_files)
        filter_layout.addWidget(self.filter_combo)

        filter_layout.addStretch()

        # 每页显示数量
        filter_layout.addWidget(QLabel("每页显示:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["50", "100", "200", "500", "1000", "全部"])
        self.page_size_combo.setCurrentText("100")
        self.page_size_combo.currentTextChanged.connect(self.change_page_size)
        filter_layout.addWidget(self.page_size_combo)

        control_layout.addLayout(filter_layout)

        # 统计信息
        self.stats_label = QLabel()
        control_layout.addWidget(self.stats_label)

        layout.addLayout(control_layout)

        # 文件列表区域
        list_layout = QVBoxLayout()

        # 批量操作按钮
        batch_layout = QHBoxLayout()

        select_all_btn = QPushButton("全选当前页")
        select_all_btn.clicked.connect(self.select_current_page)
        batch_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("取消当前页")
        deselect_all_btn.clicked.connect(self.deselect_current_page)
        batch_layout.addWidget(deselect_all_btn)

        select_all_filtered_btn = QPushButton("全选搜索结果")
        select_all_filtered_btn.clicked.connect(self.select_all_filtered)
        batch_layout.addWidget(select_all_filtered_btn)

        deselect_all_filtered_btn = QPushButton("取消所有选择")
        deselect_all_filtered_btn.clicked.connect(self.deselect_all_filtered)
        batch_layout.addWidget(deselect_all_filtered_btn)

        batch_layout.addStretch()

        # 已选择文件数量
        self.selected_count_label = QLabel("已选择: 0 个文件")
        batch_layout.addWidget(self.selected_count_label)

        list_layout.addLayout(batch_layout)

        # 文件列表
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        list_layout.addWidget(self.file_list)

        # 分页控制
        page_layout = QHBoxLayout()

        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self.prev_page)
        page_layout.addWidget(self.prev_btn)

        self.page_label = QLabel()
        page_layout.addWidget(self.page_label)

        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self.next_page)
        page_layout.addWidget(self.next_btn)

        page_layout.addStretch()

        # 跳转到页面
        page_layout.addWidget(QLabel("跳转到:"))
        self.page_input = QSpinBox()
        self.page_input.setMinimum(1)
        self.page_input.valueChanged.connect(self.jump_to_page)
        page_layout.addWidget(self.page_input)

        list_layout.addLayout(page_layout)
        layout.addLayout(list_layout)

        # 底部按钮
        button_layout = QHBoxLayout()

        # 预览选中文件
        preview_btn = QPushButton("预览选中文件")
        preview_btn.clicked.connect(self.preview_selected)
        button_layout.addWidget(preview_btn)

        button_layout.addStretch()

        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def filter_files(self):
        """过滤文件"""
        search_text = self.search_input.text().lower()
        file_type = self.filter_combo.currentText()

        self.filtered_files = []

        for file in self.all_files:
            # 搜索过滤
            if search_text and search_text not in file.lower():
                continue

            # 文件类型过滤
            if file_type == "模型文件 (.bin, .safetensors)":
                if not (file.endswith('.bin') or file.endswith('.safetensors')):
                    continue
            elif file_type == "配置文件 (.json, .yaml)":
                if not (file.endswith('.json') or file.endswith('.yaml') or file.endswith('.yml')):
                    continue
            elif file_type == "分词器 (tokenizer)":
                if 'tokenizer' not in file.lower():
                    continue
            elif file_type == "权重文件 (.pth, .ckpt)":
                if not (file.endswith('.pth') or file.endswith('.ckpt')):
                    continue
            elif file_type == "其他":
                common_exts = ['.bin', '.safetensors', '.json', '.yaml', '.yml', '.pth', '.ckpt']
                if any(file.endswith(ext) for ext in common_exts) or 'tokenizer' in file.lower():
                    continue

            self.filtered_files.append(file)

        self.current_page = 0
        self.update_file_list()
        self.update_page_controls()

    def clear_search(self):
        """清除搜索"""
        self.search_input.clear()
        self.filter_combo.setCurrentIndex(0)

    def change_page_size(self):
        """改变每页显示数量"""
        size_text = self.page_size_combo.currentText()
        if size_text == "全部":
            self.files_per_page = len(self.filtered_files)
        else:
            self.files_per_page = int(size_text)

        self.current_page = 0
        self.update_file_list()
        self.update_page_controls()

    def update_file_list(self):
        """更新文件列表显示"""
        self.file_list.clear()

        if not self.filtered_files:
            return

        # 计算当前页的文件
        start_idx = self.current_page * self.files_per_page
        end_idx = min(start_idx + self.files_per_page, len(self.filtered_files))

        current_page_files = self.filtered_files[start_idx:end_idx]

        for file in current_page_files:
            item = QListWidgetItem()
            checkbox = QCheckBox(file)
            checkbox.setChecked(file in self.selected_files)
            checkbox.toggled.connect(lambda checked, f=file: self.toggle_file_selection(f, checked))

            self.file_list.addItem(item)
            self.file_list.setItemWidget(item, checkbox)

        self.update_stats()
        self.update_selected_count()

    def update_stats(self):
        """更新统计信息"""
        total_files = len(self.all_files)
        filtered_files = len(self.filtered_files)

        if self.search_input.text() or self.filter_combo.currentIndex() > 0:
            self.stats_label.setText(f"显示 {filtered_files} / {total_files} 个文件")
        else:
            self.stats_label.setText(f"共 {total_files} 个文件")

    def update_page_controls(self):
        """更新分页控制"""
        if not self.filtered_files:
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.page_input.setMaximum(0)
            return

        total_pages = (len(self.filtered_files) - 1) // self.files_per_page + 1
        current_page_display = self.current_page + 1

        self.page_label.setText(f"{current_page_display} / {total_pages}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)

        self.page_input.setMaximum(total_pages)
        self.page_input.setValue(current_page_display)

    def prev_page(self):
        """上一页"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_file_list()
            self.update_page_controls()

    def next_page(self):
        """下一页"""
        total_pages = (len(self.filtered_files) - 1) // self.files_per_page + 1
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.update_file_list()
            self.update_page_controls()

    def jump_to_page(self):
        """跳转到指定页面"""
        page = self.page_input.value() - 1
        total_pages = (len(self.filtered_files) - 1) // self.files_per_page + 1

        if 0 <= page < total_pages:
            self.current_page = page
            self.update_file_list()
            self.update_page_controls()

    def toggle_file_selection(self, filename: str, checked: bool):
        """切换文件选择状态"""
        if checked and filename not in self.selected_files:
            self.selected_files.append(filename)
        elif not checked and filename in self.selected_files:
            self.selected_files.remove(filename)

        self.update_selected_count()

    def select_current_page(self):
        """选择当前页所有文件"""
        start_idx = self.current_page * self.files_per_page
        end_idx = min(start_idx + self.files_per_page, len(self.filtered_files))
        current_page_files = self.filtered_files[start_idx:end_idx]

        for file in current_page_files:
            if file not in self.selected_files:
                self.selected_files.append(file)

        self.update_file_list()

    def deselect_current_page(self):
        """取消选择当前页所有文件"""
        start_idx = self.current_page * self.files_per_page
        end_idx = min(start_idx + self.files_per_page, len(self.filtered_files))
        current_page_files = self.filtered_files[start_idx:end_idx]

        for file in current_page_files:
            if file in self.selected_files:
                self.selected_files.remove(file)

        self.update_file_list()

    def select_all_filtered(self):
        """选择所有搜索结果"""
        for file in self.filtered_files:
            if file not in self.selected_files:
                self.selected_files.append(file)

        self.update_file_list()

    def deselect_all_filtered(self):
        """取消所有选择"""
        self.selected_files.clear()
        self.update_file_list()

    def update_selected_count(self):
        """更新已选择文件数量"""
        count = len(self.selected_files)
        self.selected_count_label.setText(f"已选择: {count} 个文件")

    def preview_selected(self):
        """预览选中的文件"""
        if not self.selected_files:
            QMessageBox.information(self, "预览", "没有选中任何文件")
            return

        # 创建预览对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("已选择的文件")
        dialog.setGeometry(300, 300, 500, 400)

        layout = QVBoxLayout()

        # 文件列表
        file_list = QTextEdit()
        file_list.setPlainText('\n'.join(sorted(self.selected_files)))
        file_list.setReadOnly(True)
        layout.addWidget(file_list)

        # 统计信息
        stats_text = f"共选择 {len(self.selected_files)} 个文件"
        # 按类型统计
        type_counts = {}
        for file in self.selected_files:
            ext = os.path.splitext(file)[1].lower()
            if not ext:
                ext = "无扩展名"
            type_counts[ext] = type_counts.get(ext, 0) + 1

        if type_counts:
            stats_text += "\n\n文件类型统计："
            for ext, count in sorted(type_counts.items()):
                stats_text += f"\n{ext}: {count} 个"

        stats_label = QLabel(stats_text)
        layout.addWidget(stats_label)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.setLayout(layout)
        dialog.exec()

    def get_selected_files(self) -> List[str]:
        """获取选中的文件列表"""
        return self.selected_files.copy()


class HuggingFaceDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.tasks: List[DownloadTask] = []
        self.download_worker: Optional[DownloadWorker] = None
        self.settings = QSettings('HFDownloader', 'Config')

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle("HuggingFace 模型下载器 v1.1")
        self.setGeometry(100, 100, 1200, 800)

        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # 创建选项卡
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        # 下载选项卡
        download_tab = self.create_download_tab()
        tab_widget.addTab(download_tab, "下载管理")

        # 代理选项卡
        self.proxy_widget = ProxyConfigWidget()
        tab_widget.addTab(self.proxy_widget, "代理设置")

        # 状态栏
        self.statusBar().showMessage("就绪")

    def create_download_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        # 添加任务区域
        add_group = QGroupBox("添加下载任务")
        add_layout = QVBoxLayout()

        # 仓库ID
        repo_layout = QHBoxLayout()
        repo_layout.addWidget(QLabel("仓库ID:"))
        self.repo_input = QLineEdit()
        self.repo_input.setPlaceholderText("例如: microsoft/DialoGPT-medium")
        repo_layout.addWidget(self.repo_input)

        # 浏览文件按钮
        self.browse_btn = QPushButton("浏览文件")
        self.browse_btn.clicked.connect(self.browse_repo_files)
        repo_layout.addWidget(self.browse_btn)
        add_layout.addLayout(repo_layout)

        # 文件列表
        files_layout = QHBoxLayout()
        files_layout.addWidget(QLabel("文件列表:"))
        self.files_input = QTextEdit()
        self.files_input.setPlaceholderText("每行一个文件名，例如:\npytorch_model.bin\nconfig.json\ntokenizer.json")
        self.files_input.setMaximumHeight(100)
        files_layout.addWidget(self.files_input)
        add_layout.addLayout(files_layout)

        # 本地目录和版本
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("保存目录:"))
        self.dir_input = QLineEdit()
        self.dir_input.setText("./downloads")
        dir_layout.addWidget(self.dir_input)

        dir_btn = QPushButton("浏览")
        dir_btn.clicked.connect(self.select_directory)
        dir_layout.addWidget(dir_btn)

        dir_layout.addWidget(QLabel("版本:"))
        self.revision_input = QLineEdit()
        self.revision_input.setText("main")
        self.revision_input.setMaximumWidth(100)
        dir_layout.addWidget(self.revision_input)
        add_layout.addLayout(dir_layout)

        # 添加按钮
        btn_layout = QHBoxLayout()
        add_task_btn = QPushButton("添加到队列")
        add_task_btn.clicked.connect(self.add_tasks)
        btn_layout.addWidget(add_task_btn)

        clear_btn = QPushButton("清空队列")
        clear_btn.clicked.connect(self.clear_tasks)
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        add_layout.addLayout(btn_layout)

        add_group.setLayout(add_layout)
        layout.addWidget(add_group)

        # 任务列表
        task_group = QGroupBox("下载队列")
        task_layout = QVBoxLayout()

        # 表格
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(7)
        self.task_table.setHorizontalHeaderLabels([
            "仓库", "文件名", "状态", "进度", "大小", "速度", "保存路径"
        ])

        # 设置列宽
        header = self.task_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        task_layout.addWidget(self.task_table)

        # 控制按钮
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始下载")
        self.start_btn.clicked.connect(self.start_download)
        control_layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("暂停下载")
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        control_layout.addWidget(self.pause_btn)

        self.remove_btn = QPushButton("移除选中")
        self.remove_btn.clicked.connect(self.remove_selected_tasks)
        control_layout.addWidget(self.remove_btn)

        control_layout.addStretch()

        # 总进度
        self.overall_progress = QProgressBar()
        control_layout.addWidget(QLabel("总进度:"))
        control_layout.addWidget(self.overall_progress)

        task_layout.addLayout(control_layout)
        task_group.setLayout(task_layout)
        layout.addWidget(task_group)

        # 日志区域
        log_group = QGroupBox("下载日志")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        widget.setLayout(layout)
        return widget

    def browse_repo_files(self):
        """浏览仓库文件 - 使用增强版文件选择对话框"""
        repo_id = self.repo_input.text().strip()
        if not repo_id:
            QMessageBox.warning(self, "警告", "请输入仓库ID")
            return

        try:
            self.log("正在获取仓库文件列表...")
            self.browse_btn.setEnabled(False)
            self.browse_btn.setText("获取中...")

            # 在单独线程中获取文件列表
            def get_files():
                try:
                    # 设置代理
                    proxy_url = self.proxy_widget.get_proxy_url()
                    if proxy_url:
                        os.environ['HTTP_PROXY'] = proxy_url
                        os.environ['HTTPS_PROXY'] = proxy_url

                    files = list_repo_files(repo_id)
                    return files, None
                except Exception as e:
                    return None, str(e)

            # 这里为了简化，直接调用，实际应该用QThread
            files, error = get_files()

            if error:
                QMessageBox.critical(self, "错误", f"获取文件列表失败: {error}")
                return

            self.log(f"获取到 {len(files)} 个文件")

            # 使用增强版文件选择对话框
            dialog = AdvancedFileSelectionDialog(files, self)
            if dialog.exec() == dialog.DialogCode.Accepted:
                selected_files = dialog.get_selected_files()
                if selected_files:
                    self.files_input.setPlainText('\n'.join(selected_files))
                    self.log(f"已选择 {len(selected_files)} 个文件")
                else:
                    self.log("未选择任何文件")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取文件列表失败: {str(e)}")
        finally:
            self.browse_btn.setEnabled(True)
            self.browse_btn.setText("浏览文件")

    def select_directory(self):
        """选择保存目录"""
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if directory:
            self.dir_input.setText(directory)

    def add_tasks(self):
        """添加下载任务"""
        repo_id = self.repo_input.text().strip()
        files_text = self.files_input.toPlainText().strip()
        local_dir = self.dir_input.text().strip()
        revision = self.revision_input.text().strip()

        if not repo_id:
            QMessageBox.warning(self, "警告", "请输入仓库ID")
            return

        if not files_text:
            QMessageBox.warning(self, "警告", "请输入文件列表")
            return

        if not local_dir:
            QMessageBox.warning(self, "警告", "请选择保存目录")
            return

        files = [f.strip() for f in files_text.split('\n') if f.strip()]

        for filename in files:
            task = DownloadTask(
                repo_id=repo_id,
                filename=filename,
                local_dir=local_dir,
                revision=revision
            )
            self.tasks.append(task)

        self.update_task_table()
        self.log(f"已添加 {len(files)} 个下载任务")

    def clear_tasks(self):
        """清空任务队列"""
        self.tasks.clear()
        self.update_task_table()
        self.log("已清空任务队列")

    def remove_selected_tasks(self):
        """移除选中的任务"""
        selected_rows = set()
        for item in self.task_table.selectedItems():
            selected_rows.add(item.row())

        # 从后往前删除，避免索引问题
        for row in sorted(selected_rows, reverse=True):
            if 0 <= row < len(self.tasks):
                del self.tasks[row]

        self.update_task_table()
        self.log(f"已移除 {len(selected_rows)} 个任务")

    def update_task_table(self):
        """更新任务表格"""
        self.task_table.setRowCount(len(self.tasks))

        for i, task in enumerate(self.tasks):
            self.task_table.setItem(i, 0, QTableWidgetItem(task.repo_id))
            self.task_table.setItem(i, 1, QTableWidgetItem(task.filename))
            self.task_table.setItem(i, 2, QTableWidgetItem(task.status))

            # 进度条
            progress_item = QTableWidgetItem(f"{task.progress:.1f}%")
            self.task_table.setItem(i, 3, progress_item)

            size_text = self.format_size(task.size) if task.size > 0 else "未知"
            self.task_table.setItem(i, 4, QTableWidgetItem(size_text))
            self.task_table.setItem(i, 5, QTableWidgetItem(task.speed))

            local_path = os.path.join(task.local_dir, task.repo_id)
            self.task_table.setItem(i, 6, QTableWidgetItem(local_path))

    def start_download(self):
        """开始下载"""
        if not self.tasks:
            QMessageBox.warning(self, "警告", "没有下载任务")
            return

        if self.download_worker and self.download_worker.isRunning():
            QMessageBox.warning(self, "警告", "下载正在进行中")
            return

        proxy_config = self.proxy_widget.get_config()
        self.download_worker = DownloadWorker(self.tasks, proxy_config)
        self.download_worker.progress_updated.connect(self.on_progress_updated)
        self.download_worker.task_completed.connect(self.on_task_completed)
        self.download_worker.finished.connect(self.on_download_finished)

        self.download_worker.start()
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)

        self.log("开始下载...")

    def pause_download(self):
        """暂停下载"""
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.log("正在暂停下载...")

    def on_progress_updated(self, task_index: int, progress: float, speed: str, status: str):
        """进度更新"""
        if 0 <= task_index < len(self.tasks):
            self.tasks[task_index].progress = progress
            self.tasks[task_index].speed = speed
            self.tasks[task_index].status = status

            # 更新表格中的对应行
            self.task_table.setItem(task_index, 2, QTableWidgetItem(status))
            self.task_table.setItem(task_index, 3, QTableWidgetItem(f"{progress:.1f}%"))
            self.task_table.setItem(task_index, 5, QTableWidgetItem(speed))

    def on_task_completed(self, task_index: int, success: bool, message: str):
        """任务完成"""
        self.log(message)

        if 0 <= task_index < len(self.tasks):
            if success:
                self.tasks[task_index].status = "已完成"
                self.tasks[task_index].progress = 100.0
            else:
                self.tasks[task_index].status = "失败"

        self.update_task_table()
        self.update_overall_progress()

    def on_download_finished(self):
        """下载完成"""
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.log("下载任务完成")

    def update_overall_progress(self):
        """更新总进度"""
        if not self.tasks:
            self.overall_progress.setValue(0)
            return

        total_progress = sum(task.progress for task in self.tasks)
        overall = total_progress / len(self.tasks)
        self.overall_progress.setValue(int(overall))

    def log(self, message: str):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        self.statusBar().showMessage(message)

    def format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def save_settings(self):
        """保存设置"""
        self.settings.setValue("repo_id", self.repo_input.text())
        self.settings.setValue("local_dir", self.dir_input.text())
        self.settings.setValue("revision", self.revision_input.text())

        # 保存代理设置
        proxy_config = self.proxy_widget.get_config()
        self.settings.setValue("proxy_enabled", proxy_config.get('enabled', False))
        self.settings.setValue("proxy_url", proxy_config.get('url', ''))

    def load_settings(self):
        """加载设置"""
        self.repo_input.setText(self.settings.value("repo_id", ""))
        self.dir_input.setText(self.settings.value("local_dir", "./downloads"))
        self.revision_input.setText(self.settings.value("revision", "main"))

    def closeEvent(self, event):
        """关闭事件"""
        self.save_settings()

        if self.download_worker and self.download_worker.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "下载正在进行中，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.download_worker.cancel()
                self.download_worker.wait(3000)  # 等待3秒
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("HuggingFace Downloader")
    app.setOrganizationName("HFDownloader")

    # 设置应用图标和样式
    app.setStyle('Fusion')

    # 深色主题
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    window = HuggingFaceDownloader()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()