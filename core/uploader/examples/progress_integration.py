"""
进度条集成示例

本示例展示如何在不同UI框架中集成SFTP上传进度条功能
"""
import os
import uuid
import sys
import threading
import time

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# PySide6示例
def pyside6_example():
    """PySide6进度条集成示例"""
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QPushButton, QWidget
    from PySide6.QtWidgets import QProgressBar, QLabel, QFileDialog
    from sftp_uploader.core.sftp_uploader_core import SFTPUploaderCore
    from sftp_uploader.core.progress_adapter import ProgressAdapter
    import paramiko
    
    class DemoWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            
            self.setWindowTitle("SFTP上传进度条示例")
            self.resize(600, 400)
            
            # 创建中央部件
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            
            # 创建主布局
            main_layout = QVBoxLayout(central_widget)
            
            # 上传按钮
            button_layout = QHBoxLayout()
            self.upload_button = QPushButton("选择文件上传")
            self.upload_button.clicked.connect(self.select_and_upload)
            button_layout.addWidget(self.upload_button)
            main_layout.addLayout(button_layout)
            
            # 进度条区域
            self.progress_layout = QVBoxLayout()
            main_layout.addLayout(self.progress_layout)
            
            # 初始化SFTP上传器和进度适配器
            self.init_uploader()
            
        def init_uploader(self):
            # 模拟连接SFTP服务器
            # 注意：这里简化了连接过程，实际应用中应处理可能的连接错误
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                # 尝试连接到本地SFTP服务器（测试用，实际应用需替换为真实服务器）
                ssh_client.connect(hostname="localhost", port=22, username="test", password="password")
                self.sftp_client = ssh_client.open_sftp()
                
                # 创建上传器核心
                self.uploader = SFTPUploaderCore(self.sftp_client)
                
                # 创建进度适配器
                self.progress_adapter = ProgressAdapter()
                self.progress_adapter.connect_signals(self.uploader)
                
                self.upload_button.setEnabled(True)
            except Exception as e:
                # 处理连接错误
                print(f"SFTP连接错误: {str(e)}")
                self.upload_button.setText("SFTP连接失败")
                self.upload_button.setEnabled(False)
                self.sftp_client = None
                self.uploader = None
        
        def select_and_upload(self):
            if not self.uploader:
                return
                
            # 选择文件
            file_paths, _ = QFileDialog.getOpenFileNames(
                self, "选择要上传的文件", "", "所有文件 (*)"
            )
            
            if not file_paths:
                return
                
            # 上传每个文件
            for local_path in file_paths:
                file_id = str(uuid.uuid4())
                filename = os.path.basename(local_path)
                remote_path = f"/tmp/{filename}"  # 根据实际需要修改远程路径
                
                # 创建进度条控件
                progress_group = QWidget()
                progress_layout = QHBoxLayout(progress_group)
                
                # 文件信息标签
                label = QLabel(f"{filename}: 准备上传...")
                progress_layout.addWidget(label, 1)
                
                # 进度条
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_layout.addWidget(progress_bar, 2)
                
                # 添加到主布局
                self.progress_layout.addWidget(progress_group)
                
                # 注册进度条到适配器
                self.progress_adapter.register_pyside_progress_bar(file_id, progress_bar, label)
                
                # 开始上传
                self.uploader.upload_file(file_id, local_path, remote_path)
    
    # 创建应用
    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())


# Tkinter示例
def tkinter_example():
    """Tkinter进度条集成示例"""
    import tkinter as tk
    from tkinter import ttk, filedialog
    from sftp_uploader.core.sftp_uploader_core import SFTPUploaderCore
    from sftp_uploader.core.progress_adapter import ProgressAdapter, TkProgressAdapter
    import paramiko
    
    class TkDemoApp:
        def __init__(self, root):
            self.root = root
            root.title("SFTP上传进度条示例 (Tkinter)")
            root.geometry("600x400")
            
            # 顶部按钮区域
            self.button_frame = ttk.Frame(root, padding=10)
            self.button_frame.pack(fill=tk.X)
            
            self.upload_button = ttk.Button(
                self.button_frame, text="选择文件上传", command=self.select_and_upload
            )
            self.upload_button.pack(side=tk.LEFT)
            
            # 进度条区域
            self.progress_frame = ttk.Frame(root, padding=10)
            self.progress_frame.pack(fill=tk.BOTH, expand=True)
            
            # 初始化SFTP上传器
            self.init_uploader()
            
        def init_uploader(self):
            # 模拟连接SFTP服务器
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                # 尝试连接到本地SFTP服务器（测试用，实际应用需替换为真实服务器）
                ssh_client.connect(hostname="localhost", port=22, username="test", password="password")
                self.sftp_client = ssh_client.open_sftp()
                
                # 创建上传器核心
                self.uploader = SFTPUploaderCore(self.sftp_client)
                
                # 创建进度适配器
                self.progress_adapter = ProgressAdapter()
                self.progress_adapter.connect_signals(self.uploader)
                
                self.upload_button.config(state=tk.NORMAL)
            except Exception as e:
                # 处理连接错误
                print(f"SFTP连接错误: {str(e)}")
                self.upload_button.config(text="SFTP连接失败", state=tk.DISABLED)
                self.sftp_client = None
                self.uploader = None
        
        def select_and_upload(self):
            if not self.uploader:
                return
                
            # 选择文件
            file_paths = filedialog.askopenfilenames(
                title="选择要上传的文件",
                filetypes=[("所有文件", "*.*")]
            )
            
            if not file_paths:
                return
                
            # 上传每个文件
            for local_path in file_paths:
                file_id = str(uuid.uuid4())
                filename = os.path.basename(local_path)
                remote_path = f"/tmp/{filename}"  # 根据实际需要修改远程路径
                
                # 创建进度条框架
                progress_group = ttk.Frame(self.progress_frame)
                progress_group.pack(fill=tk.X, pady=5)
                
                # 文件信息标签
                label = ttk.Label(progress_group, text=f"{filename}: 准备上传...")
                label.pack(side=tk.TOP, fill=tk.X)
                
                # 进度变量和进度条
                progress_var = tk.IntVar()
                progress_bar = ttk.Progressbar(
                    progress_group, variable=progress_var, maximum=100
                )
                progress_bar.pack(side=tk.TOP, fill=tk.X)
                
                # 创建自定义适配器
                tk_adapter = TkProgressAdapter(progress_var, progress_bar, label)
                
                # 注册进度条到适配器
                self.progress_adapter.register_custom_progress_component(file_id, tk_adapter)
                
                # 开始上传
                self.uploader.upload_file(file_id, local_path, remote_path)
    
    # 创建应用
    root = tk.Tk()
    app = TkDemoApp(root)
    root.mainloop()


# 简化使用示例，展示基本用法
def simple_example():
    """简单命令行集成示例"""
    from sftp_uploader.core.sftp_uploader_core import SFTPUploaderCore
    import paramiko
    
    class SimpleProgressHandler:
        def update_progress(self, progress, filename):
            # 简单的命令行进度条
            bar_length = 30
            filled_length = int(bar_length * progress / 100)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            print(f"\r{filename}: [{bar}] {progress}%", end='')
            if progress >= 100:
                print()  # 完成时换行
    
    try:
        # 建立SFTP连接
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(hostname="localhost", port=22, username="test", password="password")
        sftp_client = ssh_client.open_sftp()
        
        # 创建上传器核心
        uploader = SFTPUploaderCore(sftp_client)
        
        # 设置进度回调
        file_handlers = {}
        
        def on_progress_updated(file_id, progress, filename):
            if file_id in file_handlers:
                file_handlers[file_id].update_progress(progress, filename)
        
        def on_upload_completed(file_id, filename):
            print(f"\n文件 {filename} 上传完成")
        
        def on_upload_failed(file_id, filename, error):
            print(f"\n文件 {filename} 上传失败: {error}")
        
        # 连接信号
        uploader.progress_updated.connect(on_progress_updated)
        uploader.upload_completed.connect(on_upload_completed)
        uploader.upload_failed.connect(on_upload_failed)
        
        # 选择文件（这里使用示例文件路径）
        local_path = "/path/to/your/file.txt"  # 替换为实际文件
        if not os.path.exists(local_path):
            print(f"文件不存在: {local_path}")
            local_path = input("请输入要上传的文件路径: ")
            if not os.path.exists(local_path):
                print("文件不存在，退出示例")
                sys.exit(1)
        
        filename = os.path.basename(local_path)
        file_id = str(uuid.uuid4())
        remote_path = f"/tmp/{filename}"
        
        # 创建并注册进度处理器
        file_handlers[file_id] = SimpleProgressHandler()
        
        # 开始上传
        print(f"开始上传: {filename}")
        uploader.upload_file(file_id, local_path, remote_path)
        
        # 等待上传完成
        while file_id in uploader.upload_threads:
            time.sleep(0.1)
        
        # 关闭连接
        sftp_client.close()
        ssh_client.close()
        
    except Exception as e:
        print(f"错误: {str(e)}")


if __name__ == "__main__":
    # 根据命令行参数选择示例
    if len(sys.argv) > 1:
        example = sys.argv[1].lower()
        if example == "pyside6":
            pyside6_example()
        elif example == "tkinter":
            tkinter_example()
        elif example == "simple":
            simple_example()
        else:
            print(f"未知示例: {example}")
            print("可用示例: pyside6, tkinter, simple")
    else:
        # 默认运行PySide6示例
        print("运行 PySide6 示例")
        print("其他可用示例: tkinter, simple")
        pyside6_example() 