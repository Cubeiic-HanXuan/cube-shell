"""
KPtyDevice模块 - 从KDE/Qt终端模拟器转换而来

这个模块将KPty封装为QIODevice，使其可以与Qt流类一起使用，
提供异步I/O操作、信号发射、缓冲机制等功能。

原始文件：
- kptydevice.h
- kptydevice.cpp

版权信息：
Copyright (C) 2007 Oswald Buddenhagen <ossi@kde.org>
Copyright (C) 2010 KDE e.V. <kde-ev-board@kde.org>

转换为Python PySide6版本
"""

import errno
import logging
import os
import sys
import time
from typing import Optional, Union

# Platform detection
IS_WINDOWS = sys.platform == 'win32'

if not IS_WINDOWS:
    import fcntl
    import select
    import termios
else:
    fcntl = None
    select = None
    termios = None

# 直接导入PySide6
from PySide6.QtCore import (
    QIODevice, QObject, Signal, QSocketNotifier, QTimer,
    QByteArray, QCoreApplication, Slot
)

# 导入KPty模块
from .kpty import KPty, KPtyPrivate

# 常量定义
KMAXINT = (2 ** 31 - 1)
CHUNKSIZE = 4096

# 平台特定的ioctl命令定义
if IS_WINDOWS:
    PTY_BYTES_AVAILABLE = 0  # Windows不使用ioctl控制PTY
elif sys.platform in ['freebsd', 'darwin']:  # FreeBSD, macOS
    PTY_BYTES_AVAILABLE = termios.TIOCOUTQ  # "the other end's output queue size"
elif hasattr(termios, 'TIOCINQ'):
    PTY_BYTES_AVAILABLE = termios.TIOCINQ  # "our end's input queue size"
else:
    PTY_BYTES_AVAILABLE = termios.FIONREAD  # more generic ioctl


# NO_INTR宏的Python实现
def no_intr(func, *args):
    """重试机制，处理EINTR中断"""
    while True:
        try:
            return func(*args)
        except OSError as e:
            if e.errno != errno.EINTR:
                raise
            continue


# timeradd和timersub的Python实现（用于非Linux平台）
def timeradd(a, b):
    """时间相加"""
    sec = a.tv_sec + b.tv_sec
    usec = a.tv_usec + b.tv_usec
    if usec >= 1000000:
        sec += 1
        usec -= 1000000
    return time.struct_time((sec, usec))


def timersub(a, b):
    """时间相减"""
    sec = a.tv_sec - b.tv_sec
    usec = a.tv_usec - b.tv_usec
    if usec < 0:
        sec -= 1
        usec += 1000000
    return time.struct_time((sec, usec))


# 日志记录器
logger = logging.getLogger(__name__)


class KRingBuffer:
    """
    环形缓冲区实现 - 对应C++ KRingBuffer

    对应C++: class KRingBuffer
    提供与C++版本完全一致的接口和行为
    """

    def __init__(self):
        """初始化缓冲区 - 对应C++构造函数"""
        self.clear()

    def clear(self):
        """清空缓冲区 - 对应C++: void clear()"""
        self.buffers = []
        tmp = bytearray(CHUNKSIZE)
        self.buffers.append(tmp)
        self.head = 0
        self.tail = 0
        self.totalSize = 0  # 使用C++风格的驼峰命名

    def isEmpty(self) -> bool:
        """检查缓冲区是否为空 - 对应C++: inline bool isEmpty() const"""
        return len(self.buffers) == 1 and self.tail == 0

    def size(self) -> int:
        """返回缓冲区大小 - 对应C++: inline int size() const"""
        return self.totalSize

    def readSize(self) -> int:
        """返回可读取大小 - 对应C++: inline int readSize() const"""
        if len(self.buffers) == 1:
            return self.tail - self.head
        else:
            return len(self.buffers[0]) - self.head

    def readPointer(self) -> bytes:
        """返回读取指针 - 对应C++: inline const char *readPointer() const"""
        assert self.totalSize > 0, "Buffer must not be empty (Q_ASSERT equivalent)"
        return bytes(self.buffers[0][self.head:self.head + self.readSize()])

    def free(self, bytes_count: int):
        """释放指定字节数 - 对应C++: void free(int bytes)"""
        self.totalSize -= bytes_count
        assert self.totalSize >= 0, "Total size must not be negative (Q_ASSERT equivalent)"

        # 对应C++的forever循环
        while True:
            nbs = self.readSize()

            if bytes_count < nbs:
                self.head += bytes_count
                if self.head == self.tail and len(self.buffers) == 1:
                    self.buffers[0] = bytearray(CHUNKSIZE)
                    self.head = self.tail = 0
                break

            bytes_count -= nbs
            if len(self.buffers) == 1:
                self.buffers[0] = bytearray(CHUNKSIZE)
                self.head = self.tail = 0
                break

            self.buffers.pop(0)  # 对应C++的pop_front()
            self.head = 0

    def reserve(self, bytes_count: int) -> memoryview:
        """预留指定字节数空间 - 对应C++: char *reserve(int bytes)"""
        self.totalSize += bytes_count

        if self.tail + bytes_count <= len(self.buffers[-1]):
            # 当前缓冲区有足够空间
            start = self.tail
            self.tail += bytes_count
            return memoryview(self.buffers[-1])[start:self.tail]
        else:
            # 需要新的缓冲区 - 对应C++逻辑
            self.buffers[-1] = self.buffers[-1][:self.tail]  # resize
            tmp = bytearray(max(CHUNKSIZE, bytes_count))
            self.buffers.append(tmp)
            self.tail = bytes_count
            return memoryview(tmp)[:bytes_count]

    def unreserve(self, bytes_count: int):
        """取消预留的字节数 - 对应C++: inline void unreserve(int bytes)"""
        self.totalSize -= bytes_count
        self.tail -= bytes_count

    def write(self, data: Union[bytes, str], length: Optional[int] = None):
        """写入数据 - 对应C++: inline void write(const char *data, int len)"""
        if isinstance(data, str):
            data = data.encode('utf-8')

        if length is not None:
            data = data[:length]

        data_len = len(data)
        view = self.reserve(data_len)
        view[:] = data

    def indexAfter(self, char: Union[int, str], maxLength: int = KMAXINT) -> int:
        """查找字符首次出现后的索引 - 对应C++: int indexAfter(char c, int maxLength = KMAXINT) const"""
        if isinstance(char, str):
            char = ord(char)

        index = 0
        start = self.head
        buffer_idx = 0

        # 对应C++的forever循环逻辑
        while True:
            if maxLength == 0:
                return index
            if index == self.size():
                return -1

            if buffer_idx >= len(self.buffers):
                break

            buf = self.buffers[buffer_idx]
            buffer_idx += 1

            # 确定结束位置
            if buffer_idx == len(self.buffers):
                end = self.tail
            else:
                end = len(buf)

            length = min(end - start, maxLength)

            # 查找字符 - 对应C++的memchr
            for i in range(start, start + length):
                if buf[i] == char:
                    return index + (i - start) + 1

            index += length
            maxLength -= length
            start = 0

        return -1

    def lineSize(self, maxLength: int = KMAXINT) -> int:
        """返回行大小（到换行符） - 对应C++: inline int lineSize(int maxLength = KMAXINT) const"""
        return self.indexAfter(ord('\n'), maxLength)

    def canReadLine(self) -> bool:
        """检查是否可以读取完整一行 - 对应C++: inline bool canReadLine() const"""
        return self.lineSize() != -1

    def read(self, data: bytearray, maxLength: int) -> int:
        """读取数据到提供的缓冲区 - 对应C++: int read(char *data, int maxLength)"""
        bytesToRead = min(self.size(), maxLength)
        readSoFar = 0

        while readSoFar < bytesToRead:
            ptr = self.readPointer()
            bs = min(bytesToRead - readSoFar, len(ptr))
            data[readSoFar:readSoFar + bs] = ptr[:bs]
            readSoFar += bs
            self.free(bs)

        return readSoFar

    def readLine(self, data: bytearray, maxLength: int) -> int:
        """读取一行数据 - 对应C++: int readLine(char *data, int maxLength)"""
        lineLen = self.lineSize(min(maxLength, self.size()))
        if lineLen == -1:
            lineLen = min(maxLength, self.size())
        return self.read(data, lineLen)


class KPtyDevicePrivate(KPtyPrivate):
    """
    KPtyDevice的私有实现类 - 对应C++ KPtyDevicePrivate

    对应C++: class KPtyDevicePrivate : public KPtyPrivate
    """

    def __init__(self, parent: 'KPtyDevice'):
        super().__init__(parent)
        # 对应C++成员变量的命名风格
        self.emittedReadyRead = False  # 对应C++: bool emittedReadyRead
        self.emittedBytesWritten = False  # 对应C++: bool emittedBytesWritten
        self.readNotifier: Optional[QSocketNotifier] = None  # 对应C++: QSocketNotifier *readNotifier
        self.writeNotifier: Optional[QSocketNotifier] = None  # 对应C++: QSocketNotifier *writeNotifier
        self.readBuffer = KRingBuffer()  # 对应C++: KRingBuffer readBuffer
        self.writeBuffer = KRingBuffer()  # 对应C++: KRingBuffer writeBuffer
        self.suspended = False  # 额外的暂停状态变量

    def _k_canRead(self) -> bool:
        """
        检查是否可以读取数据 - 对应C++: bool KPtyDevicePrivate::_k_canRead()

        这是一个私有槽函数，对应C++的Q_PRIVATE_SLOT
        Returns:
            是否成功读取到数据
        """
        q = self.q_ptr
        read_bytes = 0

        # 完整版本，使用ioctl检查可用字节数 - 对应C++逻辑
        try:
            # 检查可用字节数 - 对应C++的ioctl(masterFd(), PTY_BYTES_AVAILABLE, ...)
            import array

            # 根据平台选择合适的数据类型
            if sys.platform == 'irix':
                # IRIX使用size_t，但我们用int近似
                buf = array.array('I', [0])  # unsigned int
            else:
                buf = array.array('i', [0])  # int

            # 使用平台特定的ioctl命令
            fcntl.ioctl(q.masterFd(), PTY_BYTES_AVAILABLE, buf)
            available = buf[0]

            # Solaris平台特殊处理 - 对应C++的Q_OS_SOLARIS逻辑
            if sys.platform == 'sunos5':  # Solaris
                if available == 0:
                    try:
                        # Read the 0-byte STREAMS message
                        data = no_intr(os.read, q.masterFd(), 0)
                        if len(data) < 0:  # 实际上应该返回0
                            if self.readNotifier:
                                self.readNotifier.setEnabled(False)
                            if hasattr(q, 'readEof'):
                                q.readEof.emit()
                            return False
                    except OSError:
                        if self.readNotifier:
                            self.readNotifier.setEnabled(False)
                        if hasattr(q, 'readEof'):
                            q.readEof.emit()
                        return False
                    return True

            if available == 0:
                if self.readNotifier:
                    self.readNotifier.setEnabled(False)
                if hasattr(q, 'readEof'):
                    q.readEof.emit()
                return False

            # 预留缓冲区空间 - 对应C++的readBuffer.reserve(available)
            ptr_view = self.readBuffer.reserve(available)

            # 读取数据 - 对应C++的NO_INTR宏
            try:
                data = no_intr(os.read, q.masterFd(), available)
                read_bytes = len(data)
                if read_bytes > 0:
                    ptr_view[:read_bytes] = data
            except OSError as e:
                self.readBuffer.unreserve(available)
                if e.errno == errno.EBADF:
                    if self.readNotifier:
                        self.readNotifier.setEnabled(False)
                    return False
                q.setErrorString("Error reading from PTY")
                return False

            if read_bytes < available:
                # 调整缓冲区大小，如果读取的字节数少于预期
                self.readBuffer.unreserve(available - read_bytes)

        except (OSError, IOError) as e:
            if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                return False
            if e.errno == errno.EBADF:
                if self.readNotifier:
                    self.readNotifier.setEnabled(False)
                return False
            logger.warning(f"读取PTY数据失败: {e}")
            q.setErrorString("Error reading from PTY")
            return False

        if not read_bytes:
            if self.readNotifier:
                self.readNotifier.setEnabled(False)
            if hasattr(q, 'readEof'):
                q.readEof.emit()
            return False
        else:
            # 发射readyRead信号 - 对应C++逻辑
            if not self.emittedReadyRead:
                self.emittedReadyRead = True
                if hasattr(q, 'readyRead'):
                    q.readyRead.emit()
                self.emittedReadyRead = False
            return True

    def _k_canWrite(self) -> bool:
        """
        检查是否可以写入数据 - 对应C++: bool KPtyDevicePrivate::_k_canWrite()

        这是一个私有槽函数，对应C++的Q_PRIVATE_SLOT
        Returns:
            是否成功写入数据
        """
        q = self.q_ptr

        if self.writeNotifier:
            self.writeNotifier.setEnabled(False)
        if self.writeBuffer.isEmpty():
            return False

        # 忽略SIGPIPE信号 - 对应C++的qt_ignore_sigpipe()
        self._ignore_sigpipe()

        try:
            # 写入数据 - 对应C++的write逻辑
            data_to_write = self.writeBuffer.readPointer()
            write_size = self.writeBuffer.readSize()

            if not data_to_write or write_size <= 0:
                return False

            wrote_bytes = no_intr(os.write, q.masterFd(), data_to_write)
            if wrote_bytes > 0:
                self.writeBuffer.free(wrote_bytes)

                # 发射bytesWritten信号 - 对应C++逻辑
                if not self.emittedBytesWritten:
                    self.emittedBytesWritten = True
                    if hasattr(q, 'bytesWritten'):
                        q.bytesWritten.emit(wrote_bytes)
                    self.emittedBytesWritten = False

                if not self.writeBuffer.isEmpty():
                    if self.writeNotifier:
                        self.writeNotifier.setEnabled(True)

                return True
            else:
                q.setErrorString("Error writing to PTY")
                return False

        except (OSError, IOError) as e:
            logger.warning(f"写入PTY数据失败: {e}")
            q.setErrorString("Error writing to PTY")
            return False

    def _ignore_sigpipe(self):
        """忽略SIGPIPE信号 - 对应C++: qt_ignore_sigpipe()"""
        try:
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        except (AttributeError, OSError):
            pass  # 在某些平台上可能不支持

    def doWait(self, msecs: int, reading: bool) -> bool:
        """
        等待I/O操作 - 对应C++: bool KPtyDevicePrivate::doWait(int msecs, bool reading)

        Args:
            msecs: 超时时间（毫秒），-1表示无限等待
            reading: True表示等待读取，False表示等待写入

        Returns:
            操作是否成功
        """
        q = self.q_ptr

        # 时间设置（对应C++的timeval处理）
        if msecs < 0:
            timeout = None
        else:
            timeout = msecs / 1000.0

        # 非Linux平台需要计算绝对时间 - 对应C++的平台特定逻辑
        if sys.platform != 'linux':
            import time as time_mod
            end_time = time_mod.time() + timeout if timeout else None
        else:
            end_time = None

        # 对应C++的while循环条件
        while (reading and self.readNotifier and self.readNotifier.isEnabled()) or \
                (not reading and not self.writeBuffer.isEmpty()):

            # 计算剩余超时时间
            if msecs >= 0:
                if sys.platform != 'linux' and end_time:
                    current_time = time.time()
                    remaining = end_time - current_time
                    if remaining <= 0:
                        q.setErrorString("PTY operation timed out")
                        return False
                    timeout = remaining
                else:
                    timeout = msecs / 1000.0
            else:
                timeout = None

            try:
                # 使用select进行I/O多路复用 - 对应C++的select系统调用
                read_fds = []
                write_fds = []

                if self.readNotifier and self.readNotifier.isEnabled():
                    read_fds.append(q.masterFd())
                if not self.writeBuffer.isEmpty():
                    write_fds.append(q.masterFd())

                ready_read, ready_write, _ = select.select(read_fds, write_fds, [], timeout)

                # 检查select结果 - 对应C++的switch语句
                if not ready_read and not ready_write:
                    if timeout is not None:
                        q.setErrorString("PTY operation timed out")
                        return False
                    continue

                # 处理可读事件 - 对应C++的FD_ISSET检查
                if ready_read and q.masterFd() in ready_read:
                    can_read = self._k_canRead()
                    if reading and can_read:
                        return True

                # 处理可写事件 - 对应C++的FD_ISSET检查
                if ready_write and q.masterFd() in ready_write:
                    can_write = self._k_canWrite()
                    if not reading:
                        return can_write

            except OSError as e:
                if e.errno == errno.EINTR:
                    continue  # 被中断，继续循环 - 对应C++的EINTR处理
                logger.warning(f"PTY等待操作失败: {e}")
                return False

        return False

    def finishOpen(self, mode: int):
        """
        完成打开操作 - 对应C++: void KPtyDevicePrivate::finishOpen(QIODevice::OpenMode mode)

        Args:
            mode: 打开模式
        """
        q = self.q_ptr

        # 调用QIODevice的open - 对应C++: q->QIODevice::open(mode)
        super(KPtyDevice, q).open(mode)

        # 设置非阻塞模式 - 对应C++: fcntl(q->masterFd(), F_SETFL, O_NONBLOCK)
        try:
            fcntl.fcntl(q.masterFd(), fcntl.F_SETFL, os.O_NONBLOCK)
        except OSError as e:
            logger.warning(f"设置非阻塞模式失败: {e}")

        # 清空缓冲区 - 对应C++: readBuffer.clear()
        self.readBuffer.clear()

        # 检查是否有QCoreApplication实例和事件循环
        try:
            app = QCoreApplication.instance()
            if app is not None:
                # 创建socket通知器 - 对应C++的new QSocketNotifier
                self.readNotifier = QSocketNotifier(q.masterFd(), QSocketNotifier.Read, q)
                self.writeNotifier = QSocketNotifier(q.masterFd(), QSocketNotifier.Write, q)

                # 连接信号 - 对应C++的QObject::connect
                self.readNotifier.activated.connect(self._k_canRead)
                self.writeNotifier.activated.connect(self._k_canWrite)

                # 启用读取通知 - 对应C++: readNotifier->setEnabled(true)
                self.readNotifier.setEnabled(True)
            else:
                logger.debug("没有QCoreApplication实例，跳过QSocketNotifier创建")
        except ImportError:
            logger.debug("PySide6不可用，跳过QSocketNotifier创建")


class KPtyDevice(QIODevice, KPty):
    """
    将KPty封装为QIODevice，可与Qt流类一起使用

    对应C++: class KPtyDevice : public QIODevice, public KPty
    提供与C++版本完全一致的接口和行为
    """

    # 信号定义 - 对应C++的Q_SIGNALS
    readEof = Signal()  # 对应C++: void readEof()

    def __init__(self, parent: Optional[QObject] = None):
        """
        构造函数 - 对应C++: KPtyDevice::KPtyDevice(QObject *parent)

        Args:
            parent: 父对象
        """
        QIODevice.__init__(self, parent)

        # 使用KPtyDevicePrivate作为私有实现 - 对应C++的Q_D宏
        private = KPtyDevicePrivate(self)
        KPty.__init__(self, private)

    def __del__(self):
        """
        析构函数：如果pty仍然打开，它将被关闭 - 对应C++: KPtyDevice::~KPtyDevice()

        注意：utmp注册不会自动撤销
        """
        try:
            self.close()
        except (RuntimeError, AttributeError):
            # 忽略PySide6对象已被删除的错误
            pass

    # Q_D宏的Python等价实现
    def _d_func(self):
        """获取私有实现指针 - 对应C++的Q_D宏"""
        # KPtyDevice有两套私有数据：
        # 1. KPtyDevicePrivate (用于Device特定功能)
        # 2. KPtyPrivate (继承自KPty，用于PTY基本功能)
        # 这里返回KPtyDevicePrivate
        return self.d_ptr

    # 对应C++的override方法
    def open(self, mode: Union[int, None] = None, fd: Optional[int] = None) -> bool:
        """
        创建pty master/slave对，或者使用现有的fd打开

        Args:
            mode: 打开模式，默认为ReadWrite | Unbuffered
            fd: 可选的现有文件描述符（用于attach到现有pty）

        Returns:
            成功时返回True

        对应C++:
        - bool KPtyDevice::open(OpenMode mode = ReadWrite | Unbuffered) override
        - bool KPtyDevice::open(int fd, OpenMode mode = ReadWrite | Unbuffered)
        """
        if mode is None:
            mode = QIODevice.ReadWrite | QIODevice.Unbuffered

        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)

        if self.masterFd() >= 0:
            return True

        # 调用KPty的open方法 - 对应C++逻辑
        if fd is not None:
            success = KPty.open(self, fd)
        else:
            success = KPty.open(self)

        if not success:
            self.setErrorString("Error opening PTY")
            return False

        # 完成打开操作 - 对应C++: d->finishOpen(mode)
        d.finishOpen(mode)

        return True

    def close(self):
        """
        关闭pty master/slave对 - 对应C++: void KPtyDevice::close() override
        """
        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)

        if self.masterFd() < 0:
            return

        # 删除socket通知器 - 对应C++的delete操作
        if hasattr(d, 'readNotifier') and d.readNotifier:
            try:
                d.readNotifier.setEnabled(False)
                d.readNotifier.deleteLater()
            except RuntimeError:
                pass  # 对象已被删除
            d.readNotifier = None

        if hasattr(d, 'writeNotifier') and d.writeNotifier:
            try:
                d.writeNotifier.setEnabled(False)
                d.writeNotifier.deleteLater()
            except RuntimeError:
                pass  # 对象已被删除
            d.writeNotifier = None

        # 调用QIODevice的close - 对应C++: QIODevice::close()
        try:
            super().close()
        except RuntimeError:
            pass  # PySide6对象已被删除

        # 调用KPty的close - 对应C++: KPty::close()
        KPty.close(self)

    def setSuspended(self, suspended: bool):
        """
        设置是否暂停监听PTY数据 - 对应C++: void KPtyDevice::setSuspended(bool suspended)

        当KPtyDevice被暂停时，它将不再尝试缓冲来自pty的数据，也不会发射任何信号。

        不要在关闭的pty上使用。
        在调用open()后，pty不会被暂停。如果您需要确保不读取数据，
        请在主循环再次进入之前（即打开pty后立即）调用此函数。

        Args:
            suspended: 是否暂停
        """
        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)
        d.suspended = suspended
        if d.readNotifier:
            d.readNotifier.setEnabled(not suspended)

    def isSuspended(self) -> bool:
        """
        返回KPtyDevice是否暂停监听数据 - 对应C++: bool KPtyDevice::isSuspended() const

        不要在关闭的pty上使用。

        Returns:
            如果暂停监听则返回True

        参见setSuspended()
        """
        d = self._d_func()  # 对应C++的Q_D(const KPtyDevice)
        if d.readNotifier:
            return not d.readNotifier.isEnabled()
        else:
            # 在没有通知器的情况下（比如没有PySide6），返回私有数据中的状态
            return d.suspended

    # @reimp - 对应C++的@reimp注释
    def isSequential(self) -> bool:
        """
        返回设备是否为顺序设备 - 对应C++: bool KPtyDevice::isSequential() const override

        Returns:
            总是返回True，因为PTY是顺序设备
        """
        return True

    # @reimp
    def canReadLine(self) -> bool:
        """
        检查是否可以读取完整一行 - 对应C++: bool KPtyDevice::canReadLine() const override

        Returns:
            如果可以读取完整一行则返回True
        """
        d = self._d_func()  # 对应C++的Q_D(const KPtyDevice)
        if HAS_PYSIDE6:
            return QIODevice.canReadLine(self) or d.readBuffer.canReadLine()
        else:
            return d.readBuffer.canReadLine()

    # @reimp
    def atEnd(self) -> bool:
        """
        检查是否已到达末尾 - 对应C++: bool KPtyDevice::atEnd() const override

        Returns:
            如果已到达末尾则返回True
        """
        d = self._d_func()  # 对应C++的Q_D(const KPtyDevice)
        if HAS_PYSIDE6:
            return QIODevice.atEnd(self) and d.readBuffer.isEmpty()
        else:
            return d.readBuffer.isEmpty()

    # @reimp
    def bytesAvailable(self) -> int:
        """
        返回可读取的字节数 - 对应C++: qint64 KPtyDevice::bytesAvailable() const override

        Returns:
            可读取的字节数
        """
        d = self._d_func()  # 对应C++的Q_D(const KPtyDevice)
        return QIODevice.bytesAvailable(self) + d.readBuffer.size()

    # @reimp
    def bytesToWrite(self) -> int:
        """
        返回待写入的字节数 - 对应C++: qint64 KPtyDevice::bytesToWrite() const override

        Returns:
            待写入的字节数
        """
        d = self._d_func()  # 对应C++的Q_D(const KPtyDevice)
        return d.writeBuffer.size()

    def waitForBytesWritten(self, msecs: int = -1) -> bool:
        """
        等待字节写入完成 - 对应C++: bool KPtyDevice::waitForBytesWritten(int msecs) override

        Args:
            msecs: 超时时间（毫秒），-1表示无限等待

        Returns:
            成功时返回True
        """
        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)
        return d.doWait(msecs, False)

    def waitForReadyRead(self, msecs: int = -1) -> bool:
        """
        等待数据可读 - 对应C++: bool KPtyDevice::waitForReadyRead(int msecs) override

        Args:
            msecs: 超时时间（毫秒），-1表示无限等待

        Returns:
            有数据可读时返回True
        """
        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)
        return d.doWait(msecs, True)

    # protected方法 - 对应C++的protected区域
    def readData(self, maxlen: int) -> bytes:
        """
        读取数据（保护方法） - 对应C++: qint64 KPtyDevice::readData(char *data, qint64 maxlen) override

        Args:
            maxlen: 最大读取字节数

        Returns:
            读取的数据
        """
        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)
        max_len = min(maxlen, KMAXINT)  # 对应C++的qMin<qint64>(maxlen, KMAXINT)

        if max_len <= 0:
            return b''

        buffer = bytearray(max_len)
        bytes_read = d.readBuffer.read(buffer, max_len)

        return bytes(buffer[:bytes_read])

    def readLineData(self, maxlen: int) -> bytes:
        """
        读取一行数据（保护方法） - 对应C++: qint64 KPtyDevice::readLineData(char *data, qint64 maxlen) override

        Args:
            maxlen: 最大读取字节数

        Returns:
            读取的行数据
        """
        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)
        max_len = min(maxlen, KMAXINT)  # 对应C++的qMin<qint64>(maxlen, KMAXINT)

        if max_len <= 0:
            return b''

        buffer = bytearray(max_len)
        bytes_read = d.readBuffer.readLine(buffer, max_len)

        return bytes(buffer[:bytes_read])

    def writeData(self, data: bytes) -> int:
        """
        写入数据（保护方法） - 对应C++: qint64 KPtyDevice::writeData(const char *data, qint64 len) override

        Args:
            data: 要写入的数据

        Returns:
            写入的字节数
        """
        if isinstance(data, str):
            data = data.encode('utf-8')

        d = self._d_func()  # 对应C++的Q_D(KPtyDevice)
        data_len = len(data)

        # C++版本中有断言检查长度不超过KMAXINT - 对应C++: Q_ASSERT(len <= KMAXINT)
        assert data_len <= KMAXINT, f"Data length {data_len} exceeds KMAXINT {KMAXINT}"

        d.writeBuffer.write(data, data_len)

        if d.writeNotifier:
            d.writeNotifier.setEnabled(True)

        return data_len

    # 错误处理方法
    def setErrorString(self, error_string: str):
        """设置错误字符串 - 对应C++的错误处理"""
        if hasattr(super(), 'setErrorString'):
            super().setErrorString(error_string)
        else:
            self._error_string = error_string
            logger.error(f"KPtyDevice错误: {error_string}")

    def errorString(self) -> str:
        """获取错误字符串 - 对应C++的错误处理"""
        if hasattr(super(), 'errorString'):
            return super().errorString()
        else:
            return getattr(self, '_error_string', '')

    # C++兼容性方法 - 对应C++的方法名
    def masterFd(self) -> int:
        """获取master文件描述符 - 对应C++方法名"""
        d = self.d_ptr  # 使用KPty的d_ptr，避免递归
        return d.masterFd

    def slaveFd(self) -> int:
        """获取slave文件描述符 - 对应C++方法名"""
        d = self.d_ptr  # 使用KPty的d_ptr，避免递归
        return d.slaveFd

    def slaveName(self) -> str:
        """获取slave设备名称 - 对应C++方法名"""
        d = self.d_ptr  # 使用KPty的d_ptr，避免递归
        return d.ttyName.decode() if isinstance(d.ttyName, bytes) else d.ttyName

    def ttyName(self) -> str:
        """获取TTY设备名称 - 对应C++兼容性方法，与slaveName相同"""
        return self.slaveName()

    # 槽函数 - 对应C++的Q_PRIVATE_SLOT
    @Slot()
    def _k_canRead(self):
        """读取数据槽函数 - 对应C++的Q_PRIVATE_SLOT"""
        d = self._d_func()
        return d._k_canRead()

    @Slot()
    def _k_canWrite(self):
        """写入数据槽函数 - 对应C++的Q_PRIVATE_SLOT"""
        d = self._d_func()
        return d._k_canWrite()


# 便利函数
def create_pty_device(parent: Optional[QObject] = None) -> Optional[KPtyDevice]:
    """
    创建并打开PTY设备的便利函数

    Args:
        parent: 父对象

    Returns:
        成功时返回KPtyDevice对象，失败时返回None
    """
    device = KPtyDevice(parent)
    if device.open():
        return device
    else:
        return None


# 导出类和函数
__all__ = [
    'KPtyDevice',
    'KPtyDevicePrivate',
    'KRingBuffer',
    'create_pty_device'
]