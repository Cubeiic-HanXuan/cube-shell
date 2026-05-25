"""
Paramiko SSH shell channel 到 QTermWidget 的桥接适配器。
将 Paramiko channel 的 I/O 桥接到 QTermWidget Session 的内部数据流。
"""
import threading

from PySide6.QtCore import QObject, Signal, Qt


class ParamikoBridge(QObject):
    """将 Paramiko shell channel 桥接到 QTermWidget Session"""

    channelClosed = Signal()
    dataReceived = Signal(bytes, int)

    def __init__(self, session, channel, parent=None):
        """
        Args:
            session: qtermwidget 的 Session 对象
            channel: paramiko.Channel（已 invoke_shell）
        """
        super().__init__(parent)
        self._session = session
        self._channel = channel
        self._running = False
        self._reader_thread = None
        self._original_set_window_size = None

    def start(self):
        """启动桥接 — 连接信号并开始 I/O 转发"""
        # 1. 拦截 Emulation 的 sendData 信号 → 转发到 Paramiko channel
        emulation = self._session.emulation()
        if emulation:
            emulation.sendData.connect(self._on_emulation_send_data)

        # 2. Hook resize：monkey-patch _shellProcess.setWindowSize
        #    让 Session.updateTerminalSize() 调用时能同步到 Paramiko channel
        shell_process = getattr(self._session, '_shellProcess', None)
        if shell_process:
            self._original_set_window_size = shell_process.setWindowSize
            shell_process.setWindowSize = self._proxy_set_window_size

        # 3. 将 dataReceived 信号用 QueuedConnection 连接到 session.onReceiveBlock
        #    确保槽函数始终在主线程（UI 线程）中执行，避免跨线程操作 QTimer/Screen
        self.dataReceived.connect(
            self._session.onReceiveBlock, Qt.ConnectionType.QueuedConnection
        )

        # 4. 启动读取线程
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _proxy_set_window_size(self, lines, cols):
        """代理窗口大小设置 → Paramiko channel resize_pty
        
        注意参数顺序：
            内部 setWindowSize(lines, cols)
            Paramiko resize_pty(width=cols, height=rows)
        """
        self.resize(cols, lines)

    def _on_emulation_send_data(self, data: bytes, length: int):
        """用户键盘输入 → Paramiko channel"""
        if self._running and self._channel and not self._channel.closed:
            try:
                self._channel.send(data[:length])
            except Exception:
                pass

    def _read_loop(self):
        """后台线程：Paramiko channel → Session.onReceiveBlock → 终端渲染"""
        while self._running:
            try:
                if self._channel.closed:
                    break
                data = self._channel.recv(4096)
                if not data:
                    break
                self.dataReceived.emit(data, len(data))
            except Exception:
                break
        self._running = False
        self.channelClosed.emit()

    def resize(self, cols, rows):
        """同步窗口大小到远程 PTY"""
        if self._running and self._channel and not self._channel.closed:
            try:
                self._channel.resize_pty(width=cols, height=rows)
            except Exception:
                pass

    def stop(self):
        """停止桥接并关闭 channel"""
        self._running = False
        # 恢复原始 setWindowSize
        shell_process = getattr(self._session, '_shellProcess', None)
        if self._original_set_window_size and shell_process:
            shell_process.setWindowSize = self._original_set_window_size
        # 断开 dataReceived 信号
        try:
            self.dataReceived.disconnect(self._session.onReceiveBlock)
        except Exception:
            pass
        # 断开 sendData 信号
        emulation = self._session.emulation()
        if emulation:
            try:
                emulation.sendData.disconnect(self._on_emulation_send_data)
            except Exception:
                pass
        # 关闭 channel
        if self._channel and not self._channel.closed:
            try:
                self._channel.close()
            except Exception:
                pass
