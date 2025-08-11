import sys
import os
import time
import urllib.request
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass
import json

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QGroupBox, QSpinBox, QFileDialog,
    QMessageBox, QStyledItemDelegate, QStyleOptionViewItem
)
from PyQt6.QtCore import (
    pyqtSignal, Qt, QSettings, QRect,
    QThreadPool, QRunnable, QObject
)
from PyQt6.QtGui import QColor, QPainter, QIcon
from urllib.parse import urljoin
from ui.components.tree_file_selection_dialog import HuggingfaceFileDialog
from ui.proxy_config_widget import ProxyConfigWidget
from ui.utils import set_black_ui
from huggingface_hub import hf_hub_download

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(BASE_DIR, "icon.png")


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
    """自定义进度条委托 - 优化版"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        if index.column() == 3:  # 进度列
            progress_data = index.data(Qt.ItemDataRole.UserRole)
            if progress_data is not None:
                progress_value = float(progress_data)

                # 绘制进度条背景
                bg_rect = QRect(option.rect)
                bg_rect.adjust(2, 2, -2, -2)  # 添加边距
                painter.fillRect(bg_rect, QColor(45, 45, 45))

                # 绘制进度条
                if progress_value > 0:
                    progress_rect = QRect(bg_rect)
                    progress_rect.setWidth(int(bg_rect.width() * progress_value / 100))

                    # 根据状态选择颜色
                    status = index.model().data(index.siblingAtColumn(2), Qt.ItemDataRole.DisplayRole)
                    if status == "已完成":
                        color = QColor(76, 175, 80)  # 绿色
                    elif status == "失败":
                        color = QColor(244, 67, 54)  # 红色
                    elif status == "下载中":
                        color = QColor(33, 150, 243)  # 蓝色
                    elif status == "暂停":
                        color = QColor(255, 152, 0)  # 橙色
                    else:
                        color = QColor(96, 125, 139)  # 灰色

                    painter.fillRect(progress_rect, color)

                # 绘制边框
                painter.setPen(QColor(80, 80, 80))
                painter.drawRect(bg_rect)

                # 绘制文本
                painter.setPen(QColor(255, 255, 255))
                font = painter.font()
                font.setPointSize(9)
                painter.setFont(font)
                painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, f"{progress_value:.1f}%")
                return

        super().paint(painter, option, index)


class DownloadWorkerSignals(QObject):
    """下载线程信号"""
    progress_updated = pyqtSignal(str, float, str, str, int, int)  # task_id, progress, speed, status, downloaded, total
    task_completed = pyqtSignal(str, bool, str)  # task_id, success, message
    task_started = pyqtSignal(str)  # task_id


class SingleDownloadWorker(QRunnable):
    """单个文件下载工作线程 - 优化版"""

    def __init__(self, task: DownloadTask, proxy_config: Dict, signals: DownloadWorkerSignals, token: str = None):
        super().__init__()
        self.task = task
        self.proxy_config = proxy_config
        self.signals = signals
        self.token = token  # 添加token支持
        self.is_cancelled = False
        self.manager = None
        self._start_time = None
        self._last_update_time = None
        self._last_downloaded = 0
        self._speed_samples = []  # 用于平滑速度计算

    def run(self):
        # 在开始执行前检查是否已被取消
        if self.manager and self.manager.is_cancelled():
            return

        if self.is_cancelled:
            return

        try:
            # 发送task_started信号前再次检查
            if self.manager and self.manager.is_cancelled():
                return

            self.signals.task_started.emit(self.task.task_id)

            # 检查本地文件是否已存在并获取已下载大小
            local_file_path = self.get_local_file_path()
            initial_downloaded = 0
            if local_file_path.exists():
                initial_downloaded = local_file_path.stat().st_size
                self.task.downloaded = initial_downloaded

            # 初始化速度计算参数
            self._start_time = time.time()
            self._last_update_time = self._start_time
            self._last_downloaded = initial_downloaded

            # 如果文件已完成，直接返回
            if self.task.size > 0 and initial_downloaded >= self.task.size:
                self.signals.progress_updated.emit(
                    self.task.task_id, 100.0, "已完成", "已完成", initial_downloaded, self.task.size
                )
                self.signals.task_completed.emit(
                    self.task.task_id, True, f"文件已存在: {local_file_path}"
                )
                return

            # 发送初始进度（不归零已下载的进度）
            if self.task.size > 0 and initial_downloaded > 0:
                initial_progress = (initial_downloaded / self.task.size) * 100
                self.signals.progress_updated.emit(
                    self.task.task_id, initial_progress, "准备中", "下载中", initial_downloaded, self.task.size
                )
            else:
                self.signals.progress_updated.emit(
                    self.task.task_id, 0, "准备中", "下载中", initial_downloaded, 0
                )

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
                # 获取最终文件大小
                final_size = local_file_path.stat().st_size if local_file_path.exists() else 0
                self.signals.progress_updated.emit(
                    self.task.task_id, 100, "完成", "已完成", final_size, final_size
                )
                self.signals.task_completed.emit(
                    self.task.task_id, True, f"下载完成: {local_path}"
                )

        except Exception as e:
            self.signals.progress_updated.emit(
                self.task.task_id, self.task.progress, "错误", "失败", self.task.downloaded, self.task.size
            )
            self.signals.task_completed.emit(
                self.task.task_id, False, f"下载失败: {str(e)}"
            )

    def get_local_file_path(self) -> Path:
        """获取本地文件路径"""
        local_dir = Path(self.task.local_dir) / self.task.repo_id
        return local_dir / self.task.filename

    def download_with_progress(self, progress_callback):
        """带进度回调的下载函数 - 优化版"""
        try:
            # 构建下载URL
            base_url = f"https://huggingface.co/{self.task.repo_id}/resolve/{self.task.revision}/"
            file_url = urljoin(base_url, self.task.filename)
            
            # 如果有token，添加到请求头中
            headers = {}
            if self.token:
                headers['Authorization'] = f'Bearer {self.token}'
                print(f"使用token进行认证: {self.token[:5]}...{self.token[-5:] if len(self.token) > 10 else ''}")
            else:
                print("未使用token进行认证")

            # 创建本地目录
            local_file_path = self.get_local_file_path()
            local_file_path.parent.mkdir(parents=True, exist_ok=True)

            # 检查是否需要断点续传
            resume_byte_pos = 0
            if local_file_path.exists():
                resume_byte_pos = local_file_path.stat().st_size

            # 创建请求
            # 创建基本请求对象
            req = urllib.request.Request(file_url)
            
            # 添加所有头部信息
            for header, value in headers.items():
                req.add_header(header, value)
                
            # 如果需要断点续传，添加Range头
            if resume_byte_pos > 0:
                req.add_header('Range', f'bytes={resume_byte_pos}-')
                
            # 打印请求头信息，用于调试
            print(f"请求URL: {file_url}")
            print(f"请求头: {req.headers}")
            if 'Authorization' in req.headers:
                print("已包含Authorization头")
            else:
                print("未包含Authorization头")

            # 发送请求
            with urllib.request.urlopen(req) as response:
                # 获取文件总大小
                content_length = response.headers.get('content-length')
                if content_length:
                    if resume_byte_pos > 0:
                        total_size = int(content_length) + resume_byte_pos
                    else:
                        total_size = int(content_length)
                else:
                    total_size = 0

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

                        # 调用进度回调（限制更新频率）
                        current_time = time.time()
                        if current_time - self._last_update_time >= 0.1:  # 每100ms更新一次
                            if not progress_callback(downloaded, total_size):
                                break
                            self._last_update_time = current_time

            return str(local_file_path)

        except Exception as e:
            # fallback到原始方法，添加token支持
            print(f"使用fallback方法下载: {self.task.filename}")
            if self.token:
                print(f"fallback方法使用token进行认证: {self.token[:5]}...{self.token[-5:] if len(self.token) > 10 else ''}")
            else:
                print("fallback方法未使用token进行认证")
                
            return hf_hub_download(
                repo_id=self.task.repo_id,
                filename=self.task.filename,
                local_dir=self.task.local_dir,
                revision=self.task.revision,
                resume_download=True,
                token=self.token  # 使用token进行认证
            )

    def calculate_speed(self, downloaded: int) -> str:
        """计算下载速度 - 优化版，使用滑动平均"""
        current_time = time.time()

        if self._last_update_time is None:
            self._last_update_time = current_time
            self._last_downloaded = downloaded
            return "0 B/s"

        time_diff = current_time - self._last_update_time
        if time_diff <= 0:
            return self.format_speed(0)

        # 计算当前速度
        bytes_diff = downloaded - self._last_downloaded
        current_speed = bytes_diff / time_diff

        # 添加到样本中用于平滑处理
        self._speed_samples.append(current_speed)
        if len(self._speed_samples) > 5:  # 保留最近5个样本
            self._speed_samples.pop(0)

        # 计算平滑速度
        smooth_speed = sum(self._speed_samples) / len(self._speed_samples)

        self._last_update_time = current_time
        self._last_downloaded = downloaded

        return self.format_speed(smooth_speed)

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
        self.is_downloading = False
        self._is_cancelled = False  # 添加全局取消标志

        # 只在这里连接一次
        self.signals.task_completed.connect(self._on_task_completed)

    def start_downloads(self, tasks: List[DownloadTask], proxy_config: Dict, token: str = None):
        """开始多线程下载"""
        self.total_tasks = len(tasks)
        self.completed_tasks = 0
        self.is_downloading = True
        self._is_cancelled = False  # 重置取消标志

        for task in tasks:
            worker = SingleDownloadWorker(task, proxy_config, self.signals, token)
            worker.manager = self  # 让worker能够访问manager
            self.active_workers[task.task_id] = worker
            self.thread_pool.start(worker)

    def _on_task_completed(self, task_id: str, success: bool, message: str):
        """任务完成处理"""
        self.completed_tasks += 1
        if task_id in self.active_workers:
            del self.active_workers[task_id]

        if self.completed_tasks >= self.total_tasks:
            self.is_downloading = False
            self.all_completed.emit()

    def cancel_all(self):
        """取消所有下载"""
        self._is_cancelled = True  # 设置全局取消标志
        self.is_downloading = False

        # 取消所有活跃的worker
        for worker in self.active_workers.values():
            worker.cancel()

        # 清空线程池队列中等待的任务
        self.thread_pool.clear()  # 这会清除队列中等待的任务

        # 等待当前正在执行的任务完成
        self.thread_pool.waitForDone(3000)
        self.active_workers.clear()

    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._is_cancelled

    def is_active(self) -> bool:
        """检查是否有活跃的下载"""
        return self.is_downloading and len(self.active_workers) > 0


class HuggingFaceDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.tasks: Dict[str, DownloadTask] = {}
        self.download_manager = MultiThreadDownloadManager(max_workers=4)
        self.settings = QSettings('HFDownloader', 'Config')

        self.init_ui()
        self.setup_connections()
        self.load_settings()
        self.load_tasks_from_file()  # 启动时加载任务

    def save_tasks_to_file(self, filename="tasks.json"):
        data = []
        for task in self.tasks.values():
            if task.status == "已完成":
                continue
            data.append({
                "repo_id": task.repo_id,
                "filename": task.filename,
                "local_dir": task.local_dir,
                "revision": task.revision,
                "status": task.status,
                "progress": task.progress,
                "size": task.size,
                "downloaded": task.downloaded,
                "speed": task.speed,
                "task_id": task.task_id,
            })
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存任务文件失败: {e}")

    def load_tasks_from_file(self, filename="tasks.json"):
        if not os.path.exists(filename):
            return
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                if item["status"] == "已完成":
                    continue
                task = DownloadTask(**item)
                # 检查本地文件实际大小
                local_file_path = os.path.join(task.local_dir, task.repo_id, task.filename)
                if os.path.exists(local_file_path):
                    file_size = os.path.getsize(local_file_path)
                    task.downloaded = file_size
                    if task.size > 0:
                        task.progress = (file_size / task.size) * 100
                        if file_size >= task.size:
                            task.status = "已完成"
                        elif task.status not in ["失败"]:
                            task.status = "待下载"
                    else:
                        task.progress = 0
                        if task.status not in ["失败"]:
                            task.status = "待下载"
                else:
                    # 文件不存在，重置进度
                    task.downloaded = 0
                    task.progress = 0
                    if task.status not in ["失败"]:
                        task.status = "待下载"

                self.tasks[task.task_id] = task
            self.update_task_table()
            self.update_overall_progress()
            self.log(f"已加载 {len(self.tasks)} 个历史任务")
        except Exception as e:
            self.log(f"加载任务文件失败: {e}")

    def init_ui(self):
        self.setWindowTitle("HuggingFace 模型下载器")
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

        # 控制按钮 - 优化布局
        control_layout = QHBoxLayout()

        # 下载控制按钮组
        download_controls = QHBoxLayout()
        self.start_btn = QPushButton("🚀 开始下载")
        self.start_btn.clicked.connect(self.start_download)
        download_controls.addWidget(self.start_btn)

        self.pause_btn = QPushButton("⏸️ 暂停下载")
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        download_controls.addWidget(self.pause_btn)

        self.remove_btn = QPushButton("❌ 移除选中")
        self.remove_btn.clicked.connect(self.remove_selected_tasks)
        download_controls.addWidget(self.remove_btn)

        control_layout.addLayout(download_controls)
        control_layout.addStretch()

        # 总进度显示
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("总进度:"))
        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimumWidth(200)
        progress_layout.addWidget(self.overall_progress)

        # 进度文本标签
        self.progress_label = QLabel("0/0")
        progress_layout.addWidget(self.progress_label)

        control_layout.addLayout(progress_layout)

        task_layout.addLayout(control_layout)
        task_group.setLayout(task_layout)
        layout.addWidget(task_group)

        # 日志区域
        log_group = QGroupBox("下载日志")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
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
        
        # Huggingface认证设置
        auth_group = QGroupBox("Huggingface认证")
        auth_layout = QVBoxLayout()
        
        # Token设置
        token_layout = QHBoxLayout()
        token_layout.addWidget(QLabel("Access Token:"))
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("输入Huggingface Access Token以访问私有模型")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)  # 密码模式显示
        token_layout.addWidget(self.token_input)
        
        # 显示/隐藏Token按钮
        self.toggle_token_btn = QPushButton("显示")
        self.toggle_token_btn.setMaximumWidth(60)
        self.toggle_token_btn.clicked.connect(self.toggle_token_visibility)
        token_layout.addWidget(self.toggle_token_btn)
        
        auth_layout.addLayout(token_layout)
        
        # 添加说明标签
        token_info = QLabel("注意: 访问令牌用于下载需要登录的私有模型，可从Huggingface网站的设置页面获取。")
        token_info.setWordWrap(True)
        token_info.setStyleSheet("color: #888; font-size: 11px;")
        auth_layout.addWidget(token_info)
        
        auth_group.setLayout(auth_layout)
        layout.addWidget(auth_group)

        layout.addStretch()
        widget.setLayout(layout)
        return widget
        
    def toggle_token_visibility(self):
        """切换Token显示/隐藏状态"""
        if self.token_input.echoMode() == QLineEdit.EchoMode.Password:
            self.token_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_token_btn.setText("隐藏")
        else:
            self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_token_btn.setText("显示")

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
            # 显示加载状态
            self.log("正在获取仓库文件列表...")
            self.browse_btn.setEnabled(False)
            self.browse_btn.setText("获取中...")
            
            # 获取token
            token = self.token_input.text().strip()

            # 使用树状文件选择对话框，传入token
            selected_files = HuggingfaceFileDialog.select_files_simple(
                self.repo_input.text(),
                self.revision_input.text(),
                token=token if token else None
            )

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
        self.save_tasks_to_file()
        self.log(f"已添加 {len(files)} 个下载任务")

    def clear_tasks(self):
        """清空任务队列"""
        if self.download_manager.is_active():
            QMessageBox.warning(self, "警告", "下载进行中，无法清空队列")
            return

        self.tasks.clear()
        self.update_task_table()
        self.save_tasks_to_file()
        self.log("已清空任务队列")

    def remove_selected_tasks(self):
        """移除选中的任务"""
        if self.download_manager.is_active():
            QMessageBox.warning(self, "警告", "下载进行中，无法移除任务")
            return

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
        self.save_tasks_to_file()
        self.log(f"已移除 {len(selected_rows)} 个任务")

    def update_task_table(self):
        """更新任务表格 - 优化版"""
        self.task_table.setRowCount(len(self.tasks))

        for i, (task_id, task) in enumerate(self.tasks.items()):
            # 仓库名
            repo_item = QTableWidgetItem(task.repo_id)
            self.task_table.setItem(i, 0, repo_item)

            # 文件名
            file_item = QTableWidgetItem(task.filename)
            self.task_table.setItem(i, 1, file_item)

            # 状态
            status_item = QTableWidgetItem(task.status)
            # 根据状态设置颜色
            if task.status == "已完成":
                status_item.setForeground(QColor(76, 175, 80))
            elif task.status == "失败":
                status_item.setForeground(QColor(244, 67, 54))
            elif task.status == "下载中":
                status_item.setForeground(QColor(33, 150, 243))
            elif task.status == "暂停":
                status_item.setForeground(QColor(255, 152, 0))
            self.task_table.setItem(i, 2, status_item)

            # 进度条
            progress_item = QTableWidgetItem(f"{task.progress:.1f}%")
            progress_item.setData(Qt.ItemDataRole.UserRole, task.progress)
            self.task_table.setItem(i, 3, progress_item)

            # 已下载
            downloaded_text = self.format_size(task.downloaded) if task.downloaded > 0 else "--"
            self.task_table.setItem(i, 4, QTableWidgetItem(downloaded_text))

            # 总大小
            size_text = self.format_size(task.size) if task.size > 0 else "--"
            self.task_table.setItem(i, 5, QTableWidgetItem(size_text))

            # 速度
            self.task_table.setItem(i, 6, QTableWidgetItem(task.speed))

            # 保存路径
            local_path = os.path.join(task.local_dir, task.repo_id)
            self.task_table.setItem(i, 7, QTableWidgetItem(local_path))

    def start_download(self):
        """开始下载 - 优化版"""
        if not self.tasks:
            QMessageBox.warning(self, "警告", "没有下载任务")
            return

        proxy_config = self.proxy_widget.get_config()
        
        # 获取token
        token = self.token_input.text().strip() if hasattr(self, 'token_input') else None

        # 包含待下载、失败和暂停状态的任务
        pending_tasks = [task for task in self.tasks.values()
                         if task.status in ["待下载", "失败", "暂停"]]

        if not pending_tasks:
            QMessageBox.information(self, "信息", "所有任务已完成")
            return

        # 开始下载前，更新所有待下载任务的状态
        for task in pending_tasks:
            if task.status in ["暂停", "待下载"]:
                task.status = "准备中"
            elif task.status == "失败":
                task.status = "准备中"

        self.update_task_table()

        # 传入token参数
        self.download_manager.start_downloads(pending_tasks, proxy_config, token)
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)

        self.log(f"开始下载 {len(pending_tasks)} 个任务...")

    def pause_download(self):
        """暂停下载"""
        self.download_manager.cancel_all()
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)

        # 只将正在下载的任务设为“暂停”，准备中的任务回退为“待下载”
        for task in self.tasks.values():
            if task.status == "下载中":
                task.status = "暂停"
            elif task.status == "准备中":
                task.status = "待下载"

        self.update_task_table()
        self.update_overall_progress()
        self.save_tasks_to_file()
        self.log("下载已暂停，可点击开始下载继续")

    def update_concurrent_downloads(self, value: int):
        """更新并发下载数"""
        self.download_manager.thread_pool.setMaxThreadCount(value)
        self.log(f"并发下载数已设置为: {value}")

    def on_task_started(self, task_id: str):
        """任务开始回调 - 优化版"""
        if task_id in self.tasks:
            self.tasks[task_id].status = "下载中"
            self.update_task_table()

    def on_progress_updated(self, task_id: str, progress: float, speed: str,
                            status: str, downloaded: int = None, total: int = None):
        """进度更新回调 - 优化版"""
        if task_id in self.tasks:
            task = self.tasks[task_id]

            # 更新任务信息
            task.progress = progress
            task.speed = speed
            task.status = status

            if downloaded is not None:
                task.downloaded = downloaded
            if total is not None and total > 0:
                task.size = total

            # 限制UI更新频率
            current_time = time.time()
            if not hasattr(self, '_last_ui_update') or current_time - self._last_ui_update > 0.2:
                self.update_task_table()
                self.update_overall_progress()
                self._last_ui_update = current_time

    def on_task_completed(self, task_id: str, success: bool, message: str):
        """任务完成回调 - 优化版"""
        self.log(message)

        if task_id in self.tasks:
            task = self.tasks[task_id]
            if success:
                task.status = "已完成"
                task.progress = 100.0
                task.speed = "完成"
            else:
                task.status = "失败"
                task.speed = "失败"

        self.update_task_table()
        self.update_overall_progress()
        self.save_tasks_to_file()

    def on_all_completed(self):
        """所有任务完成回调 - 优化版"""
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)

        # 显示完成统计
        completed_count = sum(1 for task in self.tasks.values() if task.status == "已完成")
        failed_count = sum(1 for task in self.tasks.values() if task.status == "失败")

        self.log(f"所有下载任务完成 - 成功: {completed_count}, 失败: {failed_count}")

        if failed_count == 0:
            QMessageBox.information(
                self, "下载完成",
                f"🎉 所有下载任务已成功完成！\n\n"
                f"✅ 成功: {completed_count} 个\n"
                f"📁 保存位置: {self.dir_input.text()}"
            )
        else:
            QMessageBox.warning(
                self, "下载完成",
                f"下载任务已完成！\n\n"
                f"✅ 成功: {completed_count} 个\n"
                f"❌ 失败: {failed_count} 个\n"
                f"💡 可重新点击开始下载重试失败的任务"
            )

    def update_overall_progress(self):
        """更新总进度 - 优化版"""
        if not self.tasks:
            self.overall_progress.setValue(0)
            self.progress_label.setText("0/0")
            return

        completed_count = sum(1 for task in self.tasks.values() if task.status == "已完成")
        total_count = len(self.tasks)

        # 计算总体进度
        total_progress = sum(task.progress for task in self.tasks.values())
        overall = total_progress / total_count if total_count > 0 else 0

        self.overall_progress.setValue(int(overall))
        self.progress_label.setText(f"{completed_count}/{total_count}")

    def log(self, message: str):
        """添加日志 - 优化版"""
        timestamp = time.strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.log_text.append(formatted_message)

        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        self.statusBar().showMessage(message)

    def format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes == 0:
            return "0 B"

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
        
        # 保存Huggingface Token
        self.settings.setValue("hf_token", self.token_input.text())

        # 保存代理设置
        proxy_config = self.proxy_widget.get_config()
        self.settings.setValue("proxy_enabled", proxy_config.get('enabled', False))
        self.settings.setValue("proxy_host", proxy_config.get('proxy_host', ''))
        self.settings.setValue("proxy_port", proxy_config.get('proxy_port', ''))
        self.save_tasks_to_file()

    def load_settings(self):
        """加载设置"""
        self.repo_input.setText(self.settings.value("repo_id", ""))
        self.dir_input.setText(self.settings.value("local_dir", "./downloads"))
        self.revision_input.setText(self.settings.value("revision", "main"))
        self.concurrent_spin.setValue(int(self.settings.value("concurrent_downloads", 4)))
        self.retry_spin.setValue(int(self.settings.value("retry_count", 3)))
        
        # 加载Huggingface Token
        self.token_input.setText(self.settings.value("hf_token", ""))

        self.proxy_widget.proxy_enabled.setChecked(bool(self.settings.value("proxy_enabled", False)))
        self.proxy_widget.proxy_host.setText(self.settings.value("proxy_host", ""))
        self.proxy_widget.proxy_port.setValue(int(self.settings.value("proxy_port", 7890)))

    def closeEvent(self, event):
        """关闭事件 - 优化版"""
        self.save_settings()

        # 检查是否有正在下载的任务
        if self.download_manager.is_active():
            reply = QMessageBox.question(
                self, "确认退出",
                "⚠️ 有下载正在进行中，确定要退出吗？\n\n"
                "💡 下载进度会被保存，下次启动时可以继续",
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
    app.setWindowIcon(QIcon(ICON_PATH))

    # 深色主题
    set_black_ui(app)

    window = HuggingFaceDownloader()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()