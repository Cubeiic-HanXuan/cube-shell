"""
Pty模块 - 从QTerminal/Konsole转换而来

这个类用于启动终端进程，向其发送数据，从其接收数据，
并操作用于与进程通信的伪终端接口的各种属性。

原始文件：
- Pty.h
- Pty.cpp

版权信息：
Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>
Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

转换为Python PySide6版本
"""

import os
import signal
import platform
import logging
import struct
import sys
from typing import Optional, List, Dict, Callable
from enum import IntEnum

# Platform detection
IS_WINDOWS = sys.platform == 'win32'

if not IS_WINDOWS:
    import termios
else:
    termios = None

# 直接导入PySide6官方绑定
from PySide6.QtCore import QObject, QSize, Signal, Slot, QTimer, QProcess
from PySide6.QtCore import QByteArray

# 导入KPtyProcess
from .kptyprocess import KPtyProcess, PtyChannelFlag

# 配置日志记录器
logger = logging.getLogger(__name__)


class Pty(KPtyProcess):
    """
    Pty类用于启动终端进程，发送数据到进程，从进程接收数据，
    并操作用于与进程通信的伪终端接口的各种属性。

    要使用这个类，构造一个实例并连接到sendData槽和receivedData信号
    来发送数据到进程或从进程接收数据。

    要启动终端进程，使用程序名和适当的参数调用start()方法。

    对应C++: class Pty: public KPtyProcess
    """

    # 信号定义 - 对应C++: signals:
    receivedData = Signal(bytes, int)  # 对应C++: void receivedData(const char* buffer, int length)

    def __init__(self, parent: Optional[QObject] = None):
        """
        构造一个新的Pty。

        连接到sendData()槽和receivedData()信号以准备发送和接收终端进程的数据。

        要启动终端进程，使用要启动的程序名和适当的参数调用start()方法。

        Args:
            parent: 父对象

        对应C++: explicit Pty(QObject* parent = nullptr)
        """
        super().__init__(parent)
        self._init()

    @classmethod
    def createWithMasterFd(cls, ptyMasterFd: int, parent: Optional[QObject] = None) -> 'Pty':
        """
        使用打开的pty master构造进程。

        Args:
            ptyMasterFd: pty master文件描述符
            parent: 父对象

        Returns:
            Pty: 新的Pty实例

        对应C++: explicit Pty(int ptyMasterFd, QObject* parent = nullptr)
        """
        instance = cls.__new__(cls)
        # 使用KPtyProcess的createWithFd方法
        KPtyProcess._initKPtyProcess(instance, ptyMasterFd, parent)
        instance._init()
        return instance

    def _init(self):
        """
        初始化Pty - 对应C++: void init()

        设置默认值并连接信号。
        """
        # 必须调用父类的子进程修改器，因为它设置文件描述符等
        # 对应C++: auto parentChildProcModifier = KPtyProcess::childProcessModifier()
        original_modifier = getattr(self, '_childModifier', None)

        def child_process_modifier():
            """子进程修改器 - 对应C++: setChildProcessModifier([parentChildProcModifier = ...])"""
            # 首先调用父类修改器
            if original_modifier:
                original_modifier()

            # 重置所有信号处理程序 - 对应C++信号处理代码
            # 这确保终端应用程序响应通过键序列生成的信号，如Ctrl+C（发送SIGINT）
            try:
                # 对应C++: struct sigaction action
                for sig in range(1, signal.NSIG):
                    try:
                        # 对应C++: action.sa_handler = SIG_DFL
                        signal.signal(sig, signal.SIG_DFL)
                    except (OSError, ValueError):
                        # 某些信号无法重置，忽略错误
                        pass
            except Exception as e:
                logger.warning(f"重置信号处理程序失败: {e}")

        # 设置修改器
        self._childModifier = child_process_modifier

        # 初始化实例变量 - 对应C++私有成员
        self._windowColumns = 0  # 对应C++: int _windowColumns
        self._windowLines = 0  # 对应C++: int _windowLines
        self._eraseChar = 0  # 对应C++: char _eraseChar
        self._xonXoff = True  # 对应C++: bool _xonXoff
        self._utf8 = True  # 对应C++: bool _utf8

        # 连接信号 - 对应C++: connect(pty(), SIGNAL(readyRead()), this, SLOT(dataReceived()))
        if self.pty() and hasattr(self.pty(), 'readyRead'):
            self.pty().readyRead.connect(self._dataReceived)

        # 设置PTY通道 - 对应C++: setPtyChannels(KPtyProcess::AllChannels)
        self.setPtyChannels(PtyChannelFlag.AllChannels)

    def __del__(self):
        """
        析构函数 - 对应C++: ~Pty() override
        """
        # 警告：不要在析构函数中进行复杂的QObject操作
        # Python的GC机制可能在QApplication销毁后才调用此函数
        # 此时底层的C++对象可能已经部分或完全销毁

        # 仅做最基本的资源释放尝试，不保证成功
        try:
            # 如果pty对象还存在，尝试关闭文件描述符
            if hasattr(self, 'pty') and self.pty():
                try:
                    self.pty().close()
                except:
                    pass
        except:
            pass

    def setWindowSize(self, lines: int, cols: int):
        """
        设置此终端使用的窗口大小（字符的行数和列数）。

        Args:
            lines: 行数
            cols: 列数

        对应C++: void Pty::setWindowSize(int lines, int cols)
        """
        self._windowColumns = cols
        self._windowLines = lines

        # 调用父类方法，父类已经处理了Windows和Linux的差异
        super().setWindowSize(lines, cols)

    def windowSize(self) -> QSize:
        """
        返回此终端使用的窗口大小。

        Returns:
            QSize: 窗口大小

        对应C++: QSize Pty::windowSize() const
        """
        return QSize(self._windowColumns, self._windowLines)

    def setFlowControlEnabled(self, enable: bool):
        """
        启用或禁用Xon/Xoff流控制。
        流控制设置可能稍后被终端应用程序更改，
        所以flowControlEnabled()可能不等于之前调用setFlowControlEnabled()中@p enable的值。

        Args:
            enable: 是否启用流控制

        对应C++: void Pty::setFlowControlEnabled(bool enable)
        """
        self._xonXoff = enable

        if IS_WINDOWS:
            return

        # 对应C++: if (pty()->masterFd() >= 0)
        if self.pty() and self.pty().masterFd() >= 0:
            try:
                # 对应C++: struct ::termios ttmode; pty()->tcGetAttr(&ttmode)
                pty_device = self.pty()
                if hasattr(pty_device, 'tcGetAttr'):
                    ttmode = pty_device.tcGetAttr()
                else:
                    # 备用方法，直接使用termios
                    ttmode = termios.tcgetattr(pty_device.masterFd())

                # 对应C++流控制设置
                if not enable:
                    # 对应C++: ttmode.c_iflag &= ~(IXOFF | IXON)
                    ttmode[0] &= ~(termios.IXOFF | termios.IXON)
                else:
                    # 对应C++: ttmode.c_iflag |= (IXOFF | IXON)
                    ttmode[0] |= (termios.IXOFF | termios.IXON)

                # 对应C++: if (!pty()->tcSetAttr(&ttmode))
                if hasattr(pty_device, 'tcSetAttr'):
                    if not pty_device.tcSetAttr(ttmode):
                        logger.warning("无法设置终端属性")
                else:
                    termios.tcsetattr(pty_device.masterFd(), termios.TCSANOW, ttmode)

            except Exception as e:
                logger.warning(f"设置流控制失败: {e}")

    def flowControlEnabled(self) -> bool:
        """
        查询终端状态并返回是否启用了Xon/Xoff流控制。

        Returns:
            bool: 是否启用流控制

        对应C++: bool Pty::flowControlEnabled() const
        """
        # 对应C++: if (pty()->masterFd() >= 0)
        if self.pty() and self.pty().masterFd() >= 0:
            try:
                # 对应C++: struct ::termios ttmode; pty()->tcGetAttr(&ttmode)
                pty_device = self.pty()
                if hasattr(pty_device, 'tcGetAttr'):
                    ttmode = pty_device.tcGetAttr()
                else:
                    ttmode = termios.tcgetattr(pty_device.masterFd())

                # 对应C++: return ttmode.c_iflag & IXOFF && ttmode.c_iflag & IXON
                return bool((ttmode[0] & termios.IXOFF) and (ttmode[0] & termios.IXON))

            except Exception as e:
                logger.warning(f"获取流控制状态失败: {e}")

        logger.warning("无法获取流控制状态，终端未连接")
        return False

    @Slot(bool)
    def setUtf8Mode(self, enable: bool):
        """
        在支持的系统上将pty设置为UTF-8模式。

        Args:
            enable: 是否启用UTF-8模式

        对应C++: void Pty::setUtf8Mode(bool enable)
        """
        self._utf8 = enable

        if IS_WINDOWS:
            return

        # 对应C++: #ifdef IUTF8
        if not hasattr(termios, 'IUTF8'):
            return  # 系统不支持IUTF8

        # 对应C++: if (pty()->masterFd() >= 0)
        if self.pty() and self.pty().masterFd() >= 0:
            try:
                # 对应C++: struct ::termios ttmode; pty()->tcGetAttr(&ttmode)
                pty_device = self.pty()
                if hasattr(pty_device, 'tcGetAttr'):
                    ttmode = pty_device.tcGetAttr()
                else:
                    ttmode = termios.tcgetattr(pty_device.masterFd())

                # 对应C++UTF-8设置
                if not enable:
                    # 对应C++: ttmode.c_iflag &= ~IUTF8
                    ttmode[0] &= ~termios.IUTF8
                else:
                    # 对应C++: ttmode.c_iflag |= IUTF8
                    ttmode[0] |= termios.IUTF8

                # 对应C++: if (!pty()->tcSetAttr(&ttmode))
                if hasattr(pty_device, 'tcSetAttr'):
                    if not pty_device.tcSetAttr(ttmode):
                        logger.warning("无法设置终端属性")
                else:
                    termios.tcsetattr(pty_device.masterFd(), termios.TCSANOW, ttmode)

            except Exception as e:
                logger.warning(f"设置UTF-8模式失败: {e}")

    def setErase(self, erase: int):
        """
        设置退格字符。

        Args:
            erase: 退格字符（ASCII值）

        对应C++: void Pty::setErase(char erase)
        """
        self._eraseChar = erase

        if IS_WINDOWS:
            return

        # 对应C++: if (pty()->masterFd() >= 0)
        if self.pty() and self.pty().masterFd() >= 0:
            try:
                # 对应C++: struct ::termios ttmode; pty()->tcGetAttr(&ttmode)
                pty_device = self.pty()
                if hasattr(pty_device, 'tcGetAttr'):
                    ttmode = pty_device.tcGetAttr()
                else:
                    ttmode = termios.tcgetattr(pty_device.masterFd())

                # 对应C++: ttmode.c_cc[VERASE] = erase
                if isinstance(ttmode, list) and len(ttmode) > 6:
                    ttmode[6][termios.VERASE] = erase

                # 对应C++: if (!pty()->tcSetAttr(&ttmode))
                if hasattr(pty_device, 'tcSetAttr'):
                    if not pty_device.tcSetAttr(ttmode):
                        logger.warning("无法设置终端属性")
                else:
                    termios.tcsetattr(pty_device.masterFd(), termios.TCSANOW, ttmode)

            except Exception as e:
                logger.warning(f"设置退格字符失败: {e}")

    def erase(self) -> int:
        """
        获取退格字符。

        Returns:
            int: 退格字符（ASCII值）

        对应C++: char Pty::erase() const
        """
        if IS_WINDOWS:
            return self._eraseChar

        # 对应C++: if (pty()->masterFd() >= 0)
        if self.pty() and self.pty().masterFd() >= 0:
            try:
                # 对应C++: struct ::termios ttyAttributes; pty()->tcGetAttr(&ttyAttributes)
                pty_device = self.pty()
                if hasattr(pty_device, 'tcGetAttr'):
                    ttmode = pty_device.tcGetAttr()
                else:
                    ttmode = termios.tcgetattr(pty_device.masterFd())

                # 对应C++: return ttyAttributes.c_cc[VERASE]
                if isinstance(ttmode, list) and len(ttmode) > 6:
                    return ttmode[6][termios.VERASE]
            except Exception as e:
                logger.warning(f"获取退格字符失败: {e}")

        return self._eraseChar

    def addEnvironmentVariables(self, environment: List[str]):
        """
        获取键=值对列表并将它们添加到进程的环境中。

        Args:
            environment: 环境变量列表，格式为"KEY=VALUE"

        对应C++: void Pty::addEnvironmentVariables(const QStringList& environment)
        """
        termEnvVarAdded = False

        # 对应C++: for (const QString &pair : environment)
        for pair in environment:
            # 对应C++: int pos = pair.indexOf(QLatin1Char('='))
            pos = pair.find('=')

            if pos >= 0:
                # 对应C++: QString variable = pair.left(pos); QString value = pair.mid(pos+1)
                variable = pair[:pos]
                value = pair[pos + 1:]

                # 对应C++: setEnv(variable,value)
                self.setEnv(variable, value)

                # 对应C++: if (variable == QLatin1String("TERM"))
                if variable == "TERM":
                    termEnvVarAdded = True

        # 对应C++: if (!termEnvVarAdded) setEnv(QStringLiteral("TERM"), QStringLiteral("xterm-256color"))
        if not termEnvVarAdded:
            self.setEnv("TERM", "xterm-256color")

    def start(self, program: str, programArguments: List[str],
              environment: List[str], winid: int, addToUtmp: bool) -> int:
        """
        启动终端进程。

        如果进程成功启动则返回0，否则返回非零。

        Args:
            program: 要启动的程序路径
            programArguments: 传递给程序的参数
            environment: 添加到新进程环境的键=值对列表
            winid: 指定进程环境中WINDOWID环境变量的值
            addToUtmp: 指定是否应为使用的pty创建utmp条目

        Returns:
            int: 成功时返回0，失败时返回非零

        对应C++: int Pty::start(const QString& program, const QStringList& programArguments, ...)
        """
        # 对应C++: clearProgram()
        self.clearProgram()

        # 对应C++: 历史原因检查和设置程序
        # Q_ASSERT(programArguments.count() >= 1)
        if len(programArguments) < 1:
            logger.error("程序参数列表不能为空")
            return -1

        # 对应C++: setProgram(program, programArguments.mid(1))
        self.setProgram(program, programArguments[1:])

        # 对应C++: addEnvironmentVariables(environment)
        self.addEnvironmentVariables(environment)

        # 对应C++: setEnv(QLatin1String("WINDOWID"), QString::number(winid))
        self.setEnv("WINDOWID", str(winid))
        # 对应C++: setEnv(QLatin1String("COLORTERM"), QLatin1String("truecolor"))
        self.setEnv("COLORTERM", "truecolor")

        # 对应C++语言环境修复
        # 对应C++: setEnv(QLatin1String("LANGUAGE"),QString(),false)
        self.setEnv("LANGUAGE", "", False)  # 不覆盖现有值

        # 对应C++: setUseUtmp(addToUtmp)
        self.setUseUtmp(addToUtmp)

        # 设置终端属性 - 对应C++中的termios操作
        self._applyTerminalSettings()

        # 对应C++: pty()->setWinSize(_windowLines, _windowColumns)
        if self.pty():
            self.pty().setWinSize(self._windowLines, self._windowColumns)

        # 对应C++: KProcess::start()
        try:
            # 严格对应C++: 无参数调用
            super().start()
        except Exception as e:
            logger.error(f"启动进程失败: {e}")
            return -1

        # 对应C++: if (!waitForStarted()) return -1
        if not self.waitForStarted():
            return -1

        # 启动一个独立线程来监控读取错误，用于处理PTY异常断开
        # 这不是标准C++实现的一部分，但对于Python版本是必要的
        return 0

    def _applyTerminalSettings(self):
        """
        应用终端设置 - 对应C++: start()方法中的termios操作
        """
        if IS_WINDOWS:
            return

        if not self.pty() or self.pty().masterFd() < 0:
            return

        try:
            # 对应C++: struct ::termios ttmode; pty()->tcGetAttr(&ttmode)
            pty_device = self.pty()
            if hasattr(pty_device, 'tcGetAttr'):
                ttmode = pty_device.tcGetAttr()
            else:
                ttmode = termios.tcgetattr(pty_device.masterFd())

            # 对应C++流控制设置
            if not self._xonXoff:
                # 对应C++: ttmode.c_iflag &= ~(IXOFF | IXON)
                ttmode[0] &= ~(termios.IXOFF | termios.IXON)
            else:
                # 对应C++: ttmode.c_iflag |= (IXOFF | IXON)
                ttmode[0] |= (termios.IXOFF | termios.IXON)

            # 对应C++UTF-8设置
            if hasattr(termios, 'IUTF8'):
                if not self._utf8:
                    # 对应C++: ttmode.c_iflag &= ~IUTF8
                    ttmode[0] &= ~termios.IUTF8
                else:
                    # 对应C++: ttmode.c_iflag |= IUTF8
                    ttmode[0] |= termios.IUTF8

            # 对应C++: if (_eraseChar != 0) ttmode.c_cc[VERASE] = _eraseChar
            if self._eraseChar != 0 and isinstance(ttmode, list) and len(ttmode) > 6:
                # Python termios中控制字符必须是bytes类型!
                erase_char = self._eraseChar
                if isinstance(erase_char, str):
                    erase_char_byte = erase_char.encode('latin-1')[0:1] if erase_char else b'\x08'
                elif isinstance(erase_char, int):
                    # 确保值在有效范围内 (0-255)
                    erase_char = max(0, min(255, int(erase_char)))
                    erase_char_byte = bytes([erase_char])
                elif isinstance(erase_char, bytes):
                    erase_char_byte = erase_char[0:1] if len(erase_char) > 0 else b'\x08'
                else:
                    erase_char_byte = b'\x08'  # 默认退格字符

                # Python termios要求控制字符是单字节bytes对象
                ttmode[6][termios.VERASE] = erase_char_byte

            # 对应C++: if (!pty()->tcSetAttr(&ttmode))
            if hasattr(pty_device, 'tcSetAttr'):
                if not pty_device.tcSetAttr(ttmode):
                    logger.warning("无法设置终端属性")
            else:
                termios.tcsetattr(pty_device.masterFd(), termios.TCSANOW, ttmode)

        except Exception as e:
            logger.warning(f"应用终端设置失败: {e}")

    def setEmptyPTYProperties(self):
        """
        为"空PTY"设置属性。

        对应C++: void Pty::setEmptyPTYProperties()
        """
        # 这与_applyTerminalSettings相同的逻辑
        self._applyTerminalSettings()

    def setWriteable(self, writeable: bool):
        """
        设置PTY是否可写。

        Args:
            writeable: 是否允许其他用户写入终端

        对应C++: void Pty::setWriteable(bool writeable)
        """
        if not self.pty():
            logger.warning("PTY设备未初始化，无法设置写权限")
            return

        try:
            # 对应C++: struct stat sbuf; stat(pty()->ttyName(), &sbuf)
            tty_name = self.pty().ttyName()
            if not tty_name:
                logger.warning("无法获取PTY设备名称")
                return

            # 获取当前文件状态
            import stat
            current_stat = os.stat(tty_name)
            current_mode = current_stat.st_mode

            if writeable:
                # 对应C++: chmod(pty()->ttyName(), sbuf.st_mode | S_IWGRP)
                new_mode = current_mode | stat.S_IWGRP
            else:
                # 对应C++: chmod(pty()->ttyName(), sbuf.st_mode & ~(S_IWGRP|S_IWOTH))
                new_mode = current_mode & ~(stat.S_IWGRP | stat.S_IWOTH)

            os.chmod(tty_name, new_mode)

        except (OSError, AttributeError) as e:
            logger.warning(f"设置PTY写权限失败: {e}")

    @Slot(bool)
    def lockPty(self, lock: bool):
        """
        暂停或恢复处理来自终端进程标准输出的数据。

        Args:
            lock: 如果为True，暂停输出处理；否则恢复处理

        对应C++: void Pty::lockPty(bool lock)
        """
        # 对应C++注释：TODO: Support for locking the Pty
        # 目前C++实现是空的，我们也保持相同
        # if lock:
        #     suspend()
        # else:
        #     resume()
        pass

    @Slot(bytes, int)
    def sendData(self, data: bytes, length: int = None):
        """
        向当前控制终端的进程发送数据（其ID由foregroundProcessGroup()返回）

        Args:
            data: 要发送的数据
            length: 数据长度（如果为None，使用数据的实际长度）

        对应C++: void Pty::sendData(const char* data, int length)
        """
        if length is None:
            length = len(data)

        # 对应C++: if (!length) return
        if not length:
            return

        # 截取指定长度的数据
        if length < len(data):
            data = data[:length]

        # 对应C++: if (!pty()->write(data,length))
        # 使用writeData方法，这是KPtyDevice实际的写入实现
        if not self.pty():
            logger.warning("Pty::sendData - PTY设备未初始化")
            return

        try:
            bytes_written = self.pty().writeData(data)
            if bytes_written != len(data):
                logger.warning(f"Pty::sendData - 数据写入不完整：期望{len(data)}字节，实际写入{bytes_written}字节")
        except Exception as e:
            logger.warning(f"Pty::sendData - 无法向终端进程发送输入数据: {e}")

    @Slot()
    def _dataReceived(self):
        """
        处理来自PTY的数据 - 对应C++: void Pty::dataReceived()

        当pty设备有数据可读时调用此方法。
        读取数据并通过receivedData信号发出。
        """
        # 对应C++: QByteArray data = pty()->readAll();
        if not self.pty():
            return

        try:
            qbytearray_data = self.pty().readAll()

            # 对应C++: if (data.isEmpty()) { return; }
            if not qbytearray_data or len(qbytearray_data) == 0:
                return

            # 对应C++: emit receivedData(data.constData(),data.size());
            # 修复：QByteArray转换为bytes
            try:
                # 方法1：直接使用bytes()构造函数
                bytes_data = bytes(qbytearray_data)
                self.receivedData.emit(bytes_data, len(bytes_data))
                logger.debug(f"发出receivedData信号，数据长度: {len(bytes_data)}")

            except Exception as conv_error:
                # 方法2：使用data()方法
                try:
                    if hasattr(qbytearray_data, 'data'):
                        raw_data = qbytearray_data.data()
                        self.receivedData.emit(raw_data, len(raw_data))
                        logger.debug(f"使用data()方法发出receivedData信号，数据长度: {len(raw_data)}")
                    else:
                        logger.warning(f"QByteArray转换失败: {conv_error}")
                except Exception as e2:
                    logger.warning(f"receivedData信号发送失败: {e2}")

        except Exception as e:
            logger.warning(f"_dataReceived处理失败: {e}")

    def foregroundProcessGroup(self) -> int:
        """
        返回终端当前前台进程的进程ID。
        这是当前正在读取通过sendData()发送到终端的输入的进程。

        如果读取前台进程组时出现问题，将返回0。

        Returns:
            int: 前台进程组ID，出错时返回0

        对应C++: int Pty::foregroundProcessGroup() const
        """
        # 对应C++: const int master_fd = pty()->masterFd()
        if not self.pty():
            return 0

        master_fd = self.pty().masterFd()

        # 对应C++: if (master_fd >= 0)
        if master_fd >= 0:
            try:
                # 对应C++: int pid = tcgetpgrp(master_fd)
                import os
                pid = os.tcgetpgrp(master_fd)

                # 对应C++: if (pid != -1) return pid
                if pid != -1:
                    return pid

            except OSError as e:
                logger.debug(f"获取前台进程组失败: {e}")

        return 0

    def closePty(self):
        """
        关闭底层的pty master/slave对。

        对应C++: void Pty::closePty()
        """
        # 对应C++: pty()->close()
        if self.pty():
            self.pty().close()

    # 父类方法的重写和扩展
    def setEnv(self, name: str, value: str, overwrite: bool = True):
        """
        设置环境变量 - 扩展自KProcess

        Args:
            name: 变量名
            value: 变量值
            overwrite: 是否覆盖现有值
        """
        if hasattr(super(), 'setEnv'):
            super().setEnv(name, value, overwrite)
        else:
            # 备用实现
            if overwrite or name not in os.environ:
                os.environ[name] = value

    def clearProgram(self):
        """清除程序设置 - 扩展自KProcess"""
        if hasattr(super(), 'clearProgram'):
            super().clearProgram()
        else:
            # 备用实现
            self._program = ""
            self._arguments = []

    def setProgram(self, program: str, arguments: List[str] = None):
        """
        设置要执行的程序和参数

        Args:
            program: 程序路径
            arguments: 程序参数列表
        """
        if hasattr(super(), 'setProgram'):
            super().setProgram(program, arguments or [])
        else:
            # 备用实现
            self._program = program
            self._arguments = arguments or []

    def waitForStarted(self, msecs: int = 30000) -> bool:
        """
        等待进程启动

        Args:
            msecs: 等待时间（毫秒）

        Returns:
            bool: 进程是否成功启动
        """
        if hasattr(super(), 'waitForStarted'):
            return super().waitForStarted(msecs)
        else:
            # 备用实现 - 简化版本
            return True


# 便利函数
def createPty(parent: Optional[QObject] = None) -> Optional[Pty]:
    """
    创建Pty进程的便利函数

    Args:
        parent: 父对象

    Returns:
        Optional[Pty]: 成功时返回Pty对象，失败时返回None
    """
    try:
        pty = Pty(parent)
        if pty.pty() and pty.pty().masterFd() != -1:
            return pty
        else:
            logger.error("无法创建Pty：PTY设备初始化失败")
            return None
    except Exception as e:
        logger.error(f"创建Pty失败: {e}")
        return None


def createPtyWithMasterFd(masterFd: int, parent: Optional[QObject] = None) -> Optional[Pty]:
    """
    使用现有master文件描述符创建Pty进程的便利函数

    Args:
        masterFd: master文件描述符
        parent: 父对象

    Returns:
        Optional[Pty]: 成功时返回Pty对象，失败时返回None
    """
    try:
        pty = Pty.createWithMasterFd(masterFd, parent)
        return pty
    except Exception as e:
        logger.error(f"使用master FD创建Pty失败: {e}")
        return None


# 导出的类和函数
__all__ = [
    'Pty',
    'createPty',
    'createPtyWithMasterFd'
]