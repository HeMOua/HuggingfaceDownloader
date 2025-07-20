import os
import time
import sys
from huggingface_hub import HfApi
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QPushButton, QWidget, QHBoxLayout

from ui.components.tree_file_selection_dialog import SelectionMode, HuggingfaceFileTreeWidget, LocalFileTreeWidget

os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"


def test_huggingface_api():
    api = HfApi()

    repo_id = "hf-internal-testing/tiny-random-bert"
    revision = "main"
    t0 = time.time()
    repo_info = api.model_info(repo_id=repo_id, revision=revision, files_metadata=False)
    print("简单信息获取耗时:", time.time() - t0)

    t1 = time.time()
    repo_info = api.model_info(repo_id=repo_id, revision=revision, files_metadata=True)
    print("详细信息获取耗时:", time.time() - t1)
    print("模型大小:", repo_info.size)


# 使用示例
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QTabWidget
    import sys

    app = QApplication(sys.argv)

    main_window = QMainWindow()
    main_window.setWindowTitle("文件树控件示例 - 支持隐藏文件显示")
    main_window.resize(1000, 700)

    central_widget = QWidget()
    main_window.setCentralWidget(central_widget)

    layout = QVBoxLayout(central_widget)

    # 创建选项卡控件来演示不同的选择模式
    tab_widget = QTabWidget()
    layout.addWidget(tab_widget)


    # 复选框模式（显示隐藏文件，智能勾选）
    # checkbox_tree = LocalFileTreeWidget(
    #     root_path=".",
    #     selection_mode=SelectionMode.CHECKBOX,
    #     show_hidden_files=True,  # 显示隐藏文件
    #     show_file_icons=True,
    #     expandable_by_default=True,
    #     auto_check_children=True  # 启用自动勾选子项
    # )
    # tab_widget.addTab(checkbox_tree, "复选框模式（显示隐藏文件）")

    repo_id = "hf-internal-testing/tiny-random-bert"
    revision = "main"
    checkbox_tree_no_hidden = HuggingfaceFileTreeWidget(
        repo_id=repo_id,
        revision=revision,
        selection_mode=SelectionMode.CHECKBOX,
        show_hidden_files=True,  # 显示隐藏文件
        show_file_icons=True,
        expandable_by_default=True,
        auto_check_children=True  # 启用自动勾选子项
    )
    tab_widget.addTab(checkbox_tree_no_hidden, "复选框模式（不显示隐藏文件）")


    # 连接信号
    def on_file_selected(file_info):
        hidden_status = " (隐藏)" if file_info.is_hidden else ""
        print(f"单个文件选中: {file_info.path} ({'文件夹' if file_info.is_dir else '文件'}){hidden_status}")


    def on_files_selected(file_infos):
        files = [f.path for f in file_infos if not f.is_dir]
        folders = [f.path for f in file_infos if f.is_dir]
        hidden_files = [f.path for f in file_infos if f.is_hidden and not f.is_dir]
        hidden_folders = [f.path for f in file_infos if f.is_hidden and f.is_dir]

        print(f"选中 {len(files)} 个文件, {len(folders)} 个文件夹")
        if hidden_files:
            print(f"  隐藏文件: {hidden_files[:3]}{'...' if len(hidden_files) > 3 else ''}")
        if hidden_folders:
            print(f"  隐藏文件夹: {hidden_folders[:3]}{'...' if len(hidden_folders) > 3 else ''}")
        if files:
            print(f"  普通文件: {[f for f in files if not any(f.startswith(h) for h in ['.git', '.idea'])][:3]}")
        if folders:
            normal_folders = [f for f in folders if not any(f.startswith(h) for h in ['.git', '.idea'])]
            if normal_folders:
                print(f"  普通文件夹: {normal_folders[:3]}{'...' if len(normal_folders) > 3 else ''}")


    def on_selection_changed(file_infos):
        hidden_count = sum(1 for f in file_infos if f.is_hidden)
        print(f"选择变化: 总共 {len(file_infos)} 项, 其中 {hidden_count} 个隐藏项")


    for tree in [checkbox_tree_no_hidden]:
        tree.file_selected.connect(on_file_selected)
        tree.files_selected.connect(on_files_selected)
        tree.selection_changed.connect(on_selection_changed)
        tree.load_data()

    main_window.show()
    sys.exit(app.exec())