"""
KProcess模块 - 从QTerminal/KDE转换而来

原始文件：
- kprocess.h  
- kprocess.cpp

版权信息：
Copyright (C) 2007 Oswald Buddenhagen <ossi@kde.org>

转换为Python PySide6版本，完全模拟C++行为
"""

import os
import platform
from enum import IntEnum
from typing import List, Optional, Union

from PySide6.QtCore import QObject, QProcess, QIODevice, QProcessEnvironment

# 常量定义 - 与C++保持一致
DUMMYENV = "_KPROCESS_DUMMY_="

class OutputChannelMode(IntEnum):
    """
    输出通道模式枚举。
    对应C++: enum OutputChannelMode
    """
    SeparateChannels = 0  # QProcess::SeparateChannels
    """标准输出和标准错误作为独立通道处理"""
    
    MergedChannels = 1  # QProcess::MergedChannels
    """标准输出和标准错误合并为一个通道"""
    
    ForwardedChannels = 2  # QProcess::ForwardedChannels
    """标准输出和标准错误都转发到父进程"""
    
    OnlyStdoutChannel = 3  # QProcess::ForwardedErrorChannel
    """只处理标准输出，标准错误转发"""
    
    OnlyStderrChannel = 4  # QProcess::ForwardedOutputChannel
    """只处理标准错误，标准输出转发"""


class KProcessPrivate:
    """
    KProcess私有数据类。
    对应C++: class KProcessPrivate
    """
    
    def __init__(self, q: 'KProcess'):
        self.openMode: QIODevice.OpenModeFlag = QIODevice.OpenModeFlag.ReadWrite
        self.prog: str = ""
        self.args: List[str] = []
        self.q_ptr: 'KProcess' = q


class KProcess(QProcess):
    """
    子进程调用、监控和控制类。
    
    这个类通过一些有用的功能扩展了QProcess，用更合理的值覆盖了一些默认值，
    并将部分API包装为更易访问的形式。
    这是在KDE中生成子进程的首选方式；不要直接使用QProcess。
    
    对应C++: class KProcess : public QProcess
    """
    
    def __init__(self, parent: Optional[QObject] = None):
        """
        构造函数。
        
        Args:
            parent: 父对象
            
        对应C++: KProcess::KProcess(QObject *parent)
        """
        super().__init__(parent)
        self._d: KProcessPrivate = KProcessPrivate(self)
        self.setOutputChannelMode(OutputChannelMode.ForwardedChannels)
    
    def _initWithPrivateData(self, d: KProcessPrivate, parent: Optional[QObject] = None):
        """
        使用私有数据的受保护构造函数。
        
        Args:
            d: 私有数据对象
            parent: 父对象
            
        对应C++: KProcess::KProcess(KProcessPrivate *d, QObject *parent)
        """
        super().__init__(parent)
        self._d = d
        self._d.q_ptr = self
        self.setOutputChannelMode(OutputChannelMode.ForwardedChannels)
    
    @classmethod
    def createWithPrivateData(cls, d: KProcessPrivate, parent: Optional[QObject] = None) -> 'KProcess':
        """
        创建带私有数据的KProcess实例的类方法。
        
        Args:
            d: 私有数据对象
            parent: 父对象
            
        Returns:
            KProcess: 新的KProcess实例
            
        对应C++: KProcess::KProcess(KProcessPrivate *d, QObject *parent)
        """
        instance = cls.__new__(cls)
        instance._initWithPrivateData(d, parent)
        return instance
    
    def __lshift__(self, arg: Union[str, List[str]]) -> 'KProcess':
        """
        向命令行参数列表追加元素。
        
        如果还没有设置可执行文件，则会设置可执行文件。
        
        例如，执行"ls -l /usr/local/bin"可以这样实现：
        ```python
        p = KProcess()
        p << "ls" << "-l" << "/usr/local/bin"
        ```
        
        Args:
            arg: 要添加的参数或参数列表
            
        Returns:
            KProcess: 返回自身的引用
            
        对应C++: KProcess &operator<<(const QString& arg)
                KProcess &operator<<(const QStringList& args)
        """
        if isinstance(arg, str):
            if not self._d.prog:
                self._d.prog = arg
            else:
                self._d.args.append(arg)
        elif isinstance(arg, list):
            if not self._d.prog:
                self.setProgram(arg)
            else:
                self._d.args.extend(arg)
        return self
    
    # ============= C++风格的公开方法 =============
    
    def setOutputChannelMode(self, mode: OutputChannelMode):
        """
        设置如何处理子进程的输出通道。
        
        默认值是ForwardedChannels，这与QProcess不同。
        不要请求超过你实际处理的内容，因为输出会丢失。
        
        此函数必须在启动进程之前调用。
        
        Args:
            mode: 输出通道处理模式
            
        对应C++: void setOutputChannelMode(OutputChannelMode mode)
        """
        qprocess_mode = QProcess.ProcessChannelMode(mode.value)
        super().setProcessChannelMode(qprocess_mode)
    
    def outputChannelMode(self) -> OutputChannelMode:
        """
        查询子进程的输出通道如何处理。
        
        Returns:
            OutputChannelMode: 输出通道处理模式
            
        对应C++: OutputChannelMode outputChannelMode() const
        """
        qprocess_mode = super().processChannelMode()
        return OutputChannelMode(qprocess_mode.value)
    
    def setNextOpenMode(self, mode: QIODevice.OpenModeFlag):
        """
        设置进程将要打开的QIODevice打开模式。
        
        此函数必须在启动进程之前调用。
        
        Args:
            mode: 打开模式。注意此模式会根据通道模式和重定向自动"缩减"。
                 默认是QIODevice.ReadWrite。
                 
        对应C++: void setNextOpenMode(QIODevice::OpenMode mode)
        """
        self._d.openMode = mode
    
    def setEnv(self, name: str, value: str, overwrite: bool = True):
        """
        向进程环境添加变量。
        
        此函数必须在启动进程之前调用。
        
        Args:
            name: 环境变量名
            value: 环境变量的新值
            overwrite: 如果为False且环境变量已设置，将保留旧值
            
        对应C++: void setEnv(const QString &name, const QString &value, bool overwrite)
        """
        env = self.processEnvironment()
        if env.isEmpty():
            env = QProcessEnvironment.systemEnvironment()
            # 移除虚拟环境变量
            env.remove(DUMMYENV.rstrip('='))
        
        if env.contains(name) and not overwrite:
            return
        
        env.insert(name, value)
        self.setProcessEnvironment(env)
    
    def unsetEnv(self, name: str):
        """
        从进程环境中移除变量。
        
        此函数必须在启动进程之前调用。
        
        Args:
            name: 环境变量名
            
        对应C++: void unsetEnv(const QString &name)
        """
        env = self.processEnvironment()
        if env.isEmpty():
            env = QProcessEnvironment.systemEnvironment()
            env.remove(DUMMYENV.rstrip('='))
        
        if env.contains(name):
            env.remove(name)
            # 如果环境为空，设置虚拟变量
            if env.isEmpty():
                env.insert(DUMMYENV.rstrip('='), "")
            self.setProcessEnvironment(env)
    
    def clearEnvironment(self):
        """
        清空进程环境。
        
        注意在*NIX上会自动添加LD_LIBRARY_PATH/DYLD_LIBRARY_PATH。
        
        此函数必须在启动进程之前调用。
        
        对应C++: void clearEnvironment()
        """
        env = QProcessEnvironment()
        env.insert(DUMMYENV.rstrip('='), "")
        self.setProcessEnvironment(env)
    
    def setProgram(self, exe_or_argv: Union[str, List[str]], args: Optional[List[str]] = None):
        """
        设置程序和命令行参数。
        
        此函数必须在启动进程之前调用。
        
        Args:
            exe_or_argv: 要执行的程序或程序及参数列表
            args: 程序的命令行参数，每个列表元素一个参数
            
        对应C++: void setProgram(const QString &exe, const QStringList &args)
                void setProgram(const QStringList &argv)
        """
        if isinstance(exe_or_argv, str):
            # setProgram(exe, args)
            self._d.prog = exe_or_argv
            self._d.args = args or []
        elif isinstance(exe_or_argv, list):
            # setProgram(argv)
            assert exe_or_argv, "参数列表不能为空"
            argv = exe_or_argv.copy()
            self._d.prog = argv.pop(0)
            self._d.args = argv
        
        # Windows平台的处理
        if platform.system() == "Windows":
            try:
                self.setNativeArguments("")
            except AttributeError:
                # PySide6可能没有setNativeArguments方法
                pass
    
    def clearProgram(self):
        """
        清除程序和命令行参数列表。
        
        对应C++: void clearProgram()
        """
        self._d.prog = ""
        self._d.args.clear()
        
        # Windows平台的处理
        if platform.system() == "Windows":
            try:
                self.setNativeArguments("")
            except AttributeError:
                # PySide6可能没有setNativeArguments方法
                pass
    
    def setShellCommand(self, cmd: str):
        """
        设置通过shell执行的命令（*NIX上是POSIX sh，Windows上是cmd.exe）。
        
        除了用户提供的命令外，将此用于其他任何用途通常都是个坏主意，
        因为命令的语法取决于平台。
        包括管道等重定向最好由QProcess提供的相应函数处理。
        
        如果KProcess确定命令实际上不需要shell，它会透明地执行而不使用shell，
        以提高性能。
        
        此函数必须在启动进程之前调用。
        
        Args:
            cmd: 要通过shell执行的命令。
                调用者必须确保在作为参数传递时，所有文件名等都已正确引用。
                不这样做通常会导致严重的安全漏洞。
                
        对应C++: void setShellCommand(const QString &cmd)
        """
        self._d.args.clear()
        
        if platform.system() == "Windows":
            # Windows实现 - 更精确地模拟C++逻辑
            try:
                import ctypes
                
                # 检查ctypes是否有windll属性（只在Windows上存在）
                if hasattr(ctypes, 'windll'):
                    # 尝试获取系统目录 - 模拟C++的GetSystemDirectoryW
                    buffer_size = 261  # MAX_PATH + 1
                    buffer = ctypes.create_unicode_buffer(buffer_size)
                    actual_length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, buffer_size)
                    
                    if actual_length > 0:
                        system_dir = buffer.value
                        self._d.prog = os.path.join(system_dir, "cmd.exe")
                    else:
                        # 后备方案
                        system_dir = os.environ.get('SYSTEMROOT', r'C:\Windows')
                        self._d.prog = os.path.join(system_dir, "System32", "cmd.exe")
                else:
                    # 在非Windows平台的测试环境中使用后备方案
                    system_dir = os.environ.get('SYSTEMROOT', r'C:\Windows')
                    self._d.prog = os.path.join(system_dir, "System32", "cmd.exe")
            except (ImportError, OSError, AttributeError):
                # 如果ctypes不可用或出现其他错误，使用后备方案
                system_dir = os.environ.get('SYSTEMROOT', r'C:\Windows')
                self._d.prog = os.path.join(system_dir, "System32", "cmd.exe")
            
            # 设置原生参数 - 完全模拟C++逻辑
            try:
                self.setNativeArguments(f'/V:OFF /S /C "{cmd}"')
            except AttributeError:
                # PySide6可能没有setNativeArguments方法，或方法名不同
                # 这在非Windows平台的测试中是可以接受的
                pass
        else:
            # Unix实现 - 完全模拟C++的复杂逻辑
            shell_path = "/bin/sh"
            
            # 检查是否是符号链接 - 模拟C++的QFile::symLinkTarget
            if os.path.islink(shell_path):
                try:
                    target = os.readlink(shell_path)
                    if target and os.path.isabs(target):
                        shell_path = target
                    elif target:
                        shell_path = os.path.join(os.path.dirname(shell_path), target)
                except OSError:
                    pass
            
            # 对于非主流Linux系统，尝试找到更好的POSIX shell
            # 模拟C++中的条件编译逻辑
            non_mainstream_unix = not (
                platform.system() == "Linux" or 
                platform.system().endswith("BSD") or 
                platform.system() == "GNU"
            )
            
            if non_mainstream_unix:
                for shell_name in ['ksh', 'ash', 'bash', 'zsh']:
                    shell_full_path = self._findExecutable(shell_name)
                    if shell_full_path:
                        shell_path = shell_full_path
                        break
            
            self._d.prog = shell_path
            self._d.args = ["-c", cmd]
    
    def _findExecutable(self, name: str) -> Optional[str]:
        """
        查找可执行文件 - 模拟C++的KStandardDirs::findExe
        
        Args:
            name: 可执行文件名
            
        Returns:
            可执行文件的完整路径，如果未找到则返回None
        """
        import shutil
        return shutil.which(name)
    
    def program(self) -> List[str]:
        """
        获取当前设置的程序和参数。
        
        Returns:
            List[str]: 列表，第一个元素是程序，其余的是程序的命令行参数。
            
        对应C++: QStringList program() const
        """
        # 完全模拟C++行为：总是将prog添加到开头，即使是空字符串
        result = self._d.args.copy()
        result.insert(0, self._d.prog)
        return result
    
    def start(self):
        """
        启动进程。
        
        对应C++: void start()
        """
        super().start(self._d.prog, self._d.args, self._d.openMode)
    
    def execute(self, msecs: int = -1) -> int:
        """
        启动进程，等待其完成，并返回退出代码。
        
        此方法大致等同于以下序列：
        ```python
        start()
        waitForFinished(msecs)
        return exitCode()
        ```
        
        与其他execute()变体不同，此方法不是静态的，
        因此进程可以正确参数化并与之通信。
        
        Args:
            msecs: 在杀死进程之前等待进程退出的时间
            
        Returns:
            int: -2如果进程无法启动，-1如果进程崩溃，否则返回退出代码
            
        对应C++: int execute(int msecs)
        """
        self.start()
        if not self.waitForFinished(msecs):
            self.kill()
            self.waitForFinished(-1)
            return -2
        
        if self.exitStatus() == QProcess.ExitStatus.NormalExit:
            return self.exitCode()
        else:
            return -1
    
    @staticmethod
    def execute(exe: str, args: Optional[List[str]] = None, msecs: int = -1) -> int:
        """
        静态方法：执行程序并返回退出代码。
        
        Args:
            exe: 要执行的程序
            args: 程序的命令行参数，每个列表元素一个参数
            msecs: 在杀死进程之前等待进程退出的时间
            
        Returns:
            int: -2如果进程无法启动，-1如果进程崩溃，否则返回退出代码
            
        对应C++: static int execute(const QString &exe, const QStringList &args, int msecs)
        """
        process = KProcess()
        process.setProgram(exe, args or [])
        return process.execute(msecs)
    
    @staticmethod
    def executeArgv(argv: List[str], msecs: int = -1) -> int:
        """
        静态方法：执行程序并返回退出代码。
        
        Args:
            argv: 要执行的程序和命令行参数，每个列表元素一个参数
            msecs: 在杀死进程之前等待进程退出的时间
            
        Returns:
            int: -2如果进程无法启动，-1如果进程崩溃，否则返回退出代码
            
        对应C++: static int execute(const QStringList &argv, int msecs)
        """
        process = KProcess()
        process.setProgram(argv)
        return process.execute(msecs)
    
    def startDetached(self) -> int:
        """
        启动进程并从中分离。
        
        与其他startDetached()变体不同，此方法不是静态的，
        因此进程可以正确参数化。
        注意：目前仅支持setProgram()/setShellCommand()和setWorkingDirectory()参数化。
        
        调用此函数后，KProcess对象可以立即重新使用。
        
        Returns:
            int: 启动进程的PID，错误时返回0
            
        对应C++: int startDetached()
        """
        try:
            # 使用QProcess的startDetached，并尝试获取PID
            success, pid = QProcess.startDetached(
                self._d.prog, 
                self._d.args, 
                self.workingDirectory()
            )
            return int(pid) if success and pid > 0 else 0
        except Exception:
            return 0
    
    @staticmethod
    def startDetached(exe: str, args: Optional[List[str]] = None) -> int:
        """
        静态方法：启动进程并分离。
        
        Args:
            exe: 要启动的程序
            args: 程序的命令行参数，每个列表元素一个参数
            
        Returns:
            int: 启动进程的PID，错误时返回0
            
        对应C++: static int startDetached(const QString &exe, const QStringList &args)
        """
        try:
            success, pid = QProcess.startDetached(exe, args or [], "")
            return int(pid) if success and pid > 0 else 0
        except Exception:
            return 0
    
    @staticmethod 
    def startDetachedArgv(argv: List[str]) -> int:
        """
        静态方法：启动进程并分离。
        
        Args:
            argv: 要启动的程序和命令行参数，每个列表元素一个参数
            
        Returns:
            int: 启动进程的PID，错误时返回0
            
        对应C++: static int startDetached(const QStringList &argv)
        """
        if not argv:
            return 0
        
        prog = argv[0]
        args = argv[1:] if len(argv) > 1 else []
        return KProcess.startDetached(prog, args)
    
    # ============= 隐藏QProcess的方法（私有接口） =============
    
    def setProcessChannelMode(self, *args, **kwargs):
        """
        隐藏的QProcess方法。请使用setOutputChannelMode()代替。
        
        对应C++: private: using QProcess::setProcessChannelMode;
        
        Raises:
            AttributeError: 提示使用正确的方法
        """
        raise AttributeError(
            "setProcessChannelMode被隐藏，请使用setOutputChannelMode()方法代替"
        )
    
    def processChannelMode(self, *args, **kwargs):
        """
        隐藏的QProcess方法。请使用outputChannelMode()代替。
        
        对应C++: private: using QProcess::processChannelMode;
        
        Raises:
            AttributeError: 提示使用正确的方法
        """
        raise AttributeError(
            "processChannelMode被隐藏，请使用outputChannelMode()方法代替"
        )
    
    # ============= 兼容性方法（同时支持两种命名） =============
    
    # Python风格的兼容方法（保持向后兼容）
    def set_output_channel_mode(self, mode: OutputChannelMode):
        """兼容性方法：Python风格名称"""
        return self.setOutputChannelMode(mode)
    
    def output_channel_mode(self) -> OutputChannelMode:
        """兼容性方法：Python风格名称"""
        return self.outputChannelMode()
    
    def set_next_open_mode(self, mode: QIODevice.OpenModeFlag):
        """兼容性方法：Python风格名称"""
        return self.setNextOpenMode(mode)
    
    def set_env(self, name: str, value: str, overwrite: bool = True):
        """兼容性方法：Python风格名称"""
        return self.setEnv(name, value, overwrite)
    
    def unset_env(self, name: str):
        """兼容性方法：Python风格名称"""
        return self.unsetEnv(name)
    
    def clear_environment(self):
        """兼容性方法：Python风格名称"""
        return self.clearEnvironment()
    
    def set_program(self, exe_or_argv: Union[str, List[str]], args: Optional[List[str]] = None):
        """兼容性方法：Python风格名称"""
        return self.setProgram(exe_or_argv, args)
    
    def clear_program(self):
        """兼容性方法：Python风格名称"""
        return self.clearProgram()
    
    def set_shell_command(self, cmd: str):
        """兼容性方法：Python风格名称"""
        return self.setShellCommand(cmd)
    
    def start_detached(self) -> int:
        """兼容性方法：Python风格名称"""
        return self.startDetached()
    
    @staticmethod
    def execute_static(exe: str, args: Optional[List[str]] = None, msecs: int = -1) -> int:
        """兼容性方法：Python风格名称"""
        return execute(exe, args, msecs)
    
    @staticmethod
    def execute_argv(argv: List[str], msecs: int = -1) -> int:
        """兼容性方法：Python风格名称"""
        return executeArgv(argv, msecs)
    
    @staticmethod
    def start_detached_static(exe: str, args: Optional[List[str]] = None) -> int:
        """兼容性方法：Python风格名称"""
        return KProcess.startDetached(exe, args)
    
    @staticmethod
    def start_detached_argv(argv: List[str]) -> int:
        """兼容性方法：Python风格名称"""
        return KProcess.startDetachedArgv(argv)


# ============= 全局便利函数 =============

def execute(exe: str, args: Optional[List[str]] = None, msecs: int = -1) -> int:
    """
    便利函数：执行程序并返回退出代码
    
    对应C++中的静态方法使用
    """
    return KProcess.execute(exe, args, msecs)


def executeArgv(argv: List[str], msecs: int = -1) -> int:
    """
    便利函数：从参数列表执行程序并返回退出代码
    
    对应C++中的静态方法使用
    """
    return KProcess.executeArgv(argv, msecs)


def startDetached(exe: str, args: Optional[List[str]] = None) -> int:
    """
    便利函数：启动分离进程
    
    对应C++中的静态方法使用
    """
    return KProcess.startDetached(exe, args)


def startDetachedArgv(argv: List[str]) -> int:
    """
    便利函数：从参数列表启动分离进程
    
    对应C++中的静态方法使用
    """
    return KProcess.startDetachedArgv(argv)


# ============= 兼容性别名（保持向后兼容） =============

# Python风格的便利函数
def execute_static(exe: str, args: Optional[List[str]] = None, msecs: int = -1) -> int:
    """便利函数：执行程序并返回退出代码（Python风格命名）"""
    return execute(exe, args, msecs)


def execute_argv(argv: List[str], msecs: int = -1) -> int:
    """便利函数：从参数列表执行程序并返回退出代码（Python风格命名）"""
    return executeArgv(argv, msecs)


def start_detached(exe: str, args: Optional[List[str]] = None) -> int:
    """便利函数：启动分离进程（Python风格命名）"""
    return startDetached(exe, args)


def start_detached_argv(argv: List[str]) -> int:
    """便利函数：从参数列表启动分离进程（Python风格命名）"""
    return startDetachedArgv(argv) 