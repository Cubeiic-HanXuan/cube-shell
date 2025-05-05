from PySide6.QtCore import QObject, Slot, QTimer
from PySide6.QtWidgets import QProgressBar, QLabel


class ProgressAdapter(QObject):
    """
    进度条适配器，用于连接SFTPUploaderCore信号到UI进度条组件
    支持不同类型的进度条控件：PySide6原生、自定义进度条或其他UI框架的进度条
    """

    def __init__(self):
        super().__init__()
        # 储存文件ID和对应的进度条控件和标签
        self.progress_bars = {}  # file_id -> ProgressBar 对象
        self.labels = {}  # file_id -> Label 对象 (可选)
        self.progress_data = {}  # file_id -> {progress, filename} (保存最新进度)
        # 存储样式模板
        self.progress_bar_style = None  # 进度条样式模板
        self.label_style = None  # 标签样式模板

        # 存储额外信息标签
        self.file_info_labels = {}  # file_id -> 文件信息标签 (名称、大小)
        self.path_info_labels = {}  # file_id -> 路径信息标签 (本地路径、远程路径)

        # 使用现有系统的信息格式
        self.use_existing_format = True  # 是否使用现有系统的信息展示格式
        self.format_callbacks = {}  # 自定义格式化回调

    def set_style_template(self, progress_bar_style=None, label_style=None):
        """
        设置样式模板，用于创建的新进度条组件

        Args:
            progress_bar_style: 进度条样式模板，可以是字符串(QSS)或样式对象
            label_style: 标签样式模板，可以是字符串(QSS)或样式对象
        """
        self.progress_bar_style = progress_bar_style
        self.label_style = label_style

    def clone_style_from(self, progress_bar=None, label=None):
        """
        从现有组件克隆样式

        Args:
            progress_bar: 现有的进度条组件
            label: 现有的标签组件
        """
        if progress_bar:
            if isinstance(progress_bar, QProgressBar):
                # 克隆QProgressBar样式
                self.progress_bar_style = progress_bar.styleSheet()
            else:
                # 尝试提取样式
                try:
                    self.progress_bar_style = getattr(progress_bar, 'styleSheet', lambda: None)() or None
                except:
                    pass

        if label:
            if isinstance(label, QLabel):
                # 克隆QLabel样式
                self.label_style = label.styleSheet()
            else:
                # 尝试提取样式
                try:
                    self.label_style = getattr(label, 'styleSheet', lambda: None)() or None
                except:
                    pass

    def _apply_style(self, widget, style=None):
        """应用样式到组件"""
        if not style or not widget:
            return

        if isinstance(style, str) and hasattr(widget, 'setStyleSheet'):
            # 应用QSS样式
            widget.setStyleSheet(style)
        elif hasattr(style, 'apply_to') and callable(style.apply_to):
            # 使用自定义样式对象
            style.apply_to(widget)
        elif isinstance(style, dict) and hasattr(widget, 'setProperty'):
            # 应用属性字典
            for key, value in style.items():
                widget.setProperty(key, value)

    def register_pyside_progress_bar(self, file_id, progress_bar, label=None):
        """
        注册PySide6原生的QProgressBar和可选的QLabel

        Args:
            file_id: 文件唯一标识
            progress_bar: QProgressBar对象
            label: 可选的QLabel对象，用于显示文件名和进度信息
        """
        self.progress_bars[file_id] = progress_bar
        if label:
            self.labels[file_id] = label

        # 应用样式（如果有）
        self._apply_style(progress_bar, self.progress_bar_style)
        self._apply_style(label, self.label_style)

        # 初始化进度数据
        self.progress_data[file_id] = {"progress": 0, "filename": ""}

    def register_custom_progress_component(self, file_id, component):
        """
        注册自定义进度组件，需要实现update_progress方法

        Args:
            file_id: 文件唯一标识
            component: 自定义进度组件，必须实现update_progress(progress, filename)方法
        """
        if not hasattr(component, 'update_progress'):
            raise ValueError("自定义进度组件必须实现update_progress(progress, filename)方法")

        # 尝试应用样式到自定义组件
        if hasattr(component, 'apply_style'):
            if self.progress_bar_style:
                component.apply_style(self.progress_bar_style)

        self.progress_bars[file_id] = component

    def create_progress_bar(self, parent=None):
        """
        创建一个与现有样式一致的进度条

        Args:
            parent: 父组件

        Returns:
            QProgressBar: 新创建的进度条
        """
        progress_bar = QProgressBar(parent)
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)

        # 应用样式
        self._apply_style(progress_bar, self.progress_bar_style)

        return progress_bar

    def create_label(self, text="", parent=None):
        """
        创建一个与现有样式一致的标签

        Args:
            text: 标签文本
            parent: 父组件

        Returns:
            QLabel: 新创建的标签
        """
        label = QLabel(text, parent)

        # 应用样式
        self._apply_style(label, self.label_style)

        return label

    def clear(self, file_id=None):
        """
        清除已注册的进度条

        Args:
            file_id: 可选，特定文件ID；如果为None则清除所有
        """
        if file_id:
            if file_id in self.progress_bars:
                del self.progress_bars[file_id]
            if file_id in self.labels:
                del self.labels[file_id]
            if file_id in self.progress_data:
                del self.progress_data[file_id]
            if file_id in self.file_info_labels:
                del self.file_info_labels[file_id]
            if file_id in self.path_info_labels:
                del self.path_info_labels[file_id]
        else:
            self.progress_bars.clear()
            self.labels.clear()
            self.progress_data.clear()
            self.file_info_labels.clear()
            self.path_info_labels.clear()

    def connect_signals(self, uploader):
        """
        连接SFTPUploaderCore的信号

        Args:
            uploader: SFTPUploaderCore实例
        """
        uploader.progress_updated.connect(self.on_progress_updated)
        uploader.upload_completed.connect(self.on_upload_completed)
        uploader.upload_failed.connect(self.on_upload_failed)
        uploader.upload_started.connect(self.on_upload_started)

    @Slot(str, int, str)
    def on_progress_updated(self, file_id, progress, filename):
        """处理上传进度更新信号"""
        if file_id in self.progress_bars:
            progress_bar = self.progress_bars[file_id]

            # 保存最新进度数据
            self.progress_data[file_id] = {
                "progress": progress,
                "filename": filename
            }

            # 根据进度条类型执行不同的更新操作
            if isinstance(progress_bar, QProgressBar):
                # PySide6原生QProgressBar
                progress_bar.setValue(progress)
            elif hasattr(progress_bar, 'update_progress'):
                # 自定义进度组件
                progress_bar.update_progress(progress, filename)

            # 如果有标签，更新标签内容
            if file_id in self.labels and isinstance(self.labels[file_id], QLabel):
                self.labels[file_id].setText(f"{filename}")

    @Slot(str, str)
    def on_upload_completed(self, file_id, filename):
        """处理上传完成信号"""
        if file_id in self.progress_bars:
            progress_bar = self.progress_bars[file_id]

            # 设置进度为100%
            if isinstance(progress_bar, QProgressBar):
                progress_bar.setValue(100)
            elif hasattr(progress_bar, 'update_progress'):
                progress_bar.update_progress(100, filename)

            # 如果有标签，更新标签内容
            if file_id in self.labels and isinstance(self.labels[file_id], QLabel):
                self.labels[file_id].setText(f"{filename}: 已完成")

    @Slot(str, str, str)
    def on_upload_failed(self, file_id, filename, error):
        """处理上传失败信号"""
        if file_id in self.progress_bars:
            print(f"上传失败: {filename} - {error}")
            # 如果有标签，显示错误信息
            if file_id in self.labels and isinstance(self.labels[file_id], QLabel):
                self.labels[file_id].setText(f"{filename}: 失败 - {error}")

    @Slot(str, str, int)
    def on_upload_started(self, file_id, filename, total_size):
        """处理上传开始信号"""
        if file_id in self.progress_bars:
            progress_bar = self.progress_bars[file_id]

            # 获取路径信息（如果有）
            local_path = ""
            remote_path = ""
            if file_id in self.progress_data:
                local_path = self.progress_data[file_id].get("local_path", "")
                remote_path = self.progress_data[file_id].get("remote_path", "")

            # 保存初始进度数据
            self.progress_data[file_id] = {
                "progress": 0,
                "filename": filename,
                "total_size": total_size,
                "local_path": local_path,
                "remote_path": remote_path
            }

            # 初始化进度为0
            if isinstance(progress_bar, QProgressBar):
                progress_bar.setValue(0)
            elif hasattr(progress_bar, 'update_progress'):
                progress_bar.update_progress(0, filename)

            # 更新文件信息标签
            if file_id in self.file_info_labels:
                file_info = self.format_file_info(filename, total_size)
                self.file_info_labels[file_id].setText(file_info)

            # 更新路径信息标签
            if file_id in self.path_info_labels and local_path and remote_path:
                path_info = self.format_path_info(local_path, remote_path)
                self.path_info_labels[file_id].setText(path_info)

            # 如果有状态标签，初始化标签内容
            if file_id in self.labels and isinstance(self.labels[file_id], QLabel):
                self.labels[file_id].setText(f"开始上传 (0%)")

    def set_use_existing_format(self, use_existing_format=True):
        """
        设置是否使用现有系统的信息展示格式

        Args:
            use_existing_format: 是否使用现有系统的信息展示格式
        """
        self.use_existing_format = use_existing_format

    def set_format_callbacks(self, file_info_callback=None, path_info_callback=None):
        """
        设置信息格式化回调函数

        Args:
            file_info_callback: 格式化文件信息的回调，接收(filename, size)参数
            path_info_callback: 格式化路径信息的回调，接收(local_path, remote_path)参数
        """
        if file_info_callback:
            self.format_callbacks['file_info'] = file_info_callback
        if path_info_callback:
            self.format_callbacks['path_info'] = path_info_callback

    def format_file_info(self, filename, size):
        """格式化文件信息"""
        if 'file_info' in self.format_callbacks:
            return self.format_callbacks['file_info'](filename, size)

        # 默认格式
        size_str = self.format_size(size) if size else ""
        return f"{filename} {size_str}"

    def format_path_info(self, local_path, remote_path):
        """格式化路径信息"""
        if 'path_info' in self.format_callbacks:
            return self.format_callbacks['path_info'](local_path, remote_path)

        # 默认格式
        return f"本地: {local_path} → 远程: {remote_path}"

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

    def register_complete_progress_item(self, file_id, progress_bar, file_info_label, path_info_label,
                                        status_label=None):
        """
        注册完整的进度项，包含文件信息、路径信息和进度条

        Args:
            file_id: 文件唯一标识
            progress_bar: 进度条控件
            file_info_label: 文件信息标签 (名称、大小)
            path_info_label: 路径信息标签 (本地路径、远程路径)
            status_label: 可选的状态标签
        """
        self.progress_bars[file_id] = progress_bar
        if status_label:
            self.labels[file_id] = status_label

        self.file_info_labels[file_id] = file_info_label
        self.path_info_labels[file_id] = path_info_label

        # 应用样式
        self._apply_style(progress_bar, self.progress_bar_style)
        self._apply_style(file_info_label, self.label_style)
        self._apply_style(path_info_label, self.label_style)
        if status_label:
            self._apply_style(status_label, self.label_style)

        # 初始化进度数据
        self.progress_data[file_id] = {
            "progress": 0,
            "filename": "",
            "local_path": "",
            "remote_path": "",
            "total_size": 0
        }

    def create_complete_progress_item(self, parent=None):
        """
        创建一个完整的进度项，包含文件信息、路径信息和进度条

        Args:
            parent: 父组件

        Returns:
            tuple: (progress_bar, file_info_label, path_info_label, status_label)
        """
        # 创建标签
        file_info_label = self.create_label("", parent)
        path_info_label = self.create_label("", parent)
        status_label = self.create_label("准备上传", parent)

        # 创建进度条
        progress_bar = self.create_progress_bar(parent)

        return progress_bar, file_info_label, path_info_label, status_label

    def update_file_paths(self, file_id, local_path, remote_path):
        """
        更新文件路径信息

        Args:
            file_id: 文件唯一标识
            local_path: 本地文件路径
            remote_path: 远程文件路径
        """
        # 更新数据
        if file_id in self.progress_data:
            self.progress_data[file_id]["local_path"] = local_path
            self.progress_data[file_id]["remote_path"] = remote_path

            # 更新路径信息标签
            if file_id in self.path_info_labels:
                path_info = self.format_path_info(local_path, remote_path)
                self.path_info_labels[file_id].setText(path_info)


# 适配器类用于其他UI框架的进度条
class ProgressBarAdapter:
    """
    进度条适配器基类，用于适配不同类型的进度条控件
    继承此类并实现必要的方法来支持不同UI框架的进度条
    """

    def __init__(self):
        self.style = None

    def apply_style(self, style):
        """
        应用样式到进度条

        Args:
            style: 样式对象或字符串
        """
        self.style = style
        self._apply_style_impl()

    def _apply_style_impl(self):
        """实现样式应用，子类应重写此方法"""
        pass

    def update_progress(self, progress, filename):
        """
        更新进度和文件名 - 子类必须实现此方法
        """
        raise NotImplementedError("子类必须实现update_progress方法")


# TK进度条适配器示例
class TkProgressAdapter(ProgressBarAdapter):
    """
    适配Tkinter的进度条
    """

    def __init__(self, progress_var, progress_bar, label=None):
        """
        初始化Tkinter进度条适配器

        Args:
            progress_var: Tkinter的进度变量 (IntVar)
            progress_bar: Tkinter的进度条控件
            label: 可选的Tkinter标签控件
        """
        super().__init__()
        self.progress_var = progress_var
        self.progress_bar = progress_bar
        self.label = label

    def _apply_style_impl(self):
        """应用样式到Tkinter组件"""
        if not self.style:
            return

        if isinstance(self.style, dict):
            # 应用字典样式
            for key, value in self.style.items():
                if key == 'background':
                    self.progress_bar.configure(background=value)
                elif key == 'foreground':
                    self.progress_bar.configure(foreground=value)
                elif key == 'borderwidth':
                    self.progress_bar.configure(borderwidth=value)
                elif key == 'relief':
                    self.progress_bar.configure(relief=value)
                elif key == 'width':
                    self.progress_bar.configure(width=value)
                elif key == 'height':
                    self.progress_bar.configure(height=value)
                # 其他样式属性...

    def update_progress(self, progress, filename):
        """更新Tkinter进度条"""
        self.progress_var.set(progress)
        if self.label:
            self.label.config(text=f"{filename}: {progress}%")


# QT非PySide6进度条适配器示例
class QtProgressAdapter(ProgressBarAdapter):
    """
    适配PyQt5或其他Qt基础的进度条
    """

    def __init__(self, progress_bar, label=None):
        """
        初始化Qt进度条适配器

        Args:
            progress_bar: PyQt的进度条控件
            label: 可选的标签控件
        """
        super().__init__()
        self.progress_bar = progress_bar
        self.label = label

    def _apply_style_impl(self):
        """应用样式到PyQt组件"""
        if not self.style:
            return

        if isinstance(self.style, str) and hasattr(self.progress_bar, 'setStyleSheet'):
            # 应用QSS样式
            self.progress_bar.setStyleSheet(self.style)
            if self.label and hasattr(self.label, 'setStyleSheet'):
                self.label.setStyleSheet(self.style)

    def update_progress(self, progress, filename):
        """更新PyQt进度条"""
        self.progress_bar.setValue(progress)
        if self.label:
            self.label.setText(f"{filename}: {progress}%")


# 自定义Web进度条适配器示例
class WebProgressAdapter(ProgressBarAdapter):
    """
    适配Web前端的进度条，通过回调函数更新
    """

    def __init__(self, progress_callback, style_callback=None):
        """
        初始化Web进度条适配器

        Args:
            progress_callback: 更新进度的回调函数，接收 progress 和 filename 参数
            style_callback: 可选的样式应用回调函数，接收样式参数
        """
        super().__init__()
        self.progress_callback = progress_callback
        self.style_callback = style_callback

    def _apply_style_impl(self):
        """应用样式到Web组件"""
        if self.style_callback and self.style:
            self.style_callback(self.style)

    def update_progress(self, progress, filename):
        """通过回调更新Web进度条"""
        self.progress_callback(progress, filename)
