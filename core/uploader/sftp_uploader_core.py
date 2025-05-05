import json
import os
import threading
import time

from PySide6.QtCore import QObject, Signal


class SFTPUploaderCore(QObject):
    """
    SFTP文件上传核心组件
    假设sftp_client已经通过外部系统创建和管理
    专注于文件上传、断点续传和进度反馈功能
    """
    # 定义信号
    progress_updated = Signal(str, int, str)  # 文件ID, 进度百分比, 文件名
    chunk_progress_updated = Signal(str, str, int)  # 文件ID, 分片ID, 进度百分比 
    upload_started = Signal(str, str, int)  # 文件ID, 文件名, 总大小
    upload_completed = Signal(str, str)  # 文件ID, 文件名
    upload_failed = Signal(str, str, str)  # 文件ID, 文件名, 错误信息

    # 分片大小: 4MB
    CHUNK_SIZE = 4 * 1024 * 1024
    # 最大重试次数
    MAX_RETRIES = 3

    def __init__(self, sftp_client=None):
        """
        初始化上传器核心
        
        Args:
            sftp_client: 外部系统提供的SFTP客户端对象
        """
        super().__init__()
        self.sftp_client = sftp_client
        self.upload_threads = {}
        self.chunk_metadata = {}  # 文件ID -> {分片信息}
        self.chunk_status = {}  # 文件ID -> {分片状态}
        self.stop_events = {}
        self.metadata_dir = os.path.expanduser("~/.sftp_uploader")
        self.op_lock = threading.Lock()

        # 创建元数据目录
        if not os.path.exists(self.metadata_dir):
            os.makedirs(self.metadata_dir)

    def set_sftp_client(self, sftp_client):
        """设置SFTP客户端对象"""
        self.sftp_client = sftp_client

    def safe_emit_progress(self, file_id, progress, filename):
        """安全地发射进度信号（跨线程）"""
        self.progress_updated.emit(file_id, progress, filename)

    def safe_emit_completed(self, file_id, filename):
        """安全地发射完成信号（跨线程）"""
        self.upload_completed.emit(file_id, filename)

    def safe_emit_failed(self, file_id, filename, error):
        """安全地发射失败信号（跨线程）"""
        self.upload_failed.emit(file_id, filename, error)

    def safe_emit_started(self, file_id, filename, total_size):
        """安全地发射开始信号（跨线程）"""
        self.upload_started.emit(file_id, filename, total_size)

    def _get_metadata_path(self, file_id):
        """获取断点续传元数据文件路径"""
        return os.path.join(self.metadata_dir, f"{file_id}.json")

    def _save_metadata(self, file_id, local_path, remote_path, uploaded_size=0):
        """保存断点续传元数据"""
        metadata = {
            "file_id": file_id,
            "local_path": local_path,
            "remote_path": remote_path,
            "uploaded_size": uploaded_size,
            "last_modified": os.path.getmtime(local_path),
            "timestamp": time.time()
        }

        with open(self._get_metadata_path(file_id), 'w') as f:
            json.dump(metadata, f)

    def _load_metadata(self, file_id):
        """加载断点续传元数据"""
        metadata_path = self._get_metadata_path(file_id)
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)

                # 检查文件是否被修改过
                if os.path.exists(metadata["local_path"]):
                    current_mtime = os.path.getmtime(metadata["local_path"])
                    if current_mtime != metadata["last_modified"]:
                        # 文件已被修改，重新上传
                        return None
                    return metadata
            except:
                pass
        return None

    def _delete_metadata(self, file_id):
        """删除断点续传元数据"""
        metadata_path = self._get_metadata_path(file_id)
        if os.path.exists(metadata_path):
            os.remove(metadata_path)

    def _mkdir_p(self, remote_path):
        """递归创建远程目录"""
        if remote_path == '/':
            return

        try:
            with self.op_lock:
                self.sftp_client.stat(remote_path)
        except Exception:
            parent = os.path.dirname(remote_path)
            if parent != remote_path:
                self._mkdir_p(parent)

            with self.op_lock:
                self.sftp_client.mkdir(remote_path)

    def _upload_chunk(self, file_id, local_path, remote_path, offset, chunk_size):
        """上传文件分片（顺序上传模式）"""
        if not self.sftp_client:
            self.safe_emit_failed(file_id, os.path.basename(local_path), "SFTP客户端未设置")
            return False

        for retry in range(self.MAX_RETRIES):
            try:
                # 使用锁保护SFTP操作
                with self.op_lock:
                    # 确认远程文件是否存在
                    try:
                        remote_file_size = self.sftp_client.stat(remote_path).st_size
                        file_exists = True
                    except:
                        # 远程文件不存在，记录状态
                        remote_file_size = 0
                        file_exists = False

                total_size = os.path.getsize(local_path)

                # 打开本地文件读取相应块
                with open(local_path, 'rb') as local_file:
                    local_file.seek(offset)
                    chunk_data = local_file.read(chunk_size)

                    # 处理远程文件
                    with self.op_lock:
                        if not file_exists:
                            # 文件不存在，创建新文件并写入
                            # 确保父目录存在
                            try:
                                parent_dir = os.path.dirname(remote_path)
                                if parent_dir:
                                    try:
                                        self.sftp_client.stat(parent_dir)
                                    except:
                                        # 如果父目录不存在，创建它
                                        self._mkdir_p(parent_dir)
                            except Exception as e:
                                print(f"创建目录失败: {str(e)}")

                            # 创建新文件
                            with self.sftp_client.open(remote_path, 'wb') as remote_file:
                                # 如果需要在开头填充零字节（由于偏移量不为0）
                                if offset > 0:
                                    remote_file.write(b'\0' * offset)
                                # 写入数据
                                remote_file.write(chunk_data)
                        else:
                            # 文件存在，但需要调整大小
                            if offset > remote_file_size:
                                with self.sftp_client.open(remote_path, 'ab') as remote_file:
                                    remote_file.write(b'\0' * (offset - remote_file_size))

                            # 打开文件进行读写
                            with self.sftp_client.open(remote_path, 'rb+') as remote_file:
                                remote_file.seek(offset)
                                remote_file.write(chunk_data)

                    # 更新元数据
                    self._save_metadata(file_id, local_path, remote_path, offset + len(chunk_data))

                    # 更新进度
                    progress = min(100, int((offset + len(chunk_data)) / total_size * 100))
                    self.safe_emit_progress(file_id, progress, os.path.basename(local_path))

                    # 判断是否完成
                    if offset + len(chunk_data) >= total_size:
                        self._delete_metadata(file_id)
                        self.safe_emit_completed(file_id, os.path.basename(local_path))

                return True

            except Exception as e:
                if retry < self.MAX_RETRIES - 1:
                    time.sleep(1)  # 等待1秒后重试
                else:
                    self.safe_emit_failed(file_id, os.path.basename(local_path),
                                          f"上传失败(重试{self.MAX_RETRIES}次): {str(e)}")
                    return False

        return False

    def _upload_file_worker(self, file_id, local_path, remote_path):
        """文件上传工作线程"""
        try:
            if not self.sftp_client:
                self.safe_emit_failed(file_id, os.path.basename(local_path), "SFTP客户端未设置")
                return

            try:
                if not os.path.exists(local_path):
                    raise FileNotFoundError(f"本地文件不存在: {local_path}")

                # 确保远程目录存在
                remote_dir = os.path.dirname(remote_path)
                try:
                    with self.op_lock:
                        self.sftp_client.stat(remote_dir)
                except:
                    # 创建远程目录
                    self._mkdir_p(remote_dir)

                # 获取文件大小
                total_size = os.path.getsize(local_path)

                # 加载断点续传元数据
                metadata = self._load_metadata(file_id)
                if metadata and metadata["local_path"] == local_path and metadata[
                    "remote_path"] == remote_path and "uploaded_size" in metadata:
                    # 断点续传
                    offset = metadata["uploaded_size"]
                else:
                    # 新文件上传，覆盖模式
                    offset = 0

                self.safe_emit_started(file_id, os.path.basename(local_path), total_size)

                # 上传文件分片
                while offset < total_size:
                    # 检查是否停止上传
                    if file_id in self.stop_events and self.stop_events[file_id].is_set():
                        break

                    # 计算当前分片大小
                    current_chunk_size = min(self.CHUNK_SIZE, total_size - offset)

                    # 上传分片
                    success = self._upload_chunk(file_id, local_path, remote_path, offset, current_chunk_size)
                    if not success:
                        break

                    # 更新偏移量
                    offset += current_chunk_size

            except Exception as e:
                self.safe_emit_failed(file_id, os.path.basename(local_path), str(e))

        finally:
            # 清理线程资源
            with self.op_lock:
                if file_id in self.upload_threads:
                    del self.upload_threads[file_id]
                if file_id in self.stop_events:
                    del self.stop_events[file_id]

    def upload_file(self, file_id, local_path, remote_path):
        """开始上传文件
        
        Args:
            file_id: 文件唯一标识
            local_path: 本地文件路径
            remote_path: 远程文件路径
        """
        if not self.sftp_client:
            raise ValueError("SFTP客户端未设置")

        # 创建停止事件
        self.stop_events[file_id] = threading.Event()

        # 创建并启动上传线程
        thread = threading.Thread(
            target=self._upload_file_worker,
            args=(file_id, local_path, remote_path)
        )
        thread.daemon = True
        self.upload_threads[file_id] = thread
        thread.start()

        return file_id

    def cancel_upload(self, file_id):
        """取消文件上传"""
        if file_id in self.stop_events:
            self.stop_events[file_id].set()

    def batch_upload(self, file_mappings):
        """批量上传文件
        
        Args:
            file_mappings: 包含 {file_id: (local_path, remote_path)} 的字典
        """
        if not self.sftp_client:
            raise ValueError("SFTP客户端未设置")

        results = {}
        for file_id, (local_path, remote_path) in file_mappings.items():
            results[file_id] = self.upload_file(file_id, local_path, remote_path)
        return results
