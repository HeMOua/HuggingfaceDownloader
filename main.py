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

from ui.components.tree_file_selection_dialog import HuggingfaceFileTreeWidget, HuggingfaceFileDialog
from ui.proxy_config_widget import ProxyConfigWidget
from ui.utils import set_black_ui

try:
    from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download, repo_info, HfApi
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


class LoadingDialog(QDialog):
    """加载对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在获取仓库信息")
        self.setFixedSize(300, 120)
        self.setModal(True)
        
        layout = QVBoxLayout()
        
        # 加载文本
        self.loading_label = QLabel("正在获取仓库文件列表，请稍候...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.loading_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 设置为不确定模式
        layout.addWidget(self.progress_bar)
        
        # 取消按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)


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
            # 设置代理
            proxy_url = self.proxy_widget.get_proxy_url()
            if proxy_url:
                os.environ['HTTP_PROXY'] = proxy_url
                os.environ['HTTPS_PROXY'] = proxy_url

            # 显示加载状态
            self.log("正在获取仓库文件列表...")
            self.browse_btn.setEnabled(False)
            self.browse_btn.setText("获取中...")

            # 使用树状文件选择对话框
            selected_files = HuggingfaceFileDialog.select_files_simple(self.repo_input.text(), self.revision_input.text())

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
    set_black_ui(app)

    window = HuggingFaceDownloader()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()