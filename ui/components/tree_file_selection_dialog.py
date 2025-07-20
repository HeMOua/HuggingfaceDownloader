import os
import json
from typing import List, Dict, Any, Optional, Callable, Union
from enum import Enum
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QLabel, QCheckBox,
                             QProgressBar, QStackedWidget, QHeaderView, QStyle, QDialog, QDialogButtonBox, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QFileInfo
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from huggingface_hub import HfApi


class SelectionMode(Enum):
    """选择模式枚举"""
    SINGLE = "single"  # 单选
    MULTI = "multi"  # 多选（按住Ctrl/Shift）
    CHECKBOX = "checkbox"  # 复选框多选
    NONE = "none"  # 不可选择


class IconProvider:
    """图标提供器"""

    def __init__(self):
        self._icon_cache = {}
        self._init_default_icons()

    def _init_default_icons(self):
        """初始化默认图标"""
        # 使用系统提供的标准图标
        style = QStyle.StandardPixmap

        # 文件夹图标
        self._icon_cache['folder'] = self._get_system_icon(style.SP_DirIcon)
        self._icon_cache['folder_open'] = self._get_system_icon(style.SP_DirOpenIcon)
        self._icon_cache['folder_hidden'] = self._create_hidden_folder_icon()

        # 通用文件图标
        self._icon_cache['file'] = self._get_system_icon(style.SP_FileIcon)
        self._icon_cache['file_hidden'] = self._create_hidden_file_icon()

        # 特定文件类型图标
        self._icon_cache['txt'] = self._create_text_icon()
        self._icon_cache['py'] = self._create_python_icon()
        self._icon_cache['js'] = self._create_javascript_icon()
        self._icon_cache['html'] = self._create_html_icon()
        self._icon_cache['css'] = self._create_css_icon()
        self._icon_cache['json'] = self._create_json_icon()
        self._icon_cache['xml'] = self._create_xml_icon()
        self._icon_cache['md'] = self._create_markdown_icon()
        self._icon_cache['jpg'] = self._get_system_icon(style.SP_FileDialogDetailedView)
        self._icon_cache['png'] = self._get_system_icon(style.SP_FileDialogDetailedView)
        self._icon_cache['gif'] = self._get_system_icon(style.SP_FileDialogDetailedView)
        self._icon_cache['pdf'] = self._create_pdf_icon()
        self._icon_cache['zip'] = self._create_archive_icon()
        self._icon_cache['rar'] = self._create_archive_icon()
        self._icon_cache['7z'] = self._create_archive_icon()

        # 特殊文件夹图标
        self._icon_cache['git'] = self._create_git_icon()
        self._icon_cache['idea'] = self._create_idea_icon()
        self._icon_cache['vscode'] = self._create_vscode_icon()
        self._icon_cache['node_modules'] = self._create_node_modules_icon()

    def _get_system_icon(self, icon_type) -> QIcon:
        """获取系统图标"""
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                return app.style().standardIcon(icon_type)
        except:
            pass
        return QIcon()

    def _create_colored_icon(self, text: str, color: QColor, size: int = 16) -> QIcon:
        """创建带颜色的文本图标"""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制背景圆角矩形
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, 2, 2)

        # 绘制文本
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)

        painter.end()
        return QIcon(pixmap)

    def _create_text_icon(self) -> QIcon:
        return self._create_colored_icon("TXT", QColor(100, 100, 100))

    def _create_python_icon(self) -> QIcon:
        return self._create_colored_icon("PY", QColor(55, 118, 171))

    def _create_javascript_icon(self) -> QIcon:
        return self._create_colored_icon("JS", QColor(240, 219, 79))

    def _create_html_icon(self) -> QIcon:
        return self._create_colored_icon("HTML", QColor(227, 79, 38))

    def _create_css_icon(self) -> QIcon:
        return self._create_colored_icon("CSS", QColor(21, 114, 182))

    def _create_json_icon(self) -> QIcon:
        return self._create_colored_icon("JSON", QColor(255, 204, 84))

    def _create_xml_icon(self) -> QIcon:
        return self._create_colored_icon("XML", QColor(255, 153, 0))

    def _create_markdown_icon(self) -> QIcon:
        return self._create_colored_icon("MD", QColor(0, 0, 0))

    def _create_pdf_icon(self) -> QIcon:
        return self._create_colored_icon("PDF", QColor(220, 53, 69))

    def _create_archive_icon(self) -> QIcon:
        return self._create_colored_icon("ZIP", QColor(108, 117, 125))

    def _create_git_icon(self) -> QIcon:
        return self._create_colored_icon("GIT", QColor(240, 80, 50))

    def _create_idea_icon(self) -> QIcon:
        return self._create_colored_icon("IDE", QColor(255, 99, 71))

    def _create_vscode_icon(self) -> QIcon:
        return self._create_colored_icon("VSC", QColor(0, 120, 215))

    def _create_node_modules_icon(self) -> QIcon:
        return self._create_colored_icon("NPM", QColor(203, 56, 55))

    def _create_hidden_folder_icon(self) -> QIcon:
        return self._create_colored_icon("◯", QColor(150, 150, 150))

    def _create_hidden_file_icon(self) -> QIcon:
        return self._create_colored_icon("◯", QColor(120, 120, 120))

    def get_icon(self, file_info) -> QIcon:
        """根据文件信息获取图标"""
        is_hidden = file_info.name.startswith('.')

        if file_info.is_dir:
            # 特殊文件夹图标
            folder_name = file_info.name.lower()
            if folder_name == '.git':
                return self._icon_cache.get('git', self._icon_cache.get('folder', QIcon()))
            elif folder_name in ['.idea', '.vscode']:
                return self._icon_cache.get('idea', self._icon_cache.get('folder', QIcon()))
            elif folder_name == 'node_modules':
                return self._icon_cache.get('node_modules', self._icon_cache.get('folder', QIcon()))
            elif is_hidden:
                return self._icon_cache.get('folder_hidden', self._icon_cache.get('folder', QIcon()))
            else:
                return self._icon_cache.get('folder', QIcon())

        # 文件图标
        if is_hidden:
            return self._icon_cache.get('file_hidden', self._icon_cache.get('file', QIcon()))

        # 根据文件扩展名获取图标
        ext = os.path.splitext(file_info.name)[1].lower().lstrip('.')

        # 图片文件
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp']:
            return self._icon_cache.get('png', self._icon_cache.get('file', QIcon()))

        # 压缩文件
        if ext in ['zip', 'rar', '7z', 'tar', 'gz', 'bz2']:
            return self._icon_cache.get('zip', self._icon_cache.get('file', QIcon()))

        # 特定文件类型
        if ext in self._icon_cache:
            return self._icon_cache[ext]

        # 默认文件图标
        return self._icon_cache.get('file', QIcon())


class FileInfo:
    """文件信息数据类"""

    def __init__(self, path: str, size: int = 0, modified_time: str = "",
                 file_type: str = "", selected: bool = False, **kwargs):
        self.path = path
        self.size = size
        self.modified_time = modified_time
        self.file_type = file_type
        self.selected = selected  # 选中状态
        self.extra_data = kwargs

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def is_dir(self) -> bool:
        return self.file_type == "directory" or self.path.endswith('/')

    @property
    def is_hidden(self) -> bool:
        """判断是否为隐藏文件/文件夹"""
        return self.name.startswith('.')

    def size_formatted(self) -> str:
        """格式化文件大小"""
        return self.format_size(self.size)

    @staticmethod
    def format_size(size):
        """静态方法格式化文件大小"""
        if size == 0:
            return "0 B"
        size = size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"


class DataLoader(QThread):
    """数据加载线程"""
    data_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, loader_func: Callable, *args, **kwargs):
        super().__init__()
        self.loader_func = loader_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            data = self.loader_func(*self.args, **self.kwargs)
            self.data_loaded.emit(data)
        except Exception as e:
            self.error_occurred.emit(str(e))


class FileTreeWidget(QWidget):
    """通用文件树控件基类"""

    # 信号
    file_selected = pyqtSignal(FileInfo)  # 单个文件选中
    files_selected = pyqtSignal(list)  # 多个文件选中
    selection_changed = pyqtSignal(list)  # 选择变化
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()

    def __init__(self,
                 selection_mode: SelectionMode = SelectionMode.SINGLE,
                 enable_drag_drop: bool = False,
                 show_hidden_files: bool = True,  # 默认显示隐藏文件
                 show_file_icons: bool = True,
                 expandable_by_default: bool = True,
                 show_toolbar: bool = True,
                 show_size_column: bool = True,
                 show_date_column: bool = True,
                 show_type_column: bool = True,
                 auto_check_children: bool = True,  # 新增：是否自动勾选子项
                 enable_simple_loading: bool = True,
                 parent=None):
        super().__init__(parent)

        # 构造方法属性
        self.selection_mode = selection_mode
        self.enable_drag_drop = enable_drag_drop
        self.show_hidden_files = show_hidden_files
        self.show_file_icons = show_file_icons
        self.expandable_by_default = expandable_by_default
        self.show_toolbar = show_toolbar
        self.show_size_column = show_size_column
        self.show_date_column = show_date_column
        self.show_type_column = show_type_column
        self.auto_check_children = auto_check_children

        # 配置属性
        self.enable_simple_loading = enable_simple_loading  # 是否启用简单数据预加载
        self.auto_refresh_interval = 0  # 自动刷新间隔(秒)，0表示不自动刷新

        # 图标提供器
        self.icon_provider = IconProvider() if show_file_icons else None

        # 内部数据
        self._current_data = []
        self._is_loading = False
        self._current_params = {}  # 当前加载参数
        self._selected_files = []  # 当前选中的文件列表
        self._updating_check_state = False  # 防止递归更新标志
        self._expand_status = False  # 展开状态

        # 线程
        self._simple_loader = None
        self._detail_loader = None

        # 定时器
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self.refresh)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)

        # 工具栏
        if self.show_toolbar:
            toolbar_layout = QHBoxLayout()

            self.refresh_btn = QPushButton("刷新")
            self.refresh_btn.clicked.connect(self.refresh)

            # 隐藏文件切换按钮
            self.show_hidden_cb = QCheckBox("显示隐藏文件")
            self.show_hidden_cb.setChecked(self.show_hidden_files)
            self.show_hidden_cb.toggled.connect(self._on_show_hidden_toggled)

            # 选择模式相关控件
            if self.selection_mode == SelectionMode.CHECKBOX:
                self.select_all_cb = QCheckBox("全选")
                self.select_all_cb.toggled.connect(self._on_select_all_toggled)
                toolbar_layout.addWidget(self.select_all_cb)

                self.clear_selection_btn = QPushButton("清空选择")
                self.clear_selection_btn.clicked.connect(self.clear_selection)
                toolbar_layout.addWidget(self.clear_selection_btn)

                self.toggle_expand_btn = QPushButton("展开全部")
                self.toggle_expand_btn.clicked.connect(self.toggle_expand_status)
                toolbar_layout.addWidget(self.toggle_expand_btn)

            # 选择信息标签
            self.selection_info_label = QLabel("已选择: 0 项")

            self.total_size_label = QLabel("总大小: 0 B")

            toolbar_layout.addWidget(self.refresh_btn)
            toolbar_layout.addWidget(self.show_hidden_cb)
            toolbar_layout.addWidget(self.selection_info_label)
            toolbar_layout.addWidget(self.total_size_label)
            toolbar_layout.addStretch()

            layout.addLayout(toolbar_layout)

        # 主显示区域 - 使用堆叠窗口
        self.stacked_widget = QStackedWidget()

        # 加载页面
        self.loading_widget = self._create_loading_widget()
        self.stacked_widget.addWidget(self.loading_widget)

        # 树形控件页面
        self.tree_widget = self._create_tree_widget()
        self.stacked_widget.addWidget(self.tree_widget)

        layout.addWidget(self.stacked_widget)

        # 默认显示树形控件
        self.stacked_widget.setCurrentWidget(self.tree_widget)

    def _create_loading_widget(self) -> QWidget:
        """创建加载界面"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addStretch()

        # 加载标签
        self.loading_label = QLabel("正在加载文件列表...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 无限进度条

        layout.addWidget(self.loading_label)
        layout.addWidget(self.progress_bar)
        layout.addStretch()

        return widget

    def _create_tree_widget(self) -> QTreeWidget:
        """创建树形控件"""
        tree = QTreeWidget()

        # 设置列标题
        headers = ["名称"]
        if self.show_size_column:
            headers.append("大小")
        if self.show_date_column:
            headers.append("修改时间")
        if self.show_type_column:
            headers.append("类型")

        tree.setHeaderLabels(headers)

        # 设置选择模式
        if self.selection_mode == SelectionMode.SINGLE:
            tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        elif self.selection_mode == SelectionMode.MULTI:
            tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        elif self.selection_mode == SelectionMode.CHECKBOX:
            tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        elif self.selection_mode == SelectionMode.NONE:
            tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)

        # 连接信号
        if self.selection_mode != SelectionMode.NONE:
            tree.itemClicked.connect(self._on_item_clicked)
            if self.selection_mode == SelectionMode.MULTI:
                tree.itemSelectionChanged.connect(self._on_selection_changed)
            elif self.selection_mode == SelectionMode.CHECKBOX:
                tree.itemChanged.connect(self._on_item_changed)
        
        # 连接展开/收缩事件
        tree.itemExpanded.connect(self._on_item_expanded)
        tree.itemCollapsed.connect(self._on_item_collapsed)

        # 设置拖拽
        if self.enable_drag_drop:
            tree.setDragEnabled(True)
            tree.setAcceptDrops(True)
            tree.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)

        # 设置列宽
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        col_index = 1
        if self.show_size_column:
            header.setSectionResizeMode(col_index, QHeaderView.ResizeMode.ResizeToContents)
            col_index += 1
        if self.show_date_column:
            header.setSectionResizeMode(col_index, QHeaderView.ResizeMode.ResizeToContents)
            col_index += 1
        if self.show_type_column:
            header.setSectionResizeMode(col_index, QHeaderView.ResizeMode.ResizeToContents)

        return tree

    def _connect_signals(self):
        """连接信号"""
        self.loading_started.connect(self._on_loading_started)
        self.loading_finished.connect(self._on_loading_finished)

    def _update_selection_info(self):
        """更新选择信息显示"""
        total_files = len([item for item in self._current_data if not item.is_dir])
        selected_files = self.get_all_selected_files()
        selected_count = len(selected_files)
        self.selection_info_label.setText(f"已选择: {selected_count} / {total_files} 个文件")

        # 计算选中文件的总大小
        total_size = 0
        for file in selected_files:
            total_size += file.size

        self.total_size_label.setText("总大小: " + FileInfo.format_size(total_size))

    def _on_show_hidden_toggled(self, enabled: bool):
        """显示隐藏文件切换"""
        self.show_hidden_files = enabled
        # 重新加载数据以应用新的显示设置
        if self._current_data:
            self._populate_tree(self._current_data)

    def _on_select_all_toggled(self, checked: bool):
        """全选/取消全选"""
        if self.selection_mode == SelectionMode.CHECKBOX:
            self._updating_check_state = True
            self._set_all_items_checked(self.tree_widget.invisibleRootItem(), checked)
            self._updating_check_state = False
            self._update_selected_files()

    def _set_all_items_checked(self, parent_item, checked: bool):
        """递归设置所有项的选中状态"""
        for i in range(parent_item.childCount()):
            item = parent_item.child(i)
            if checked:
                item.setCheckState(0, Qt.CheckState.Checked)
            else:
                item.setCheckState(0, Qt.CheckState.Unchecked)
            self._set_all_items_checked(item, checked)

    def _on_loading_started(self):
        """加载开始"""
        self._is_loading = True
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setEnabled(False)
        self.stacked_widget.setCurrentWidget(self.loading_widget)

    def _on_loading_finished(self):
        """加载完成"""
        self._is_loading = False
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setEnabled(True)
        self.stacked_widget.setCurrentWidget(self.tree_widget)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """树形项点击事件"""
        file_info = item.data(0, Qt.ItemDataRole.UserRole)
        if not file_info:
            return

        if self.selection_mode == SelectionMode.SINGLE:
            self._selected_files = [file_info]
            self.file_selected.emit(file_info)
            self.selection_changed.emit(self._selected_files)
            self._update_selection_info()
        elif self.selection_mode == SelectionMode.CHECKBOX:
            # 复选框模式下点击会触发 _on_item_changed，这里不需要处理
            pass

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """树形项状态变化事件（复选框模式）"""
        if self._updating_check_state or column != 0:
            return

        self._updating_check_state = True

        try:
            # 获取当前项的选中状态
            current_state = item.checkState(0)

            # 如果启用了自动勾选子项功能
            if self.auto_check_children:
                # 设置所有子项的状态与当前项一致
                self._set_children_check_state(item, current_state)

            # 更新父项的状态
            self._update_parent_check_state(item)

        finally:
            self._updating_check_state = False

        # 更新选中文件列表
        self._update_selected_files()

    def _set_children_check_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        """设置所有子项的勾选状态"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, state)
            # 递归设置子项的子项
            self._set_children_check_state(child, state)

    def _update_parent_check_state(self, item: QTreeWidgetItem):
        """更新父项的勾选状态"""
        parent = item.parent()
        if not parent:
            return

        # 检查同级项的状态
        checked_count = 0
        unchecked_count = 0
        partial_count = 0

        for i in range(parent.childCount()):
            child = parent.child(i)
            state = child.checkState(0)
            if state == Qt.CheckState.Checked:
                checked_count += 1
            elif state == Qt.CheckState.Unchecked:
                unchecked_count += 1
            else:  # PartiallyChecked
                partial_count += 1

        # 根据子项状态设置父项状态
        if partial_count > 0 or (checked_count > 0 and unchecked_count > 0):
            # 部分选中
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        elif checked_count > 0 and unchecked_count == 0:
            # 全部选中
            parent.setCheckState(0, Qt.CheckState.Checked)
        else:
            # 全部未选中
            parent.setCheckState(0, Qt.CheckState.Unchecked)

        # 递归更新上级父项
        self._update_parent_check_state(parent)

    def _on_selection_changed(self):
        """选择变化事件（多选模式）"""
        if self.selection_mode == SelectionMode.MULTI:
            selected_items = self.tree_widget.selectedItems()
            self._selected_files = []
            for item in selected_items:
                file_info = item.data(0, Qt.ItemDataRole.UserRole)
                if file_info:
                    self._selected_files.append(file_info)

            self.files_selected.emit(self._selected_files)
            self.selection_changed.emit(self._selected_files)
            self._update_selection_info()

    def _update_selected_files(self):
        """更新选中文件列表（复选框模式）"""
        if self.selection_mode == SelectionMode.CHECKBOX:
            self._selected_files = []
            self._collect_checked_items(self.tree_widget.invisibleRootItem())
            self.files_selected.emit(self._selected_files)
            self.selection_changed.emit(self._selected_files)
            self._update_selection_info()

    def _collect_checked_items(self, parent_item):
        """递归收集选中的项 - 修复计数问题"""
        for i in range(parent_item.childCount()):
            item = parent_item.child(i)
            state = item.checkState(0)
            file_info = item.data(0, Qt.ItemDataRole.UserRole)

            if state == Qt.CheckState.Checked and file_info:
                # 如果项目被完全勾选，添加该项目
                self._selected_files.append(file_info)
                # 如果是文件夹且启用了自动勾选子项，则不需要递归收集子项
                # 因为父项被选中意味着所有子项都被选中，但我们只记录被直接勾选的项
                if not self.auto_check_children or not file_info.is_dir:
                    # 如果没有启用自动勾选或者不是文件夹，继续检查子项
                    self._collect_checked_items(item)
            elif state == Qt.CheckState.PartiallyChecked:
                # 如果是部分选中状态，需要检查子项
                self._collect_checked_items(item)
            # state == Qt.CheckState.Unchecked 的情况不需要处理

    def _collect_all_checked_files(self, parent_item, include_folders: bool = False) -> List[FileInfo]:
        """收集所有实际被勾选的文件和文件夹（包括通过父项间接选中的）"""
        result = []

        def collect_recursive(item, parent_checked=False):
            state = item.checkState(0)
            file_info = item.data(0, Qt.ItemDataRole.UserRole)

            current_checked = (state == Qt.CheckState.Checked) or parent_checked

            if current_checked and file_info:
                if include_folders or not file_info.is_dir:
                    result.append(file_info)

            # 判断是否需要继续递归子项
            if item.childCount() > 0:
                for j in range(item.childCount()):
                    child = item.child(j)
                    # 如果自动勾选子项，并且当前是 Checked，则子项也算勾选
                    collect_recursive(child, current_checked if self.auto_check_children else False)
            elif state == Qt.CheckState.PartiallyChecked:
                # 只有部分选中时，强制递归其子项
                for j in range(item.childCount()):
                    collect_recursive(item.child(j), False)

        for i in range(parent_item.childCount()):
            collect_recursive(parent_item.child(i))

        return result

    def get_all_selected_files(self) -> List[FileInfo]:
        """获取所有实际被选中的文件和文件夹（包括通过父项间接选中的）"""
        if self.selection_mode == SelectionMode.CHECKBOX:
            return self._collect_all_checked_files(self.tree_widget.invisibleRootItem())
        else:
            return self._selected_files.copy()

    def get_simple_file_list(self, **params) -> List[str]:
        """
        获取简单文件列表（仅路径）
        子类需要重写此方法
        """
        raise NotImplementedError("子类必须实现 get_simple_file_list 方法")

    def get_detailed_file_list(self, **params) -> List[FileInfo]:
        """
        获取详细文件列表
        子类需要重写此方法
        """
        raise NotImplementedError("子类必须实现 get_detailed_file_list 方法")

    def load_data(self, force_refresh: bool = False, **params):
        """
        加载数据
        :param force_refresh: 是否强制刷新
        :param params: 加载参数
        """
        if self._is_loading:
            return

        # 保存当前参数
        self._current_params = params

        self.loading_started.emit()

        if self.enable_simple_loading:
            # 先加载简单数据
            self._load_simple_data_async()
        else:
            # 直接加载详细数据
            self._load_detailed_data_async()

    def _load_simple_data_async(self):
        """异步加载简单数据"""
        self.loading_label.setText("正在快速加载文件列表...")

        self._simple_loader = DataLoader(self.get_simple_file_list, **self._current_params)
        self._simple_loader.data_loaded.connect(self._on_simple_data_loaded)
        self._simple_loader.error_occurred.connect(self._on_data_error)
        self._simple_loader.start()

    def _load_detailed_data_async(self):
        """异步加载详细数据"""
        self.loading_label.setText("正在加载详细文件信息...")

        self._detail_loader = DataLoader(self.get_detailed_file_list, **self._current_params)
        self._detail_loader.data_loaded.connect(self._on_detailed_data_loaded)
        self._detail_loader.error_occurred.connect(self._on_data_error)
        self._detail_loader.start()

    def _on_simple_data_loaded(self, data: List[str]):
        """简单数据加载完成"""
        # 转换为FileInfo对象
        file_infos = [FileInfo(path) for path in data]
        self._populate_tree_simple(file_infos)

        # 显示树形控件
        self.stacked_widget.setCurrentWidget(self.tree_widget)

        # 继续加载详细数据
        self._load_detailed_data_async()

    def _on_detailed_data_loaded(self, data: List[FileInfo]):
        """详细数据加载完成"""
        self._current_data = data
        self._populate_tree(data)
        self.loading_finished.emit()

    def _on_data_error(self, error_msg: str):
        """数据加载错误"""
        self.loading_label.setText(f"加载失败: {error_msg}")
        self.loading_finished.emit()

    def _populate_tree_simple(self, file_infos: List[FileInfo]):
        """使用简单数据填充树形控件"""
        self.tree_widget.clear()
        tree_dict = self._build_tree_structure(file_infos)
        self._add_tree_items(tree_dict, self.tree_widget)

    def _populate_tree(self, file_infos: List[FileInfo]):
        """使用详细数据填充树形控件"""
        self.tree_widget.clear()
        self._current_data = file_infos
        tree_dict = self._build_tree_structure(file_infos)
        self._add_tree_items(tree_dict, self.tree_widget)

        # 清空选择
        self._selected_files = []
        self._update_selection_info()
        
        # 重置展开状态
        self._expand_status = False
        if hasattr(self, 'toggle_expand_btn'):
            self.toggle_expand_btn.setText("展开全部")

    @staticmethod
    def sort_tree_items(items: List[FileInfo]) -> List[FileInfo]:
        """自定义排序：文件夹在前，文件在后，同类型按字母序"""
        folders = []
        files = []

        for item in items:
            if item.is_dir:
                folders.append(item)
            else:
                files.append(item)

        # 分别对文件夹和文件进行字母排序
        folders.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())

        # 文件夹在前，文件在后
        return folders + files

    def _build_tree_structure(self, file_infos: List[FileInfo]) -> Dict:
        """构建树形结构"""
        tree_dict = {}

        # 首先添加所有文件夹
        folders = set()
        for file_info in file_infos:
            # 应用隐藏文件过滤
            if not self.show_hidden_files and file_info.is_hidden:
                continue

            parts = file_info.path.strip('/').split('/')
            # 创建文件夹路径
            for i in range(len(parts) - 1):
                folder_path = '/'.join(parts[:i + 1])
                folders.add(folder_path)

        # 为文件夹创建FileInfo对象
        for folder_path in folders:
            folder_info = FileInfo(
                path=folder_path,
                file_type="directory",
                size=0,
                modified_time=""
            )
            # 检查文件夹是否应该被显示
            if self.show_hidden_files or not folder_info.is_hidden:
                file_infos.append(folder_info)

        file_infos = self.sort_tree_items(file_infos)

        # 构建树形结构
        for file_info in file_infos:
            # 应用隐藏文件过滤
            if not self.show_hidden_files and file_info.is_hidden:
                continue

            parts = file_info.path.strip('/').split('/')
            current_level = tree_dict

            for i, part in enumerate(parts):
                if part not in current_level:
                    current_level[part] = {
                        '_children': {},
                        '_file_info': None
                    }

                if i == len(parts) - 1:
                    # 叶子节点
                    current_level[part]['_file_info'] = file_info

                current_level = current_level[part]['_children']

        return tree_dict

    def _add_tree_items(self, tree_dict: Dict, parent):
        """递归添加树形项"""
        for name, node in tree_dict.items():
            item = QTreeWidgetItem(parent)
            file_info = node['_file_info']

            # 设置显示文本
            item.setText(0, name)

            # 设置复选框
            if self.selection_mode == SelectionMode.CHECKBOX:
                item.setCheckState(0, Qt.CheckState.Unchecked)

            if file_info:
                # 设置图标
                if self.show_file_icons and self.icon_provider:
                    icon = self.icon_provider.get_icon(file_info)
                    item.setIcon(0, icon)

                # 设置隐藏文件的视觉样式
                if file_info.is_hidden:
                    font = item.font(0)
                    font.setItalic(True)
                    item.setFont(0, font)
                    # 设置较淡的颜色
                    item.setForeground(0, QColor(128, 128, 128))

                col_index = 1
                if self.show_size_column:
                    item.setText(col_index, file_info.size_formatted())
                    col_index += 1
                if self.show_date_column:
                    item.setText(col_index, file_info.modified_time)
                    col_index += 1
                if self.show_type_column:
                    display_type = "文件夹" if file_info.is_dir else file_info.file_type
                    if file_info.is_hidden:
                        display_type += " (隐藏文件)"
                    item.setText(col_index, display_type)

                item.setData(0, Qt.ItemDataRole.UserRole, file_info)

            # 递归添加子项
            if node['_children']:
                self._add_tree_items(node['_children'], item)
                if self.expandable_by_default:
                    item.setExpanded(True)  # 默认展开文件夹

    def refresh(self):
        """刷新数据"""
        self.load_data(force_refresh=True, **self._current_params)

    def set_auto_refresh(self, interval_seconds: int):
        """设置自动刷新间隔"""
        self.auto_refresh_interval = interval_seconds

        if interval_seconds > 0:
            self._refresh_timer.start(interval_seconds * 1000)
        else:
            self._refresh_timer.stop()

    def get_selected_files(self) -> List[FileInfo]:
        """获取当前直接选中的文件列表（不包括通过父项间接选中的）"""
        return self._selected_files.copy()

    def get_selected_file(self) -> Optional[FileInfo]:
        """获取当前选中的第一个文件"""
        if self._selected_files:
            return self._selected_files[0]
        return None

    def clear_selection(self):
        """清空选择"""
        if self.selection_mode == SelectionMode.CHECKBOX:
            self._updating_check_state = True
            self._set_all_items_checked(self.tree_widget.invisibleRootItem(), False)
            self._updating_check_state = False
            if hasattr(self, 'select_all_cb'):
                self.select_all_cb.setChecked(False)
        elif self.selection_mode == SelectionMode.MULTI:
            self.tree_widget.clearSelection()
        elif self.selection_mode == SelectionMode.SINGLE:
            self.tree_widget.clearSelection()

        self._selected_files = []
        self._update_selection_info()

    def select_files(self, file_paths: List[str]):
        """根据路径选择文件"""
        if self.selection_mode == SelectionMode.NONE:
            return

        def find_and_select_item(parent_item, remaining_paths):
            for i in range(parent_item.childCount()):
                item = parent_item.child(i)
                file_info = item.data(0, Qt.ItemDataRole.UserRole)

                if file_info and file_info.path in remaining_paths:
                    if self.selection_mode == SelectionMode.CHECKBOX:
                        item.setCheckState(0, Qt.CheckState.Checked)
                    elif self.selection_mode == SelectionMode.SINGLE:
                        self.tree_widget.setCurrentItem(item)
                    elif self.selection_mode == SelectionMode.MULTI:
                        item.setSelected(True)

                find_and_select_item(item, remaining_paths)

        find_and_select_item(self.tree_widget.invisibleRootItem(), file_paths)

        if self.selection_mode == SelectionMode.CHECKBOX:
            self._update_selected_files()
        elif self.selection_mode == SelectionMode.MULTI:
            self._on_selection_changed()

    def toggle_expand_status(self):
        """切换展开/收缩状态"""
        if self._expand_status:
            # 当前是展开状态，执行收缩
            self.tree_widget.collapseAll()
            self.toggle_expand_btn.setText("展开全部")
            self._expand_status = False
        else:
            # 当前是收缩状态，执行展开
            self.tree_widget.expandAll()
            self.toggle_expand_btn.setText("收起全部")
            self._expand_status = True

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """项目展开事件"""
        # 检查是否所有项目都已展开
        self._check_expand_status()

    def _on_item_collapsed(self, item: QTreeWidgetItem):
        """项目收缩事件"""
        # 检查是否所有项目都已收缩
        self._check_expand_status()

    def _check_expand_status(self):
        """检查并更新展开状态"""
        if not hasattr(self, 'toggle_expand_btn'):
            return
            
        # 检查是否所有项目都已展开
        all_expanded = self._are_all_items_expanded(self.tree_widget.invisibleRootItem())
        
        if all_expanded != self._expand_status:
            self._expand_status = all_expanded
            if all_expanded:
                self.toggle_expand_btn.setText("收起全部")
            else:
                self.toggle_expand_btn.setText("展开全部")

    def _are_all_items_expanded(self, parent_item: QTreeWidgetItem) -> bool:
        """递归检查所有项目是否都已展开"""
        for i in range(parent_item.childCount()):
            item = parent_item.child(i)
            # 如果项目有子项但未展开，返回False
            if item.childCount() > 0 and not item.isExpanded():
                return False
            # 递归检查子项
            if not self._are_all_items_expanded(item):
                return False
        return True

    def set_selection_mode(self, mode: SelectionMode):
        """动态设置选择模式"""
        self.selection_mode = mode

        # 重新创建树形控件
        old_tree = self.tree_widget
        self.tree_widget = self._create_tree_widget()
        self.stacked_widget.removeWidget(old_tree)
        self.stacked_widget.addWidget(self.tree_widget)
        old_tree.deleteLater()

        # 重新填充数据
        if self._current_data:
            self._populate_tree(self._current_data)


class LocalFileTreeWidget(FileTreeWidget):
    """示例实现类"""

    def __init__(self,
                 root_path: str = ".",
                 selection_mode: SelectionMode = SelectionMode.SINGLE,
                 **kwargs):
        self.root_path = root_path
        super().__init__(selection_mode=selection_mode, **kwargs)

    def get_simple_file_list(self, **params) -> List[str]:
        """获取简单文件列表"""
        import time
        time.sleep(0.5)  # 模拟网络延迟

        # 支持过滤参数
        extensions = params.get('extensions', None)
        max_depth = params.get('max_depth', None)

        file_list = []
        for root, dirs, files in os.walk(self.root_path):
            # 深度限制
            if max_depth is not None:
                depth = root.replace(self.root_path, '').count(os.sep)
                if depth >= max_depth:
                    dirs.clear()  # 不再深入子目录
                    continue

            # 处理文件夹（包括隐藏文件夹）
            for dir_name in dirs[:]:  # 使用切片复制，因为可能会修改原列表
                dir_path = os.path.join(root, dir_name)
                rel_path = os.path.relpath(dir_path, self.root_path)
                # 隐藏文件夹过滤逻辑在 _build_tree_structure 中处理
                # 这里不过滤，让所有文件夹都能被发现

            for file in files:
                # 扩展名过滤
                if extensions and not any(file.endswith(ext) for ext in extensions):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.root_path)
                file_list.append(rel_path.replace('\\', '/'))

        return file_list

    def get_detailed_file_list(self, **params) -> List[FileInfo]:
        """获取详细文件列表"""
        import time
        time.sleep(1.0)  # 模拟更长的加载时间

        # 支持过滤参数
        extensions = params.get('extensions', None)
        max_depth = params.get('max_depth', None)

        file_list = []

        # 首先遍历并添加所有文件夹
        for root, dirs, files in os.walk(self.root_path):
            # 深度限制
            if max_depth is not None:
                depth = root.replace(self.root_path, '').count(os.sep)
                if depth >= max_depth:
                    dirs.clear()
                    continue

            # 添加当前文件夹（如果不是根目录）
            if root != self.root_path:
                rel_path = os.path.relpath(root, self.root_path)
                try:
                    stat = os.stat(root)
                    modified_time = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(stat.st_mtime)
                    )

                    folder_info = FileInfo(
                        path=rel_path.replace('\\', '/'),
                        size=0,
                        modified_time=modified_time,
                        file_type="directory"
                    )
                    file_list.append(folder_info)
                except OSError:
                    continue

            # 处理文件
            for file in files:
                # 扩展名过滤
                if extensions and not any(file.endswith(ext) for ext in extensions):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.root_path)

                try:
                    stat = os.stat(file_path)
                    size = stat.st_size
                    modified_time = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(stat.st_mtime)
                    )

                    file_info = FileInfo(
                        path=rel_path.replace('\\', '/'),
                        size=size,
                        modified_time=modified_time,
                        file_type="file"
                    )
                    file_list.append(file_info)
                except OSError:
                    continue

        return file_list


class HuggingfaceFileTreeWidget(FileTreeWidget):
    """Hugging Face 数据提供者"""

    def __init__(self, repo_id: str, revision: str = "main", token: Optional[str] = None,
                 selection_mode: SelectionMode = SelectionMode.CHECKBOX, **kwargs):
        """
        初始化 Hugging Face 数据提供者

        Args:
            repo_id: 仓库ID，格式如 "username/model-name"
            revision: 分支或标签，默认为 "main"
            token: Hugging Face 访问令牌（可选）
        """
        self.repo_id = repo_id
        self.revision = revision
        self.api = HfApi(token=token)
        super().__init__(selection_mode=selection_mode, **kwargs)

    def get_simple_file_list(self) -> List[str]:
        """
        获取简单文件路径列表（快速获取）

        如果 enable_simple_preload 为 False，则直接从详细信息中提取路径列表

        Returns:
            文件路径列表
        """
        try:
            # 快速获取文件列表，不包含详细元数据
            repo_info = self.api.model_info(
                repo_id=self.repo_id,
                revision=self.revision,
                files_metadata=False
            )

            file_paths = []
            if hasattr(repo_info, 'siblings') and repo_info.siblings:
                for sibling in repo_info.siblings:
                    if hasattr(sibling, 'rfilename'):
                        file_paths.append(sibling.rfilename)

            return file_paths

        except Exception as e:
            print(f"获取简单文件列表失败: {e}")
            return []

    def get_detailed_file_list(self) -> List[FileInfo]:
        """
        获取详细文件信息（可能较慢）

        Returns:
            详细文件信息列表
        """

        try:
            # 获取包含详细元数据的仓库信息
            repo_info = self.api.model_info(
                repo_id=self.repo_id,
                revision=self.revision,
                files_metadata=True
            )

            detailed_info = []
            if hasattr(repo_info, 'siblings') and repo_info.siblings:
                for sibling in repo_info.siblings:
                    file_info = self._convert_sibling_to_file_info(sibling)
                    if file_info:
                        detailed_info.append(file_info)

            return detailed_info

        except Exception as e:
            print(f"获取详细文件信息失败: {e}")
            # 如果获取详细信息失败，并且启用了简单预加载，返回简单信息
            return []

    def _convert_sibling_to_file_info(self, sibling) -> Optional[FileInfo]:
        """
        将 RepoSibling 转换为 FileInfo

        Args:
            sibling: RepoSibling 对象

        Returns:
            FileInfo 对象或 None
        """
        try:
            # 获取基本信息
            path = getattr(sibling, 'rfilename', '')
            if not path:
                return None

            # 文件大小
            size = getattr(sibling, 'size', 0)

            # 如果有 LFS 信息，使用 LFS 的大小
            if hasattr(sibling, 'lfs') and sibling.lfs:
                lfs_size = getattr(sibling.lfs, 'size', 0)
                if lfs_size > 0:
                    size = lfs_size

            # 文件类型
            file_type = self._get_file_type(path)

            # 是否为目录（在 Hugging Face 中，通常都是文件）
            is_directory = False

            # 修改时间（Hugging Face API 可能不提供，使用当前时间作为占位符）
            modified_time = self._get_modified_time(sibling)

            return FileInfo(
                path=path,
                size=size,
                modified_time=modified_time,
                file_type=file_type,
                is_directory=is_directory
            )

        except Exception as e:
            print(f"转换文件信息失败 {getattr(sibling, 'rfilename', 'unknown')}: {e}")
            return None

    def _get_file_type(self, path: str) -> str:
        """
        根据文件路径获取文件类型

        Args:
            path: 文件路径

        Returns:
            文件类型描述
        """
        _, ext = os.path.splitext(path.lower())

        type_mapping = {
            '.py': 'Python脚本',
            '.json': 'JSON配置',
            '.txt': '文本文件',
            '.md': 'Markdown文档',
            '.yml': 'YAML配置',
            '.yaml': 'YAML配置',
            '.bin': '二进制文件',
            '.safetensors': 'SafeTensors模型',
            '.onnx': 'ONNX模型',
            '.pt': 'PyTorch模型',
            '.pth': 'PyTorch模型',
            '.h5': 'HDF5模型',
            '.pkl': 'Pickle文件',
            '.gitattributes': 'Git属性',
            '.gitignore': 'Git忽略',
            '': '无扩展名文件'
        }

        return type_mapping.get(ext, f'{ext.upper()}文件' if ext else '未知类型')

    def _get_modified_time(self, sibling) -> str:
        """
        获取文件修改时间

        Args:
            sibling: RepoSibling 对象

        Returns:
            格式化的修改时间字符串
        """
        # Hugging Face API 通常不提供文件修改时间
        # 可以尝试从其他字段获取，或者返回默认值
        if hasattr(sibling, 'last_modified'):
            try:
                # 如果有修改时间字段，进行格式化
                last_modified = sibling.last_modified
                if isinstance(last_modified, str):
                    return last_modified
                elif hasattr(last_modified, 'strftime'):
                    return last_modified.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass

        # 返回默认值
        return "未知"

    def _create_basic_file_info_from_simple_list(self) -> List[FileInfo]:
        """
        从简单文件列表创建基本的文件信息

        Returns:
            基本文件信息列表
        """
        simple_list = self.get_simple_file_list()
        basic_info = []

        for path in simple_list:
            file_info = FileInfo(
                path=path,
                size=0,
                modified_time="未知",
                file_type=self._get_file_type(path),
                is_directory=False
            )
            basic_info.append(file_info)

        return basic_info


class HuggingfaceFileDialog(QDialog):
    """HuggingFace 文件选择对话框"""

    def __init__(self, repo_id: str, revision: str = "main", token: Optional[str] = None,
                 title: str = "选择文件", parent=None):
        """
        初始化对话框

        Args:
            repo_id: HuggingFace 仓库ID
            revision: 分支或标签
            token: HuggingFace 访问令牌
            title: 对话框标题
            parent: 父窗口
        """
        super().__init__(parent)

        self.repo_id = repo_id
        self.revision = revision
        self.token = token
        self.selected_files = []

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(800, 600)

        self._setup_ui()
        self._connect_signals()

        # 自动加载数据
        self.file_tree.load_data()

    def _setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)

        # 顶部信息区域
        info_layout = QVBoxLayout()

        # 仓库信息标签
        repo_label = QLabel(f"仓库: {self.repo_id}")
        repo_font = QFont()
        repo_font.setBold(True)
        repo_font.setPointSize(12)
        repo_label.setFont(repo_font)

        revision_label = QLabel(f"分支/标签: {self.revision}")
        revision_label.setStyleSheet("color: #666;")

        info_layout.addWidget(repo_label)
        info_layout.addWidget(revision_label)
        layout.addLayout(info_layout)

        # 文件树控件
        self.file_tree = HuggingfaceFileTreeWidget(
            repo_id=self.repo_id,
            revision=self.revision,
            token=self.token,
            selection_mode=SelectionMode.CHECKBOX,
            show_hidden_files=True,
            show_file_icons=True,
            expandable_by_default=False,
            auto_check_children=True,
            enable_simple_loading=False
        )
        layout.addWidget(self.file_tree)

        # 选择信息标签
        self.selection_summary_label = QLabel("未选择任何文件")
        self.selection_summary_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(self.selection_summary_label)

        # 按钮区域
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        self.ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)

        self.ok_button.setText("确定")
        self.cancel_button.setText("取消")
        self.ok_button.setEnabled(False)  # 初始状态禁用确定按钮

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout.addWidget(button_box)

    def _connect_signals(self):
        """连接信号"""
        # 监听文件选择变化
        self.file_tree.selection_changed.connect(self._on_selection_changed)

        # 监听加载状态
        self.file_tree.loading_started.connect(self._on_loading_started)
        self.file_tree.loading_finished.connect(self._on_loading_finished)

    def _on_selection_changed(self, selected_files: List[FileInfo]):
        """处理文件选择变化"""
        self.selected_files = selected_files

        # 更新选择信息
        if not selected_files:
            self.selection_summary_label.setText("未选择任何文件")
            self.ok_button.setEnabled(False)
        else:
            # 统计文件和文件夹数量
            files_count = sum(1 for f in selected_files if not f.is_dir)
            folders_count = sum(1 for f in selected_files if f.is_dir)

            parts = []
            if files_count > 0:
                parts.append(f"{files_count} 个文件")
            if folders_count > 0:
                parts.append(f"{folders_count} 个文件夹")

            summary = f"已选择: {', '.join(parts)}"
            self.selection_summary_label.setText(summary)
            self.ok_button.setEnabled(True)

    def _on_loading_started(self):
        """加载开始时禁用按钮"""
        self.ok_button.setEnabled(False)
        self.selection_summary_label.setText("正在加载文件列表...")

    def _on_loading_finished(self):
        """加载完成时恢复按钮状态"""
        if self.selected_files:
            self.ok_button.setEnabled(True)
        self.selection_summary_label.setText("加载完成，请选择文件")

    def get_selected_files(self) -> List[FileInfo]:
        """
        获取当前选中的文件列表

        Returns:
            选中的文件信息列表
        """
        return self.file_tree.get_all_selected_files()

    def accept(self):
        """确定按钮点击处理"""
        # 获取最新的选中文件
        self.selected_files = self.get_selected_files()

        if not self.selected_files:
            QMessageBox.warning(self, "提示", "请至少选择一个文件或文件夹")
            return

        super().accept()

    @staticmethod
    def select_files(repo_id: str, revision: str = "main", token: Optional[str] = None,
                     title: str = "选择 HuggingFace 文件", parent=None) -> Optional[List[FileInfo]]:
        """
        静态方法：显示文件选择对话框

        Args:
            repo_id: HuggingFace 仓库ID
            revision: 分支或标签
            token: HuggingFace 访问令牌
            title: 对话框标题
            parent: 父窗口

        Returns:
            选中的文件列表，如果用户取消则返回 None
        """
        dialog = HuggingfaceFileDialog(
            repo_id=repo_id,
            revision=revision,
            token=token,
            title=title,
            parent=parent
        )

        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                return dialog.get_selected_files()
            else:
                return None
        except Exception as e:
            QMessageBox.critical(
                parent,
                "错误",
                f"加载 HuggingFace 仓库时出错:\n{str(e)}"
            )
            return None
        finally:
            dialog.deleteLater()

    @staticmethod
    def select_files_simple(repo_id: str, revision: str = "main", token: Optional[str] = None) -> Optional[List[str]]:
        """
        静态方法：选择文件并返回文件路径列表

        Args:
            repo_id: HuggingFace 仓库ID
            revision: 分支或标签
            token: HuggingFace 访问令牌

        Returns:
            选中文件的路径列表，如果用户取消则返回 None
        """
        selected_files = HuggingfaceFileDialog.select_files(
            repo_id=repo_id,
            revision=revision,
            token=token
        )

        if selected_files:
            return [file_info.path for file_info in selected_files]
        else:
            return None
