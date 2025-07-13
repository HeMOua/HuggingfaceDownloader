import sys
import os
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse
import concurrent.futures
from collections import defaultdict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QGroupBox, QCheckBox, QSpinBox, QComboBox, QFileDialog,
    QMessageBox, QSplitter, QFrame, QScrollArea, QListWidget,
    QListWidgetItem, QDialog, QGridLayout, QTreeWidget, QTreeWidgetItem,
    QStyledItemDelegate, QStyleOptionViewItem
)
from PyQt6.QtCore import (
    QThread, pyqtSignal, QTimer, Qt, QSettings, QSize, QRect, QMutex,
    QThreadPool, QRunnable, QObject
)
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPalette, QColor, QPainter

try:
    from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download, repo_info
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
    task_id: str = ""

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"{self.repo_id}:{self.filename}"


class ProgressItemDelegate(QStyledItemDelegate):
    """自定义进度条委托"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        if index.column() == 3:  # 进度列
            progress_data = index.data(Qt.ItemDataRole.UserRole)
            if progress_data is not None:
                progress_value = float(progress_data)

                # 绘制进度条
                progress_rect = QRect(option.rect)
                progress_rect.setWidth(int(progress_rect.width() * progress_value / 100))

                # 背景
                painter.fillRect(option.rect, QColor(60, 60, 60))

                # 进度条
                if progress_value > 0:
                    color = QColor(42, 130, 218) if progress_value < 100 else QColor(46, 125, 50)
                    painter.fillRect(progress_rect, color)

                # 文本
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, f"{progress_value:.1f}%")
                return

        super().paint(painter, option, index)


class DownloadWorkerSignals(QObject):
    """下载线程信号"""
    progress_updated = pyqtSignal(str, float, str, str, int, int)  # task_id, progress, speed, status, downloaded, total
    task_completed = pyqtSignal(str, bool, str)  # task_id, success, message
    task_started = pyqtSignal(str)  # task_id


class SingleDownloadWorker(QRunnable):
    """单个文件下载工作线程"""

    def __init__(self, task: DownloadTask, proxy_config: Dict, signals: DownloadWorkerSignals):
        super().__init__()
        self.task = task
        self.proxy_config = proxy_config
        self.signals = signals
        self.is_cancelled = False

    def run(self):
        try:
            self.signals.task_started.emit(self.task.task_id)
            self.signals.progress_updated.emit(
                self.task.task_id, 0, "0 B/s", "准备下载", 0, 0
            )

            # 设置代理
            if self.proxy_config.get('enabled', False):
                proxy_url = self.proxy_config.get('url', '')
                if proxy_url:
                    os.environ['HTTP_PROXY'] = proxy_url
                    os.environ['HTTPS_PROXY'] = proxy_url

            # 创建自定义的下载函数，支持进度回调
            def progress_callback(downloaded: int, total: int):
                if self.is_cancelled:
                    return False

                if total > 0:
                    progress = (downloaded / total) * 100
                    speed = self.calculate_speed(downloaded)
                    self.signals.progress_updated.emit(
                        self.task.task_id, progress, speed, "下载中", downloaded, total
                    )
                return True

            # 下载文件
            local_path = self.download_with_progress(progress_callback)

            if not self.is_cancelled:
                self.signals.progress_updated.emit(
                    self.task.task_id, 100, "完成", "已完成", 0, 0
                )
                self.signals.task_completed.emit(
                    self.task.task_id, True, f"下载完成: {local_path}"
                )

        except Exception as e:
            self.signals.progress_updated.emit(
                self.task.task_id, 0, "错误", "失败", 0, 0
            )
            self.signals.task_completed.emit(
                self.task.task_id, False, f"下载失败: {str(e)}"
            )

    def download_with_progress(self, progress_callback):
        """带进度回调的下载函数"""
        try:
            # 首先获取文件信息
            from huggingface_hub import HfApi
            api = HfApi()

            # 使用自定义下载逻辑
            import urllib.request
            from urllib.parse import urljoin

            # 构建下载URL
            base_url = f"https://huggingface.co/{self.task.repo_id}/resolve/{self.task.revision}/"
            file_url = urljoin(base_url, self.task.filename)

            # 创建本地目录
            local_dir = Path(self.task.local_dir) / self.task.repo_id
            local_dir.mkdir(parents=True, exist_ok=True)

            local_file_path = local_dir / self.task.filename

            # 如果文件已存在，检查是否需要断点续传
            resume_byte_pos = 0
            if local_file_path.exists():
                resume_byte_pos = local_file_path.stat().st_size

            # 创建请求
            req = urllib.request.Request(file_url)
            if resume_byte_pos > 0:
                req.add_header('Range', f'bytes={resume_byte_pos}-')

            # 发送请求
            with urllib.request.urlopen(req) as response:
                total_size = int(response.headers.get('content-length', 0))
                if resume_byte_pos > 0:
                    total_size += resume_byte_pos

                downloaded = resume_byte_pos

                # 打开本地文件
                mode = 'ab' if resume_byte_pos > 0 else 'wb'
                with open(local_file_path, mode) as f:
                    while True:
                        if self.is_cancelled:
                            break

                        chunk = response.read(8192)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded += len(chunk)

                        # 调用进度回调
                        if not progress_callback(downloaded, total_size):
                            break

            return str(local_file_path)

        except Exception as e:
            # fallback到原始方法
            return hf_hub_download(
                repo_id=self.task.repo_id,
                filename=self.task.filename,
                local_dir=self.task.local_dir,
                revision=self.task.revision,
                resume_download=True
            )

    def calculate_speed(self, downloaded: int) -> str:
        """计算下载速度"""
        if not hasattr(self, '_start_time'):
            self._start_time = time.time()
            self._last_downloaded = 0
            return "0 B/s"

        current_time = time.time()
        time_diff = current_time - self._start_time

        if time_diff > 0:
            speed_bps = (downloaded - self._last_downloaded) / time_diff
            return self.format_speed(speed_bps)

        return "0 B/s"

    def format_speed(self, speed_bps: float) -> str:
        """格式化速度"""
        for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
            if speed_bps < 1024.0:
                return f"{speed_bps:.1f} {unit}"
            speed_bps /= 1024.0
        return f"{speed_bps:.1f} TB/s"

    def cancel(self):
        self.is_cancelled = True


class MultiThreadDownloadManager(QObject):
    """多线程下载管理器"""
    all_completed = pyqtSignal()

    def __init__(self, max_workers: int = 3):
        super().__init__()
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(max_workers)
        self.signals = DownloadWorkerSignals()
        self.active_workers: Dict[str, SingleDownloadWorker] = {}
        self.completed_tasks = 0
        self.total_tasks = 0

    def start_downloads(self, tasks: List[DownloadTask], proxy_config: Dict):
        """开始多线程下载"""
        self.total_tasks = len(tasks)
        self.completed_tasks = 0

        for task in tasks:
            worker = SingleDownloadWorker(task, proxy_config, self.signals)
            self.active_workers[task.task_id] = worker

            # 连接完成信号
            self.signals.task_completed.connect(self._on_task_completed)

            self.thread_pool.start(worker)

    def _on_task_completed(self, task_id: str, success: bool, message: str):
        """任务完成处理"""
        self.completed_tasks += 1
        if task_id in self.active_workers:
            del self.active_workers[task_id]

        if self.completed_tasks >= self.total_tasks:
            self.all_completed.emit()

    def cancel_all(self):
        """取消所有下载"""
        for worker in self.active_workers.values():
            worker.cancel()
        self.thread_pool.waitForDone(3000)
        self.active_workers.clear()


from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget,
                             QTreeWidgetItem, QPushButton, QLineEdit, QLabel,
                             QHeaderView, QMessageBox, QTextEdit)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
import os
from collections import defaultdict
from typing import List


class TreeFileSelectionDialog(QDialog):
    """树状文件选择对话框"""

    def __init__(self, files: List[str], parent=None):
        super().__init__(parent)
        self.all_files = files
        self.selected_files = []
        self.file_tree = {}
        self.build_file_tree()
        self.init_ui()
        self.populate_tree()

    def build_file_tree(self):
        """构建文件树结构"""
        self.file_tree = {}

        for file_path in self.all_files:
            parts = file_path.split('/')
            current = self.file_tree

            for i, part in enumerate(parts):
                if part not in current:
                    current[part] = {} if i < len(parts) - 1 else {'__is_file__': True, '__path__': file_path}
                current = current[part]

    def get_file_icon(self, filename: str) -> QIcon:
        """根据文件扩展名返回对应的图标"""
        # 使用系统标准图标或自定义图标
        style = self.style()

        if os.path.isdir(filename):
            return style.standardIcon(style.StandardPixmap.SP_DirIcon)

        ext = os.path.splitext(filename)[1].lower()

        # 根据文件扩展名设置不同图标
        if ext in ['.bin', '.safetensors', '.pth', '.ckpt']:
            # 模型文件 - 使用计算机图标
            return style.standardIcon(style.StandardPixmap.SP_ComputerIcon)
        elif ext in ['.json', '.yaml', '.yml', '.toml', '.ini']:
            # 配置文件 - 使用文档图标
            return style.standardIcon(style.StandardPixmap.SP_FileDialogDetailedView)
        elif ext in ['.txt', '.md', '.readme']:
            # 文本文件
            return style.standardIcon(style.StandardPixmap.SP_FileIcon)
        elif ext in ['.py', '.js', '.cpp', '.c', '.java']:
            # 代码文件
            return style.standardIcon(style.StandardPixmap.SP_FileDialogListView)
        elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            # 图片文件
            return style.standardIcon(style.StandardPixmap.SP_FileDialogDetailedView)
        elif 'tokenizer' in filename.lower():
            # 分词器文件
            return style.standardIcon(style.StandardPixmap.SP_DialogApplyButton)
        else:
            # 其他文件
            return style.standardIcon(style.StandardPixmap.SP_FileIcon)

    def get_folder_icon(self) -> QIcon:
        """获取文件夹图标"""
        style = self.style()
        return style.standardIcon(style.StandardPixmap.SP_DirIcon)

    def sort_tree_items(self, items: list) -> list:
        """自定义排序：文件夹在前，文件在后，同类型按字母序"""
        folders = []
        files = []

        for name, content in items:
            if isinstance(content, dict) and content.get('__is_file__'):
                files.append((name, content))
            else:
                folders.append((name, content))

        # 分别对文件夹和文件进行字母排序
        folders.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[0].lower())

        # 文件夹在前，文件在后
        return folders + files

    def init_ui(self):
        self.setWindowTitle("选择文件 - 树状结构")
        self.setGeometry(200, 200, 900, 700)

        layout = QVBoxLayout()

        # 顶部控制区域
        control_layout = QHBoxLayout()

        # 搜索
        control_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入文件名进行搜索...")
        self.search_input.textChanged.connect(self.filter_tree)
        control_layout.addWidget(self.search_input)

        # 展开/折叠按钮
        expand_all_btn = QPushButton("展开所有")
        expand_all_btn.clicked.connect(self.expand_all)
        control_layout.addWidget(expand_all_btn)

        collapse_all_btn = QPushButton("折叠所有")
        collapse_all_btn.clicked.connect(self.collapse_all)
        control_layout.addWidget(collapse_all_btn)

        layout.addLayout(control_layout)

        # 批量操作
        batch_layout = QHBoxLayout()

        select_all_btn = QPushButton("全选所有文件")
        select_all_btn.clicked.connect(self.select_all_files)
        batch_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("取消所有选择")
        deselect_all_btn.clicked.connect(self.deselect_all_files)
        batch_layout.addWidget(deselect_all_btn)

        batch_layout.addStretch()

        # 统计信息
        self.stats_label = QLabel()
        batch_layout.addWidget(self.stats_label)

        layout.addLayout(batch_layout)

        # 文件树
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["文件/文件夹", "大小", "类型"])
        header = self.tree_widget.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.tree_widget.setColumnWidth(1, 100)
        self.tree_widget.setColumnWidth(2, 100)
        self.tree_widget.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.tree_widget)

        # 底部按钮
        button_layout = QHBoxLayout()

        # 预览按钮
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

    def populate_tree(self):
        """填充树状结构"""
        self.tree_widget.clear()
        self._create_tree_items(self.file_tree, self.tree_widget)
        self.update_stats()

    def _create_tree_items(self, tree_dict: dict, parent_item):
        """递归创建树项目"""
        # 获取所有项目并排序
        items = [(name, content) for name, content in tree_dict.items() if not name.startswith('__')]
        sorted_items = self.sort_tree_items(items)

        for name, content in sorted_items:
            item = QTreeWidgetItem(parent_item)
            item.setText(0, name)

            if isinstance(content, dict) and content.get('__is_file__'):
                # 这是一个文件
                file_path = content['__path__']
                item.setText(2, "文件")
                item.setData(0, Qt.ItemDataRole.UserRole, file_path)
                item.setCheckState(0, Qt.CheckState.Unchecked)

                # 设置文件图标
                item.setIcon(0, self.get_file_icon(name))

                # 设置文件类型和大小信息
                ext = os.path.splitext(name)[1].lower()
                if ext in ['.bin', '.safetensors', '.pth', '.ckpt']:
                    item.setText(1, "模型文件")
                elif ext in ['.json', '.yaml', '.yml', '.toml', '.ini']:
                    item.setText(1, "配置文件")
                elif 'tokenizer' in name.lower():
                    item.setText(1, "分词器文件")
                elif ext in ['.txt', '.md', '.readme']:
                    item.setText(1, "文档文件")
                elif ext in ['.py', '.js', '.cpp', '.c', '.java']:
                    item.setText(1, "代码文件")
                elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                    item.setText(1, "图片文件")
                else:
                    item.setText(1, "其他文件")
            else:
                # 这是一个文件夹
                item.setText(1, "")
                item.setText(2, "文件夹")
                item.setData(0, Qt.ItemDataRole.UserRole, None)

                # 设置文件夹图标
                item.setIcon(0, self.get_folder_icon())

                # 设置部分选中状态
                item.setCheckState(0, Qt.CheckState.Unchecked)

                # 递归创建子项目
                self._create_tree_items(content, item)

    def on_item_changed(self, item: QTreeWidgetItem, column: int):
        """处理项目状态变化"""
        if column == 0:  # 复选框列
            file_path = item.data(0, Qt.ItemDataRole.UserRole)

            if file_path:  # 这是一个文件
                if item.checkState(0) == Qt.CheckState.Checked:
                    if file_path not in self.selected_files:
                        self.selected_files.append(file_path)
                else:
                    if file_path in self.selected_files:
                        self.selected_files.remove(file_path)
            else:  # 这是一个文件夹
                self._update_children_state(item, item.checkState(0))

            self._update_parent_state(item)
            self.update_stats()

    def _update_children_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        """更新子项目状态"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, state)

            file_path = child.data(0, Qt.ItemDataRole.UserRole)
            if file_path:  # 这是文件
                if state == Qt.CheckState.Checked:
                    if file_path not in self.selected_files:
                        self.selected_files.append(file_path)
                else:
                    if file_path in self.selected_files:
                        self.selected_files.remove(file_path)
            else:  # 这是文件夹
                self._update_children_state(child, state)

    def _update_parent_state(self, item: QTreeWidgetItem):
        """更新父项目状态"""
        parent = item.parent()
        if not parent:
            return

        # 检查同级项目的状态
        checked_count = 0
        partially_checked_count = 0
        total_count = parent.childCount()

        for i in range(total_count):
            child = parent.child(i)
            state = child.checkState(0)
            if state == Qt.CheckState.Checked:
                checked_count += 1
            elif state == Qt.CheckState.PartiallyChecked:
                partially_checked_count += 1

        # 设置父项目状态
        if checked_count == total_count:
            parent.setCheckState(0, Qt.CheckState.Checked)
        elif checked_count > 0 or partially_checked_count > 0:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        else:
            parent.setCheckState(0, Qt.CheckState.Unchecked)

        # 递归更新上级父项目
        self._update_parent_state(parent)

    def filter_tree(self):
        """过滤树状结构"""
        search_text = self.search_input.text().lower()
        self._filter_tree_items(self.tree_widget.invisibleRootItem(), search_text)

    def _filter_tree_items(self, parent_item, search_text: str) -> bool:
        """递归过滤树项目"""
        has_visible_child = False

        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child_name = child.text(0).lower()

            # 检查子项目
            child_has_visible = self._filter_tree_items(child, search_text)

            # 检查当前项目是否匹配
            current_matches = search_text in child_name if search_text else True

            # 显示/隐藏项目
            should_show = current_matches or child_has_visible
            child.setHidden(not should_show)

            if should_show:
                has_visible_child = True

        return has_visible_child

    def expand_all(self):
        """展开所有项目"""
        self.tree_widget.expandAll()

    def collapse_all(self):
        """折叠所有项目"""
        self.tree_widget.collapseAll()

    def select_all_files(self):
        """选择所有文件"""
        self.selected_files.clear()
        self._select_all_items(self.tree_widget.invisibleRootItem(), True)
        self.update_stats()

    def deselect_all_files(self):
        """取消选择所有文件"""
        self.selected_files.clear()
        self._select_all_items(self.tree_widget.invisibleRootItem(), False)
        self.update_stats()

    def _select_all_items(self, parent_item, select: bool):
        """递归选择/取消选择所有项目"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            file_path = child.data(0, Qt.ItemDataRole.UserRole)

            state = Qt.CheckState.Checked if select else Qt.CheckState.Unchecked
            child.setCheckState(0, state)

            if file_path and select:
                if file_path not in self.selected_files:
                    self.selected_files.append(file_path)

            self._select_all_items(child, select)

    def update_stats(self):
        """更新统计信息"""
        total_files = len(self.all_files)
        selected_count = len(self.selected_files)
        self.stats_label.setText(f"已选择: {selected_count} / {total_files} 个文件")

    def preview_selected(self):
        """预览选中文件"""
        if not self.selected_files:
            QMessageBox.information(self, "预览", "没有选中任何文件")
            return

        # 创建预览对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("已选择的文件")
        dialog.setGeometry(300, 300, 600, 500)

        layout = QVBoxLayout()

        # 按文件夹分组显示
        grouped_files = defaultdict(list)
        for file_path in sorted(self.selected_files):
            folder = os.path.dirname(file_path) if '/' in file_path else '根目录'
            grouped_files[folder].append(os.path.basename(file_path))

        preview_text = QTextEdit()
        preview_content = f"共选择 {len(self.selected_files)} 个文件：\n\n"

        for folder, files in grouped_files.items():
            preview_content += f"📁 {folder}/\n"
            for file in files:
                preview_content += f"  📄 {file}\n"
            preview_content += "\n"

        preview_text.setPlainText(preview_content)
        preview_text.setReadOnly(True)
        layout.addWidget(preview_text)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.setLayout(layout)
        dialog.exec()

    def get_selected_files(self) -> List[str]:
        """获取选中的文件列表"""
        return self.selected_files.copy()

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


class HuggingFaceDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.tasks: Dict[str, DownloadTask] = {}
        self.download_manager = MultiThreadDownloadManager(max_workers=4)
        self.settings = QSettings('HFDownloader', 'Config')

        self.init_ui()
        self.setup_connections()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle("HuggingFace 模型下载器 v2.0 - 多线程增强版")
        self.setGeometry(100, 100, 1400, 900)

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

        # 设置选项卡
        settings_tab = self.create_settings_tab()
        tab_widget.addTab(settings_tab, "设置")

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
        self.browse_btn = QPushButton("🗂️ 浏览文件")
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

        dir_btn = QPushButton("📁 浏览")
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
        add_task_btn = QPushButton("➕ 添加到队列")
        add_task_btn.clicked.connect(self.add_tasks)
        btn_layout.addWidget(add_task_btn)

        clear_btn = QPushButton("🗑️ 清空队列")
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
        self.task_table.setColumnCount(8)
        self.task_table.setHorizontalHeaderLabels([
            "仓库", "文件名", "状态", "进度", "已下载", "总大小", "速度", "保存路径"
        ])

        # 设置自定义委托
        self.progress_delegate = ProgressItemDelegate()
        self.task_table.setItemDelegate(self.progress_delegate)

        # 设置列宽
        header = self.task_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, 120)  # 进度条列固定宽度
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)

        task_layout.addWidget(self.task_table)

        # 控制按钮
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("🚀 开始下载")
        self.start_btn.clicked.connect(self.start_download)
        control_layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("⏸️ 暂停下载")
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        control_layout.addWidget(self.pause_btn)

        self.remove_btn = QPushButton("❌ 移除选中")
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

    def create_settings_tab(self) -> QWidget:
        """创建设置选项卡"""
        widget = QWidget()
        layout = QVBoxLayout()

        # 下载设置
        download_group = QGroupBox("下载设置")
        download_layout = QVBoxLayout()

        # 并发数设置
        concurrent_layout = QHBoxLayout()
        concurrent_layout.addWidget(QLabel("同时下载任务数:"))
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(4)
        self.concurrent_spin.valueChanged.connect(self.update_concurrent_downloads)
        concurrent_layout.addWidget(self.concurrent_spin)
        concurrent_layout.addWidget(QLabel("个"))
        concurrent_layout.addStretch()
        download_layout.addLayout(concurrent_layout)

        # 重试设置
        retry_layout = QHBoxLayout()
        retry_layout.addWidget(QLabel("下载失败重试次数:"))
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(3)
        retry_layout.addWidget(self.retry_spin)
        retry_layout.addWidget(QLabel("次"))
        retry_layout.addStretch()
        download_layout.addLayout(retry_layout)

        download_group.setLayout(download_layout)
        layout.addWidget(download_group)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def setup_connections(self):
        """设置信号连接"""
        # 下载管理器信号
        self.download_manager.signals.progress_updated.connect(self.on_progress_updated)
        self.download_manager.signals.task_completed.connect(self.on_task_completed)
        self.download_manager.signals.task_started.connect(self.on_task_started)
        self.download_manager.all_completed.connect(self.on_all_completed)

    def browse_repo_files(self):
        """浏览仓库文件 - 使用树状文件选择对话框"""
        repo_id = self.repo_input.text().strip()
        if not repo_id:
            QMessageBox.warning(self, "警告", "请输入仓库ID")
            return

        try:
            self.log("正在获取仓库文件列表...")
            self.browse_btn.setEnabled(False)
            self.browse_btn.setText("获取中...")

            # 设置代理
            proxy_url = self.proxy_widget.get_proxy_url()
            if proxy_url:
                os.environ['HTTP_PROXY'] = proxy_url
                os.environ['HTTPS_PROXY'] = proxy_url

            # 获取文件列表
            files = list_repo_files(repo_id)
            self.log(f"获取到 {len(files)} 个文件")

            # 使用树状文件选择对话框
            dialog = TreeFileSelectionDialog(files, self)
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
            self.browse_btn.setText("🗂️ 浏览文件")

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
            self.tasks[task.task_id] = task

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

        task_ids = list(self.tasks.keys())

        # 从后往前删除，避免索引问题
        for row in sorted(selected_rows, reverse=True):
            if 0 <= row < len(task_ids):
                task_id = task_ids[row]
                del self.tasks[task_id]

        self.update_task_table()
        self.log(f"已移除 {len(selected_rows)} 个任务")

    def update_task_table(self):
        """更新任务表格"""
        self.task_table.setRowCount(len(self.tasks))

        for i, (task_id, task) in enumerate(self.tasks.items()):
            self.task_table.setItem(i, 0, QTableWidgetItem(task.repo_id))
            self.task_table.setItem(i, 1, QTableWidgetItem(task.filename))
            self.task_table.setItem(i, 2, QTableWidgetItem(task.status))

            # 进度条
            progress_item = QTableWidgetItem(f"{task.progress:.1f}%")
            progress_item.setData(Qt.ItemDataRole.UserRole, task.progress)
            self.task_table.setItem(i, 3, progress_item)

            downloaded_text = self.format_size(task.downloaded) if task.downloaded > 0 else "--"
            self.task_table.setItem(i, 4, QTableWidgetItem(downloaded_text))

            size_text = self.format_size(task.size) if task.size > 0 else "--"
            self.task_table.setItem(i, 5, QTableWidgetItem(size_text))

            self.task_table.setItem(i, 6, QTableWidgetItem(task.speed))

            local_path = os.path.join(task.local_dir, task.repo_id)
            self.task_table.setItem(i, 7, QTableWidgetItem(local_path))

    def start_download(self):
        """开始下载"""
        if not self.tasks:
            QMessageBox.warning(self, "警告", "没有下载任务")
            return

        proxy_config = self.proxy_widget.get_config()

        # 只下载未完成的任务
        pending_tasks = [task for task in self.tasks.values()
                         if task.status in ["待下载", "失败"]]

        if not pending_tasks:
            QMessageBox.information(self, "信息", "所有任务已完成")
            return

        self.download_manager.start_downloads(pending_tasks, proxy_config)
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)

        self.log(f"开始下载 {len(pending_tasks)} 个任务...")

    def pause_download(self):
        """暂停下载"""
        self.download_manager.cancel_all()
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.log("下载已暂停")

    def update_concurrent_downloads(self, value: int):
        """更新并发下载数"""
        self.download_manager.thread_pool.setMaxThreadCount(value)
        self.log(f"并发下载数已设置为: {value}")

    def on_task_started(self, task_id: str):
        """任务开始回调"""
        if task_id in self.tasks:
            self.tasks[task_id].status = "下载中"
            self.update_task_table()

    def on_progress_updated(self, task_id: str, progress: float, speed: str,
                            status: str, downloaded: int, total: int):
        """进度更新回调"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.progress = progress
            task.speed = speed
            task.status = status
            task.downloaded = downloaded
            task.size = total

            self.update_task_table()
            self.update_overall_progress()

    def on_task_completed(self, task_id: str, success: bool, message: str):
        """任务完成回调"""
        self.log(message)

        if task_id in self.tasks:
            task = self.tasks[task_id]
            if success:
                task.status = "已完成"
                task.progress = 100.0
            else:
                task.status = "失败"
                task.progress = 0.0

        self.update_task_table()
        self.update_overall_progress()

    def on_all_completed(self):
        """所有任务完成回调"""
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.log("所有下载任务完成")

        # 显示完成统计
        completed_count = sum(1 for task in self.tasks.values() if task.status == "已完成")
        failed_count = sum(1 for task in self.tasks.values() if task.status == "失败")

        QMessageBox.information(
            self, "下载完成",
            f"下载任务已完成！\n\n"
            f"成功: {completed_count} 个\n"
            f"失败: {failed_count} 个\n"
            f"总计: {len(self.tasks)} 个"
        )

    def update_overall_progress(self):
        """更新总进度"""
        if not self.tasks:
            self.overall_progress.setValue(0)
            return

        total_progress = sum(task.progress for task in self.tasks.values())
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
        self.settings.setValue("concurrent_downloads", self.concurrent_spin.value())
        self.settings.setValue("retry_count", self.retry_spin.value())

        # 保存代理设置
        proxy_config = self.proxy_widget.get_config()
        self.settings.setValue("proxy_enabled", proxy_config.get('enabled', False))
        self.settings.setValue("proxy_host", proxy_config.get('proxy_host', ''))
        self.settings.setValue("proxy_port", proxy_config.get('proxy_port', ''))

    def load_settings(self):
        """加载设置"""
        self.repo_input.setText(self.settings.value("repo_id", ""))
        self.dir_input.setText(self.settings.value("local_dir", "./downloads"))
        self.revision_input.setText(self.settings.value("revision", "main"))
        self.concurrent_spin.setValue(int(self.settings.value("concurrent_downloads", 4)))
        self.retry_spin.setValue(int(self.settings.value("retry_count", 3)))

        self.proxy_widget.proxy_enabled.setChecked(bool(self.settings.value("proxy_enabled", False)))
        self.proxy_widget.proxy_host.setText(self.settings.value("proxy_host", ""))
        self.proxy_widget.proxy_port.setValue(int(self.settings.value("proxy_port", 7890)))

    def closeEvent(self, event):
        """关闭事件"""
        self.save_settings()

        # 检查是否有正在下载的任务
        if any(task.status == "下载中" for task in self.tasks.values()):
            reply = QMessageBox.question(
                self, "确认退出",
                "有下载正在进行中，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.download_manager.cancel_all()
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