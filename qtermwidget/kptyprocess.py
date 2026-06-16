#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复的KPtyProcess实现
解决PySide6不支持setChildProcessModifier的问题
"""

import os
import subprocess
import signal
from enum import IntFlag
import sys
import errno
import threading

MAX_READ_PER_ACTIVATION = 256 * 1024
READ_CHUNK_SIZE = 64 * 1024
MAX_OUTPUT_BUFFER_BYTES = 1024 * 1024

# Platform detection
IS_WINDOWS = sys.platform == 'win32'

if IS_WINDOWS:
    try:
        from winpty import PtyProcess as WinPtyProcess

    except ImportError:
        print("警告: 未找到winpty模块，Windows终端功能将不可用。请安装pywinpty: pip install pywinpty")
        WinPtyProcess = None
    # ConPTY 后端能完整透传 256/真彩色等 VT 序列；旧的 winpty 后端会把控制台
    # 缓冲区降级为 16 色，导致 Claude Code 等 TUI 的选中行背景高亮丢失。
    # 这里显式优先 ConPTY，失败再回退 winpty。
    try:
        from winpty.enums import Backend as WinPtyBackend
    except Exception:
        WinPtyBackend = None
else:
    import pty
    import termios
    import fcntl

from PySide6.QtCore import QProcess, QIODevice, QObject, QSocketNotifier, Signal, QSize, QDir, Slot
from .kprocess import KProcess
from .kpty_device import KPtyDevice


class PtyChannelFlag(IntFlag):
    """
    PTY通道标志枚举 - 对应C++: enum PtyChannelFlag

    这些标志指定PTY应该连接到哪些标准输入/输出通道
    """
    NoChannels = 0  # PTY不连接到任何通道 - 对应C++: NoChannels = 0
    StdinChannel = 1  # 将PTY连接到stdin - 对应C++: StdinChannel = 1
    StdoutChannel = 2  # 将PTY连接到stdout - 对应C++: StdoutChannel = 2
    StderrChannel = 4  # 将PTY连接到stderr - 对应C++: StderrChannel = 4
    AllOutputChannels = 6  # 将PTY连接到所有输出通道 - 对应C++: AllOutputChannels = 6
    AllChannels = 7  # 将PTY连接到所有通道 - 对应C++: AllChannels = 7


class KPtyProcess(KProcess):
    """
    这个类通过PTY（伪TTY）支持扩展了KProcess.

    严格对应C++: class KPtyProcess : public KProcess

    注意：由于PySide6不支持setChildProcessModifier，本实现使用Python的pty模块
    """

    # 添加所需的信号
    receivedData = Signal(bytes, int)

    # sendData = Signal(bytes)  # 改为Slot实现

    def __init__(self, parent=None):
        super().__init__(parent)

        # PTY相关 - 严格对应C++: std::unique_ptr<KPtyDevice> pty;
        self._pty = KPtyDevice(self)
        self._ptySlaveFd = -1
        self._ptyChannels = PtyChannelFlag.NoChannels
        self._addUtmp = False  # 对应C++: d->addUtmp = false (默认值)

        # 进程相关
        self._masterFd = -1
        self._slaveFd = -1
        self._childPid = -1
        self._notifier = None

        # Windows相关
        self._winpty_process = None
        self._winpty_backend = None  # 实际使用的 PTY 后端（"ConPTY" / "winpty..."），便于诊断
        self._read_thread = None
        self._read_running = False
        self._win_input_filter_buf = ""
        self._win_input_filter_seq = "\x1b[2~"
        self._window_lines = 24
        self._window_cols = 80

        # 关键修复：严格对应C++构造函数中的pty->open()调用
        # 对应C++: d->pty->open() 或 d->pty->open(ptyMasterFd)
        if not IS_WINDOWS:
            if not self._pty.open():
                print("KPtyDevice打开失败")
                # 对应C++的错误处理，但不抛出异常，保持与C++行为一致

        # 初始化PTY通道
        self.setPtyChannels(PtyChannelFlag.AllChannels)

    @staticmethod
    def _configure_ssh_tty_attrs(attrs):
        # termios.tcgetattr(fd) 在 Python 中返回一个 7 元素列表：
        # [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
        # - iflag: 输入模式标志（如何解释“输入进来的字节”）
        # - oflag: 输出模式标志（如何处理“输出出去的字节”）
        # - cflag: 控制模式标志（字符大小/奇偶校验/波特率等底层参数）
        # - lflag: 本地模式标志（行缓冲/回显/信号键等“终端交互行为”）
        # - cc   : 控制字符表（如 Ctrl+C、Ctrl+Z、退格键等具体按键对应的控制码）
        #
        # 这里的目标不是“重写一整套终端行为”，而是只做“UTF-8 安全”的最小修复：
        # - 关闭 ISTRIP，避免 UTF-8 输入被裁剪成 7-bit（中文会变成 e%= 这类乱码）
        # - 确保 8-bit 字符模式（CS8）
        # - 系统支持时启用 IUTF8
        #
        # 其他标志（例如 ECHO/ICANON/OPOST/ICRNL/IXON 等）尽量保持系统默认值，
        # 避免在 macOS 本机 shell 场景引入“回车多空行”等交互副作用。
        attrs = list(attrs)
        # ISTRIP: 把所有输入字节强行裁剪成 7-bit（清掉最高位）
        # 这会直接破坏 UTF-8（中文属于多字节且每个字节经常 >= 0x80）。
        # 典型症状是：
        #   '好' UTF-8 为 E5 A5 BD，被 ISTRIP 后变成 65 25 3D => "e%="
        # 所以这里必须明确关闭 ISTRIP。
        if hasattr(termios, "ISTRIP"):
            attrs[0] &= ~termios.ISTRIP

        # IUTF8: 让内核按 UTF-8 语义处理某些输入特性（如果系统支持）。
        # 这不是“必须项”，但开启后更贴近现代终端默认行为。
        if hasattr(termios, "IUTF8"):
            attrs[0] |= termios.IUTF8

        # 控制模式（cflag）
        # CS8   : 8-bit 字符（这是 UTF-8 正常传输的必要条件之一）
        # CREAD : 允许接收字符
        # CLOCAL: 忽略调制解调器控制线（对 PTY 场景通常更合适）
        attrs[2] |= (termios.CS8 | termios.CREAD | termios.CLOCAL)
        return attrs

    @Slot(bytes)
    def sendData(self, data):
        """发送数据到PTY - 这个方法作为slot接收emulation的sendData信号"""
        self.write(data)

    def write(self, data):
        """写入数据到进程"""
        if IS_WINDOWS:
            if self._winpty_process:
                try:
                    # winpty通常期望字符串输入
                    if isinstance(data, bytes):
                        data = data.replace(b"\x1b[2~", b"")
                        data = data.decode('utf-8', errors='ignore')
                    if self._win_input_filter_seq:
                        buf = (self._win_input_filter_buf or "") + (data or "")
                        buf = buf.replace(self._win_input_filter_seq, "")
                        max_keep = max(0, len(self._win_input_filter_seq) - 1)
                        keep = ""
                        if max_keep:
                            tail = buf[-max_keep:]
                            for k in range(len(tail), 0, -1):
                                if self._win_input_filter_seq.startswith(tail[-k:]):
                                    keep = tail[-k:]
                                    break
                        if keep:
                            data = buf[:-len(keep)]
                        else:
                            data = buf
                        self._win_input_filter_buf = keep
                    return self._winpty_process.write(data)
                except Exception as e:
                    print(f"Windows PTY写入失败: {e}")
                    return -1
            return 0

        # Linux/macOS
        if self._masterFd >= 0:
            try:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                return os.write(self._masterFd, data)
            except OSError as e:
                print(f"PTY写入失败: {e}")
                return -1

        # Fallback to QProcess.write (likely won't work if not started via QProcess)
        return super().write(data)

    def setWinSizeWindows(self, lines, cols):
        """Windows平台设置窗口大小"""
        if IS_WINDOWS and self._winpty_process:
            try:
                if hasattr(self._winpty_process, "setwinsize"):
                    self._winpty_process.setwinsize(lines, cols)
                elif hasattr(self._winpty_process, "set_winsize"):
                    self._winpty_process.set_winsize(lines, cols)
                elif hasattr(self._winpty_process, "pty") and hasattr(self._winpty_process.pty, "set_size"):
                    self._winpty_process.pty.set_size(cols, lines)
            except Exception as e:
                print(f"⚠️ 设置Windows PTY窗口大小失败: {e}")

    def pty(self):
        """
        返回PTY设备对象 - 严格对应C++: KPtyDevice *KPtyProcess::pty() const

        对应C++实现：
        KPtyDevice *KPtyProcess::pty() const
        {
            Q_D(const KPtyProcess);
            return d->pty.get();
        }

        Returns:
            KPtyDevice对象，如果未初始化则返回None
        """
        # 对应C++的Q_D(const KPtyProcess)宏 - 获取私有数据
        # 在Python中，我们直接访问实例变量，但要确保架构一致性
        if hasattr(self, '_pty') and self._pty is not None:
            return self._pty  # 对应C++的d->pty.get()
        else:
            return None  # 对应C++中pty为nullptr的情况

    def ptyChannels(self):
        """返回当前PTY通道设置"""
        return self._ptyChannels

    def setPtyChannels(self, channels):
        """设置PTY通道"""
        self._ptyChannels = channels

    def start(self, program=None, arguments=None, environment=None, window_id=0, add_to_utmp=False):
        """
        启动进程 - 严格对应C++版本的start方法签名

        对应C++: int start(const QString &program, const QStringList &arguments,
                           const QStringList &environment, int windowId, bool addToUtmp)

        Args:
            program: 要执行的程序路径
            arguments: 命令行参数列表
            environment: 环境变量列表（格式为 ["KEY=value", ...]）
            window_id: 窗口ID（X11相关，在Python中暂不使用）
            add_to_utmp: 是否添加到utmp记录

        Returns:
            int: 成功返回0，失败返回负数
        """

        # 如果已经在运行，先停止
        if self.state() != QProcess.ProcessState.NotRunning:
            self.kill()

        # 获取程序和参数
        if program is None:
            program = self.program()
        if arguments is None:
            arguments = self.arguments()

        # 如果program是列表，取第一个元素作为程序名
        if isinstance(program, list):
            if len(program) > 0:
                arguments = program[1:] + (arguments if arguments else [])
                program = program[0]
            else:
                program = None

        if not program:
            # 没有指定要运行的程序"
            self.setProcessState(QProcess.ProcessState.NotRunning)
            self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
            return

        # Windows平台特殊处理
        if IS_WINDOWS:
            return self._start_windows(program, arguments, environment)

        try:
            # 创建PTY
            self._masterFd, self._slaveFd = pty.openpty()

            # 设置PTY属性
            self._setup_pty_attributes()

            # 更新Pty对象的文件描述符
            self._pty._masterFd = self._masterFd
            self._pty._slaveFd = self._slaveFd
            self._ptySlaveFd = self._slaveFd

            # 设置进程状态
            self.setProcessState(QProcess.ProcessState.Starting)

            # 设置环境变量 - 使用传入的environment参数
            if environment is not None:
                env_dict = {}
                # 解析环境变量列表
                for env_var in environment:
                    if '=' in env_var:
                        key, value = env_var.split('=', 1)
                        env_dict[key] = value
                # 添加必要的系统环境变量
                for key in ['PATH', 'HOME', 'USER', 'SHELL']:
                    if key not in env_dict and key in os.environ:
                        env_dict[key] = os.environ[key]
            else:
                env_dict = os.environ.copy()

            # 关键：设置TERM环境变量，这对于SSH会话正确初始化至关重要
            env_dict['TERM'] = 'xterm-256color'  # 强制设置，不检查是否已存在

            env_dict['COLORTERM'] = ''
            env_dict['LANG'] = env_dict.get('LANG', 'en_US.UTF-8')  # 确保语言环境设置
            env_dict['LC_ALL'] = env_dict.get('LC_ALL', 'en_US.UTF-8')  # 完整的语言环境

            # 强制shell识别为交互式终端 - SSH关键设置
            if 'SSH_TTY' not in env_dict:
                env_dict['SSH_TTY'] = f'/dev/pts/{os.getpid()}'  # 模拟SSH TTY

            # 修复：不强制设置PS1，让shell使用默认提示符，避免重复
            # 只在PS1未设置时设置简单提示符
            if 'PS1' not in env_dict or not env_dict['PS1']:
                env_dict['PS1'] = '\\u@\\h:\\w$ '  # 标准bash提示符
            env_dict['PS2'] = '> '  # 续行提示符

            # 强制shell行为设置
            env_dict['SHELL'] = env_dict.get('SHELL', '/bin/bash')  # 确保shell路径
            env_dict['TERM_PROGRAM'] = 'qtermwidget'

            # 重要：SSH需要这些环境变量来正确初始化远程shell
            env_dict['USER'] = env_dict.get('USER', 'user')
            if 'HOME' not in env_dict:
                env_dict['HOME'] = os.path.expanduser('~')

            # 确保输出不被缓冲 - SSH会话的重要设置
            env_dict['PYTHONUNBUFFERED'] = '1'
            if 'FORCE_COLOR' in os.environ and 'FORCE_COLOR' not in env_dict:
                env_dict['FORCE_COLOR'] = os.environ.get('FORCE_COLOR', '')

            # 清理可能干扰SSH的环境变量
            for problematic_var in ['TMUX', 'TMUX_PANE', 'TERM_SESSION_ID']:
                env_dict.pop(problematic_var, None)

            # 启动子进程
            self._start_child_process(program, arguments, env_dict)

            # 设置读取通知器
            self._setup_notifier()

            # 发出started信号
            self.setProcessState(QProcess.ProcessState.Running)
            self.started.emit()

            print(f"✅ 进程启动成功，PID: {self._childPid}")
            return 0  # 成功返回0，对应C++版本

        except Exception as e:
            print(f"❌ 启动进程失败: {e}")
            self._cleanup()
            self.setProcessState(QProcess.ProcessState.NotRunning)
            self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
            return -1  # 失败返回负数，对应C++版本

    def _setup_pty_attributes(self):
        """设置PTY属性 - 严格对应C++版本的设置"""
        try:
            # 获取当前属性
            attrs = termios.tcgetattr(self._slaveFd)

            # 只设置C++版本中设置的标志，不改变其他设置
            # 对应C++: if (!_xonXoff) ttmode.c_iflag &= ~(IXOFF | IXON); else ttmode.c_iflag |= (IXOFF | IXON);
            if not getattr(self, '_xonXoff', True):  # 默认启用流控制
                attrs[0] &= ~(termios.IXOFF | termios.IXON)
            else:
                attrs[0] |= (termios.IXOFF | termios.IXON)

            # 对应C++: #ifdef IUTF8 if (!_utf8) ttmode.c_iflag &= ~IUTF8; else ttmode.c_iflag |= IUTF8;
            if hasattr(termios, 'IUTF8'):
                if not getattr(self, '_utf8', True):  # 默认启用UTF8
                    attrs[0] &= ~termios.IUTF8
                else:
                    attrs[0] |= termios.IUTF8

            # 对应C++: if (_eraseChar != 0) ttmode.c_cc[VERASE] = _eraseChar;
            erase_char = getattr(self, '_eraseChar', '\x7f')  # 默认退格字符
            if isinstance(erase_char, str):
                attrs[6][termios.VERASE] = ord(erase_char)
            else:
                attrs[6][termios.VERASE] = erase_char

            # 重要：不设置c_lflag（本地标志），保持PTY的默认raw模式
            # 这与C++版本一致，C++版本没有修改c_lflag

            termios.tcsetattr(self._slaveFd, termios.TCSANOW, attrs)

        except Exception as e:
            print(f"⚠️ 设置PTY属性失败: {e}")

    def _start_child_process(self, program, arguments, env_dict):
        """
        启动子进程 - 严格对应C++的setChildProcessModifier逻辑

        对应C++: setChildProcessModifier([d]() {
            d->pty->setCTty();
            if (d->ptyChannels & StdinChannel) {
                dup2(d->pty->slaveFd(), 0);
            }
            if (d->ptyChannels & StdoutChannel) {
                dup2(d->pty->slaveFd(), 1);
            }
            if (d->ptyChannels & StderrChannel) {
                dup2(d->pty->slaveFd(), 2);
            }
        });
        """

        # 准备命令行
        cmd = [program] + (arguments if arguments else [])

        def child_setup():
            """
            子进程设置函数 - 强化版本，确保SSH会话正确工作

            关键修复：SSH会话需要正确的控制终端和会话设置
            """
            try:
                # 第一步：创建新的会话和进程组 - SSH必需
                os.setsid()  # 创建新会话，成为会话领导者

                # 第二步：设置控制终端 - 这是SSH显示提示符的关键！
                import fcntl
                import termios

                # 强制设置控制终端
                try:
                    fcntl.ioctl(self._slaveFd, termios.TIOCSCTTY, 1)  # 使用force=1
                except OSError:
                    # 如果失败，尝试不使用force
                    fcntl.ioctl(self._slaveFd, termios.TIOCSCTTY, 0)

                # 第三步：重定向标准输入输出 - 确保SSH数据流正确
                # 必须按顺序重定向，确保所有通道都连接到PTY
                os.dup2(self._slaveFd, 0)  # stdin
                os.dup2(self._slaveFd, 1)  # stdout
                os.dup2(self._slaveFd, 2)  # stderr

                # 第四步：关闭不需要的文件描述符
                # 在子进程中，我们不需要master fd，只需要slave fd
                if self._masterFd >= 0 and self._masterFd != self._slaveFd:
                    try:
                        os.close(self._masterFd)
                    except:
                        pass  # 忽略关闭错误

                # 这里是在子进程中、且已经把 stdin/stdout/stderr 全部 dup 到 slave PTY 之后，
                # 再对 fd=0（也就是“这个 slave PTY”）设置 tty 属性。
                #
                # 为什么要在这里设置？
                # - ssh -t / vim 等交互程序对“控制终端”行为有预期：
                #   需要回显、需要 Ctrl+C/Ctrl+Z 生效、需要 8-bit 透明传输等。
                # - 如果 tty 输入标志错误（例如 ISTRIP 被打开），UTF-8 每个字节的最高位会被清掉，
                #   中文就会变成类似 "e%="、"^Z" 这种看起来像“转译字符”的乱码。
                #
                # 所以这里统一把 slave PTY 调整为“类似真实终端”的一组 termios 标志。
                attrs = termios.tcgetattr(0)
                attrs = KPtyProcess._configure_ssh_tty_attrs(attrs)
                termios.tcsetattr(0, termios.TCSANOW, attrs)

                try:
                    if os.path.isdir(self.workingDirectory()):
                        os.chdir(self.workingDirectory())
                except Exception:
                    pass

            except Exception as e:
                # SSH会话设置失败是严重问题，但我们仍然尝试继续
                import sys
                sys.stderr.write(f"子进程PTY设置失败: {e}\n")
                sys.stderr.flush()

        try:
            # 关键修复：使用更直接的方式启动进程，避免subprocess的复杂性
            # 这是解决SSH连接问题的关键

            pid = os.fork()
            if pid == 0:
                # 子进程
                try:
                    # 执行child_setup中的所有设置
                    child_setup()

                    # 执行目标程序 - 修复：使用execvpe来支持PATH查找
                    # execvpe会在PATH环境变量中搜索程序，支持相对路径如"ssh"
                    if '/' in program:
                        # 绝对路径或相对路径，直接使用execve
                        os.execve(program, cmd, env_dict)
                    else:
                        # 程序名，使用execvpe在PATH中查找
                        os.execvpe(program, cmd, env_dict)
                except Exception as e:
                    # 子进程中的错误
                    import sys
                    sys.stderr.write(f"子进程执行失败: {e}\n")
                    sys.stderr.flush()
                    os._exit(1)
            else:
                # 父进程(直接fork子进程成功)
                self._childPid = pid

                # 父进程关闭slave端，只保留master端
                if self._slaveFd >= 0:
                    os.close(self._slaveFd)
                    # 父进程已关闭slave fd，只保留master fd用于通信
                    self._slaveFd = -1

                # 设置master fd为非阻塞模式
                import fcntl
                flags = fcntl.fcntl(self._masterFd, fcntl.F_GETFL)
                fcntl.fcntl(self._masterFd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        except Exception as e:
            raise Exception(f"启动子进程失败: {e}")

    def _setup_notifier(self):
        """
        设置读取通知器 (QSocketNotifier)

        这个方法在PTY主设备文件描述符(masterFd)上创建一个QSocketNotifier。

        作用机制：
        1. 监控 _masterFd 的可读事件 (QSocketNotifier.Type.Read)。
        2. 当PTY有数据可读时（即子进程向stdout/stderr输出了内容），
           底层Qt事件循环会触发 notifier 的 activated 信号。
        3. 信号连接到 self._read_from_pty 方法，从而实现异步、非阻塞的数据读取。

        这是实现终端异步I/O的核心机制，避免了使用阻塞的 read() 调用卡死GUI线程。
        """
        if self._notifier:
            self._notifier.deleteLater()

        self._notifier = QSocketNotifier(self._masterFd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._read_from_pty)

    def _read_from_pty(self):
        """从PTY读取数据"""
        try:
            if self._notifier:
                try:
                    self._notifier.setEnabled(False)
                except Exception:
                    pass

            total = 0
            while total < MAX_READ_PER_ACTIVATION:
                try:
                    data = os.read(self._masterFd, READ_CHUNK_SIZE)
                except OSError as e:
                    if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        break
                    if e.errno == errno.EBADF:
                        self._handle_process_exit()
                        return
                    self._handle_process_exit()
                    return

                if not data:
                    self._handle_process_exit()
                    return

                if isinstance(data, str):
                    data = data.encode('utf-8')

                total += len(data)

                self.readyReadStandardOutput.emit()
                self.receivedData.emit(data, len(data))

                if not hasattr(self, '_output_buffer'):
                    self._output_buffer = bytearray()
                self._output_buffer.extend(data)
                if len(self._output_buffer) > MAX_OUTPUT_BUFFER_BYTES:
                    overflow = len(self._output_buffer) - MAX_OUTPUT_BUFFER_BYTES
                    del self._output_buffer[:overflow]

        except Exception as e:
            print(f"❌ PTY读取异常: {e}")
            # 捕获所有未预期的异常，防止崩溃
            pass
        finally:
            if self._notifier:
                try:
                    self._notifier.setEnabled(True)
                except Exception:
                    pass

    def _handle_process_exit(self):
        """处理进程退出"""
        if self._childPid > 0:
            try:
                # 尝试回收进程
                pid, status = os.waitpid(self._childPid, os.WNOHANG)
                if pid > 0:
                    # print(f"✅ 进程 {pid} 已回收，状态: {status}")
                    self._childPid = -1
                    exit_code = os.waitstatus_to_exitcode(status) if hasattr(os, 'waitstatus_to_exitcode') else (
                            status >> 8)
                    self.finished.emit(exit_code)
                    self.setProcessState(QProcess.ProcessState.NotRunning)
                    self._cleanup()
                else:
                    # 进程还未退出，可能还在关闭中
                    pass
            except OSError:
                # 进程可能已经不存在
                pass

    def _check_process_status(self):
        """检查进程状态 - 这里的实现留空，因为我们不希望在读取循环中频繁调用 waitpid"""
        pass

    def processId(self):
        """返回进程ID"""
        return self._childPid if self._childPid > 0 else 0

    def kill(self):
        """终止进程"""
        if IS_WINDOWS and self._winpty_process:
            self._read_running = False
            try:
                self._winpty_process.terminate()
                self._winpty_process = None
            except:
                pass
            self._cleanup()
            return

        if self._childPid > 0:
            try:
                os.kill(self._childPid, signal.SIGKILL)
                # 关键：立即等待进程结束，避免僵尸进程
                # os.waitpid 确保进程状态被回收
                os.waitpid(self._childPid, 0)
            except OSError:
                # 进程可能已经不存在了
                pass
            except Exception:
                pass
        self._cleanup()

    def terminate(self):
        """温和地终止进程"""
        if IS_WINDOWS and self._winpty_process:
            self.kill()
            return

        if self._childPid > 0:
            try:
                os.kill(self._childPid, signal.SIGTERM)
                # 尝试立即回收（优化），如果不行则由_read_from_pty处理
                self._handle_process_exit()
            except OSError:
                pass
            except Exception:
                pass

    # write方法已移至上方

    def readAllStandardOutput(self):
        """读取所有标准输出"""
        if hasattr(self, '_output_buffer') and self._output_buffer:
            data = bytes(self._output_buffer)
            self._output_buffer = bytearray()
            return data
        return b''

    def readAll(self):
        """读取所有可用数据"""
        return self.readAllStandardOutput()

    def setFlowControlEnabled(self, enabled):
        """设置流控制（暂时不实现）"""
        pass

    # sendData方法已移至上方

    def openPty(self):
        """打开PTY"""
        # 这在start()方法中已经实现了
        return True

    def setWinSize(self, lines, cols):
        """设置窗口大小 - 关键：SSH连接需要正确的终端尺寸"""
        self._window_lines = int(lines)
        self._window_cols = int(cols)
        if IS_WINDOWS:
            self.setWinSizeWindows(lines, cols)
            return

        if self._masterFd >= 0:
            try:
                import struct
                import fcntl
                import termios

                # 使用TIOCSWINSZ ioctl设置窗口大小
                win_size = struct.pack('HHHH', lines, cols, 0, 0)
                fcntl.ioctl(self._masterFd, termios.TIOCSWINSZ, win_size)

                # 如果有子进程，发送SIGWINCH信号通知尺寸变化
                if self._childPid > 0:
                    os.kill(self._childPid, signal.SIGWINCH)

            except Exception as e:
                print(f"⚠️ 设置PTY窗口大小失败: {e}")

        # 同时更新pty对象（如果存在）
        if self._pty:
            try:
                self._pty.setWinSize(lines, cols)
            except Exception as e:
                print(f"⚠️ 更新pty对象失败: {e}")

    def setErase(self, erase_char):
        """设置擦除字符"""
        pass  # 暂时不实现

    def setUseUtmp(self, use_utmp):
        """
        设置是否使用utmp - 严格对应C++: void KPtyProcess::setUseUtmp(bool value)

        对应C++实现：
        void KPtyProcess::setUseUtmp(bool value)
        {
            Q_D(KPtyProcess);
            d->addUtmp = value;
        }

        Args:
            use_utmp: 是否使用utmp
        """
        # 对应C++的Q_D(KPtyProcess)宏和d->addUtmp = value
        self._addUtmp = use_utmp

    def isUseUtmp(self):
        """
        返回是否使用utmp - 严格对应C++: bool KPtyProcess::isUseUtmp() const

        对应C++实现：
        bool KPtyProcess::isUseUtmp() const
        {
            Q_D(const KPtyProcess);
            return d->addUtmp;
        }

        Returns:
            是否使用utmp
        """
        # 对应C++的Q_D(const KPtyProcess)宏和return d->addUtmp
        return getattr(self, '_addUtmp', False)

    def setWriteable(self, writeable):
        """设置是否可写"""
        pass  # 暂时不实现

    def setEmptyPTYProperties(self):
        """设置空PTY属性"""
        pass  # 暂时不实现

    def foregroundProcessGroup(self):
        """获取前台进程组"""
        return self._childPid

    def windowSize(self):
        """获取窗口大小"""
        return QSize(getattr(self, "_window_cols", 80), getattr(self, "_window_lines", 24))

    def setWindowSize(self, lines, cols):
        """设置窗口大小"""
        self.setWinSize(lines, cols)

    def closePty(self):
        """关闭PTY"""
        self._cleanup()

    def waitForFinished(self, timeout=3000):
        """等待进程结束"""
        if hasattr(self, '_subprocess') and self._subprocess:
            try:
                self._subprocess.wait(timeout=timeout / 1000)
                return True
            except subprocess.TimeoutExpired:
                return False
        return True

    def exitStatus(self):
        """获取退出状态"""
        if hasattr(self, '_subprocess') and self._subprocess:
            return self._subprocess.returncode
        return 0

    def setUtf8Mode(self, enabled):
        """设置UTF8模式"""
        pass  # 暂时不实现

    def lockPty(self, lock):
        """锁定PTY"""
        pass  # 暂时不实现

    def _cleanup(self):
        """清理资源 - 供内部调用"""
        if hasattr(self, '_notifier') and self._notifier:
            self._notifier.deleteLater()
            self._notifier = None

        if hasattr(self, '_masterFd') and self._masterFd >= 0:
            try:
                os.close(self._masterFd)
            except:
                pass
        self._masterFd = -1

        if hasattr(self, '_slaveFd') and self._slaveFd >= 0:
            try:
                os.close(self._slaveFd)
            except:
                pass
            self._slaveFd = -1

        self._childPid = -1

        if hasattr(self, '_subprocess'):
            del self._subprocess

        # 关键修复：更新QProcess状态
        # 这样Qt的C++析构函数就不会认为进程还在运行
        try:
            self.setProcessState(QProcess.ProcessState.NotRunning)
        except:
            pass

    def __del__(self):
        """
        析构函数

        覆盖QProcess的析构行为，避免在Python GC时触发Qt的"Destroyed while process is still running"警告。
        """
        # 1. 仅做纯Python资源清理
        try:
            if hasattr(self, '_masterFd') and self._masterFd >= 0:
                try:
                    os.close(self._masterFd)
                except:
                    pass
                self._masterFd = -1

            if hasattr(self, '_slaveFd') and self._slaveFd >= 0:
                try:
                    os.close(self._slaveFd)
                except:
                    pass
                self._slaveFd = -1
        except:
            pass

        # 2. 关键：不要调用 super().__del__()
        # QProcess的C++析构函数会自动被调用（由PySide/Qt绑定层管理）
        # 我们不需要（也不应该）在Python的__del__中手动干预Qt对象的销毁流程
        pass

    def _start_windows(self, program, arguments, environment):
        """Windows平台启动进程 - 使用winpty"""
        if not self._winpty_process:
            try:
                from winpty import PtyProcess as WinPtyProcess
            except ImportError:
                print("未安装winpty")
                self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
                return -1

        try:
            # 准备环境变量
            env_dict = os.environ.copy()
            if environment:
                for env_var in environment:
                    if '=' in env_var:
                        key, value = env_var.split('=', 1)
                        env_dict[key] = value

            # 设置TERM
            env_dict['TERM'] = 'xterm-256color'
            # 通过 ConPTY 可完整透传真彩色，显式告知子进程（Node 的 supports-color
            # 据此启用 24-bit 色），确保 Claude Code 等 TUI 的高亮背景按全保真渲染
            env_dict['COLORTERM'] = 'truecolor'

            # 准备命令行
            cmd_args = [program] + (arguments if arguments else [])

            # 获取工作目录
            cwd = self.workingDirectory() if self.workingDirectory() and os.path.isdir(
                self.workingDirectory()) else None

            # 优先使用 ConPTY 后端（完整透传真彩色/256 色 SGR，修复 Windows 下
            # TUI 选中行背景高亮丢失的问题）；ConPTY 不可用时回退到 winpty。
            #
            # 注意 pywinpty 的 PtyProcess.spawn 内部为：
            #     backend = backend or os.environ.get('PYWINPTY_BACKEND', None)
            # 而 3.x 起 Backend.ConPTY == 0，直接传 backend=Backend.ConPTY 会因 0
            # 为假值被丢弃、退化成自动选择。各版本枚举值还不同（3.x: ConPTY=0；
            # 2.x: ConPTY=1）。因此改用环境变量 PYWINPTY_BACKEND 强制——其字符串
            # 非空可绕过上面的假值判断，且用 str(int(Backend.ConPTY)) 动态取当前
            # 版本的正确值。ConPTY 不可用（旧 Windows）时回退到默认/ winpty。
            spawn_kwargs = dict(cwd=cwd, env=env_dict, dimensions=(24, 80))
            self._winpty_process = None
            self._winpty_backend = "auto"

            conpty_val = None
            if WinPtyBackend is not None:
                try:
                    conpty_val = str(int(WinPtyBackend.ConPTY))
                except Exception:
                    conpty_val = None

            if conpty_val is not None:
                _prev_backend_env = os.environ.get("PYWINPTY_BACKEND")
                os.environ["PYWINPTY_BACKEND"] = conpty_val
                try:
                    self._winpty_process = WinPtyProcess.spawn(cmd_args, **spawn_kwargs)
                    self._winpty_backend = "ConPTY"
                except Exception as e:
                    print(f"ConPTY 后端启动失败，回退 winpty: {e}")
                    self._winpty_process = None
                finally:
                    # 还原环境变量，避免影响后续逻辑（子进程使用的是 env_dict，不受影响）
                    if _prev_backend_env is None:
                        os.environ.pop("PYWINPTY_BACKEND", None)
                    else:
                        os.environ["PYWINPTY_BACKEND"] = _prev_backend_env

            if self._winpty_process is None:
                self._winpty_process = WinPtyProcess.spawn(cmd_args, **spawn_kwargs)
                self._winpty_backend = "winpty/auto(fallback)"

            print(f"[cube-shell] Windows PTY 后端 = {self._winpty_backend}")

            self._childPid = 12345  # 假PID

            self.setProcessState(QProcess.ProcessState.Running)
            self.started.emit()

            # 启动读取线程
            self._read_running = True
            self._read_thread = threading.Thread(target=self._read_from_winpty)
            self._read_thread.daemon = True
            self._read_thread.start()

            return 0

        except Exception as e:
            self.setProcessState(QProcess.ProcessState.NotRunning)
            self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
            return -1

    def _read_from_winpty(self):
        """Windows读取线程"""
        while self._read_running and self._winpty_process and self._winpty_process.isalive():
            try:
                # 读取数据
                data = self._winpty_process.read(4096)
                if data:
                    # 确保是bytes
                    if isinstance(data, str):
                        data = data.encode('utf-8')

                    # 发射信号
                    self.readyReadStandardOutput.emit()
                    self.receivedData.emit(data, len(data))

                    # 缓冲数据
                    if not hasattr(self, '_output_buffer'):
                        self._output_buffer = b''
                    self._output_buffer += data
            except EOFError:
                break
            except Exception as e:
                break

        # 退出循环
        self._handle_process_exit_windows()

    def _handle_process_exit_windows(self):
        """Windows进程退出处理"""
        if self._read_running:
            self._read_running = False
            self.setProcessState(QProcess.ProcessState.NotRunning)
            try:
                # 尝试符合QProcess信号签名
                self.finished.emit(0, QProcess.ExitStatus.NormalExit)
            except:
                self.finished.emit(0)
            self._cleanup()
