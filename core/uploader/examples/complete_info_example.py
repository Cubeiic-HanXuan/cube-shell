"""
完整信息展示示例

本示例展示如何在移植SFTP上传功能时保持现有系统的完整信息展示格式
"""
import os
import uuid
import sys
import threading

from core.uploader.progress_adapter import ProgressAdapter
from core.uploader.sftp_uploader_core import SFTPUploaderCore

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget
from PySide6.QtWidgets import QProgressBar, QLabel, QPushButton, QFileDialog, QFrame
from PySide6.QtCore import Qt
import paramiko


class CompleteInfoDemo(QMainWindow):
    """展示完整信息格式的上传界面"""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("完整信息展示示例")
        self.resize(800, 600)

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建主布局
        main_layout = QVBoxLayout(central_widget)

        # 创建两个区域 - 上半部分是现有系统，下半部分是移植后的上传功能
        # 上半部分 - 现有系统风格
        self.existing_panel = QWidget()
        self.existing_panel.setObjectName("existingPanel")
        main_layout.addWidget(self.existing_panel, 1)

        existing_layout = QVBoxLayout(self.existing_panel)
        existing_title = QLabel("现有系统风格 - 完整信息展示")
        existing_title.setObjectName("sectionTitle")
        existing_layout.addWidget(existing_title)

        # 添加一些模拟的现有文件条目
        for i in range(2):
            self.add_existing_file_item(
                existing_layout,
                f"测试文件{i + 1}.txt",
                1024 * 1024 * (i + 1),
                f"/用户/本地路径/测试文件{i + 1}.txt",
                f"/远程/服务器/路径/测试文件{i + 1}.txt",
                (i + 1) * 40
            )

        # 下半部分 - 移植后的上传功能
        self.upload_panel = QWidget()
        self.upload_panel.setObjectName("uploadPanel")
        main_layout.addWidget(self.upload_panel, 2)

        upload_layout = QVBoxLayout(self.upload_panel)
        upload_title = QLabel("移植后的SFTP上传功能")
        upload_title.setObjectName("sectionTitle")
        upload_layout.addWidget(upload_title)

        # 上传按钮
        button_layout = QHBoxLayout()
        self.upload_button = QPushButton("选择文件上传")
        self.upload_button.clicked.connect(self.select_and_upload)
        button_layout.addWidget(self.upload_button)
        button_layout.addStretch()
        upload_layout.addLayout(button_layout)

        # 上传列表区域
        self.upload_list_widget = QWidget()
        self.upload_list_layout = QVBoxLayout(self.upload_list_widget)
        self.upload_list_layout.setAlignment(Qt.AlignTop)

        # 创建滚动区域
        scroll_area = QWidget()  # 简化示例，实际应使用QScrollArea
        scroll_layout = QVBoxLayout(scroll_area)
        scroll_layout.addWidget(self.upload_list_widget)
        upload_layout.addWidget(scroll_area)

        # 应用样式
        self.setup_styles()

        # 初始化SFTP上传器和进度适配器
        self.init_uploader()

    def setup_styles(self):
        """设置样式"""
        self.setStyleSheet("""
            QLabel#sectionTitle {
                font-size: 16px;
                font-weight: bold;
                color: #2c3e50;
                padding: 5px;
                border-bottom: 1px solid #bdc3c7;
                margin-bottom: 10px;
            }
            
            QLabel#fileInfoLabel {
                font-weight: bold;
                color: #2c3e50;
                font-size: 13px;
            }
            
            QLabel#pathInfoLabel {
                color: #7f8c8d;
                font-size: 12px;
            }
            
            QLabel#statusLabel {
                color: #16a085;
                font-weight: bold;
            }
            
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 3px;
                background-color: #ecf0f1;
                text-align: center;
                height: 16px;
            }
            
            QProgressBar::chunk {
                background-color: #3498db;
                border-radius: 2px;
            }
            
            QWidget#fileItem {
                background-color: #f9f9f9;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 8px;
                margin: 4px 0px;
            }
            
            QPushButton {
                background-color: #3498db;
                color: white;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)

    def add_existing_file_item(self, parent_layout, filename, size, local_path, remote_path, progress):
        """添加模拟的现有文件上传项"""
        file_item = QWidget()
        file_item.setObjectName("fileItem")
        item_layout = QVBoxLayout(file_item)

        # 第一行：文件名和大小 + 状态
        first_row = QHBoxLayout()
        file_info = QLabel(f"{filename} ({self.format_size(size)})")
        file_info.setObjectName("fileInfoLabel")
        first_row.addWidget(file_info)

        first_row.addStretch()

        status = QLabel(f"{progress}%")
        status.setObjectName("statusLabel")
        first_row.addWidget(status)

        item_layout.addLayout(first_row)

        # 第二行：路径信息
        path_info = QLabel(f"本地: {local_path} → 远程: {remote_path}")
        path_info.setObjectName("pathInfoLabel")
        item_layout.addWidget(path_info)

        # 第三行：进度条
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(progress)
        item_layout.addWidget(progress_bar)

        parent_layout.addWidget(file_item)

        return file_item, file_info, path_info, status, progress_bar

    def init_uploader(self):
        """初始化SFTP上传器"""
        try:
            # 创建模拟SFTP客户端
            self.sftp_client = MockSFTPClient()

            # 创建上传器核心
            self.uploader = SFTPUploaderCore(self.sftp_client)

            # 创建进度适配器
            self.progress_adapter = ProgressAdapter()

            # 使用现有系统的信息格式
            self.progress_adapter.set_use_existing_format(True)

            # 自定义格式化回调
            self.progress_adapter.set_format_callbacks(
                file_info_callback=lambda filename, size: f"{filename} ({self.format_size(size)})",
                path_info_callback=lambda local, remote: f"本地: {local} → 远程: {remote}"
            )

            # 连接信号
            self.progress_adapter.connect_signals(self.uploader)

            self.upload_button.setEnabled(True)

        except Exception as e:
            print(f"初始化上传器错误: {str(e)}")
            self.upload_button.setText("初始化失败")
            self.upload_button.setEnabled(False)

    def format_size(self, size_bytes):
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def select_and_upload(self):
        """选择文件并上传"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要上传的文件", "", "所有文件 (*)"
        )

        if not file_paths:
            return

        # 上传每个文件
        for local_path in file_paths:
            # 创建唯一ID
            file_id = str(uuid.uuid4())
            filename = os.path.basename(local_path)
            remote_path = f"/tmp/{filename}"  # 实际应用中应由用户指定或配置

            # 创建文件条目容器
            file_item = QWidget()
            file_item.setObjectName("fileItem")
            item_layout = QVBoxLayout(file_item)

            # 创建完整的进度项
            progress_bar, file_info_label, path_info_label, status_label = self.progress_adapter.create_complete_progress_item(
                file_item)

            # 设置标签样式
            file_info_label.setObjectName("fileInfoLabel")
            path_info_label.setObjectName("pathInfoLabel")
            status_label.setObjectName("statusLabel")

            # 第一行：文件信息和状态
            first_row = QHBoxLayout()
            first_row.addWidget(file_info_label)
            first_row.addStretch()
            first_row.addWidget(status_label)
            item_layout.addLayout(first_row)

            # 第二行：路径信息
            item_layout.addWidget(path_info_label)

            # 第三行：进度条
            item_layout.addWidget(progress_bar)

            # 添加到上传列表
            self.upload_list_layout.addWidget(file_item)

            # 注册到进度适配器
            self.progress_adapter.register_complete_progress_item(
                file_id, progress_bar, file_info_label, path_info_label, status_label
            )

            # 更新文件路径信息
            self.progress_adapter.update_file_paths(file_id, local_path, remote_path)

            # 获取文件大小
            file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

            # 开始上传 - 这将触发upload_started信号
            self.uploader.upload_file(file_id, local_path, remote_path)


# 模拟SFTP客户端，用于演示
class MockSFTPClient:
    """模拟SFTP客户端，用于演示不实际上传文件"""

    def stat(self, path):
        """模拟stat方法"""

        class MockStat:
            st_size = 0

        return MockStat()

    def mkdir(self, path):
        """模拟mkdir方法"""
        pass

    def open(self, path, mode):
        """模拟open方法"""

        class MockFile:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def write(self, data):
                pass

            def seek(self, offset):
                pass

            def read(self, size):
                return b''

        # 启动模拟上传线程
        if 'w' in mode:
            threading.Thread(
                target=self._simulate_upload,
                args=(path,),
                daemon=True
            ).start()

        return MockFile()

    def _simulate_upload(self, path):
        """模拟上传过程，发送进度更新"""
        import time
        import random

        # 睡眠一段时间，模拟上传延迟
        time.sleep(0.5)

        # 获取信号处理对象
        sender = None
        for frame in sys._current_frames().values():
            if 'self' in frame.f_locals and hasattr(frame.f_locals['self'], 'safe_emit_progress'):
                sender = frame.f_locals['self']
                break

        if not sender:
            return

        # 文件ID和文件名
        from pathlib import Path
        filename = Path(path).name
        file_id = next((fid for fid, data in sender.progress_data.items()
                        if data.get('filename') == filename), None)

        if not file_id:
            return

        # 模拟上传进度
        for progress in range(0, 101, 5):
            # 添加随机延迟
            time.sleep(0.1 + random.random() * 0.3)

            # 发送进度更新信号
            sender.safe_emit_progress(file_id, progress, filename)

            # 上传完成时发送完成信号
            if progress >= 100:
                time.sleep(0.5)
                sender.safe_emit_completed(file_id, filename)
                break


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CompleteInfoDemo()
    window.show()
    sys.exit(app.exec())
