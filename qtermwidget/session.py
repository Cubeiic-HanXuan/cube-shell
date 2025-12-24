#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Session - 终端会话管理器 (修复版本)
严格按照C++ Session.cpp/Session.h实现

原始C++文件：
- qtermwidget/lib/Session.cpp  
- qtermwidget/lib/Session.h

Copyright (C) 2006-2007 by Robert Knight <robertknight@gmail.com>
Copyright (C) 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

转换为Python版本，严格遵循C++接口和行为
"""

import logging
import os
import re
import signal
from enum import IntEnum
from pathlib import Path
from typing import List, Optional, Dict

from PySide6.QtCore import (
    QObject, QTimer, QProcess, QSize, QDir,
    Signal, Slot, Property, QProcessEnvironment,
    QThread, QMetaObject, Qt
)
from PySide6.QtGui import QColor, QKeyEvent

# 设置日志
logger = logging.getLogger(__name__)

# 导入依赖 - 注意：使用Pty而不是KPtyProcess
from qtermwidget.emulation import Emulation
from qtermwidget.history import HistoryType
from qtermwidget.shell_command import ShellCommand
from qtermwidget.terminal_display import TerminalDisplay
from qtermwidget.vt102_emulation import Vt102Emulation

# 尝试导入Pty类 - 这是C++版本使用的正确类型
try:
    from qtermwidget.pty import Pty

    PTY_AVAILABLE = True
except ImportError:
    # 如果Pty不可用，回退到KPtyProcess (但这不是最佳选择)
    from qtermwidget.kptyprocess import KPtyProcess as Pty

    PTY_AVAILABLE = False

# 活动状态常量 - 对应C++: Emulation.h中的定义
NOTIFYNORMAL = 0  # 正常状态
NOTIFYBELL = 1  # 响铃事件
NOTIFYACTIVITY = 2  # 活动状态
NOTIFYSILENCE = 3  # 静默状态

# 视图阈值常量 - 对应C++: SESSION_VIEW_*_THRESHOLD
VIEW_LINES_THRESHOLD = 2
VIEW_COLUMNS_THRESHOLD = 2


class Session(QObject):
    """
    表示由伪终端和终端模拟器组成的终端会话。
    
    伪终端(PTY)处理终端进程和Konsole之间的I/O。
    终端模拟器处理PTY的输出流，并产生字符图像，
    然后在连接到会话的视图上显示。
    
    每个会话可以通过addView()方法连接到一个或多个视图。
    
    严格对应C++: class Session : public QObject
    """

    # 枚举定义 - 严格对应C++版本
    class TitleRole(IntEnum):
        """标题角色 - 对应C++: enum TitleRole"""
        NameRole = 0  # 会话名称
        DisplayedTitleRole = 1  # 显示的标题

    class TabTitleContext(IntEnum):
        """标签标题上下文 - 对应C++: enum TabTitleContext"""
        LocalTabTitle = 0  # 本地标签标题
        RemoteTabTitle = 1  # 远程标签标题

    # Qt属性定义 - 对应C++: Q_PROPERTY宏
    name = Property(str, lambda self: self.nameTitle())
    processId = Property(int, lambda self: self.processId())
    keyBindings = Property(str, lambda self: self.keyBindings(), lambda self, value: self.setKeyBindings(value))
    size = Property(QSize, lambda self: self.size(), lambda self, value: self.setSize(value))

    # 信号定义 - 严格对应C++版本
    started = Signal()
    finished = Signal()
    receivedData = Signal(str)
    titleChanged = Signal()
    profileChanged = Signal(str)
    stateChanged = Signal(int)
    bellRequest = Signal(str)
    changeTabTextColorRequest = Signal(int)
    changeBackgroundColorRequest = Signal(QColor)
    openUrlRequest = Signal(str)
    resizeRequest = Signal(QSize)
    profileChangeCommandReceived = Signal(str)
    flowControlEnabledChanged = Signal(bool)
    cursorChanged = Signal(object, bool)  # KeyboardCursorShape, bool
    silence = Signal()
    activity = Signal()

    # 类变量 - 对应C++: static int lastSessionId
    lastSessionId = 0

    def __init__(self, parent: Optional[QObject] = None):
        """
        构造新会话 - 对应C++: Session::Session(QObject* parent)
        
        要启动终端进程，在使用setProgram()和setArguments()
        指定程序和参数后调用run()方法。
        
        如果没有明确指定程序或参数，Session会回退到使用
        SHELL环境变量中指定的程序。
        """
        super().__init__(parent)

        # 基本成员变量 - 严格对应C++版本
        self._uniqueIdentifier = 0  # 对应C++: int _uniqueIdentifier

        # 核心组件 - 注意类型对应
        self._shellProcess: Optional[Pty] = None  # 对应C++: Pty *_shellProcess
        self._emulation: Optional[Emulation] = None  # 对应C++: Emulation *_emulation
        self._views: List[TerminalDisplay] = []  # 对应C++: QList<TerminalDisplay *> _views

        # 监控相关 - 对应C++成员
        self._monitorActivity = False  # 对应C++: bool _monitorActivity
        self._monitorSilence = False  # 对应C++: bool _monitorSilence
        self._notifiedActivity = False  # 对应C++: bool _notifiedActivity
        self._masterMode = False  # 对应C++: bool _masterMode
        self._autoClose = True  # 对应C++: bool _autoClose
        self._wantedClose = False  # 对应C++: bool _wantedClose
        self._monitorTimer: Optional[QTimer] = None  # 对应C++: QTimer *_monitorTimer

        # 时间相关
        self._silenceSeconds = 10  # 对应C++: int _silenceSeconds

        # 标题和图标 - 对应C++成员
        self._nameTitle = ""  # 对应C++: QString _nameTitle
        self._displayTitle = ""  # 对应C++: QString _displayTitle
        self._userTitle = ""  # 对应C++: QString _userTitle
        self._localTabTitleFormat = ""  # 对应C++: QString _localTabTitleFormat
        self._remoteTabTitleFormat = ""  # 对应C++: QString _remoteTabTitleFormat
        self._iconName = ""  # 对应C++: QString _iconName
        self._iconText = ""  # 对应C++: QString _iconText
        self._isTitleChanged = False  # 对应C++: bool _isTitleChanged

        # 系统设置
        self._addToUtmp = False  # 对应C++: bool _addToUtmp (默认false)
        self._flowControl = True  # 对应C++: bool _flowControl
        self._fullScripting = False  # 对应C++: bool _fullScripting

        # 程序和环境 - 注意环境变量类型修正
        self._program = ""  # 对应C++: QString _program
        self._arguments: List[str] = []  # 对应C++: QStringList _arguments
        self._environment: List[str] = []  # 对应C++: QStringList _environment (修正: 不是字典!)
        self._initialWorkingDir = ""  # 对应C++: QString _initialWorkingDir

        # 会话标识
        Session.lastSessionId += 1  # 对应C++: _sessionId = ++lastSessionId
        self._sessionId = Session.lastSessionId  # 对应C++: int _sessionId

        # 颜色和配置
        self._modifiedBackground = QColor()  # 对应C++: QColor _modifiedBackground
        self._profileKey = ""  # 对应C++: QString _profileKey
        self._hasDarkBackground = False  # 对应C++: bool _hasDarkBackground

        # PTY从设备文件描述符 - 对应C++: int ptySlaveFd
        self._ptySlaveFd = -1

        # 初始化组件 - 严格按照C++构造函数顺序
        self._initializeShellProcess()
        self._initializeEmulation()
        self._connectSignals()
        self._setupMonitorTimer()

    def _initializeShellProcess(self):
        """初始化Shell进程 - 对应C++构造函数中的PTY创建"""
        # 对应C++: _shellProcess = new Pty();
        # 但实际上应该使用KPtyProcess，因为它提供了更完整的功能
        from .kptyprocess import KPtyProcess
        self._shellProcess = KPtyProcess()

        # 对应C++: ptySlaveFd = _shellProcess->pty()->slaveFd();
        if hasattr(self._shellProcess, 'pty') and self._shellProcess.pty():
            self._ptySlaveFd = self._shellProcess.pty().slaveFd()
        elif hasattr(self._shellProcess, 'slaveFd'):
            self._ptySlaveFd = self._shellProcess.slaveFd()

    def _initializeEmulation(self):
        """初始化终端模拟器 - 对应C++构造函数中的模拟器创建"""
        # 对应C++: _emulation = new Vt102Emulation();
        self._emulation = Vt102Emulation()
        # 设置默认键绑定 - 对应C++中的默认初始化
        self._emulation.setKeyBindings("default")

    def _connectSignals(self):
        """连接信号 - 对应C++构造函数中的connect调用"""
        if not self._emulation or not self._shellProcess:
            return

        try:
            # 连接模拟器信号 - 对应C++的connect调用
            # connect(_emulation, SIGNAL(titleChanged(int, const QString &)), this, SLOT(setUserTitle(int, const QString &)));
            if hasattr(self._emulation, 'titleChanged'):
                self._emulation.titleChanged.connect(self.setUserTitle)

            # connect(_emulation, SIGNAL(stateSet(int)), this, SLOT(activityStateSet(int)));
            if hasattr(self._emulation, 'stateSet'):
                self._emulation.stateSet.connect(self.activityStateSet)

            # connect(_emulation, SIGNAL(changeTabTextColorRequest(int)), this, SIGNAL(changeTabTextColorRequest(int)));
            if hasattr(self._emulation, 'changeTabTextColorRequest'):
                self._emulation.changeTabTextColorRequest.connect(self.changeTabTextColorRequest)

            # connect(_emulation, SIGNAL(profileChangeCommandReceived(const QString &)), this, SIGNAL(profileChangeCommandReceived(const QString &)));
            if hasattr(self._emulation, 'profileChangeCommandReceived'):
                self._emulation.profileChangeCommandReceived.connect(self.profileChangeCommandReceived)

            # connect(_emulation, SIGNAL(imageResizeRequest(QSize)), this, SLOT(onEmulationSizeChange(QSize)));
            if hasattr(self._emulation, 'imageResizeRequest'):
                self._emulation.imageResizeRequest.connect(self.onEmulationSizeChange)

            # connect(_emulation, SIGNAL(imageSizeChanged(int, int)), this, SLOT(onViewSizeChange(int, int)));
            if hasattr(self._emulation, 'imageSizeChanged'):
                self._emulation.imageSizeChanged.connect(self.onViewSizeChange)

            # connect(_emulation, &Vt102Emulation::cursorChanged, this, &Session::cursorChanged);
            if hasattr(self._emulation, 'cursorChanged'):
                self._emulation.cursorChanged.connect(self.cursorChanged)

            # 连接PTY信号
            # _shellProcess->setUtf8Mode(true);
            if hasattr(self._shellProcess, 'setUtf8Mode'):
                self._shellProcess.setUtf8Mode(True)

            # connect(_shellProcess, SIGNAL(receivedData(const char *,int)), this, SLOT(onReceiveBlock(const char *,int)));
            if hasattr(self._shellProcess, 'receivedData'):
                self._shellProcess.receivedData.connect(self.onReceiveBlock)
                logger.debug("Session: Connected receivedData signal successfully")

            # connect(_emulation, SIGNAL(sendData(const char *,int)), _shellProcess, SLOT(sendData(const char *,int)));
            if hasattr(self._emulation, 'sendData') and hasattr(self._shellProcess, 'sendData'):
                self._emulation.sendData.connect(self._shellProcess.sendData)
                print(f"Connected sendData signal successfully: {self._emulation} -> {self._shellProcess}")
            else:
                print(f"Failed to connect sendData signal: emulation.sendData={hasattr(self._emulation, 'sendData')}, shellProcess.sendData={hasattr(self._shellProcess, 'sendData')}")

            # connect(_emulation, SIGNAL(lockPtyRequest(bool)), _shellProcess, SLOT(lockPty(bool)));
            if hasattr(self._emulation, 'lockPtyRequest') and hasattr(self._shellProcess, 'lockPty'):
                self._emulation.lockPtyRequest.connect(self._shellProcess.lockPty)

            # connect(_emulation, SIGNAL(useUtf8Request(bool)), _shellProcess, SLOT(setUtf8Mode(bool)));
            if hasattr(self._emulation, 'useUtf8Request') and hasattr(self._shellProcess, 'setUtf8Mode'):
                self._emulation.useUtf8Request.connect(self._shellProcess.setUtf8Mode)

            # connect(_shellProcess, SIGNAL(finished(int,QProcess::ExitStatus)), this, SLOT(done(int,QProcess::ExitStatus)));
            if hasattr(self._shellProcess, 'finished'):
                self._shellProcess.finished.connect(self.done)

        except Exception as e:
            print(f"Warning: Signal connection failed: {e}")

    def _setupMonitorTimer(self):
        """设置监控定时器 - 对应C++构造函数最后部分"""
        # 对应C++: _monitorTimer = new QTimer(this);
        self._monitorTimer = QTimer(self)
        self._monitorTimer.setSingleShot(True)
        self._monitorTimer.timeout.connect(self.monitorTimerDone)

        # =============================================================================

    # 公共方法 - 严格按照C++ Session.h的顺序和命名
    # =============================================================================

    def __del__(self):
        """析构函数 - 对应C++: Session::~Session()"""
        try:
            self.close()
            # 清理资源 - 按照C++版本的顺序
            if hasattr(self, '_emulation'):
                self._emulation = None
            if hasattr(self, '_shellProcess'):
                self._shellProcess = None
        except Exception:
            # 析构函数中忽略异常
            pass

    def isRunning(self) -> bool:
        """
        返回会话是否正在运行 - 对应C++: bool isRunning() const
        
        在成功调用run()后，这将返回true。
        """
        return (self._shellProcess is not None and
                self._shellProcess.state() == QProcess.ProcessState.Running)

    def setProfileKey(self, profileKey: str):
        """
        设置与此会话关联的配置文件 - 对应C++: void setProfileKey(const QString &)
        
        @param profileKey 可用于从SessionManager获取当前配置文件设置的键
        """
        self._profileKey = profileKey
        self.profileChanged.emit(profileKey)

    def profileKey(self) -> str:
        """
        返回与此会话关联的配置文件键 - 对应C++: QString profileKey() const
        
        这可以传递给SessionManager以获取当前配置文件设置。
        """
        return self._profileKey

    def addView(self, widget: TerminalDisplay):
        """
        为此会话添加新视图 - 对应C++: void addView(TerminalDisplay *)
        
        查看小部件将显示终端的输出，来自查看小部件的输入
        (按键、鼠标活动等)将发送到终端。
        
        可以使用removeView()移除视图。当移除最后一个视图时，
        会话将自动关闭。
        """
        # 对应C++: Q_ASSERT(!_views.contains(widget));
        if widget in self._views:
            return

        # 对应C++: _views.append(widget);
        self._views.append(widget)

        # 连接模拟器-视图信号和槽
        if self._emulation is not None:
            try:
                # connect(widget, &TerminalDisplay::keyPressedSignal, _emulation, &Emulation::sendKeyEvent);
                if hasattr(widget, 'keyPressedSignal') and hasattr(self._emulation, 'sendKeyEvent'):
                    widget.keyPressedSignal.connect(self._emulation.sendKeyEvent)

                # connect(widget, SIGNAL(mouseSignal(int,int,int,int)), _emulation, SLOT(sendMouseEvent(int,int,int,int)));
                if hasattr(widget, 'mouseSignal') and hasattr(self._emulation, 'sendMouseEvent'):
                    widget.mouseSignal.connect(self._emulation.sendMouseEvent)

                # connect(widget, SIGNAL(sendStringToEmu(const char *)), _emulation, SLOT(sendString(const char *)));
                if hasattr(widget, 'sendStringToEmu') and hasattr(self._emulation, 'sendString'):
                    widget.sendStringToEmu.connect(self._emulation.sendString)

                # 允许模拟器在前台进程指示是否对鼠标信号感兴趣时通知视图
                # connect(_emulation, SIGNAL(programUsesMouseChanged(bool)), widget, SLOT(setUsesMouse(bool)));
                if hasattr(self._emulation, 'programUsesMouseChanged') and hasattr(widget, 'setUsesMouse'):
                    self._emulation.programUsesMouseChanged.connect(widget.setUsesMouse)

                # widget->setUsesMouse(_emulation->programUsesMouse());
                if hasattr(widget, 'setUsesMouse') and hasattr(self._emulation, 'programUsesMouse'):
                    widget.setUsesMouse(self._emulation.programUsesMouse())

                # connect(_emulation, SIGNAL(programBracketedPasteModeChanged(bool)), widget, SLOT(setBracketedPasteMode(bool)));
                if hasattr(self._emulation, 'programBracketedPasteModeChanged') and hasattr(widget,
                                                                                            'setBracketedPasteMode'):
                    self._emulation.programBracketedPasteModeChanged.connect(widget.setBracketedPasteMode)

                # widget->setBracketedPasteMode(_emulation->programBracketedPasteMode());
                if hasattr(widget, 'setBracketedPasteMode') and hasattr(self._emulation, 'programBracketedPasteMode'):
                    widget.setBracketedPasteMode(self._emulation.programBracketedPasteMode())

                # widget->setScreenWindow(_emulation->createWindow());
                if hasattr(widget, 'setScreenWindow') and hasattr(self._emulation, 'createWindow'):
                    widget.setScreenWindow(self._emulation.createWindow())

            except Exception as e:
                print(f"Warning: 连接模拟器-视图信号失败: {e}")

        # 连接视图信号和槽
        try:
            # QObject::connect(widget, SIGNAL(changedContentSizeSignal(int,int)), this, SLOT(onViewSizeChange(int,int)));
            if hasattr(widget, 'changedContentSizeSignal'):
                widget.changedContentSizeSignal.connect(self.onViewSizeChange)

            # QObject::connect(widget, SIGNAL(destroyed(QObject *)), this, SLOT(viewDestroyed(QObject *)));
            widget.destroyed.connect(self.viewDestroyed)

            # 关闭槽
            # QObject::connect(this, SIGNAL(finished()), widget, SLOT(close()));
            self.finished.connect(widget.close)

        except Exception as e:
            print(f"Warning: 连接视图信号失败: {e}")

    def removeView(self, widget: TerminalDisplay):
        """
        从此会话中移除视图 - 对应C++: void removeView(TerminalDisplay *)
        
        当移除最后一个视图时，会话将自动关闭。
        
        @p widget将不再显示输出或向终端发送输入
        """
        # 对应C++: _views.removeAll(widget);
        if widget in self._views:
            self._views.remove(widget)

        # 对应C++: disconnect(widget, nullptr, this, nullptr);
        try:
            widget.disconnect(self)
        except Exception:
            pass

        if self._emulation is not None:
            try:
                # 断开视图的按键信号、鼠标活动信号、字符串发送信号
                # ... 以及addView()中连接的任何其他信号
                # disconnect(widget, nullptr, _emulation, nullptr);
                widget.disconnect(self._emulation)

                # 断开模拟器发出的状态改变信号
                # disconnect(_emulation, nullptr, widget, nullptr);
                self._emulation.disconnect(widget)

            except Exception:
                pass

        # 当移除最后一个视图时自动关闭会话
        # if (_views.count() == 0) { close(); }
        if len(self._views) == 0:
            self.close()

    def views(self) -> List[TerminalDisplay]:
        """
        返回连接到此会话的视图 - 对应C++: QList<TerminalDisplay *> views() const
        """
        return self._views.copy()

    def emulation(self) -> Optional[Emulation]:
        """
        返回用于编码/解码进程字符的终端模拟实例 - 对应C++: Emulation * emulation() const
        """
        return self._emulation

    def environment(self) -> List[str]:
        """
        返回此会话的环境变量列表 - 对应C++: QStringList environment() const
        
        @return 类似VARIABLE=VALUE的字符串列表
        """
        return self._environment.copy()

    def setEnvironment(self, environment: List[str]):
        """
        设置此会话的环境 - 对应C++: void setEnvironment(const QStringList &)
        
        @param environment 应该是类似VARIABLE=VALUE的字符串列表
        """
        self._environment = environment.copy()

    def sessionId(self) -> int:
        """返回此会话的唯一ID - 对应C++: int sessionId() const"""
        return self._sessionId

    def userTitle(self) -> str:
        """
        返回用户设置的会话标题 - 对应C++: QString userTitle() const
        
        返回用户设置的会话标题(即在终端中运行的程序)，
        如果用户没有设置自定义标题，则返回空字符串
        """
        return self._userTitle

    def setTabTitleFormat(self, context: TabTitleContext, format_str: str):
        """
        设置此会话用于标签标题的格式 - 对应C++: void setTabTitleFormat(TabTitleContext, const QString &)
        
        @param context 应设置格式的上下文
        @param format_str 标签标题格式。这可以是纯文本和动态元素的混合，
                         动态元素由'%'字符后跟一个字母表示(例如%d表示目录)。
                         可用的动态元素取决于@p context
        """
        if context == Session.TabTitleContext.LocalTabTitle:
            self._localTabTitleFormat = format_str
        elif context == Session.TabTitleContext.RemoteTabTitle:
            self._remoteTabTitleFormat = format_str

    def tabTitleFormat(self, context: TabTitleContext) -> str:
        """返回此会话用于标签标题的格式 - 对应C++: QString tabTitleFormat(TabTitleContext) const"""
        if context == Session.TabTitleContext.LocalTabTitle:
            return self._localTabTitleFormat
        elif context == Session.TabTitleContext.RemoteTabTitle:
            return self._remoteTabTitleFormat
        return ""

    def arguments(self) -> List[str]:
        """返回调用run()时传递给shell进程的参数 - 对应C++: QStringList arguments() const"""
        return self._arguments.copy()

    def program(self) -> str:
        """返回调用run()时启动的shell进程的程序名 - 对应C++: QString program() const"""
        return self._program

    def setArguments(self, arguments: List[str]):
        """
        设置调用run()时会话程序将传递的命令行参数 - 对应C++: void setArguments(const QStringList &)
        """
        self._arguments = [ShellCommand.expand(arg) for arg in arguments]

    def setProgram(self, program: str):
        """设置调用run()时要执行的程序 - 对应C++: void setProgram(const QString &)"""
        self._program = ShellCommand.expand(program)

    def initialWorkingDirectory(self) -> str:
        """返回会话的当前工作目录 - 对应C++: QString initialWorkingDirectory()"""
        return self._initialWorkingDir

    def setInitialWorkingDirectory(self, directory: str):
        """
        设置运行会话时的初始工作目录 - 对应C++: void setInitialWorkingDirectory(const QString &)
        
        会话启动后这没有效果。
        """
        self._initialWorkingDir = ShellCommand.expand(directory)

    def setHistoryType(self, historyType: HistoryType):
        """
        设置此会话使用的历史存储类型 - 对应C++: void setHistoryType(const HistoryType &)
        
        终端产生的输出行被添加到历史存储中。使用的历史存储类型
        影响在丢失之前可以记住的行数以及使用的存储
        (内存中、磁盘上等)。
        """
        if self._emulation:
            if hasattr(self._emulation, 'setHistory'):
                self._emulation.setHistory(historyType)

    def historyType(self) -> Optional[HistoryType]:
        """
        返回此会话使用的历史存储类型 - 对应C++: const HistoryType & historyType() const
        """
        if self._emulation:
            if hasattr(self._emulation, 'history'):
                return self._emulation.history()
        return None

    def clearHistory(self):
        """
        清除此会话使用的历史存储 - 对应C++: void clearHistory()
        """
        if self._emulation:
            if hasattr(self._emulation, 'clearHistory'):
                self._emulation.clearHistory()

    def setMonitorActivity(self, monitor: bool):
        """
        启用会话中活动的监控 - 对应C++: void setMonitorActivity(bool)
        
        这将导致在从终端接收到输出时发出notifySessionState()
        信号，状态标志为NOTIFYACTIVITY。
        """
        self._monitorActivity = monitor
        self._notifiedActivity = False
        self.activityStateSet(NOTIFYNORMAL)

    def isMonitorActivity(self) -> bool:
        """返回是否启用活动监控 - 对应C++: bool isMonitorActivity() const"""
        return self._monitorActivity

    def setMonitorSilence(self, monitor: bool):
        """
        启用会话中静默的监控 - 对应C++: void setMonitorSilence(bool)
        
        这将导致在指定时间内未从终端接收到输出时
        发出notifySessionState()信号，状态标志为NOTIFYSILENCE，
        时间用setMonitorSilenceSeconds()指定
        """
        if self._monitorSilence == monitor:
            return

        self._monitorSilence = monitor
        if self._monitorSilence:
            if self._monitorTimer:
                self._monitorTimer.start(self._silenceSeconds * 1000)
        else:
            if self._monitorTimer:
                self._monitorTimer.stop()

        self.activityStateSet(NOTIFYNORMAL)

    def isMonitorSilence(self) -> bool:
        """
        返回是否启用会话中的不活动(静默)监控 - 对应C++: bool isMonitorSilence() const
        """
        return self._monitorSilence

    def setMonitorSilenceSeconds(self, seconds: int):
        """参见setMonitorSilence() - 对应C++: void setMonitorSilenceSeconds(int)"""
        self._silenceSeconds = seconds
        if self._monitorSilence and self._monitorTimer:
            self._monitorTimer.start(self._silenceSeconds * 1000)

    def setKeyBindings(self, bindingsId: str):
        """
        设置此会话使用的键绑定 - 对应C++: void setKeyBindings(const QString &)
        
        绑定指定如何将输入按键序列转换为发送到终端的字符流。
        
        @param bindingsId 要使用的键绑定的名称。
               可用键绑定的名称可使用KeyboardTranslatorManager类确定。
        """
        if self._emulation:
            if hasattr(self._emulation, 'setKeyBindings'):
                self._emulation.setKeyBindings(bindingsId)

    def keyBindings(self) -> str:
        """返回此会话使用的键绑定名称 - 对应C++: QString keyBindings() const"""
        if self._emulation:
            if hasattr(self._emulation, 'keyBindings'):
                return self._emulation.keyBindings()
        return ""

    def setTitle(self, role: TitleRole, newTitle: str):
        """设置指定@p role的会话标题为@p title - 对应C++: void setTitle(TitleRole, const QString &)"""
        if self.title(role) != newTitle:
            if role == Session.TitleRole.NameRole:
                self._nameTitle = newTitle
            elif role == Session.TitleRole.DisplayedTitleRole:
                self._displayTitle = newTitle

            self.titleChanged.emit()

    def title(self, role: TitleRole) -> str:
        """返回指定@p role的会话标题 - 对应C++: QString title(TitleRole) const"""
        if role == Session.TitleRole.NameRole:
            return self._nameTitle
        elif role == Session.TitleRole.DisplayedTitleRole:
            return self._displayTitle
        return ""

    def nameTitle(self) -> str:
        """用于读取name属性的便利方法。返回title(Session::NameRole) - 对应C++: QString nameTitle() const"""
        return self.title(Session.TitleRole.NameRole)

    def setIconName(self, iconName: str):
        """设置与此会话关联的图标名称 - 对应C++: void setIconName(const QString &)"""
        if iconName != self._iconName:
            self._iconName = iconName
            self.titleChanged.emit()

    def iconName(self) -> str:
        """返回与此会话关联的图标名称 - 对应C++: QString iconName() const"""
        return self._iconName

    def setIconText(self, iconText: str):
        """设置与此会话关联的图标文本 - 对应C++: void setIconText(const QString &)"""
        self._iconText = iconText

    def iconText(self) -> str:
        """返回与此会话关联的图标文本 - 对应C++: QString iconText() const"""
        return self._iconText

    def isTitleChanged(self) -> bool:
        """标题/图标是否被用户/shell更改的标志 - 对应C++: bool isTitleChanged() const"""
        return self._isTitleChanged

    def setAddToUtmp(self, add: bool):
        """指定是否应为此会话使用的pty创建utmp条目 - 对应C++: void setAddToUtmp(bool)"""
        self._addToUtmp = add

    def sendSignal(self, sig: int) -> bool:
        """向终端进程发送指定的@p signal - 对应C++: bool sendSignal(int)"""
        if self.processId() <= 0:
            return False

        try:
            # 对应C++: int result = ::kill(static_cast<pid_t>(_shellProcess->processId()), signal);
            os.kill(self._shellProcess.processId(), sig)

            # 对应C++: if (result == 0) { return _shellProcess->waitForFinished(1000); }
            if self._shellProcess:
                return self._shellProcess.waitForFinished(1000)
            return True

        except (OSError, ProcessLookupError):
            return False

    def setAutoClose(self, autoClose: bool):
        """
        指定终端进程终止时是否自动关闭会话 - 对应C++: void setAutoClose(bool)
        
        注意：C++版本中这是内联实现
        """
        self._autoClose = autoClose

    def setFlowControlEnabled(self, enabled: bool):
        """
        设置是否为此终端会话启用流控制 - 对应C++: void setFlowControlEnabled(bool)
        """
        if self._flowControl == enabled:
            return

        self._flowControl = enabled

        if self._shellProcess:
            try:
                if hasattr(self._shellProcess, 'setFlowControlEnabled'):
                    self._shellProcess.setFlowControlEnabled(self._flowControl)
            except Exception as e:
                print(f"Warning: 设置流控制失败: {e}")

        self.flowControlEnabledChanged.emit(enabled)

    def flowControlEnabled(self) -> bool:
        """返回是否为此终端会话启用流控制 - 对应C++: bool flowControlEnabled() const"""
        return self._flowControl

    def sendText(self, text: str):
        """
        向当前前台终端程序发送@p text - 对应C++: void sendText(const QString &) const
        """
        if self._emulation:
            if hasattr(self._emulation, 'sendText'):
                self._emulation.sendText(text)

    def sendKeyEvent(self, event: QKeyEvent):
        """发送键盘事件 - 对应C++: void sendKeyEvent(QKeyEvent*) const"""
        if self._emulation:
            if hasattr(self._emulation, 'sendKeyEvent'):
                self._emulation.sendKeyEvent(event, False)

    def processId(self) -> int:
        """
        返回终端进程的进程ID - 对应C++: int processId() const
        
        这是系统API用来引用进程的ID。
        """
        if self._shellProcess:
            return self._shellProcess.processId()
        return -1

    def foregroundProcessId(self) -> int:
        """
        返回终端前台进程的进程ID - 对应C++: int foregroundProcessId() const
        
        最初与processId()相同，但当用户在终端内启动其他程序时可能会改变。
        """
        if self._shellProcess:
            if hasattr(self._shellProcess, 'foregroundProcessGroup'):
                return self._shellProcess.foregroundProcessGroup()
        return -1

    def size(self) -> QSize:
        """返回终端会话的窗口大小(行和列) - 对应C++: QSize size()"""
        if self._emulation:
            if hasattr(self._emulation, 'imageSize'):
                return self._emulation.imageSize()
        return QSize()

    def setSize(self, size: QSize):
        """
        发出调整会话大小以适应指定窗口大小的请求 - 对应C++: void setSize(const QSize &)
        
        @param size 以行和列为单位的请求大小
        """
        if size.width() <= 1 or size.height() <= 1:
            return
        self.resizeRequest.emit(size)

    def setDarkBackground(self, darkBackground: bool):
        """
        设置会话是否有深色背景 - 对应C++: void setDarkBackground(bool)
        
        会话使用此信息在进程环境中设置COLORFGBG变量，
        这允许在终端中运行的程序确定背景是明亮还是黑暗，
        并默认使用适当的颜色。
        
        会话运行后这没有效果。
        """
        self._hasDarkBackground = darkBackground

    def hasDarkBackground(self) -> bool:
        """
        返回会话是否有深色背景 - 对应C++: bool hasDarkBackground() const
        
        参见setDarkBackground()
        """
        return self._hasDarkBackground

    def refresh(self):
        """
        尝试让shell程序重绘当前显示区域 - 对应C++: void refresh()
        
        例如，在清除屏幕后可以使用此方法让shell重绘提示行。
        """
        if not self._shellProcess:
            return

        try:
            # 对应C++版本的窗口大小改变逻辑
            if hasattr(self._shellProcess, 'windowSize'):
                existing_size = self._shellProcess.windowSize()
                # 先稍微增大窗口，然后恢复原大小以触发变化
                self._shellProcess.setWindowSize(existing_size.height(), existing_size.width() + 1)
                #self._shellProcess.setWindowSize(existing_size.height(), existing_size.width())
                # 延迟1ms恢复，给Shell一点反应时间
                QTimer.singleShot(1, lambda: self._shellProcess.setWindowSize(existing_size.height(), existing_size.width()))
        except Exception as e:
            print(f"Warning: 刷新失败: {e}")

    def getPtySlaveFd(self) -> int:
        """
        返回pty从设备文件描述符 - 对应C++: int getPtySlaveFd() const
        
        这可用于显示和控制远程终端。
        """
        return self._ptySlaveFd

    def windowId(self) -> int:
        """
        获取窗口ID - 对应C++: WId windowId() const
        
        在Qt5中，请求窗口ID会破坏QQuickWidget等
        """
        # 对应C++注释：在Qt5+中返回0以避免问题
        return 0

        # =============================================================================

    # 公共槽 - 对应C++: public slots
    # =============================================================================

    @Slot()
    def run(self):
        """
        启动终端会话 - 对应C++: void run()
        
        这创建终端进程并将电传打字机连接到它。
        """
        if not self._shellProcess or not self._emulation:
            print("Error: Shell process or emulation not initialized")
            return

        # 严格按照C++版本的逻辑实现
        # 对应C++注释中的shell检查逻辑
        exec_path = self._program if self._program else ""

        # 修复：只有当exec是绝对路径（以/开头）或为空时才检查文件存在性
        # 对于非绝对路径的程序（如ssh），应该直接使用，让系统在PATH中查找
        if exec_path.startswith('/') or not exec_path:
            default_shell = "/bin/sh"

            if not exec_path or (exec_path.startswith('/') and not Path(exec_path).exists()):
                exec_path = os.environ.get("SHELL", "")

            if not exec_path or (exec_path.startswith('/') and not Path(exec_path).exists()):
                print(f"Neither default shell nor $SHELL is set to a correct path. Fallback to {default_shell}")
                exec_path = default_shell

        # 处理参数 - 严格对应C++版本的参数处理逻辑
        # C++版本: arguments << exec; if (argsTmp.length()) arguments << _arguments;
        # 这意味着arguments[0]是程序名，arguments[1:]是实际参数
        argsTmp = ' '.join(self._arguments).strip() if self._arguments else ""
        # argv[0]应该是程序的基本名称，不是完整路径
        program_name = Path(exec_path).name if exec_path.startswith('/') else exec_path
        arguments = [program_name]  # 第一个参数是程序的基本名称
        if argsTmp:
            arguments.extend(self._arguments)  # 添加实际的命令行参数        
        print(f"最终执行程序: {exec_path}")
        print(f"最终参数列表: {arguments}")

        # 设置工作目录
        cwd = QDir.currentPath()
        if self._initialWorkingDir:
            self._shellProcess.setWorkingDirectory(self._initialWorkingDir)
        else:
            self._shellProcess.setWorkingDirectory(cwd)

        # 设置流控制和其他属性
        if hasattr(self._shellProcess, 'setFlowControlEnabled'):
            self._shellProcess.setFlowControlEnabled(self._flowControl)
        if hasattr(self._shellProcess, 'setErase') and hasattr(self._emulation, 'eraseChar'):
            self._shellProcess.setErase(self._emulation.eraseChar())

        # 设置颜色背景提示 - 对应C++版本
        background_color_hint = "COLORFGBG=15;0" if self._hasDarkBackground else "COLORFGBG=0;15"

        try:
            # 调用shell进程的start方法 - 严格对应C++版本的参数
            if hasattr(self._shellProcess, 'start') and callable(getattr(self._shellProcess, 'start')):
                # 准备环境变量 - 对应C++版本
                env = self._environment + [background_color_hint]

                # 调用start方法 - 严格对应C++版本的签名
                # int result = _shellProcess->start(exec, arguments, _environment << backgroundColorHint, windowId(), _addToUtmp);
                # 符合C++版本逻辑：program是可执行文件路径，arguments[1:]是实际参数
                # C++版本：setProgram(program, programArguments.mid(1))
                result = self._shellProcess.start(
                    exec_path,  # program（可执行文件路径）
                    arguments[1:],  # arguments（实际参数，不包含程序名）
                    env,  # environment
                    self.windowId(),  # window_id
                    self._addToUtmp  # add_to_utmp
                )

                if result < 0:
                    print(f"CRASHED! result: {result}")
                    return
            else:
                # 回退到QProcess风格的启动
                self._shellProcess.setProgram(exec_path)
                if len(arguments) > 1:
                    self._shellProcess.setArguments(arguments[1:])

                # 设置环境
                process_env = QProcessEnvironment.systemEnvironment()
                for env_var in self._environment:
                    if '=' in env_var:
                        key, value = env_var.split('=', 1)
                        process_env.insert(key, value)
                process_env.insert("COLORFGBG", "15;0" if self._hasDarkBackground else "0;15")
                self._shellProcess.setProcessEnvironment(process_env)

                self._shellProcess.start()

            # 对应C++: _shellProcess->setWriteable(false);
            if hasattr(self._shellProcess, 'setWriteable'):
                self._shellProcess.setWriteable(False)

            # 延迟重连信号以确保进程启动后信号正常工作
            QTimer.singleShot(200, self._ensureSignalConnections)

            self.started.emit()

        except Exception as e:
            print(f"Error starting shell process: {e}")

    @Slot()
    def runEmptyPTY(self):
        """
        为"原样"PTY启动终端会话 - 对应C++: void runEmptyPTY()
        
        (不将数据导向内部终端进程)。
        可用于控制或显示远程/外部终端。
        """
        if not self._shellProcess or not self._emulation:
            return

        # 对应C++版本的设置
        if hasattr(self._shellProcess, 'setFlowControlEnabled'):
            self._shellProcess.setFlowControlEnabled(self._flowControl)
        if hasattr(self._shellProcess, 'setErase') and hasattr(self._emulation, 'eraseChar'):
            self._shellProcess.setErase(self._emulation.eraseChar())
        if hasattr(self._shellProcess, 'setWriteable'):
            self._shellProcess.setWriteable(False)

        # 断开从模拟器到内部终端进程的数据发送
        try:
            if hasattr(self._emulation, 'sendData') and hasattr(self._shellProcess, 'sendData'):
                self._emulation.sendData.disconnect(self._shellProcess.sendData)
        except Exception:
            pass

        # 设置空PTY属性
        if hasattr(self._shellProcess, 'setEmptyPTYProperties'):
            self._shellProcess.setEmptyPTYProperties()

        self.started.emit()

    @Slot()
    def close(self):
        """
        关闭终端会话 - 对应C++: void close()
        
        这向终端进程发送挂起信号(SIGHUP)并导致发出done(Session*)信号。
        """
        # 线程安全检查：如果不是在对象所属线程调用，则通过invokeMethod调度
        if self.thread() != QThread.currentThread():
            QMetaObject.invokeMethod(self, "close", Qt.QueuedConnection)
            return

        self._autoClose = True
        self._wantedClose = True

        if self._shellProcess:
            try:
                # 使用blockSignals代替disconnect，避免"Failed to disconnect (None)"错误
                self._shellProcess.blockSignals(True)
            except Exception:
                pass

        if self.isRunning():
            try:
                # 直接使用kill()杀死进程，避免复杂的信号发送逻辑导致的竞态条件
                # C++版本虽然尝试优雅退出，但在Python中直接kill更安全可靠
                if self._shellProcess:
                    try:
                        # 检查C++对象是否有效
                        try:
                            state = self._shellProcess.state()
                        except RuntimeError:
                            # C++对象已被删除
                            state = QProcess.ProcessState.NotRunning

                        if state != QProcess.ProcessState.NotRunning:
                            # 使用kill()直接杀死进程，避免sendSignal可能导致的NULL object问题
                            try:
                                # 直接调用C++ kill，或者绕过PySide包装
                                self._shellProcess.kill()
                            except:
                                # 如果C++ kill抛出异常，尝试用os.kill
                                try:
                                    if hasattr(self._shellProcess, 'processId'):
                                        pid = self._shellProcess.processId()
                                        if pid > 0:
                                            os.kill(pid, signal.SIGKILL)
                                except:
                                    pass

                            # 关键：等待时间不能太长，否则会阻塞UI线程导致"很久才关闭"
                            # 但也不能不等待，否则会产生僵尸进程或Qt警告
                            # 10ms是一个折中值 -> 增加到 100ms 以确保进程退出
                            if hasattr(self._shellProcess, 'waitForFinished'):
                                self._shellProcess.waitForFinished(100)
                            
                        # 确保状态更新
                        if hasattr(self._shellProcess, 'state') and self._shellProcess.state() != QProcess.ProcessState.NotRunning:
                             try:
                                 # 某些平台/版本下，setProcessState可能是只读的或内部方法
                                 # 尝试模拟状态改变
                                 if hasattr(self._shellProcess, 'setProcessState'):
                                     self._shellProcess.setProcessState(QProcess.ProcessState.NotRunning)
                             except:
                                 pass
                    except Exception:
                        pass

                    # 关键修复：将_shellProcess置为None，解除Python层面的引用
                    # 这样当Session销毁时，不会再尝试访问已销毁的C++对象
                    # 并且可以让GC更早回收Python对象
                    self._shellProcess = None

                # 尝试关闭PTY
                # 注意：此时_shellProcess已经置空，无法再访问closePty
                # 但我们在上面kill()之后，PTY应该会自动清理或在_cleanup中清理

                # 强制关闭
                QTimer.singleShot(1, self.finished)

            except Exception as e:
                # 即使出错也要发出finished信号
                QTimer.singleShot(1, self.finished)
        else:
            # 终端进程已完成，直接关闭会话
            QTimer.singleShot(1, self.finished)

    @Slot(int, str)
    def setUserTitle(self, what: int, caption: str):
        """
        更改会话标题或终端模拟显示的其他可自定义方面 - 对应C++: void setUserTitle(int, const QString &)
        
        有关可更改内容的列表，请参见Emulation::titleChanged()信号。
        """
        # 严格按照C++版本实现
        modified = False

        # (btw: what=0 changes _userTitle and icon, what=1 only icon, what=2 only _nameTitle
        if what in (0, 2):
            self._isTitleChanged = True
            if self._userTitle != caption:
                self._userTitle = caption
                modified = True

        if what in (0, 1):
            self._isTitleChanged = True
            if self._iconText != caption:
                self._iconText = caption
                modified = True

        if what == 11:
            color_string = caption.split(';')[0] if ';' in caption else caption
            back_color = QColor(color_string)
            if back_color.isValid():
                if back_color != self._modifiedBackground:
                    self._modifiedBackground = back_color
                    # 对应C++注释中的断言 - 此处先跳过实现
                    # Q_ASSERT(0);
                    self.changeBackgroundColorRequest.emit(back_color)

        if what == 30:
            self._isTitleChanged = True
            if self._nameTitle != caption:
                self.setTitle(Session.TitleRole.NameRole, caption)
                return

        if what == 31:
            # 处理当前工作目录
            cwd = re.sub(r'^~', QDir.homePath(), caption)
            self.openUrlRequest.emit(cwd)

        if what == 32:
            # 通过\033]32;Icon\007更改图标
            self._isTitleChanged = True
            if self._iconName != caption:
                self._iconName = caption
                modified = True

        if what == 50:
            self.profileChangeCommandReceived.emit(caption)
            return

        if modified:
            self.titleChanged.emit()

    # =============================================================================
    # 私有槽 - 对应C++: private slots  
    # =============================================================================

    @Slot(int, 'QProcess::ExitStatus')
    def done(self, exitCode: int, exitStatus: QProcess.ExitStatus):
        """进程完成处理 - 对应C++: void done(int, QProcess::ExitStatus)"""
        if not self._autoClose:
            self._userTitle = "This session is done. Finished"
            self.titleChanged.emit()
            return

        # 对应C++版本的消息处理逻辑
        message = ""
        if not self._wantedClose or exitCode != 0:
            if self._shellProcess and self._shellProcess.exitStatus() == QProcess.ExitStatus.NormalExit:
                message = f"Session '{self._nameTitle}' exited with code {exitCode}."
            else:
                message = f"Session '{self._nameTitle}' crashed."

        if not self._wantedClose and exitStatus != QProcess.ExitStatus.NormalExit:
            message = f"Session '{self._nameTitle}' exited unexpectedly."
        else:
            self.finished.emit()

    @Slot(bytes, int)
    def onReceiveBlock(self, buffer: bytes, length: int):
        """接收数据块处理 - 对应C++: void onReceiveBlock(const char *, int)"""
        if self._emulation:
            self._emulation.receiveData(buffer, length)

        # 发出receivedData信号 - 修复：使用UTF-8编码支持SSH
        try:
            # 优先使用UTF-8，SSH连接通常使用UTF-8编码
            text = buffer[:length].decode('utf-8', errors='replace')
            self.receivedData.emit(text)
        except Exception:
            try:
                # 回退到latin-1（原始C++行为）
                text = buffer[:length].decode('latin-1', errors='replace')
                self.receivedData.emit(text)
            except Exception:
                # 最后回退
                self.receivedData.emit(str(buffer[:length]))

    @Slot()
    def monitorTimerDone(self):
        """监控定时器到期处理 - 对应C++: void monitorTimerDone()"""
        # 对应C++版本的注释和逻辑
        if self._monitorSilence:
            self.silence.emit()
            self.stateChanged.emit(NOTIFYSILENCE)
        else:
            self.stateChanged.emit(NOTIFYNORMAL)

        self._notifiedActivity = False

    @Slot(int, int)
    def onViewSizeChange(self, height: int, width: int):
        """视图大小改变处理 - 对应C++: void onViewSizeChange(int, int)"""
        self.updateTerminalSize()

    @Slot(QSize)
    def onEmulationSizeChange(self, size: QSize):
        """模拟器大小改变处理 - 对应C++: void onEmulationSizeChange(QSize)"""
        self.setSize(size)

    @Slot(int)
    def activityStateSet(self, state: int):
        """活动状态设置 - 对应C++: void activityStateSet(int)"""
        if state == NOTIFYBELL:
            self.bellRequest.emit(f"Bell in session '{self._nameTitle}'")
        elif state == NOTIFYACTIVITY:
            if self._monitorSilence:
                if self._monitorTimer:
                    self._monitorTimer.start(self._silenceSeconds * 1000)

            if self._monitorActivity:
                if not self._notifiedActivity:
                    self._notifiedActivity = True
                    self.activity.emit()

        if state == NOTIFYACTIVITY and not self._monitorActivity:
            state = NOTIFYNORMAL
        if state == NOTIFYSILENCE and not self._monitorSilence:
            state = NOTIFYNORMAL

        self.stateChanged.emit(state)

    @Slot(QObject)
    def viewDestroyed(self, view: QObject):
        """视图销毁时自动分离视图 - 对应C++: void viewDestroyed(QObject *)"""
        if isinstance(view, TerminalDisplay) and view in self._views:
            self.removeView(view)

    # =============================================================================
    # 私有方法 - 对应C++: private methods
    # =============================================================================

    def updateTerminalSize(self):
        """更新终端大小 - 对应C++: void updateTerminalSize()"""
        if not self._emulation:
            return

        min_lines = -1
        min_columns = -1

        # 选择适合所有可见视图大小的最大行列数
        for view in self._views:
            if (not view.isHidden() and
                    hasattr(view, 'lines') and hasattr(view, 'columns') and
                    view.lines() >= VIEW_LINES_THRESHOLD and
                    view.columns() >= VIEW_COLUMNS_THRESHOLD):
                min_lines = view.lines() if min_lines == -1 else min(min_lines, view.lines())
                min_columns = view.columns() if min_columns == -1 else min(min_columns, view.columns())

        # 后端模拟器必须至少有1列x1行的终端大小
        if min_lines > 0 and min_columns > 0:
            if hasattr(self._emulation, 'setImageSize'):
                self._emulation.setImageSize(min_lines, min_columns)
            if self._shellProcess and hasattr(self._shellProcess, 'setWindowSize'):
                self._shellProcess.setWindowSize(min_lines, min_columns)

    def _ensureSignalConnections(self):
        """确保信号连接正常工作 - 延迟重连机制"""
        try:
            if self._shellProcess and hasattr(self._shellProcess, 'receivedData'):
                # 尝试重新连接receivedData信号
                try:
                    self._shellProcess.receivedData.disconnect(self.onReceiveBlock)
                except:
                    pass

                self._shellProcess.receivedData.connect(self.onReceiveBlock)
                print("Session: 重新连接receivedData信号成功")

                # 启动数据检查定时器
                self._startDataCheckTimer()

        except Exception as e:
            print(f"Session: 信号重连失败: {e}")

    def _startDataCheckTimer(self):
        """启动数据检查定时器 - 主动监控数据流"""
        if not hasattr(self, '_dataCheckTimer'):
            self._dataCheckTimer = QTimer(self)
            self._dataCheckTimer.timeout.connect(self._checkDataFlow)
            self._dataCheckTimer.start(1000)  # 每秒检查一次
            print("Session: 启动数据流监控定时器")

    def _checkDataFlow(self):
        """检查数据流是否正常"""
        if not self.isRunning():
            if hasattr(self, '_dataCheckTimer'):
                self._dataCheckTimer.stop()
            return

        # 检查是否有receivedData计数器
        if not hasattr(self, '_dataReceivedCount'):
            self._dataReceivedCount = 0

        # 如果长时间没有数据，尝试手动触发
        try:
            if (self._shellProcess and
                    hasattr(self._shellProcess, '_dataReceived') and
                    callable(getattr(self._shellProcess, '_dataReceived'))):
                self._shellProcess._dataReceived()
        except Exception:
            pass


class SessionGroup(QObject):
    """
    提供分为主从会话的会话组 - 对应C++: class SessionGroup : public QObject
    
    主会话中的活动可以传播到组内的所有会话。
    传播的活动类型和传播方法由masterMode()标志控制。
    """

    class MasterMode(IntEnum):
        """主模式枚举 - 对应C++: enum MasterMode"""
        CopyInputToAll = 1  # 主会话中的任何输入按键都发送到组中的所有会话

    def __init__(self, parent: Optional[QObject] = None):
        """构造空会话组 - 对应C++: SessionGroup::SessionGroup()"""
        super().__init__(parent)
        # 对应C++: QHash<Session *,bool> _sessions; 和 int _masterMode;
        self._sessions: Dict[Session, bool] = {}  # 映射会话到其主状态
        self._masterMode = 0  # 对应C++: _masterMode(0)

    def __del__(self):
        """
        销毁会话组并移除主从会话之间的所有连接 - 对应C++: SessionGroup::~SessionGroup()
        """
        try:
            # 对应C++: connectAll(false);
            self.connectAll(False)
        except Exception:
            # 析构函数中忽略异常
            pass

    def addSession(self, session: Session):
        """向组中添加会话 - 对应C++: void addSession(Session *)"""
        # 对应C++: _sessions.insert(session, false);
        self._sessions[session] = False

        # 对应C++: QListIterator<Session *> masterIter(masters());
        # while (masterIter.hasNext()) { connectPair(masterIter.next(), session); }
        for master in self.masters():
            self.connectPair(master, session)

    def removeSession(self, session: Session):
        """从组中移除会话 - 对应C++: void removeSession(Session *)"""
        # 对应C++: setMasterStatus(session, false);
        self.setMasterStatus(session, False)

        # 对应C++: QListIterator<Session *> masterIter(masters());
        # while (masterIter.hasNext()) { disconnectPair(masterIter.next(), session); }
        for master in self.masters():
            self.disconnectPair(master, session)

        # 对应C++: _sessions.remove(session);
        if session in self._sessions:
            del self._sessions[session]

    def sessions(self) -> List[Session]:
        """返回组中当前的会话列表 - 对应C++: QList<Session *> sessions() const"""
        # 对应C++: return _sessions.keys();
        return list(self._sessions.keys())

    def setMasterStatus(self, session: Session, master: bool):
        """
        设置特定会话在组中是否为主会话 - 对应C++: void setMasterStatus(Session *, bool)
        
        组的主会话中的更改或活动可能会传播到组中的所有会话，
        取决于当前的masterMode()
        
        @param session 应更改主状态的会话
        @param master True使此会话成为主会话，否则为False
        """
        if session not in self._sessions:
            return

        # 对应C++: bool wasMaster = _sessions[session];
        was_master = self._sessions[session]
        self._sessions[session] = master

        if was_master == master:
            return

        # 对应C++版本的连接逻辑
        for other in self._sessions.keys():
            if other != session:
                if master:
                    self.connectPair(session, other)
                else:
                    self.disconnectPair(session, other)

    def masterStatus(self, session: Session) -> bool:
        """返回会话的主状态 - 对应C++: bool masterStatus(Session *) const"""
        # 对应C++: return _sessions[session];
        return self._sessions.get(session, False)

    def setMasterMode(self, mode: int):
        """
        指定组的主会话中的哪些活动传播到组中的所有会话 - 对应C++: void setMasterMode(int)
        
        @param mode MasterMode标志的位或
        """
        # 对应C++: _masterMode = mode; connectAll(false); connectAll(true);
        self._masterMode = mode
        self.connectAll(False)
        self.connectAll(True)

    def masterMode(self) -> int:
        """
        返回此组的活动MasterMode标志的位或 - 对应C++: int masterMode() const
        
        参见setMasterMode()
        """
        # 对应C++: return _masterMode;
        return self._masterMode

    def masters(self) -> List[Session]:
        """获取主会话列表 - 对应C++: QList<Session *> masters() const"""
        # 对应C++: return _sessions.keys(true);
        return [session for session, is_master in self._sessions.items() if is_master]

    def connectAll(self, connect: bool):
        """连接或断开所有会话 - 对应C++: void connectAll(bool)"""
        # 对应C++版本的双重循环逻辑
        masters_list = self.masters()

        for master in masters_list:
            for other in self._sessions.keys():
                if other != master:
                    if connect:
                        self.connectPair(master, other)
                    else:
                        self.disconnectPair(master, other)

    def connectPair(self, master: Session, other: Session):
        """连接主从会话对 - 对应C++: void connectPair(Session *, Session *) const"""
        # 对应C++版本的调试和连接逻辑
        if self._masterMode & SessionGroup.MasterMode.CopyInputToAll:
            print(f"Connection session {master.nameTitle()} to {other.nameTitle()}")

            master_emulation = master.emulation()
            other_emulation = other.emulation()

            if master_emulation and other_emulation:
                try:
                    # 对应C++: connect(master->emulation(), SIGNAL(sendData(const char *,int)), 
                    #                 other->emulation(), SLOT(sendString(const char *,int)));
                    if hasattr(master_emulation, 'sendData') and hasattr(other_emulation, 'sendString'):
                        master_emulation.sendData.connect(other_emulation.sendString)
                except Exception as e:
                    print(f"Warning: 连接会话对失败: {e}")

    def disconnectPair(self, master: Session, other: Session):
        """断开主从会话对 - 对应C++: void disconnectPair(Session *, Session *) const"""
        # 对应C++版本的调试和断开逻辑
        if self._masterMode & SessionGroup.MasterMode.CopyInputToAll:
            print(f"Disconnecting session {master.nameTitle()} from {other.nameTitle()}")

            master_emulation = master.emulation()
            other_emulation = other.emulation()

            if master_emulation and other_emulation:
                try:
                    # 对应C++: disconnect(master->emulation(), SIGNAL(sendData(const char *,int)), 
                    #                    other->emulation(), SLOT(sendString(const char *,int)));
                    if hasattr(master_emulation, 'sendData') and hasattr(other_emulation, 'sendString'):
                        master_emulation.sendData.disconnect(other_emulation.sendString)
                except Exception as e:
                    print(f"Warning: 断开会话对失败: {e}")


# =============================================================================
# 模块级别的注释 - 对应C++文件末尾
# =============================================================================

# 对应C++文件末尾的注释: //#include "moc_Session.cpp"
# 在Python中，我们不需要moc文件，PySide6会自动处理信号槽

__all__ = ['Session', 'SessionGroup', 'NOTIFYNORMAL', 'NOTIFYBELL', 'NOTIFYACTIVITY', 'NOTIFYSILENCE']
