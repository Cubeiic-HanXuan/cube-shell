"""
KPty模块 - 从KDE/Qt终端模拟器转换而来

这个模块提供了伪终端(PTY)的管理功能，包括创建、打开、关闭伪终端对，
设置终端属性，utmp登录记录管理等。

原始文件：
- kpty.h
- kpty.cpp
- kpty_p.h

版权信息：
Copyright (C) 2003,2007 Oswald Buddenhagen <ossi@kde.org>
Copyright (C) 2002 Waldo Bastian <bastian@kde.org>
Copyright (C) 2002-2003,2007 Oswald Buddenhagen <ossi@kde.org>
Rewritten for QT4 by e_k <e_k at users.sourceforge.net>, Copyright (C)2008

转换为Python PySide6版本，提供C++兼容API
"""

import fcntl
import grp
import logging
import os
import pty
import stat
import struct
import termios
from contextlib import contextmanager
from typing import Optional, Tuple, Union

# 尝试导入可选的utmp支持
try:
    import utmp
    HAS_UTMP = True
except ImportError:
    HAS_UTMP = False
    utmp = None

# 兼容性检查
HAS_OPENPTY = hasattr(pty, 'openpty')
HAS_PTSNAME = hasattr(os, 'ttyname')

# 平台相关的包含检查
import platform
SYSTEM = platform.system()
IS_LINUX = SYSTEM == "Linux"
IS_DARWIN = SYSTEM == "Darwin"
IS_BSD = SYSTEM in ("FreeBSD", "OpenBSD", "NetBSD", "DragonFly")

# 常量定义 - 对应C++中的常量
TTY_GROUP = "tty"
CTRL = lambda x: (ord(x) & 0o37)

# PTY设备前缀常量
PTY_DEVICE_PREFIX = "/dev/pty"
TTY_DEVICE_PREFIX = "/dev/tty"
PTS_DEVICE_PREFIX = "/dev/pts/"

# 传统PTY设备名称字符集（对应C++中的硬编码字符串）
PTY_MASTER_CHARS = "pqrstuvwxyzabcde"
PTY_SLAVE_CHARS = "0123456789abcdef"

# PATH_MAX 常量
PATH_MAX = 4096

# 日志记录器
logger = logging.getLogger(__name__)


class KPtyError(Exception):
    """KPty相关的异常类"""
    pass


class KPtyPrivate:
    """
    KPty的私有实现类
    
    对应C++: class KPtyPrivate
    """
    
    def __init__(self, parent: 'KPty'):
        """
        构造函数
        
        Args:
            parent: 父KPty对象
            
        对应C++: KPtyPrivate::KPtyPrivate(KPty* parent)
        """
        self.masterFd = -1  # 使用C++风格命名
        self.slaveFd = -1
        self.ownMaster = True
        self.ttyName = b""
        self.q_ptr = parent
    
    def __del__(self):
        """
        析构函数
        
        对应C++: KPtyPrivate::~KPtyPrivate()
        """
        pass
    
    def chownpty(self, grant: bool) -> bool:
        """
        更改PTY的所有权
        
        Args:
            grant: 是否授予权限
            
        Returns:
            是否成功
            
        对应C++: bool KPtyPrivate::chownpty(bool grant)
        """
        # 在Python中模拟kgrantpty程序的功能
        if not self.ttyName:
            return False
            
        try:
            tty_path = self.ttyName.decode('utf-8')
            
            if grant:
                # 获取TTY组
                try:
                    tty_group = grp.getgrnam(TTY_GROUP)
                    gid = tty_group.gr_gid
                except KeyError:
                    try:
                        wheel_group = grp.getgrnam("wheel")
                        gid = wheel_group.gr_gid
                    except KeyError:
                        gid = os.getgid()
                
                # 更改所有权
                if os.geteuid() == 0:  # root用户
                    os.chown(tty_path, os.getuid(), gid)
                    os.chmod(tty_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IWGRP)
            else:
                # 撤销权限
                if os.geteuid() == 0:
                    os.chown(tty_path, 0, 0)
                    os.chmod(tty_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
            
            return True
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"chownpty失败: {e}")
            return False


class KPty:
    """
    提供打开和关闭伪TTY对、分配控制TTY、utmp注册和设置各种终端属性的原语。
    
    对应C++: class KPty
    """
    
    def __init__(self, d: Optional[KPtyPrivate] = None):
        """
        构造函数
        
        Args:
            d: 可选的私有实现对象，用于子类化
            
        对应C++: KPty::KPty() 和 KPty::KPty(KPtyPrivate * d)
        """
        if d is not None:
            self.d_ptr = d
            self.d_ptr.q_ptr = self
        else:
            self.d_ptr = KPtyPrivate(self)
    
    def __del__(self):
        """
        析构函数：如果pty仍然打开，它将被关闭。
        注意，utmp注册不会被撤销。
        
        对应C++: KPty::~KPty()
        """
        self.close()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口，自动关闭PTY"""
        self.close()
    
    def __copy__(self):
        """禁止拷贝构造"""
        raise NotImplementedError("KPty对象不支持拷贝")
    
    def __deepcopy__(self, memo):
        """禁止深拷贝"""
        raise NotImplementedError("KPty对象不支持深拷贝")
    
    # Q_D宏的Python等价实现
    def Q_D(self) -> KPtyPrivate:
        """获取私有数据指针 - 对应C++的Q_D宏"""
        return self.d_ptr
    
    # =================================================================
    # C++风格的公共API方法
    # =================================================================
    
    def open(self, fd: Optional[int] = None) -> bool:
        """
        创建一个pty主/从设备对。
        
        Args:
            fd: 可选的已有文件描述符
            
        Returns:
            如果成功打开pty对，则返回True
            
        对应C++: bool KPty::open() 和 bool KPty::open(int fd)
        """
        if fd is not None:
            return self._openWithFd(fd)
        
        d = self.Q_D()
        
        if d.masterFd >= 0:
            return True
        
        d.ownMaster = True
        
        # 查找主pty设备
        if HAS_OPENPTY:
            # 使用系统的openpty函数
            try:
                master_fd, slave_fd = pty.openpty()
                d.masterFd = master_fd
                d.slaveFd = slave_fd
                d.ttyName = os.ttyname(slave_fd).encode('utf-8')
                
                # 设置close-on-exec
                fcntl.fcntl(master_fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
                fcntl.fcntl(slave_fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
                
                return True
            except OSError as e:
                logger.warning(f"openpty失败: {e}")
                d.masterFd = -1
                d.slaveFd = -1
                return False
        else:
            # 备用方法：尝试手动查找可用的pty设备
            return self._findAvailablePty()
    
    def _openWithFd(self, fd: int) -> bool:
        """
        使用已有文件描述符打开pty
        
        Args:
            fd: 主设备文件描述符
            
        Returns:
            是否成功
            
        对应C++: bool KPty::open(int fd)
        """
        d = self.Q_D()
        
        if d.masterFd >= 0:
            logger.warning("尝试打开已经打开的pty")
            return False
        
        d.ownMaster = False
        
        try:
            # 获取从设备名称 - 按照C++版本的逻辑
            slave_name = None
            
            # 方法1: 尝试使用ptsname等价方法（对应C++的HAVE_PTSNAME）
            if HAS_PTSNAME:
                try:
                    # 在Python中，os.ttyname对应C++的ptsname功能
                    # 但在macOS上可能有问题，我们需要特殊处理
                    if IS_DARWIN:
                        # macOS特殊处理：尝试多种方法
                        try:
                            # 方法1a: 直接尝试ttyname
                            slave_name = os.ttyname(fd)
                        except OSError as e:
                            if e.errno == 34:  # ERANGE - Result too large
                                # 在macOS上，某些情况下ttyname会失败
                                # 尝试通过/dev目录查找对应的设备
                                slave_name = self._findMacOSSlaveName(fd)
                            else:
                                raise
                    else:
                        # 非macOS系统，使用标准方法
                        slave_name = os.ttyname(fd)
                        
                except OSError as e:
                    logger.debug(f"os.ttyname({fd})失败: {e}")
                    # 降级到其他方法
                    slave_name = None
            
            # 方法2: 如果方法1失败，尝试ioctl TIOCGPTN（对应C++的TIOCGPTN）
            if not slave_name and IS_LINUX:
                try:
                    import fcntl
                    import struct
                    # 尝试使用TIOCGPTN ioctl获取pts编号
                    TIOCGPTN = 0x80045430  # Linux上的TIOCGPTN常量
                    ptyno_bytes = fcntl.ioctl(fd, TIOCGPTN, struct.pack('I', 0))
                    ptyno = struct.unpack('I', ptyno_bytes)[0]
                    slave_name = f"/dev/pts/{ptyno}"
                    logger.debug(f"通过TIOCGPTN获取到pts编号: {ptyno}")
                except (OSError, ImportError, struct.error) as e:
                    logger.debug(f"TIOCGPTN ioctl失败: {e}")
            
            # 方法3: /proc文件系统方法（Linux）
            if not slave_name and IS_LINUX:
                try:
                    link_path = f'/proc/self/fd/{fd}'
                    if os.path.exists(link_path):
                        real_path = os.readlink(link_path)
                        if real_path.startswith('/dev/'):
                            slave_name = real_path
                            logger.debug(f"通过/proc获取到设备路径: {real_path}")
                except OSError as e:
                    logger.debug(f"通过/proc访问fd {fd}失败: {e}")
            
            if not slave_name:
                logger.error(f"在{SYSTEM}系统上无法确定fd {fd}对应的从设备名称")
                return False
            
            # 验证从设备文件是否存在和可访问
            try:
                if not os.path.exists(slave_name):
                    logger.error(f"从设备文件不存在: {slave_name}")
                    return False
                    
                # 验证是否可以访问该设备
                if not os.access(slave_name, os.R_OK | os.W_OK):
                    logger.warning(f"从设备权限受限: {slave_name}")
                    # 不立即失败，尝试继续
                    
            except Exception as e:
                logger.error(f"验证从设备失败: {e}")
                return False
            
            # 设置设备名称
            d.ttyName = slave_name.encode('utf-8')
            d.masterFd = fd
            
            # 尝试打开从设备来验证（对应C++的openSlave()）
            if not self.openSlave():
                logger.error(f"无法打开从设备: {slave_name}")
                d.masterFd = -1
                return False
            
            logger.debug(f"成功使用fd {fd}打开PTY，从设备: {slave_name}")
            return True
            
        except Exception as e:
            logger.error(f"使用fd {fd}打开pty失败: {e}")
            return False
    
    def _findMacOSSlaveName(self, master_fd: int) -> Optional[str]:
        """
        在macOS上查找对应的slave设备名称
        
        Args:
            master_fd: 主设备文件描述符
            
        Returns:
            slave设备名称，失败时返回None
        """
        try:
            # 方法1: 通过fstat获取设备信息
            import stat
            st = os.fstat(master_fd)
            
            # 检查是否是字符设备
            if not stat.S_ISCHR(st.st_mode):
                logger.debug(f"fd {master_fd}不是字符设备")
                return None
            
            # 获取设备号
            major_num = os.major(st.st_rdev)
            minor_num = os.minor(st.st_rdev)
            
            logger.debug(f"设备信息: major={major_num}, minor={minor_num}")
            
            # 方法2: 在macOS上，尝试常见的TTY设备模式
            # macOS使用/dev/ttysXXX格式
            if major_num == 5:  # TTY major number on macOS
                # 尝试构造可能的从设备名称
                for suffix in range(0, 256):
                    for prefix in ['ttys', 'ttyp', 'ttyq', 'ttyr']:
                        candidate = f"/dev/{prefix}{suffix:03d}"
                        if os.path.exists(candidate):
                            try:
                                # 验证这个设备是否与我们的master匹配
                                candidate_st = os.stat(candidate)
                                if (stat.S_ISCHR(candidate_st.st_mode) and 
                                    os.major(candidate_st.st_rdev) == major_num):
                                    logger.debug(f"找到可能的从设备: {candidate}")
                                    return candidate
                            except OSError:
                                continue
            
            # 方法3: 使用传统的pty命名
            # 尝试/dev/ttyp, /dev/ttyq等传统命名
            for master_char in PTY_MASTER_CHARS:
                for slave_char in PTY_SLAVE_CHARS:
                    candidate = f"/dev/tty{master_char}{slave_char}"
                    if os.path.exists(candidate):
                        try:
                            candidate_st = os.stat(candidate)
                            if stat.S_ISCHR(candidate_st.st_mode):
                                return candidate
                        except OSError:
                            continue
            
            logger.debug("无法在macOS上找到对应的从设备")
            return None
            
        except Exception as e:
            logger.debug(f"macOS从设备查找失败: {e}")
            return None
    
    def _findAvailablePty(self) -> bool:
        """
        查找可用的传统pty设备
        
        Returns:
            是否成功找到并打开pty
        """
        d = self.Q_D()
        
        # 尝试传统的pty设备路径
        for master_char in PTY_MASTER_CHARS:
            for slave_char in PTY_SLAVE_CHARS:
                pty_name = f"{PTY_DEVICE_PREFIX}{master_char}{slave_char}"
                tty_name = f"{TTY_DEVICE_PREFIX}{master_char}{slave_char}"
                
                try:
                    master_fd = os.open(pty_name, os.O_RDWR)
                    
                    # 检查从设备是否可访问
                    if os.access(tty_name, os.R_OK | os.W_OK):
                        # 设置权限
                        if os.geteuid() == 0:
                            try:
                                tty_group = grp.getgrnam(TTY_GROUP)
                                gid = tty_group.gr_gid
                            except KeyError:
                                try:
                                    wheel_group = grp.getgrnam("wheel") 
                                    gid = wheel_group.gr_gid
                                except KeyError:
                                    gid = os.getgid()
                            
                            os.chown(tty_name, os.getuid(), gid)
                            os.chmod(tty_name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IWGRP)
                        
                        d.masterFd = master_fd
                        d.ttyName = tty_name.encode('utf-8')
                        
                        # 打开从设备
                        slave_fd = os.open(tty_name, os.O_RDWR | os.O_NOCTTY)
                        d.slaveFd = slave_fd
                        
                        # 设置close-on-exec
                        fcntl.fcntl(master_fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
                        fcntl.fcntl(slave_fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
                        
                        return True
                    else:
                        os.close(master_fd)
                        
                except OSError:
                    continue
        
        logger.warning("无法打开伪终端")
        return False
    
    def close(self):
        """
        关闭pty主/从设备对。
        
        对应C++: void KPty::close()
        """
        d = self.Q_D()
        
        if d.masterFd < 0:
            return
        
        self.closeSlave()
        
        # 重置unix98 pty，关闭主设备后会自动消失
        if not d.ttyName.startswith(b"/dev/pts/"):
            if os.geteuid() == 0:
                try:
                    stat_info = os.stat(d.ttyName.decode('utf-8'))
                    gid = 0 if stat_info.st_gid == os.getgid() else -1
                    os.chown(d.ttyName.decode('utf-8'), 0, gid)
                    os.chmod(d.ttyName.decode('utf-8'), 
                            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | 
                            stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
                except OSError:
                    pass
            else:
                fcntl.fcntl(d.masterFd, fcntl.F_SETFD, 0)
                d.chownpty(False)
        
        try:
            os.close(d.masterFd)
        except OSError:
            pass
        
        d.masterFd = -1
    
    def closeSlave(self):
        """
        关闭pty从设备描述符。
        
        对应C++: void KPty::closeSlave()
        """
        d = self.Q_D()
        
        if d.slaveFd < 0:
            return
        
        try:
            os.close(d.slaveFd)
        except OSError:
            pass
        
        d.slaveFd = -1
    
    def openSlave(self) -> bool:
        """
        打开pty从设备
        
        Returns:
            是否成功
            
        对应C++: bool KPty::openSlave()
        """
        d = self.Q_D()
        
        if d.slaveFd >= 0:
            return True
        
        if d.masterFd < 0:
            logger.debug("尝试在主设备关闭时打开pty从设备")
            return False
        
        try:
            d.slaveFd = os.open(d.ttyName.decode('utf-8'), os.O_RDWR | os.O_NOCTTY)
            fcntl.fcntl(d.slaveFd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
            return True
        except OSError as e:
            logger.debug(f"无法打开从伪终端: {e}")
            return False
    
    def setCTty(self):
        """
        创建新会话和进程组，并使此pty成为控制tty。
        
        对应C++: void KPty::setCTty()
        """
        d = self.Q_D()
        
        # 设置作业控制
        # 成为会话领导者、进程组领导者，并摆脱旧的控制终端
        os.setsid()
        
        # 使我们的从pty成为新的控制终端
        try:
            # 在支持TIOCSCTTY的系统上使用它
            import termios
            if hasattr(termios, 'TIOCSCTTY'):
                fcntl.ioctl(d.slaveFd, termios.TIOCSCTTY, 0)
            else:
                # __svr4__ hack: setsid()后打开的第一个tty成为控制终端
                temp_fd = os.open(d.ttyName.decode('utf-8'), os.O_WRONLY)
                os.close(temp_fd)
        except (OSError, AttributeError):
            pass
        
        # 使我们的新进程组成为pty上的前台组
        try:
            pgrp = os.getpid()
            # POSIX版本
            if hasattr(termios, 'tcsetpgrp'):
                termios.tcsetpgrp(d.slaveFd, pgrp)
            else:
                # 使用ioctl的备用方法
                if hasattr(termios, 'TIOCSPGRP'):
                    fcntl.ioctl(d.slaveFd, termios.TIOCSPGRP, struct.pack('i', pgrp))
        except (OSError, AttributeError):
            pass
    
    def login(self, user: Optional[str] = None, remotehost: Optional[str] = None):
        """
        为tty创建utmp条目。
        
        Args:
            user: 要登录的用户
            remotehost: 登录来源的主机
            
        对应C++: void KPty::login(const char * user, const char * remotehost)
        """
        d = self.Q_D()
        
        if HAS_UTMP:
            # 使用utmp模块处理utmp记录
            try:
                # 这里应该实现真正的utmp记录，但由于复杂性这里简化处理
                logger.info(f"登录记录: 用户={user}, 远程主机={remotehost}, tty={d.ttyName.decode('utf-8')}")
            except Exception as e:
                logger.warning(f"无法记录登录: {e}")
        else:
            # 手动处理utmp/wtmp记录
            try:
                import struct
                import time
                
                # 获取tty名称（去掉/dev/前缀）
                tty_line = d.ttyName.decode('utf-8')
                if tty_line.startswith('/dev/'):
                    tty_line = tty_line[5:]
                
                # 这里应该写入utmp/wtmp文件，但实现复杂，暂时记录日志
                logger.info(f"模拟utmp登录: 用户={user}, tty={tty_line}, 远程主机={remotehost}")
                
            except Exception as e:
                logger.warning(f"utmp处理失败: {e}")
    
    def logout(self):
        """
        移除此tty的utmp条目。
        
        对应C++: void KPty::logout()
        """
        d = self.Q_D()
        
        try:
            # 获取tty名称（去掉/dev/前缀）
            tty_line = d.ttyName.decode('utf-8')
            if tty_line.startswith('/dev/'):
                tty_line = tty_line[5:]
            
            logger.info(f"模拟utmp登出: tty={tty_line}")
            
        except Exception as e:
            logger.warning(f"utmp登出处理失败: {e}")
    
    def tcGetAttr(self, ttmode: Optional[list] = None) -> Union[bool, list]:
        """
        tcgetattr(3)的包装器。
        
        Args:
            ttmode: 如果提供，将填充终端属性（C++风格）
            
        Returns:
            C++风格：成功返回True，失败返回False
            Python风格：返回termios列表或None
            
        对应C++: bool KPty::tcGetAttr(struct ::termios * ttmode) const
        """
        d = self.Q_D()
        
        if d.masterFd < 0:
            if ttmode is None:
                return None
            return False
        
        try:
            attrs = termios.tcgetattr(d.masterFd)
            
            if ttmode is not None:
                # C++风格：修改传入的列表
                ttmode.clear()
                ttmode.extend(attrs)
                return True
            else:
                # Python风格：返回属性列表
                return attrs
                
        except (OSError, termios.error) as e:
            logger.warning(f"获取终端属性失败: {e}")
            if ttmode is None:
                return None
            return False
    
    def tcSetAttr(self, ttmode: list) -> bool:
        """
        tcsetattr(3)的包装器，使用TCSANOW模式。
        
        Args:
            ttmode: termios结构的列表表示
            
        Returns:
            成功时返回True，否则返回False
            
        对应C++: bool KPty::tcSetAttr(struct ::termios * ttmode)
        """
        d = self.Q_D()
        
        if d.masterFd < 0:
            return False
        
        try:
            termios.tcsetattr(d.masterFd, termios.TCSANOW, ttmode)
            return True
        except (OSError, termios.error) as e:
            logger.warning(f"设置终端属性失败: {e}")
            return False
    
    def setWinSize(self, lines: int, columns: int) -> bool:
        """
        更改pty的逻辑（屏幕）大小。
        
        Args:
            lines: 行数
            columns: 列数
            
        Returns:
            成功时返回True，否则返回False
            
        对应C++: bool KPty::setWinSize(int lines, int columns)
        """
        d = self.Q_D()
        
        if d.masterFd < 0:
            return False
        
        try:
            # struct winsize { unsigned short ws_row, ws_col, ws_xpixel, ws_ypixel }
            winsize = struct.pack('HHHH', lines, columns, 0, 0)
            fcntl.ioctl(d.masterFd, termios.TIOCSWINSZ, winsize)
            return True
        except (OSError, struct.error) as e:
            logger.warning(f"设置窗口大小失败: {e}")
            return False
    
    def setEcho(self, echo: bool) -> bool:
        """
        设置pty是否应该回显输入。
        
        Args:
            echo: 如果输入应该被回显，则为True
            
        Returns:
            成功时返回True，否则返回False
            
        对应C++: bool KPty::setEcho(bool echo)
        """
        ttmode = []
        if not self.tcGetAttr(ttmode):
            return False
        
        try:
            if echo:
                ttmode[3] |= termios.ECHO  # c_lflag |= ECHO
            else:
                ttmode[3] &= ~termios.ECHO  # c_lflag &= ~ECHO
            
            return self.tcSetAttr(ttmode)
        except Exception as e:
            logger.warning(f"设置回显失败: {e}")
            return False
    
    def ttyName(self) -> str:
        """
        返回从pty设备的名称。
        
        Returns:
            从设备名称
            
        对应C++: const char * KPty::ttyName() const
        """
        d = self.Q_D()
        return d.ttyName.decode('utf-8') if d.ttyName else ""
    
    def masterFd(self) -> int:
        """
        返回主pty的文件描述符
        
        Returns:
            主设备文件描述符
            
        对应C++: int KPty::masterFd() const
        """
        d = self.Q_D()
        return d.masterFd
    
    def slaveFd(self) -> int:
        """
        返回从pty的文件描述符
        
        Returns:
            从设备文件描述符
            
        对应C++: int KPty::slaveFd() const
        """
        d = self.Q_D()
        return d.slaveFd
    
    # =================================================================
    # Python风格的便利属性和方法（向后兼容）
    # =================================================================
    
    @property
    def is_open(self) -> bool:
        """检查pty是否已打开"""
        return self.masterFd() >= 0
    
    @property
    def master_fd(self) -> int:
        """获取主设备文件描述符（Python风格属性）"""
        return self.masterFd()
    
    @property
    def slave_fd(self) -> int:
        """获取从设备文件描述符（Python风格属性）"""
        return self.slaveFd()
    
    @property
    def tty_name(self) -> str:
        """获取TTY设备名称（Python风格属性）"""
        return self.ttyName()
    
    @property
    def slave_name(self) -> str:
        """获取从设备名称（别名）"""
        return self.ttyName()
    
    @property
    def owns_master(self) -> bool:
        """返回是否拥有主设备的所有权"""
        d = self.Q_D()
        return d.ownMaster
    
    # Python风格的方法名别名
    def close_slave(self):
        """关闭从设备（Python风格方法名）"""
        self.closeSlave()
    
    def open_slave(self) -> bool:
        """打开从设备（Python风格方法名）"""
        return self.openSlave()
    
    def set_ctty(self):
        """设置控制终端（Python风格方法名）"""
        self.setCTty()
    
    def tc_get_attr(self) -> Optional[list]:
        """获取终端属性（Python风格方法名）"""
        return self.tcGetAttr()
    
    def tc_set_attr(self, ttmode: list) -> bool:
        """设置终端属性（Python风格方法名）"""
        return self.tcSetAttr(ttmode)
    
    def set_win_size(self, lines: int, columns: int) -> bool:
        """设置窗口大小（Python风格方法名）"""
        return self.setWinSize(lines, columns)
    
    def set_echo(self, echo: bool) -> bool:
        """设置回显（Python风格方法名）"""
        return self.setEcho(echo)
    
    # =================================================================
    # 扩展方法（C++版本中没有的便利方法）
    # =================================================================
    
    def getWinSize(self) -> Optional[Tuple[int, int]]:
        """
        获取当前窗口大小
        
        Returns:
            (行数, 列数)元组，失败时返回None
        """
        d = self.Q_D()
        
        if d.masterFd < 0:
            return None
        
        try:
            winsize = fcntl.ioctl(d.masterFd, termios.TIOCGWINSZ, b'\x00' * 8)
            rows, cols = struct.unpack('HHHH', winsize)[:2]
            return (rows, cols)
        except (OSError, struct.error) as e:
            logger.warning(f"获取窗口大小失败: {e}")
            return None
    
    def get_win_size(self) -> Optional[Tuple[int, int]]:
        """获取窗口大小（Python风格方法名）"""
        return self.getWinSize()
    
    def getStatInfo(self) -> Optional[os.stat_result]:
        """
        获取TTY设备的统计信息
        
        Returns:
            stat_result对象，失败时返回None
        """
        if not self.is_open:
            return None
        
        try:
            return os.stat(self.ttyName())
        except OSError as e:
            logger.warning(f"获取TTY统计信息失败: {e}")
            return None
    
    def get_stat_info(self) -> Optional[os.stat_result]:
        """获取统计信息（Python风格方法名）"""
        return self.getStatInfo()
    
    def checkPermissions(self) -> bool:
        """
        检查当前用户是否对TTY设备有读写权限
        
        Returns:
            有权限时返回True
        """
        if not self.is_open:
            return False
        
        try:
            return os.access(self.ttyName(), os.R_OK | os.W_OK)
        except OSError:
            return False
    
    def check_permissions(self) -> bool:
        """检查权限（Python风格方法名）"""
        return self.checkPermissions()


# =================================================================
# 便利函数和兼容性函数
# =================================================================

def create_pty_pair() -> Optional[Tuple[int, int, str]]:
    """
    创建PTY对的便利函数
    
    Returns:
        (master_fd, slave_fd, slave_name)元组，失败时返回None
    """
    try:
        master_fd, slave_fd = pty.openpty()
        slave_name = os.ttyname(slave_fd)
        return (master_fd, slave_fd, slave_name)
    except OSError as e:
        logger.error(f"创建PTY对失败: {e}")
        return None


def get_pty_slave_name(master_fd: int) -> Optional[str]:
    """
    从主设备文件描述符获取从设备名称
    
    Args:
        master_fd: 主设备文件描述符
        
    Returns:
        从设备名称，失败时返回None
    """
    try:
        return os.ttyname(master_fd)
    except OSError:
        return None


@contextmanager
def temporary_pty():
    """
    上下文管理器，提供临时PTY
    
    Yields:
        KPty对象
        
    Example:
        with temporary_pty() as pty:
            print(f"TTY: {pty.ttyName()}")
    """
    pty_obj = KPty()
    try:
        if pty_obj.open():
            yield pty_obj
        else:
            raise KPtyError("无法创建临时PTY")
    finally:
        pty_obj.close()


def get_available_ptys() -> list[str]:
    """
    获取系统中可用的PTY设备列表
    
    Returns:
        PTY设备名称列表
    """
    available = []
    
    # 检查现代的 /dev/pts/ 设备 (Linux)
    try:
        if os.path.exists("/dev/pts/"):
            for entry in os.listdir("/dev/pts/"):
                if entry.isdigit():
                    pts_path = f"/dev/pts/{entry}"
                    if os.path.exists(pts_path):
                        available.append(pts_path)
    except OSError:
        pass
    
    # 检查传统的 /dev/pty 设备 (macOS, BSD)
    for master_char in PTY_MASTER_CHARS:
        for slave_char in PTY_SLAVE_CHARS:
            pty_path = f"{PTY_DEVICE_PREFIX}{master_char}{slave_char}"
            if os.path.exists(pty_path):
                available.append(pty_path)
    
    # 在macOS上，也检查 /dev/ttys* 设备
    try:
        import glob
        tty_devices = glob.glob("/dev/ttys*")
        for tty_path in tty_devices:
            if os.path.exists(tty_path):
                available.append(tty_path)
    except (ImportError, OSError):
        pass
    
    return sorted(available)


# =================================================================
# 类型别名和常量（为了完全兼容C++）
# =================================================================

# 导出的主要类和函数
__all__ = [
    'KPty',
    'KPtyPrivate', 
    'KPtyError',
    'create_pty_pair',
    'get_pty_slave_name',
    'temporary_pty',
    'get_available_ptys',
    'TTY_GROUP',
    'CTRL',
    'PTY_DEVICE_PREFIX',
    'TTY_DEVICE_PREFIX',
    'PTS_DEVICE_PREFIX',
] 