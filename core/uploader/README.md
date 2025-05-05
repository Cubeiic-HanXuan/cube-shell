# SFTP上传器核心组件

这个组件提供了SFTP文件上传的核心功能，专注于文件分片上传、断点续传和进度反馈，适合集成到已有SSH/SFTP连接功能的系统中。

## 特点

- 文件分片上传（4MB一片）
- 断点续传功能
- 上传进度实时反馈
- 批量上传支持
- 与PySide6 UI框架集成
- 不依赖特定的SSH连接实现

## 集成指南

### 基本用法

```python
from sftp_uploader.core.sftp_uploader_core import SFTPUploaderCore

# 假设已经有一个现有的sftp_client对象
sftp_client = your_existing_sftp_client

# 创建上传器核心
uploader = SFTPUploaderCore(sftp_client)

# 启动文件上传
file_id = "my-file-1"  # 或使用 str(uuid.uuid4()) 生成唯一ID
uploader.upload_file(file_id, "/local/path/file.txt", "/remote/path/file.txt")

# 批量上传
file_mappings = {
    "file-1": ("/local/path/file1.txt", "/remote/path/file1.txt"),
    "file-2": ("/local/path/file2.txt", "/remote/path/file2.txt")
}
uploader.batch_upload(file_mappings)
```

### 连接信号

```python
# 连接进度信号
uploader.progress_updated.connect(on_progress_updated)
uploader.upload_completed.connect(on_upload_completed)
uploader.upload_failed.connect(on_upload_failed)

# 信号处理函数
def on_progress_updated(file_id, progress, filename):
    print(f"文件 {filename} 上传进度: {progress}%")

def on_upload_completed(file_id, filename):
    print(f"文件 {filename} 上传完成")

def on_upload_failed(file_id, filename, error):
    print(f"文件 {filename} 上传失败: {error}")
```

### 后期设置SFTP客户端

如果SFTP客户端在创建上传器后才可用，可以使用`set_sftp_client`方法设置：

```python
uploader = SFTPUploaderCore()  # 初始化时不提供sftp_client
# ... 后续获取sftp_client ...
uploader.set_sftp_client(your_sftp_client)
```

### 取消上传

```python
# 取消特定文件的上传
uploader.cancel_upload("file-id")
```

## 集成到现有系统

### 传入已有的SFTP客户端

此组件要求传入的SFTP客户端对象具有以下方法：
- `stat(path)` - 获取文件状态
- `mkdir(path)` - 创建目录
- `open(path, mode)` - 打开文件，返回文件对象

Paramiko的SFTPClient或类似实现都满足上述要求。

### 自定义SFTP客户端适配器

如果您的现有SFTP客户端接口与上述要求不同，可以创建一个适配器类：

```python
class SFTPClientAdapter:
    def __init__(self, your_sftp_client):
        self.client = your_sftp_client
        
    def stat(self, path):
        # 调用您的SFTP客户端的相应方法
        return self.client.your_stat_method(path)
        
    def mkdir(self, path):
        # 调用您的SFTP客户端的相应方法
        self.client.your_mkdir_method(path)
        
    def open(self, path, mode):
        # 调用您的SFTP客户端的相应方法
        return self.client.your_open_method(path, mode)

# 使用适配器
adapter = SFTPClientAdapter(your_existing_client)
uploader = SFTPUploaderCore(adapter)
```

## 集成进度条

SFTPUploaderCore提供了丰富的信号来实时反馈上传进度。为了更便捷地集成到现有UI系统，我们提供了进度条适配器。

### 使用ProgressAdapter

`ProgressAdapter`类可以方便地将上传信号连接到不同类型的进度条控件：

```python
from sftp_uploader.core.progress_adapter import ProgressAdapter

# 创建适配器
progress_adapter = ProgressAdapter()

# 连接到上传器信号
progress_adapter.connect_signals(uploader)

# 为每个上传文件注册进度条
file_id = "my-file-1"
progress_adapter.register_pyside_progress_bar(
    file_id,             # 文件ID
    progress_bar,        # QProgressBar对象
    label                # 可选的QLabel对象
)
```

### 支持不同UI框架

我们提供了多种进度条适配器，支持不同的UI框架：

#### PySide6/PyQt进度条

```python
# 直接使用PySide6的QProgressBar
progress_adapter.register_pyside_progress_bar(file_id, progress_bar, label)
```

#### Tkinter进度条

```python
from sftp_uploader.core.progress_adapter import TkProgressAdapter

# 创建Tkinter适配器
progress_var = tk.IntVar()
progress_bar = ttk.Progressbar(root, variable=progress_var)
label = ttk.Label(root)

tk_adapter = TkProgressAdapter(progress_var, progress_bar, label)

# 注册自定义组件
progress_adapter.register_custom_progress_component(file_id, tk_adapter)
```

#### 自定义进度组件

对于其他UI框架或自定义进度条，只需要创建一个实现`update_progress(progress, filename)`方法的类：

```python
class MyCustomProgressBar:
    def __init__(self, your_progress_component):
        self.component = your_progress_component
        
    def update_progress(self, progress, filename):
        # 根据您的UI组件更新进度
        self.component.set_progress(progress)
        self.component.set_text(f"{filename}: {progress}%")

# 注册自定义组件
custom_progress = MyCustomProgressBar(your_component)
progress_adapter.register_custom_progress_component(file_id, custom_progress)
```

### 命令行进度条示例

对于命令行应用，可以使用简单的文本进度条：

```python
class ConsoleProgressBar:
    def update_progress(self, progress, filename):
        bar_length = 30
        filled_length = int(bar_length * progress / 100)
        bar = '█' * filled_length + '-' * (bar_length - filled_length)
        print(f"\r{filename}: [{bar}] {progress}%", end='')
        if progress >= 100:
            print()  # 完成时换行

# 注册进度处理器
console_bar = ConsoleProgressBar()
progress_adapter.register_custom_progress_component(file_id, console_bar)
```

## 断点续传

断点续传元数据存储在 `~/.sftp_uploader` 目录下。每个上传任务有一个JSON文件，包含上传进度信息。如果需要自定义存储位置，可以修改代码中的 `self.metadata_dir` 属性。 