#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
QTermWidget - 终端部件主实现
从qtermwidget.cpp/h转换而来

Copyright (C) 2008 e_k (e_k@users.sourceforge.net)
转换为Python PySide6版本
"""

import os
# 平台相关的默认字体
import platform
from typing import List, Optional

from PySide6.QtCore import QTranslator, QTimer
from PySide6.QtCore import (
    Qt, QSize, QPoint, QLocale, QIODevice,
    Signal, Slot, QUrl
)
from PySide6.QtGui import QFont, QKeyEvent, QResizeEvent, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QApplication, QMessageBox,
    QSizePolicy
)

from qtermwidget.color_scheme import ColorSchemeManager
from qtermwidget.filter import UrlFilter, Filter
from qtermwidget.history import HistoryTypeFile, HistoryTypeNone, HistoryTypeBuffer
from qtermwidget.history_search import HistorySearch
from qtermwidget.keyboard_translator import KeyboardTranslatorManager
from qtermwidget.qtermwidget_interface import QTermWidgetInterface, ScrollBarPosition
from qtermwidget.search_bar import SearchBar
# 导入已实现的模块
from qtermwidget.session import Session
from qtermwidget.terminal_character_decoder import PlainTextDecoder
from qtermwidget.terminal_display import TerminalDisplay

if platform.system() == "Darwin":  # macOS
    DEFAULT_FONT_FAMILY = "Menlo"
else:
    DEFAULT_FONT_FAMILY = "Monospace"

# 缩放步长
STEP_ZOOM = 1


class TermWidgetImpl:
    """
    终端部件内部实现类
    
    对应C++: class TermWidgetImpl
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        构造内部实现
        
        Args:
            parent: 父窗口部件
        """
        self.m_session = self._create_session(parent)
        self.m_terminalDisplay = self._create_terminal_display(self.m_session, parent)
    
    def _create_session(self, parent: Optional[QWidget] = None) -> Session:
        """
        创建会话对象
        
        Args:
            parent: 父窗口部件
            
        Returns:
            Session: 会话对象
        """
        session = Session(parent)
        
        session.setTitle(Session.TitleRole.NameRole, "QTermWidget")
        
        # 设置shell程序 - 优先使用环境变量SHELL
        shell_program = os.environ.get("SHELL", "/bin/bash")
        session.setProgram(shell_program)
        
        # 设置参数 - 修复：不应该传递空字符串参数
        args = []  # 空列表而不是包含空字符串的列表
        session.setArguments(args)
        session.setAutoClose(True)
        
        session.setFlowControlEnabled(True)
        session.setHistoryType(HistoryTypeBuffer(1000))
        
        session.setDarkBackground(True)
        session.setKeyBindings("")
        
        return session
    
    def _create_terminal_display(self, session: Session, parent: Optional[QWidget] = None) -> TerminalDisplay:
        """
        创建终端显示对象
        
        Args:
            session: 会话对象
            parent: 父窗口部件
            
        Returns:
            TerminalDisplay: 终端显示对象
        """
        from .terminal_display import BellMode, TripleClickMode
        
        display = TerminalDisplay(parent)
        
        # 设置响铃模式
        display.setBellMode(BellMode.NotifyBell)
        
        # 设置终端尺寸提示
        display.setTerminalSizeHint(True)
        
        # 设置三击模式
        display.setTripleClickMode(TripleClickMode.SelectWholeLine)
        
        # 设置终端启动尺寸
        display.setTerminalSizeStartup(True)
        
        # 设置随机种子
        session_id = session.sessionId()
        display.setRandomSeed(session_id * 31)
        
        return display


class QTermWidget(QWidget, QTermWidgetInterface):
    """
    QTermWidget - 主终端部件类
    
    对应C++: class QTermWidget : public QWidget, public QTermWidgetInterface
    """
    
    # 信号定义
    finished = Signal()                           # 会话结束
    copyAvailable = Signal(bool)                  # 复制可用
    termGetFocus = Signal()                       # 终端获得焦点
    termLostFocus = Signal()                      # 终端失去焦点
    termKeyPressed = Signal(QKeyEvent)            # 终端按键
    urlActivated = Signal(QUrl, bool)             # URL激活 (url, fromContextMenu)
    bell = Signal(str)                           # 响铃信号
    activity = Signal()                          # 活动信号
    silence = Signal()                           # 静默信号
    sendData = Signal(bytes, int)                # 发送数据
    profileChanged = Signal(str)                 # 配置改变
    titleChanged = Signal()                      # 标题改变
    receivedData = Signal(str)                   # 接收数据
    destroyed = Signal()                         # 销毁信号
    
    # 键盘光标形状枚举
    from .emulation import KeyboardCursorShape
    
    def __init__(self, startnow: int = 1, parent: Optional[QWidget] = None):
        """
        构造QTermWidget
        
        Args:
            startnow: 是否立即启动shell程序 (1=立即启动, 0=不启动)
            parent: 父窗口部件
        """
        super().__init__(parent)
        self.init(startnow)
    
    def init(self, startnow: int):
        """
        初始化终端部件
        
        Args:
            startnow: 是否立即启动
        """
        # 设置布局
        self.m_layout = QVBoxLayout()
        self.m_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.m_layout)
        
        # 设置翻译
        self._setup_translations()
        
        # 创建内部实现
        self.m_impl = TermWidgetImpl(self)
        self.m_layout.addWidget(self.m_impl.m_terminalDisplay)
        
        # 连接会话信号
        self._connect_session_signals()
        
        # 设置URL过滤器
        self._setup_url_filter()
        
        # 创建搜索栏
        self._setup_search_bar()
        
        # 设置焦点
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self.m_impl.m_terminalDisplay.resize(self.size())
        
        # 设置焦点代理
        self.setFocusProxy(self.m_impl.m_terminalDisplay)
        
        # 连接终端显示信号
        self._connect_terminal_display_signals()
        
        # 设置默认字体
        self._setup_default_font()
        
        # 设置默认配置
        self.setScrollBarPosition(ScrollBarPosition.NoScrollBar)
        self.setKeyboardCursorShape(self.KeyboardCursorShape.BlockCursor)
        
        # 连接会话和终端显示 - 关键：必须在 run() 之前连接
        # 这样当 shell 启动时，尺寸变化信号才能正确传递
        self.m_impl.m_session.addView(self.m_impl.m_terminalDisplay)
        
        # 连接会话事件信号
        self._connect_session_events()
        
        # 如果需要立即启动 - 放在所有连接建立之后
        if startnow and self.m_impl.m_session:
            self.m_impl.m_session.run()
    
    def _setup_translations(self):
        """设置翻译"""
        # 检查翻译目录
        xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "")
        dirs = xdg_data_dirs.split(":") if xdg_data_dirs else []
        
        if not dirs:
            dirs = ["/usr/local/share", "/usr/share"]
        
        # 添加编译时的翻译目录（这里暂时跳过）
        # dirs.append(TRANSLATIONS_DIR)
        
        self.m_translator = QTranslator(self)
        
        # 尝试加载翻译文件
        for dir_path in dirs:
            if self.m_translator.load(QLocale.system(), "qtermwidget", "_", dir_path):
                QApplication.instance().installTranslator(self.m_translator)
                break
    
    def _connect_session_signals(self):
        """连接会话信号"""
        # 关键的响铃信号连接 - 这个连接是核心功能
        try:
            if hasattr(self.m_impl.m_session, 'bellRequest'):
                # C++: connect(m_impl->m_session, SIGNAL(bellRequest(QString)), m_impl->m_terminalDisplay, SLOT(bell(QString)));
                self.m_impl.m_session.bellRequest.connect(
                    self.m_impl.m_terminalDisplay.bell
                )
                print("bellRequest -> terminalDisplay.bell 连接成功")
            
            if hasattr(self.m_impl.m_terminalDisplay, 'notifyBell'):
                # C++: connect(m_impl->m_terminalDisplay, SIGNAL(notifyBell(QString)), this, SIGNAL(bell(QString)));
                self.m_impl.m_terminalDisplay.notifyBell.connect(self.bell)
                print("terminalDisplay.notifyBell -> bell 连接成功")
        except Exception as e:
            print(f"Warning: Could not connect bell signals: {e}")
        
        # 活动和静默信号
        try:
            if hasattr(self.m_impl.m_session, 'activity'):
                # C++: connect(m_impl->m_session, SIGNAL(activity()), this, SIGNAL(activity()));
                self.m_impl.m_session.activity.connect(self.activity)
                print("session.activity -> activity 连接成功")
            
            if hasattr(self.m_impl.m_session, 'silence'):
                # C++: connect(m_impl->m_session, SIGNAL(silence()), this, SIGNAL(silence()));
                self.m_impl.m_session.silence.connect(self.silence)
                print("session.silence -> silence 连接成功")
            
            # 配置改变信号
            if hasattr(self.m_impl.m_session, 'profileChanged'):
                # C++: connect(m_impl->m_session, &Session::profileChangeCommandReceived, this, &QTermWidget::profileChanged);
                self.m_impl.m_session.profileChanged.connect(self.profileChanged)
                print("session.profileChanged -> profileChanged 连接成功")
            elif hasattr(self.m_impl.m_session, 'profileChangeCommandReceived'):
                self.m_impl.m_session.profileChangeCommandReceived.connect(self.profileChanged)
                print("session.profileChangeCommandReceived -> profileChanged 连接成功")
            
            # 接收数据信号
            if hasattr(self.m_impl.m_session, 'receivedData'):
                # C++: connect(m_impl->m_session, &Session::receivedData, this, &QTermWidget::receivedData);
                self.m_impl.m_session.receivedData.connect(self.receivedData)
                print("session.receivedData -> receivedData 连接成功")
        except Exception as e:
            print(f"Warning: Could not connect activity signals: {e}")
    
    def _setup_url_filter(self):
        """设置URL过滤器"""
        url_filter = UrlFilter()
        url_filter.activated.connect(self.urlActivated)
        
        # 获取过滤器链并添加过滤器
        filter_chain = self.m_impl.m_terminalDisplay.filterChain()
        filter_chain.addFilter(url_filter)
    
    def _setup_search_bar(self):
        """设置搜索栏"""
        self.m_searchBar = SearchBar(self)
        self.m_searchBar.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, 
            QSizePolicy.Policy.Maximum
        )
        
        # 连接搜索信号
        self.m_searchBar.searchCriteriaChanged.connect(self.find)
        self.m_searchBar.findNext.connect(self.findNext)
        self.m_searchBar.findPrevious.connect(self.findPrevious)
        
        self.m_layout.addWidget(self.m_searchBar)
        self.m_searchBar.hide()
    
    def _connect_terminal_display_signals(self):
        """连接终端显示信号"""
        try:
            # C++: connect(m_impl->m_terminalDisplay, SIGNAL(copyAvailable(bool)), this, SLOT(selectionChanged(bool)));
            self.m_impl.m_terminalDisplay.copyAvailable.connect(self.selectionChanged)
            print("terminalDisplay.copyAvailable -> selectionChanged 连接成功")
            
            # C++: connect(m_impl->m_terminalDisplay, SIGNAL(termGetFocus()), this, SIGNAL(termGetFocus()));
            self.m_impl.m_terminalDisplay.termGetFocus.connect(self.termGetFocus)
            print("terminalDisplay.termGetFocus -> termGetFocus 连接成功")
            
            # C++: connect(m_impl->m_terminalDisplay, SIGNAL(termLostFocus()), this, SIGNAL(termLostFocus()));
            self.m_impl.m_terminalDisplay.termLostFocus.connect(self.termLostFocus)
            print("terminalDisplay.termLostFocus -> termLostFocus 连接成功")
            
            # C++: connect(m_impl->m_terminalDisplay, &TerminalDisplay::keyPressedSignal, this, [this] (QKeyEvent* e, bool) { Q_EMIT termKeyPressed(e); });
            self.m_impl.m_terminalDisplay.keyPressedSignal.connect(
                lambda e, from_paste: self.termKeyPressed.emit(e)
            )
            print("terminalDisplay.keyPressedSignal -> termKeyPressed 连接成功")
            
            # 注意：键盘事件到模拟器的连接将在 session.addView() 中建立
            # 这遵循C++版本的Session::addView()逻辑
            print("键盘事件到模拟器的连接将在 session.addView() 中建立")
            
        except Exception as e:
            print(f"Warning: Could not connect terminal display signals: {e}")
    
    def _setup_default_font(self):
        """设置默认字体"""
        font = QApplication.font()
        font.setFamily(DEFAULT_FONT_FAMILY)
        font.setPointSize(10)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setTerminalFont(font)
        self.m_searchBar.setFont(font)
    
    def _connect_session_events(self):
        """连接会话事件信号"""
        try:
            # C++: connect(m_impl->m_session, SIGNAL(resizeRequest(QSize)), this, SLOT(setSize(QSize)));
            if hasattr(self.m_impl.m_session, 'resizeRequest'):
                self.m_impl.m_session.resizeRequest.connect(self.setSize)
                print("session.resizeRequest -> setSize 连接成功")
            
            # C++: connect(m_impl->m_session, SIGNAL(finished()), this, SLOT(sessionFinished()));
            if hasattr(self.m_impl.m_session, 'finished'):
                self.m_impl.m_session.finished.connect(self.sessionFinished)
                print("session.finished -> sessionFinished 连接成功")
            
            # C++: connect(m_impl->m_session, &Session::titleChanged, this, &QTermWidget::titleChanged);
            if hasattr(self.m_impl.m_session, 'titleChanged'):
                self.m_impl.m_session.titleChanged.connect(self.titleChanged)
                print("session.titleChanged -> titleChanged 连接成功")
            
            # C++: connect(m_impl->m_session, &Session::cursorChanged, this, &QTermWidget::cursorChanged);
            if hasattr(self.m_impl.m_session, 'cursorChanged'):
                try:
                    self.m_impl.m_session.cursorChanged.connect(self.cursorChanged)
                    print("session.cursorChanged -> cursorChanged 连接成功")
                except Exception as cursor_error:
                    print(f"Warning: Could not connect cursorChanged signal: {cursor_error}")
        except Exception as e:
            print(f"Warning: Could not connect session events: {e}")
    
    def close(self):
        """
        显式关闭终端组件
        
        这将安全地终止会话和进程，避免在析构时出现警告。
        建议在父窗口的closeEvent中显式调用此方法。
        """
        try:
            if hasattr(self, 'm_impl') and self.m_impl and hasattr(self.m_impl, 'm_session') and self.m_impl.m_session:
                # 先关闭会话，这会处理进程终止
                self.m_impl.m_session.close()
                
                # 等待一小段时间让进程清理
                QTimer.singleShot(10, self._finish_close)
            else:
                self._finish_close()
        except Exception:
            # 忽略错误，直接进行后续清理
            self._finish_close()
            
    def _finish_close(self):
        """完成关闭流程"""
        try:
            # 断开所有信号
            self.blockSignals(True)
            
            # 设置销毁标志
            self._is_destroying = True
            
            # 调用基类close
            super().close()
            
            # 触发延迟删除
            self.deleteLater()
        except:
            pass

    def __del__(self):
        """析构函数 - 增强安全性防止段错误"""
        try:
            # 设置销毁标志，防止重复处理
            if getattr(self, '_is_destroying', False):
                return
            self._is_destroying = True
            
            # 停止和销毁会话
            if hasattr(self, 'm_impl') and self.m_impl and hasattr(self.m_impl, 'm_session') and self.m_impl.m_session:
                try:
                    # 确保进程被终止
                    # 使用close()而不是直接访问私有变量
                    self.m_impl.m_session.close()
                except Exception:
                    pass
            
            # 发出销毁信号
            try:
                if hasattr(self, 'destroyed'):
                    self.destroyed.emit()
            except:
                pass
            
            # 跳过信号断开连接以避免警告
            pass
            
            # 后续清理逻辑...
            # 简化析构函数，避免过多操作
        except Exception:
            pass
            
            # 安全地清理搜索栏
            if hasattr(self, 'm_searchBar') and self.m_searchBar:
                try:
                    # 修复：断开特定信号
                    if hasattr(self.m_searchBar, 'searchCriteriaChanged'):
                        self.m_searchBar.searchCriteriaChanged.disconnect()
                    if hasattr(self.m_searchBar, 'findNext'):
                        self.m_searchBar.findNext.disconnect()
                    if hasattr(self.m_searchBar, 'findPrevious'):
                        self.m_searchBar.findPrevious.disconnect()
                    self.m_searchBar.deleteLater()
                    self.m_searchBar = None
                except (RuntimeError, AttributeError, TypeError):
                    pass
            
            # 安全地清理内部实现对象
            if hasattr(self, 'm_impl') and self.m_impl:
                try:
                    # 先清理终端显示
                    if hasattr(self.m_impl, 'm_terminalDisplay') and self.m_impl.m_terminalDisplay:
                        try:
                            # 修复：断开特定信号而不是使用无参数的disconnect()
                            if hasattr(self.m_impl.m_terminalDisplay, 'copyAvailable'):
                                self.m_impl.m_terminalDisplay.copyAvailable.disconnect()
                            if hasattr(self.m_impl.m_terminalDisplay, 'termGetFocus'):
                                self.m_impl.m_terminalDisplay.termGetFocus.disconnect()
                            if hasattr(self.m_impl.m_terminalDisplay, 'termLostFocus'):
                                self.m_impl.m_terminalDisplay.termLostFocus.disconnect()
                            if hasattr(self.m_impl.m_terminalDisplay, 'keyPressedSignal'):
                                self.m_impl.m_terminalDisplay.keyPressedSignal.disconnect()
                            self.m_impl.m_terminalDisplay = None
                        except (RuntimeError, AttributeError, TypeError):
                            pass
                    
                    # 再清理会话 - 遵循C++版本的逻辑
                    if hasattr(self.m_impl, 'm_session') and self.m_impl.m_session:
                        try:
                            # 修复：断开特定信号而不是使用无参数的disconnect()
                            if hasattr(self.m_impl.m_session, 'finished'):
                                self.m_impl.m_session.finished.disconnect()
                            if hasattr(self.m_impl.m_session, 'resizeRequest'):
                                self.m_impl.m_session.resizeRequest.disconnect()
                            if hasattr(self.m_impl.m_session, 'titleChanged'):
                                self.m_impl.m_session.titleChanged.disconnect()
                            
                            # 如果会话正在运行，立即强制关闭
                            if self.m_impl.m_session.isRunning():
                                print("正在强制关闭终端会话...")
                                # 在析构函数中直接强制关闭，不等待
                                self._force_close_session()
                                print("会话已强制关闭")
                            
                            self.m_impl.m_session = None
                        except (RuntimeError, AttributeError, TypeError):
                            pass
                    
                    # 清理实现对象本身
                    self.m_impl = None
                except (RuntimeError, AttributeError, TypeError):
                    pass
            
            # 清理翻译器
            if hasattr(self, 'm_translator') and self.m_translator:
                try:
                    app = QApplication.instance()
                    if app:
                        app.removeTranslator(self.m_translator)
                    self.m_translator.deleteLater()
                    self.m_translator = None
                except (RuntimeError, AttributeError):
                    pass
            
            # 最后发出销毁信号（如果对象仍然有效）
            try:
                if (hasattr(self, 'destroyed') and 
                    hasattr(self.destroyed, 'emit') and 
                    not getattr(self, '_signals_disconnected', False)):
                    self.destroyed.emit()
            except (RuntimeError, AttributeError):
                # 忽略析构时的信号错误，这在Qt对象销毁过程中是正常的
                pass
                
        except Exception:
            # 析构函数中忽略所有异常，防止程序崩溃
            pass
    
    # ===============================
    # QTermWidgetInterface接口实现
    # ===============================
    
    def sizeHint(self) -> QSize:
        """
        获取尺寸提示
        
        Returns:
            QSize: 推荐尺寸
        """
        size = self.m_impl.m_terminalDisplay.sizeHint()
        size.setHeight(150)
        return size
    
    def setTerminalSizeHint(self, enabled: bool):
        """设置终端尺寸提示"""
        self.m_impl.m_terminalDisplay.setTerminalSizeHint(enabled)
    
    def terminalSizeHint(self) -> bool:
        """获取终端尺寸提示状态"""
        return self.m_impl.m_terminalDisplay.terminalSizeHint()
    
    def startShellProgram(self):
        """启动shell程序"""
        if self.m_impl.m_session.isRunning():
            return
        self.m_impl.m_session.run()
    
    def startTerminalTeletype(self):
        """启动终端电传打字机模式"""
        if self.m_impl.m_session.isRunning():
            return
        
        self.m_impl.m_session.runEmptyPTY()
        # 重定向数据到外部接收者
        try:
            emulation = self.m_impl.m_session.emulation()
            if emulation:
                emulation.sendData.connect(self.sendData)
        except Exception as e:
            print(f"Warning: Could not connect sendData: {e}")
    
    def getShellPID(self) -> int:
        """获取shell进程ID"""
        return self.m_impl.m_session.processId()
    
    def getForegroundProcessId(self) -> int:
        """获取前台进程ID"""
        return self.m_impl.m_session.foregroundProcessId()

    def getIsRunning(self) -> bool:
        """获取会话状态"""
        return self.m_impl.m_session.isRunning()
    
    def changeDir(self, dir: str):
        """改变工作目录"""
        # 这是一个非常黑客的方式来确定shell是否在前台
        # 可能只适用于Linux
        shell_pid = self.getShellPID()
        cmd = f"ps -j {shell_pid} | tail -1 | awk '{{ print $5 }}' | grep -q \\+"
        retval = os.system(cmd)
        
        if retval == 0:
            cmd_text = f"cd {dir}\n"
            self.sendText(cmd_text)
    
    def setTerminalFont(self, font: QFont):
        """设置终端字体"""
        self.m_impl.m_terminalDisplay.setVTFont(font)
    
    def getTerminalFont(self) -> QFont:
        """获取终端字体"""
        return self.m_impl.m_terminalDisplay.getVTFont()
    
    def setTerminalOpacity(self, level: float):
        """设置终端透明度"""
        self.m_impl.m_terminalDisplay.setOpacity(level)
    
    def setTerminalBackgroundImage(self, backgroundImage: str):
        """设置终端背景图片"""
        self.m_impl.m_terminalDisplay.setBackgroundImage(backgroundImage)
    
    def setTerminalBackgroundMode(self, mode: int):
        """设置终端背景模式"""
        from .terminal_display import BackgroundMode
        self.m_impl.m_terminalDisplay.setBackgroundMode(BackgroundMode(mode))

    def setSuppressProgramBackgroundColors(self, suppress: bool):
        self.m_impl.m_terminalDisplay.setSuppressProgramBackgroundColors(suppress)
    
    def setShellProgram(self, program: str):
        """设置shell程序"""
        if not self.m_impl.m_session:
            return
        self.m_impl.m_session.setProgram(program)
    
    def setWorkingDirectory(self, dir: str):
        """设置工作目录"""
        if not self.m_impl.m_session:
            return
        self.m_impl.m_session.setInitialWorkingDirectory(dir)
    
    def workingDirectory(self) -> str:
        """获取工作目录"""
        if not self.m_impl.m_session:
            return ""
        
        # 在Linux上，尝试读取 /proc/<pid>/cwd
        if platform.system() == "Linux":
            try:
                proc_dir = f"/proc/{self.getShellPID()}/cwd"
                if os.path.exists(proc_dir):
                    return os.path.realpath(proc_dir)
            except:
                pass
        
        # 回退到初始工作目录
        return self.m_impl.m_session.initialWorkingDirectory()
    
    def setArgs(self, args: List[str]):
        """设置程序参数"""
        if not self.m_impl.m_session:
            return
        self.m_impl.m_session.setArguments(args)
    
    def setColorScheme(self, origName: str):
        """设置颜色方案"""
        cs = None
        
        # 检查是否是文件路径
        is_file = os.path.exists(origName)
        name = os.path.splitext(os.path.basename(origName))[0] if is_file else origName
        
        # 避免旧的(int)解决方案
        if name not in self.availableColorSchemes():
            if is_file:
                if ColorSchemeManager.instance().loadCustomColorScheme(origName):
                    cs = ColorSchemeManager.instance().findColorScheme(name)
                else:
                    print(f"Warning: cannot load color scheme from {origName}")
            
            if not cs:
                cs = ColorSchemeManager.instance().defaultColorScheme()
        else:
            cs = ColorSchemeManager.instance().findColorScheme(name)
        
        if not cs:
            QMessageBox.information(
                self,
                self.tr("Color Scheme Error"),
                self.tr(f"Cannot load color scheme: {name}")
            )
            return
        
        # 设置颜色表
        from qtermwidget.color_scheme import ColorEntry, TABLE_COLORS
        color_table = [ColorEntry() for _ in range(TABLE_COLORS)]
        cs.getColorTable(color_table)
        self.m_impl.m_terminalDisplay.setColorTable(color_table)
        self.m_impl.m_session.setDarkBackground(cs.hasDarkBackground())
    
    def getAvailableColorSchemes(self) -> List[str]:
        """获取可用的颜色方案"""
        return self.availableColorSchemes()
    
    @staticmethod
    def availableColorSchemes() -> List[str]:
        """获取所有可用的颜色方案"""
        ret = []
        all_schemes = ColorSchemeManager.instance().allColorSchemes()
        for cs in all_schemes:
            ret.append(cs.name())
        return ret
    
    @staticmethod
    def addCustomColorSchemeDir(custom_dir: str):
        """添加自定义颜色方案目录"""
        ColorSchemeManager.instance().addCustomColorSchemeDir(custom_dir)
    
    def setHistorySize(self, lines: int):
        """设置历史记录大小"""
        if lines < 0:
            self.m_impl.m_session.setHistoryType(HistoryTypeFile())
        elif lines == 0:
            self.m_impl.m_session.setHistoryType(HistoryTypeNone())
        else:
            self.m_impl.m_session.setHistoryType(HistoryTypeBuffer(lines))
    
    def historySize(self) -> int:
        """获取历史记录大小"""
        current_history = self.m_impl.m_session.historyType()
        
        if current_history and current_history.isEnabled():
            if current_history.isUnlimited():
                return -1
            else:
                return current_history.maximumLineCount()
        else:
            return 0
    
    def setScrollBarPosition(self, pos: ScrollBarPosition):
        """设置滚动条位置"""
        self.m_impl.m_terminalDisplay.setScrollBarPosition(pos)
    
    def scrollToEnd(self):
        """滚动到末尾"""
        self.m_impl.m_terminalDisplay.scrollToEnd()
    
    def sendText(self, text: str):
        """发送文本到终端"""
        self.m_impl.m_session.sendText(text)
    
    def sendKeyEvent(self, e: QKeyEvent):
        """发送键盘事件到终端"""
        self.m_impl.m_session.sendKeyEvent(e)
    
    def setFlowControlEnabled(self, enabled: bool):
        """设置流控制是否启用"""
        self.m_impl.m_session.setFlowControlEnabled(enabled)
    
    def flowControlEnabled(self) -> bool:
        """获取流控制状态"""
        return self.m_impl.m_session.flowControlEnabled()
    
    def setFlowControlWarningEnabled(self, enabled: bool):
        """设置流控制警告是否启用"""
        if self.flowControlEnabled():
            self.m_impl.m_terminalDisplay.setFlowControlWarningEnabled(enabled)
    
    def keyBindings(self) -> str:
        """获取当前键绑定"""
        return self.m_impl.m_session.keyBindings()
    
    def setMotionAfterPasting(self, motion: int):
        """设置粘贴后的光标移动方式"""
        from .terminal_display import MotionAfterPasting
        self.m_impl.m_terminalDisplay.setMotionAfterPasting(MotionAfterPasting(motion))
    
    def historyLinesCount(self) -> int:
        """获取历史记录行数"""
        return self.m_impl.m_terminalDisplay.screenWindow().screen().getHistLines()
    
    def screenColumnsCount(self) -> int:
        """获取屏幕列数"""
        return self.m_impl.m_terminalDisplay.screenWindow().screen().getColumns()
    
    def screenLinesCount(self) -> int:
        """获取屏幕行数"""
        return self.m_impl.m_terminalDisplay.screenWindow().screen().getLines()
    
    def setSelectionStart(self, row: int, column: int):
        """设置选择开始位置"""
        self.m_impl.m_terminalDisplay.screenWindow().screen().setSelectionStart(column, row, True)
    
    def setSelectionEnd(self, row: int, column: int):
        """设置选择结束位置"""
        self.m_impl.m_terminalDisplay.screenWindow().screen().setSelectionEnd(column, row)
    
    def getSelectionStart(self, row: int = None, column: int = None) -> tuple:
        """
        获取选择开始位置
        
        在Python中，由于没有引用参数，返回元组
        为了兼容C++版本，也可以接受可选的引用参数
        
        Args:
            row: 可选的行号引用
            column: 可选的列号引用
            
        Returns:
            tuple: (row, column) 当没有提供引用参数时
        """
        if hasattr(self.m_impl.m_terminalDisplay.screenWindow().screen(), 'getSelectionStart'):
            column_val, row_val = self.m_impl.m_terminalDisplay.screenWindow().screen().getSelectionStart()
        else:
            # 如果方法不存在，返回默认值
            row_val, column_val = 0, 0
        
        if row is not None and column is not None:
            # 模拟C++的引用参数行为
            # 在Python中无法真正修改参数，这里仅为接口兼容性
            pass
        
        return (row_val, column_val)
    
    def getSelectionEnd(self, row: int = None, column: int = None) -> tuple:
        """
        获取选择结束位置
        
        在Python中，由于没有引用参数，返回元组
        为了兼容C++版本，也可以接受可选的引用参数
        
        Args:
            row: 可选的行号引用
            column: 可选的列号引用
            
        Returns:
            tuple: (row, column) 当没有提供引用参数时
        """
        if hasattr(self.m_impl.m_terminalDisplay.screenWindow().screen(), 'getSelectionEnd'):
            column_val, row_val = self.m_impl.m_terminalDisplay.screenWindow().screen().getSelectionEnd()
        else:
            # 如果方法不存在，返回默认值
            row_val, column_val = 0, 0
        
        if row is not None and column is not None:
            # 模拟C++的引用参数行为
            # 在Python中无法真正修改参数，这里仅为接口兼容性
            pass
        
        return (row_val, column_val)
    
    def selectedText(self, preserveLineBreaks: bool = True) -> str:
        """获取选中的文本"""
        return self.m_impl.m_terminalDisplay.screenWindow().screen().selectedText(preserveLineBreaks)
    
    def setMonitorActivity(self, enabled: bool):
        """设置活动监控"""
        self.m_impl.m_session.setMonitorActivity(enabled)
    
    def setMonitorSilence(self, enabled: bool):
        """设置静默监控"""
        self.m_impl.m_session.setMonitorSilence(enabled)
    
    def setSilenceTimeout(self, seconds: int):
        """设置静默超时时间"""
        self.m_impl.m_session.setMonitorSilenceSeconds(seconds)
    
    def filterActions(self, position: QPoint) -> List[QAction]:
        """获取指定位置的过滤器动作"""
        return self.m_impl.m_terminalDisplay.filterActions(position)
    
    def getPtySlaveFd(self) -> int:
        """获取PTY从文件描述符"""
        return self.m_impl.m_session.getPtySlaveFd()
    
    def setBlinkingCursor(self, blink: bool):
        """设置光标是否闪烁"""
        self.m_impl.m_terminalDisplay.setBlinkingCursor(blink)
    
    def setBidiEnabled(self, enabled: bool):
        """设置双向文本是否启用"""
        self.m_impl.m_terminalDisplay.setBidiEnabled(enabled)
    
    def isBidiEnabled(self) -> bool:
        """获取双向文本状态"""
        return self.m_impl.m_terminalDisplay.isBidiEnabled()
    
    def setAutoClose(self, enabled: bool):
        """设置自动关闭"""
        self.m_impl.m_session.setAutoClose(enabled)
    
    def title(self) -> str:
        """获取标题"""
        title = self.m_impl.m_session.userTitle()
        
        if not title:
            title = self.m_impl.m_session.title(Session.TitleRole.NameRole)
        return title if title else ""
    
    def icon(self) -> str:
        """获取图标"""
        icon = self.m_impl.m_session.iconText()
        
        if not icon:
            icon = self.m_impl.m_session.iconName()
        return icon if icon else ""
    
    def isTitleChanged(self) -> bool:
        """检查标题是否改变"""
        return self.m_impl.m_session.isTitleChanged()
    
    def bracketText(self, text: str) -> str:
        """
        处理括号文本
        
        C++版本: void bracketText(QString& text)
        Python版本: 返回处理后的文本
        """
        try:
            # 调用底层的bracketText方法
            if hasattr(self.m_impl.m_terminalDisplay, 'bracketText'):
                # 在Python中，我们无法修改引用参数，所以直接返回处理后的结果
                result_text = text  # 复制输入文本
                # 如果底层方法返回值，使用返回值；否则假设已处理
                processed = self.m_impl.m_terminalDisplay.bracketText(result_text)
                return processed if processed is not None else result_text
            else:
                # 如果没有实现，返回原文本
                return text
        except Exception as e:
            print(f"Warning: bracketText failed: {e}")
            return text
    
    def disableBracketedPasteMode(self, disable: bool):
        """禁用括号粘贴模式"""
        self.m_impl.m_terminalDisplay.disableBracketedPasteMode(disable)
    
    def bracketedPasteModeIsDisabled(self) -> bool:
        """检查括号粘贴模式是否禁用"""
        return self.m_impl.m_terminalDisplay.bracketedPasteModeIsDisabled()
    
    def setMargin(self, margin: int):
        """设置边距"""
        self.m_impl.m_terminalDisplay.setMargin(margin)
    
    def getMargin(self) -> int:
        """获取边距"""
        return self.m_impl.m_terminalDisplay.margin()
    
    def setDrawLineChars(self, drawLineChars: bool):
        """设置是否绘制线条字符"""
        self.m_impl.m_terminalDisplay.setDrawLineChars(drawLineChars)
    
    def setBoldIntense(self, boldIntense: bool):
        """设置粗体强度"""
        self.m_impl.m_terminalDisplay.setBoldIntense(boldIntense)
    
    def setConfirmMultilinePaste(self, confirmMultilinePaste: bool):
        """设置多行粘贴确认"""
        self.m_impl.m_terminalDisplay.setConfirmMultilinePaste(confirmMultilinePaste)
    
    def setTrimPastedTrailingNewlines(self, trimPastedTrailingNewlines: bool):
        """设置修剪粘贴的尾随换行符"""
        self.m_impl.m_terminalDisplay.setTrimPastedTrailingNewlines(trimPastedTrailingNewlines)
    
    def wordCharacters(self) -> str:
        """获取单词字符"""
        return self.m_impl.m_terminalDisplay.wordCharacters()
    
    def setWordCharacters(self, chars: str):
        """设置单词字符"""
        self.m_impl.m_terminalDisplay.setWordCharacters(chars)
    
    def createWidget(self, startnow: int) -> 'QTermWidget':
        """创建新的部件实例"""
        return QTermWidget(startnow)
    
    def autoHideMouseAfter(self, delay: int):
        """设置鼠标自动隐藏延迟"""
        self.m_impl.m_terminalDisplay.autoHideMouseAfter(delay)
    
    # ===============================
    # 缺失的C++接口方法补全
    # ===============================
    
        # ===============================
    # 公共槽函数
    # ===============================
    
    @Slot()
    def copyClipboard(self):
        """复制选择到剪贴板"""
        self.m_impl.m_terminalDisplay.copyClipboard()
    
    @Slot()
    def pasteClipboard(self):
        """从剪贴板粘贴"""
        self.m_impl.m_terminalDisplay.pasteClipboard()
    
    @Slot()
    def pasteSelection(self):
        """粘贴选择"""
        self.m_impl.m_terminalDisplay.pasteSelection()
    
    @Slot()
    def zoomIn(self):
        """放大"""
        self.setZoom(STEP_ZOOM)
    
    @Slot()
    def zoomOut(self):
        """缩小"""
        self.setZoom(-STEP_ZOOM)
    
    @Slot()
    def setSize(self, size: QSize):
        """设置大小"""
        self.m_impl.m_terminalDisplay.setSize(size.width(), size.height())
    
    @Slot(str)
    def setKeyBindings(self, kb: str):
        """设置键绑定"""
        self.m_impl.m_session.setKeyBindings(kb)
    
    @Slot()
    def clear(self):
        """清除终端内容并移动到home位置"""
        emulation = self.m_impl.m_session.emulation()
        if emulation:
            # emulation.reset()
            emulation.clearEntireScreen()
        try:
            # 兼容Windows连接本地终端清屏功能
            if os.name == "nt":
                program = self.m_impl.m_session.program() if self.m_impl and self.m_impl.m_session else ""
                base = os.path.basename(program or "").lower()
                if base not in {"ssh", "ssh.exe"}:
                    self.sendText("cls\r")
                    self.m_impl.m_session.clearHistory()
                    return
        except Exception:
            pass

        self.m_impl.m_session.refresh()
        self.m_impl.m_session.clearHistory()
    
    @Slot()
    def toggleShowSearchBar(self):
        """切换搜索栏显示"""
        if self.m_searchBar.isHidden():
            self.m_searchBar.show()
        else:
            self.m_searchBar.hide()
    
    @Slot(QIODevice)
    def saveHistory(self, device: QIODevice):
        """保存历史记录"""
        # 创建文本流
        if hasattr(device, 'write'):
            # 如果设备有write方法，直接写入
            decoder = PlainTextDecoder()
            emulation = self.m_impl.m_session.emulation()
            if emulation and hasattr(decoder, 'begin') and hasattr(emulation, 'writeToStream'):
                decoder.begin(device)
                emulation.writeToStream(decoder, 0, emulation.lineCount())
    
    # ===============================
    # 事件处理
    # ===============================
    
    def resizeEvent(self, event: QResizeEvent):
        """处理窗口大小改变事件"""
        self.m_impl.m_terminalDisplay.resize(self.size())
        super().resizeEvent(event)
    
    # ===============================
    # 私有槽函数
    # ===============================
    
    @Slot()
    def sessionFinished(self):
        """会话结束处理"""
        self.finished.emit()
    
    @Slot(bool)
    def selectionChanged(self, textSelected: bool):
        """选择改变处理"""
        self.copyAvailable.emit(textSelected)
    
    @Slot()
    def find(self):
        """查找"""
        self.search(True, False)
    
    @Slot()
    def findNext(self):
        """查找下一个"""
        self.search(True, True)
    
    @Slot()
    def findPrevious(self):
        """查找上一个"""
        self.search(False, False)
    
    @Slot(int, int, int, int)
    def matchFound(self, startColumn: int, startLine: int, endColumn: int, endLine: int):
        """匹配找到处理"""
        sw = self.m_impl.m_terminalDisplay.screenWindow()
        sw.scrollTo(startLine)
        sw.setTrackOutput(False)
        sw.notifyOutputChanged()
        sw.setSelectionStart(startColumn, startLine - sw.currentLine(), False)
        sw.setSelectionEnd(endColumn, endLine - sw.currentLine())
    
    @Slot()
    def noMatchFound(self):
        """未找到匹配处理"""
        self.m_impl.m_terminalDisplay.screenWindow().clearSelection()
    
    @Slot()
    def cursorChanged(self, cursorShape, blinkingCursorEnabled: bool):
        """光标改变处理"""
        self.setKeyboardCursorShape(cursorShape)
        self.setBlinkingCursor(blinkingCursorEnabled)
    
    # ===============================
    # 私有方法
    # ===============================
    
    def search(self, forwards: bool, next: bool):
        """
        执行搜索
        
        Args:
            forwards: 是否前向搜索
            next: 是否搜索下一个
        """
        if next:  # 从当前选择后搜索
            startColumn, startLine = self.m_impl.m_terminalDisplay.screenWindow().screen().getSelectionEnd()
            startColumn += 1
        else:  # 从当前选择开始搜索
            startColumn, startLine = self.m_impl.m_terminalDisplay.screenWindow().screen().getSelectionStart()
        
        # 创建正则表达式
        from PySide6.QtCore import QRegularExpression
        
        regExp = QRegularExpression()
        
        if self.m_searchBar.useRegularExpression():
            regExp.setPattern(self.m_searchBar.searchText())
        else:
            regExp.setPattern(QRegularExpression.escape(self.m_searchBar.searchText()))
        
        # 设置模式选项
        if self.m_searchBar.matchCase():
            regExp.setPatternOptions(QRegularExpression.PatternOption.NoPatternOption)
        else:
            regExp.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
        
        # 创建历史搜索
        historySearch = HistorySearch(
            self.m_impl.m_session.emulation(),
            regExp,
            forwards,
            startColumn,
            startLine,
            self
        )
        
        # 连接信号
        historySearch.matchFound.connect(self.matchFound)
        historySearch.noMatchFound.connect(self.noMatchFound)
        historySearch.noMatchFound.connect(self.m_searchBar.noMatchFound)
        
        # 执行搜索
        historySearch.search()
    
    def setZoom(self, step: int):
        """
        设置缩放
        
        Args:
            step: 缩放步长
        """
        font = self.m_impl.m_terminalDisplay.getVTFont()
        font.setPointSize(font.pointSize() + step)
        self.setTerminalFont(font)
    
    def setKeyboardCursorShape(self, shape):
        """设置键盘光标形状"""
        self.m_impl.m_terminalDisplay.setKeyboardCursorShape(shape)
    
    def setEnvironment(self, environment: List[str]):
        """设置环境变量"""
        self.m_impl.m_session.setEnvironment(environment)
    
    # ===============================
    # 静态方法
    # ===============================
    
    @staticmethod
    def availableKeyBindings() -> List[str]:
        """获取所有可用的键绑定"""
        return KeyboardTranslatorManager.instance().allTranslators()
    
    # ===============================
    # 热点相关方法
    # ===============================
    
    def getHotSpotAt(self, *args):
        """
        获取指定位置的热点
        
        Args:
            可以是 (QPoint) 或 (row, column)
            
        Returns:
            Filter.HotSpot: 热点对象或None
        """
        if len(args) == 1 and isinstance(args[0], QPoint):
            pos = args[0]
            row, column = 0, 0
            if hasattr(self.m_impl.m_terminalDisplay, 'getCharacterPosition'):
                self.m_impl.m_terminalDisplay.getCharacterPosition(pos, row, column)
                return self.getHotSpotAt(row, column)
            else:
                return None
        elif len(args) == 2:
            row, column = args
            if hasattr(self.m_impl.m_terminalDisplay, 'filterChain'):
                filter_chain = self.m_impl.m_terminalDisplay.filterChain()
                if hasattr(filter_chain, 'hotSpotAt'):
                    return filter_chain.hotSpotAt(row, column)
            return None
        else:
            raise ValueError("Invalid arguments for getHotSpotAt")

    def _force_close_session(self):
        """
        强制关闭会话，用于析构函数和closeEvent
        
        这个方法会立即终止shell进程，不等待优雅关闭。
        """
        if not (hasattr(self, 'm_impl') and self.m_impl and self.m_impl.m_session):
            return
            
        try:
            # 断开finished信号避免递归
            if hasattr(self.m_impl.m_session, '_shellProcess'):
                shell_process = self.m_impl.m_session._shellProcess
                if shell_process:
                    try:
                        # 断开信号连接
                        if hasattr(shell_process, 'finished'):
                            shell_process.finished.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                    
                    # 立即杀死进程
                    try:
                        if hasattr(shell_process, 'kill'):
                            shell_process.kill()
                        elif hasattr(shell_process, 'terminate'):
                            shell_process.terminate()
                        
                        # 非常短暂的等待，主要是让系统处理信号
                        if hasattr(shell_process, 'waitForFinished'):
                            shell_process.waitForFinished(50)  # 只等待50ms
                    except Exception as e:
                        print(f"强制终止进程时出错: {e}")
            
            # 设置会话为已关闭状态
            if hasattr(self.m_impl.m_session, '_autoClose'):
                self.m_impl.m_session._autoClose = True
            if hasattr(self.m_impl.m_session, '_wantedClose'):
                self.m_impl.m_session._wantedClose = True
                
        except Exception as e:
            print(f"强制关闭会话时出错: {e}")
    
    def closeEvent(self, event):
        """
        处理窗口关闭事件
        
        确保在窗口关闭时正确终止终端进程，避免僵尸进程。
        """
        try:
            # 立即停止会话，避免QProcess错误
            if (hasattr(self, 'm_impl') and self.m_impl and 
                hasattr(self.m_impl, 'm_session') and self.m_impl.m_session):
                
                if self.m_impl.m_session.isRunning():
                    print("窗口关闭：正在终止终端进程...")
                    self._force_close_session()
                    print("终端进程已终止")
            
            # 接受关闭事件
            event.accept()
            
        except Exception as e:
            print(f"关闭窗口时出错: {e}")
            # 即使出错也要接受关闭事件
            event.accept()


# ===============================
# 工厂函数
# ===============================

def createTermWidget(startnow: int, parent: Optional[QWidget] = None) -> QTermWidget:
    """
    创建终端部件的工厂函数 (Python风格)
    
    Args:
        startnow: 是否立即启动
        parent: 父窗口部件
        
    Returns:
        QTermWidget: 终端部件对象
    """
    return QTermWidget(startnow, parent)

def create_term_widget(startnow: int, parent = None):
    """
    创建终端部件的工厂函数 (C兼容风格)
    
    这个函数模拟C++版本的void* createTermWidget(int startnow, void* parent)
    
    Args:
        startnow: 是否立即启动
        parent: 父窗口部件指针 (在Python中为对象引用)
        
    Returns:
        QTermWidget: 终端部件对象
    """
    return QTermWidget(startnow, parent)
