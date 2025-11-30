#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复的KPtyProcess实现
解决PySide6不支持setChildProcessModifier的问题
"""

import errno
import os
import pty
import signal
import subprocess
import termios
from enum import IntFlag

from PySide6.QtCore import QProcess, QSocketNotifier, Signal, QSize, Slot

from qtermwidget.kprocess import KProcess
from qtermwidget.kpty_device import KPtyDevice


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
    sendData = Signal(bytes)  # 添加sendData信号

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

        # 关键修复：严格对应C++构造函数中的pty->open()调用
        # 对应C++: d->pty->open() 或 d->pty->open(ptyMasterFd)
        if not self._pty.open():
            print("KPtyDevice打开失败")
            # 对应C++的错误处理，但不抛出异常，保持与C++行为一致

        # 初始化PTY通道
        self.setPtyChannels(PtyChannelFlag.AllChannels)

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
            print("进程已在运行，先停止")
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
            print("没有指定要运行的程序")
            self.setProcessState(QProcess.ProcessState.NotRunning)
            self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
            return

        print(f"使用修复的KPtyProcess启动: {program} {arguments}")

        try:
            # 创建PTY
            self._masterFd, self._slaveFd = pty.openpty()
            print(f"PTY创建成功: master={self._masterFd}, slave={self._slaveFd}")

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

            # SSH兼容性环境变量 - 这些是SSH会话正常工作的关键
            env_dict['COLORTERM'] = 'truecolor'
            env_dict['LANG'] = env_dict.get('LANG', 'en_US.UTF-8')  # 确保语言环境设置
            env_dict['LC_ALL'] = env_dict.get('LC_ALL', 'en_US.UTF-8')  # 完整的语言环境

            # SSH会话需要的终端尺寸
            # env_dict['LINES'] = '24'
            # env_dict['COLUMNS'] = '80'

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
            env_dict['FORCE_COLOR'] = '1'  # 强制颜色输出

            # 清理可能干扰SSH的环境变量
            for problematic_var in ['TMUX', 'TMUX_PANE', 'TERM_SESSION_ID']:
                env_dict.pop(problematic_var, None)

            print(f"设置环境变量: TERM={env_dict.get('TERM')}, PS1={env_dict.get('PS1')}")

            # 准备命令行
            cmd = [program] + (arguments if arguments else [])

            # 启动子进程
            self._start_child_process(program, arguments, env_dict)

            # 设置读取通知器
            self._setup_notifier()

            # 关键：设置初始终端尺寸（SSH连接需要）
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self.setWinSize(24, 80))

            # 发出started信号
            self.setProcessState(QProcess.ProcessState.Running)
            self.started.emit()

            print(f"进程启动成功，PID: {self._childPid}")
            return 0  # 成功返回0，对应C++版本

        except Exception as e:
            print(f"启动进程失败: {e}")
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
            print("PTY属性设置成功（raw模式）")

        except Exception as e:
            print(f"设置PTY属性失败: {e}")

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

                # 第五步：SSH特定设置 - 关键修复！
                # SSH需要类似于xterm的终端模式，不是完全的raw模式
                attrs = termios.tcgetattr(0)  # 获取stdin(slaveFd)的属性

                # 输入模式标志：启用中断和流控制
                attrs[0] |= (termios.BRKINT | termios.IGNPAR | termios.ISTRIP | termios.ICRNL)
                attrs[0] |= (termios.IXON | termios.IXOFF)  # 流控制

                # 输出模式标志：启用后处理
                attrs[1] |= termios.OPOST

                # 控制模式标志：8位字符
                attrs[2] |= (termios.CS8 | termios.CREAD | termios.CLOCAL)

                # 本地模式标志：这是SSH工作的关键！
                # 启用回显和规范模式，这样SSH远程shell才能正确显示
                attrs[3] |= (termios.ECHO | termios.ECHOE | termios.ECHOK | termios.ECHONL)
                attrs[3] |= (termios.ICANON | termios.ISIG)

                # 设置控制字符
                attrs[6][termios.VEOF] = 4  # Ctrl+D
                attrs[6][termios.VEOL] = 0  # 额外的行结束符
                attrs[6][termios.VERASE] = 127  # 退格字符
                attrs[6][termios.VINTR] = 3  # Ctrl+C
                attrs[6][termios.VKILL] = 21  # Ctrl+U
                attrs[6][termios.VQUIT] = 28  # Ctrl+\
                attrs[6][termios.VSTART] = 17  # Ctrl+Q
                attrs[6][termios.VSTOP] = 19  # Ctrl+S
                attrs[6][termios.VSUSP] = 26  # Ctrl+Z

                termios.tcsetattr(0, termios.TCSANOW, attrs)

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
                # 父进程
                self._childPid = pid
                print(f"直接fork子进程成功，PID: {self._childPid}")

                # 父进程关闭slave端，只保留master端
                if self._slaveFd >= 0:
                    os.close(self._slaveFd)
                    self._slaveFd = -1
                    print("父进程已关闭slave fd，只保留master fd用于通信")

                # 设置master fd为非阻塞模式
                import fcntl
                flags = fcntl.fcntl(self._masterFd, fcntl.F_GETFL)
                fcntl.fcntl(self._masterFd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                print("设置master fd为非阻塞模式")

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
            # 尝试非阻塞读取
            try:
                # 读取最多4096字节
                data = os.read(self._masterFd, 4096)
            except OSError as e:
                # EAGAIN/EWOULDBLOCK: 暂时没有数据，直接返回
                if e.errno in [errno.EAGAIN, errno.EWOULDBLOCK]:
                    return
                # EBADF: 文件描述符已关闭，直接返回
                elif e.errno == errno.EBADF:
                    self._handle_process_exit()
                    return
                # 其他错误（如EIO）：通常表示子进程已退出
                else:
                    self._handle_process_exit()
                    return

            # 读取到0字节（EOF），表示子进程已关闭写端
            if not data:
                self._handle_process_exit()
                return

            # 确保数据是bytes类型
            if isinstance(data, str):
                data = data.encode('utf-8')

            # 发出信号通知有新数据
            self.readyReadStandardOutput.emit()
            self.receivedData.emit(data, len(data))

            # 缓冲数据（供同步读取使用）
            if not hasattr(self, '_output_buffer'):
                self._output_buffer = b''
            self._output_buffer += data

        except Exception as e:
            print(f"PTY读取异常: {e}")
            # 捕获所有未预期的异常，防止崩溃
            pass

    def _handle_process_exit(self):
        """处理进程退出"""
        if self._childPid > 0:
            try:
                # 尝试回收进程
                pid, status = os.waitpid(self._childPid, os.WNOHANG)
                if pid > 0:
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
        if self._childPid > 0:
            try:
                os.kill(self._childPid, signal.SIGTERM)
                # 尝试立即回收（优化），如果不行则由_read_from_pty处理
                self._handle_process_exit()
            except OSError:
                pass
            except Exception:
                pass

    def write(self, data):
        """写入数据到进程"""
        if self._masterFd >= 0:
            try:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                written = os.write(self._masterFd, data)
                return written
            except:
                return -1
        return 0

    def readAllStandardOutput(self):
        """读取所有标准输出"""
        if hasattr(self, '_output_buffer'):
            data = self._output_buffer
            self._output_buffer = b''
            return data
        return b''

    def readAll(self):
        """读取所有可用数据"""
        return self.readAllStandardOutput()

    def setFlowControlEnabled(self, enabled):
        """设置流控制（暂时不实现）"""
        pass

    @Slot(bytes)
    def sendData(self, data):
        """发送数据到PTY - 这个方法作为slot接收emulation的sendData信号"""
        result = self.write(data)
        return result

    def openPty(self):
        """打开PTY"""
        # 这在start()方法中已经实现了
        return True

    def setWinSize(self, lines, cols):
        """设置窗口大小 - 关键：SSH连接需要正确的终端尺寸"""
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
                    try:
                        os.kill(self._childPid, signal.SIGWINCH)
                        print("已发送SIGWINCH信号通知进程窗口尺寸变化")
                    except:
                        pass

            except Exception as e:
                print(f"设置PTY窗口大小失败: {e}")

        # 同时更新pty对象（如果存在）
        if self._pty:
            try:
                self._pty.setWinSize(lines, cols)
            except:
                pass

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
        return QSize(80, 24)  # 默认大小

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
