"""
Paramiko SSH shell channel 到 QTermWidget 的桥接适配器。
将 Paramiko channel 的 I/O 桥接到 QTermWidget Session 的内部数据流。
"""
import re
import threading

from PySide6.QtCore import QObject, Signal, Qt


class ParamikoBridge(QObject):
    """将 Paramiko shell channel 桥接到 QTermWidget Session"""

    channelClosed = Signal()
    dataReceived = Signal(bytes, int)
    cwdChanged = Signal(str)  # Shell 报告工作目录变更（通过 OSC 7）

    # OSC 7 正则：\x1b]7;file://hostname/path\x07  或  \x1b]7;file://hostname/path\x1b\\
    _OSC7_PATTERN = re.compile(rb'\x1b\]7;file://[^/]*(.*?)(?:\x07|\x1b\\)')

    # AI 命令标记前缀正则：_CUBE_ID=数字; (含尾随空格)
    _CUBE_ID_PATTERN = re.compile(rb'_CUBE_ID=\d+;\s*')

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
        """后台线程：Paramiko channel → Session.onReceiveBlock → 终端渲染
        
        同时检测 OSC 7 序列并提取工作目录变更。
        """
        while self._running:
            try:
                if self._channel.closed:
                    break
                data = self._channel.recv(4096)
                if not data:
                    break

                # 检测 OSC 7 序列并提取路径
                for m in self._OSC7_PATTERN.finditer(data):
                    try:
                        path = m.group(1).decode('utf-8', errors='ignore')
                        if path:
                            self.cwdChanged.emit(path)
                    except Exception:
                        pass

                # 从数据中剥离 OSC 7 序列（避免终端渲染乱码）
                clean_data = self._OSC7_PATTERN.sub(b'', data)

                # 过滤掉 Shell 集成注入命令的回显（包含 __cs_osc7 的行）
                if b'__cs_osc7' in clean_data:
                    lines = clean_data.split(b'\r\n')
                    lines = [l for l in lines if b'__cs_osc7' not in l]
                    clean_data = b'\r\n'.join(lines)

                # 过滤 AI 命令执行标记的回显
                # 1. 过滤包含 __cube_end 或 PAGER=cat 的初始化命令行
                if b'__cube_end' in clean_data or b'PAGER=cat' in clean_data:
                    lines = clean_data.split(b'\r\n')
                    lines = [l for l in lines
                             if b'__cube_end' not in l and b'PAGER=cat' not in l]
                    clean_data = b'\r\n'.join(lines)
                # 2. 替换 _CUBE_ID=N; 前缀，只保留实际命令
                if b'_CUBE_ID=' in clean_data:
                    clean_data = self._CUBE_ID_PATTERN.sub(b'', clean_data)

                if clean_data:
                    self.dataReceived.emit(clean_data, len(clean_data))
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

    def inject_shell_integration(self):
        """向远程 Shell 注入 OSC 7 目录报告钩子（兼容 bash/zsh）。
        
        注入的命令会让 Shell 在每次显示提示符前自动输出 OSC 7 序列，
        编码当前工作目录，由 _read_loop 解析。
        回显通过 _read_loop 中的 __cs_osc7 关键字过滤，对用户无感。
        """
        if not self._running or not self._channel or self._channel.closed:
            return
        # 命令前加空格：bash 默认不记录以空格开头的命令到 history（需 HISTCONTROL=ignorespace）
        # printf '\e]7;file://%s%s\e\\' 输出：ESC]7;file://hostname/pathESC\（即 OSC 7 + ST）
        hook_cmd = (
            " __cs_osc7(){ printf '\\e]7;file://%s%s\\e\\\\' \"$(hostname)\" \"$(pwd)\"; };"
            "if [ -n \"$ZSH_VERSION\" ];then precmd(){ __cs_osc7; };"
            "elif [ -n \"$BASH_VERSION\" ];then "
            "PROMPT_COMMAND=\"${PROMPT_COMMAND:+$PROMPT_COMMAND;} __cs_osc7\";fi\n"
        )
        try:
            self._channel.send(hook_cmd.encode('utf-8'))
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
