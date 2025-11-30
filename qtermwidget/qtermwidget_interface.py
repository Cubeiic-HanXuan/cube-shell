#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
QTermWidget接口定义
从qtermwidget_interface.h转换而来

Copyright (C) 2022 Francesc Martinez (info@francescmm.com)
转换为Python PySide6版本
"""

from enum import IntEnum
from typing import List

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont, QKeyEvent, QAction

# 接口ID常量
QTERMWIDGET_INTERFACE_IID = "lxqt.qtermwidget.QTermWidgetInterface/1.5"

# 添加缺失的常量定义 - 对应C++的宏定义
DEFAULT_FONT_FAMILY = "Monospace"  # 默认字体家族
STEP_ZOOM = 1  # 缩放步长


class ScrollBarPosition(IntEnum):
    """
    描述滚动条在显示组件中的位置
    
    对应C++: enum ScrollBarPosition
    """
    # 不显示滚动条
    NoScrollBar = 0
    # 在显示器左侧显示滚动条
    ScrollBarLeft = 1
    # 在显示器右侧显示滚动条
    ScrollBarRight = 2


class QTermWidgetInterface:
    """
    QTermWidget接口类 - 定义终端部件的抽象接口
    
    对应C++: class QTermWidgetInterface
    
    注意：这是一个接口类，所有方法应该在子类中实现
    """

    def setTerminalSizeHint(self, enabled: bool) -> None:
        """
        设置终端尺寸提示
        
        Args:
            enabled: 是否启用尺寸提示
        """
        raise NotImplementedError("Subclass must implement setTerminalSizeHint")

    def terminalSizeHint(self) -> bool:
        """
        获取终端尺寸提示状态
        
        Returns:
            bool: 是否启用尺寸提示
        """
        raise NotImplementedError("Subclass must implement terminalSizeHint")

    def startShellProgram(self) -> None:
        """启动shell程序"""
        raise NotImplementedError("Subclass must implement startShellProgram")

    def startTerminalTeletype(self) -> None:
        """
        启动终端电传打字机模式
        并重定向数据给外部接收者
        """
        raise NotImplementedError("Subclass must implement startTerminalTeletype")

    def getShellPID(self) -> int:
        """
        获取shell进程ID
        
        Returns:
            int: 进程ID
        """
        raise NotImplementedError("Subclass must implement getShellPID")

    def getForegroundProcessId(self) -> int:
        """
        获取前台进程ID
        
        Returns:
            int: 前台进程ID
        """
        raise NotImplementedError("Subclass must implement getForegroundProcessId")

    def changeDir(self, dir: str) -> None:
        """
        改变工作目录
        
        Args:
            dir: 目录路径
        """
        raise NotImplementedError("Subclass must implement changeDir")

    def setTerminalFont(self, font: QFont) -> None:
        """
        设置终端字体
        
        Args:
            font: 字体对象
        """
        raise NotImplementedError("Subclass must implement setTerminalFont")

    def getTerminalFont(self) -> QFont:
        """
        获取终端字体
        
        Returns:
            QFont: 字体对象
        """
        raise NotImplementedError("Subclass must implement getTerminalFont")

    def setTerminalOpacity(self, level: float) -> None:
        """
        设置终端透明度
        
        Args:
            level: 透明度级别 (0.0-1.0)
        """
        raise NotImplementedError("Subclass must implement setTerminalOpacity")

    def setTerminalBackgroundImage(self, backgroundImage: str) -> None:
        """
        设置终端背景图片
        
        Args:
            backgroundImage: 背景图片路径
        """
        raise NotImplementedError("Subclass must implement setTerminalBackgroundImage")

    def setTerminalBackgroundMode(self, mode: int) -> None:
        """
        设置终端背景模式
        
        Args:
            mode: 背景模式
        """
        raise NotImplementedError("Subclass must implement setTerminalBackgroundMode")

    def setEnvironment(self, environment: List[str]) -> None:
        """
        设置环境变量
        
        Args:
            environment: 环境变量列表
        """
        raise NotImplementedError("Subclass must implement setEnvironment")

    def setShellProgram(self, program: str) -> None:
        """
        设置shell程序
        
        Args:
            program: shell程序路径
        """
        raise NotImplementedError("Subclass must implement setShellProgram")

    def setWorkingDirectory(self, dir: str) -> None:
        """
        设置工作目录
        
        Args:
            dir: 工作目录路径
        """
        raise NotImplementedError("Subclass must implement setWorkingDirectory")

    def workingDirectory(self) -> str:
        """
        获取工作目录
        
        Returns:
            str: 工作目录路径
        """
        raise NotImplementedError("Subclass must implement workingDirectory")

    def setArgs(self, args: List[str]) -> None:
        """
        设置程序参数
        
        Args:
            args: 参数列表
        """
        raise NotImplementedError("Subclass must implement setArgs")

    def setColorScheme(self, name: str) -> None:
        """
        设置颜色方案
        
        Args:
            name: 颜色方案名称
        """
        raise NotImplementedError("Subclass must implement setColorScheme")

    def getAvailableColorSchemes(self) -> List[str]:
        """
        获取可用的颜色方案
        
        Returns:
            List[str]: 颜色方案列表
        """
        raise NotImplementedError("Subclass must implement getAvailableColorSchemes")

    def setHistorySize(self, lines: int) -> None:
        """
        设置历史记录大小
        
        Args:
            lines: 行数，0=无历史，<0=无限历史
        """
        raise NotImplementedError("Subclass must implement setHistorySize")

    def historySize(self) -> int:
        """
        获取历史记录大小
        
        Returns:
            int: 历史记录行数
        """
        raise NotImplementedError("Subclass must implement historySize")

    def setScrollBarPosition(self, position: ScrollBarPosition) -> None:
        """
        设置滚动条位置
        
        Args:
            position: 滚动条位置
        """
        raise NotImplementedError("Subclass must implement setScrollBarPosition")

    def scrollToEnd(self) -> None:
        """滚动到末尾"""
        raise NotImplementedError("Subclass must implement scrollToEnd")

    def sendText(self, text: str) -> None:
        """
        发送文本到终端
        
        Args:
            text: 要发送的文本
        """
        raise NotImplementedError("Subclass must implement sendText")

    def sendKeyEvent(self, e: QKeyEvent) -> None:
        """
        发送键盘事件到终端
        
        Args:
            e: 键盘事件
        """
        raise NotImplementedError("Subclass must implement sendKeyEvent")

    def setFlowControlEnabled(self, enabled: bool) -> None:
        """
        设置流控制是否启用
        
        Args:
            enabled: 是否启用流控制
        """
        raise NotImplementedError("Subclass must implement setFlowControlEnabled")

    def flowControlEnabled(self) -> bool:
        """
        获取流控制状态
        
        Returns:
            bool: 是否启用流控制
        """
        raise NotImplementedError("Subclass must implement flowControlEnabled")

    def setFlowControlWarningEnabled(self, enabled: bool) -> None:
        """
        设置流控制警告是否启用
        
        Args:
            enabled: 是否启用警告
        """
        raise NotImplementedError("Subclass must implement setFlowControlWarningEnabled")

    def keyBindings(self) -> str:
        """
        获取当前键绑定
        
        Returns:
            str: 键绑定名称
        """
        raise NotImplementedError("Subclass must implement keyBindings")

    def setMotionAfterPasting(self, motion: int) -> None:
        """
        设置粘贴后的光标移动方式
        
        Args:
            motion: 移动方式
        """
        raise NotImplementedError("Subclass must implement setMotionAfterPasting")

    def historyLinesCount(self) -> int:
        """
        获取历史记录行数
        
        Returns:
            int: 历史记录行数
        """
        raise NotImplementedError("Subclass must implement historyLinesCount")

    def screenColumnsCount(self) -> int:
        """
        获取屏幕列数
        
        Returns:
            int: 屏幕列数
        """
        raise NotImplementedError("Subclass must implement screenColumnsCount")

    def screenLinesCount(self) -> int:
        """
        获取屏幕行数
        
        Returns:
            int: 屏幕行数
        """
        raise NotImplementedError("Subclass must implement screenLinesCount")

    def setSelectionStart(self, row: int, column: int) -> None:
        """
        设置选择开始位置
        
        Args:
            row: 行号
            column: 列号
        """
        raise NotImplementedError("Subclass must implement setSelectionStart")

    def setSelectionEnd(self, row: int, column: int) -> None:
        """
        设置选择结束位置
        
        Args:
            row: 行号
            column: 列号
        """
        raise NotImplementedError("Subclass must implement setSelectionEnd")

    def getSelectionStart(self, row: int, column: int) -> None:
        """
        获取选择开始位置 (通过引用参数返回)
        
        Args:
            row: 行号引用
            column: 列号引用
        """
        raise NotImplementedError("Subclass must implement getSelectionStart")

    def getSelectionEnd(self, row: int, column: int) -> None:
        """
        获取选择结束位置 (通过引用参数返回)
        
        Args:
            row: 行号引用
            column: 列号引用
        """
        raise NotImplementedError("Subclass must implement getSelectionEnd")

    def selectedText(self, preserveLineBreaks: bool = True) -> str:
        """
        获取选中的文本
        
        Args:
            preserveLineBreaks: 是否保留换行符
            
        Returns:
            str: 选中的文本
        """
        raise NotImplementedError("Subclass must implement selectedText")

    def setMonitorActivity(self, enabled: bool) -> None:
        """
        设置活动监控
        
        Args:
            enabled: 是否启用监控
        """
        raise NotImplementedError("Subclass must implement setMonitorActivity")

    def setMonitorSilence(self, enabled: bool) -> None:
        """
        设置静默监控
        
        Args:
            enabled: 是否启用监控
        """
        raise NotImplementedError("Subclass must implement setMonitorSilence")

    def setSilenceTimeout(self, seconds: int) -> None:
        """
        设置静默超时时间
        
        Args:
            seconds: 超时秒数
        """
        raise NotImplementedError("Subclass must implement setSilenceTimeout")

    def filterActions(self, position: QPoint) -> List[QAction]:
        """
        获取指定位置的过滤器动作
        
        Args:
            position: 位置
            
        Returns:
            List[QAction]: 动作列表
        """
        raise NotImplementedError("Subclass must implement filterActions")

    def getPtySlaveFd(self) -> int:
        """
        获取PTY从文件描述符
        
        Returns:
            int: 文件描述符
        """
        raise NotImplementedError("Subclass must implement getPtySlaveFd")

    def setBlinkingCursor(self, blink: bool) -> None:
        """
        设置光标是否闪烁
        
        Args:
            blink: 是否闪烁
        """
        raise NotImplementedError("Subclass must implement setBlinkingCursor")

    def setBidiEnabled(self, enabled: bool) -> None:
        """
        设置双向文本是否启用
        
        Args:
            enabled: 是否启用
        """
        raise NotImplementedError("Subclass must implement setBidiEnabled")

    def isBidiEnabled(self) -> bool:
        """
        获取双向文本状态
        
        Returns:
            bool: 是否启用双向文本
        """
        raise NotImplementedError("Subclass must implement isBidiEnabled")

    def setAutoClose(self, enabled: bool) -> None:
        """
        设置自动关闭
        
        Args:
            enabled: 是否自动关闭
        """
        raise NotImplementedError("Subclass must implement setAutoClose")

    def title(self) -> str:
        """
        获取标题
        
        Returns:
            str: 标题
        """
        raise NotImplementedError("Subclass must implement title")

    def icon(self) -> str:
        """
        获取图标
        
        Returns:
            str: 图标名称
        """
        raise NotImplementedError("Subclass must implement icon")

    def isTitleChanged(self) -> bool:
        """
        检查标题是否改变
        
        Returns:
            bool: 标题是否改变
        """
        raise NotImplementedError("Subclass must implement isTitleChanged")

    def bracketText(self, text: str) -> str:
        """
        处理括号文本
        
        在C++版本中，这个方法使用引用参数 (QString& text)
        在Python中，我们返回处理后的文本以保持函数式编程风格
        
        Args:
            text: 输入文本
            
        Returns:
            str: 处理后的文本
            
        注意：C++版本使用void bracketText(QString& text)
        """
        raise NotImplementedError("Subclass must implement bracketText")

    def disableBracketedPasteMode(self, disable: bool) -> None:
        """
        禁用括号粘贴模式
        
        Args:
            disable: 是否禁用
        """
        raise NotImplementedError("Subclass must implement disableBracketedPasteMode")

    def bracketedPasteModeIsDisabled(self) -> bool:
        """
        检查括号粘贴模式是否禁用
        
        Returns:
            bool: 是否禁用
        """
        raise NotImplementedError("Subclass must implement bracketedPasteModeIsDisabled")

    def setMargin(self, margin: int) -> None:
        """
        设置边距
        
        Args:
            margin: 边距大小
        """
        raise NotImplementedError("Subclass must implement setMargin")

    def getMargin(self) -> int:
        """
        获取边距
        
        Returns:
            int: 边距大小
        """
        raise NotImplementedError("Subclass must implement getMargin")

    def setDrawLineChars(self, drawLineChars: bool) -> None:
        """
        设置是否绘制线条字符
        
        Args:
            drawLineChars: 是否绘制
        """
        raise NotImplementedError("Subclass must implement setDrawLineChars")

    def setBoldIntense(self, boldIntense: bool) -> None:
        """
        设置粗体强度
        
        Args:
            boldIntense: 是否使用粗体强度
        """
        raise NotImplementedError("Subclass must implement setBoldIntense")

    def setConfirmMultilinePaste(self, confirmMultilinePaste: bool) -> None:
        """
        设置多行粘贴确认
        
        Args:
            confirmMultilinePaste: 是否确认多行粘贴
        """
        raise NotImplementedError("Subclass must implement setConfirmMultilinePaste")

    def setTrimPastedTrailingNewlines(self, trimPastedTrailingNewlines: bool) -> None:
        """
        设置修剪粘贴的尾随换行符
        
        Args:
            trimPastedTrailingNewlines: 是否修剪
        """
        raise NotImplementedError("Subclass must implement setTrimPastedTrailingNewlines")

    def wordCharacters(self) -> str:
        """
        获取单词字符
        
        Returns:
            str: 单词字符
        """
        raise NotImplementedError("Subclass must implement wordCharacters")

    def setWordCharacters(self, chars: str) -> None:
        """
        设置单词字符
        
        Args:
            chars: 单词字符
        """
        raise NotImplementedError("Subclass must implement setWordCharacters")

    def createWidget(self, startnow: int) -> 'QTermWidgetInterface':
        """
        创建新的部件实例
        
        Args:
            startnow: 是否立即启动
            
        Returns:
            QTermWidgetInterface: 新的部件实例
        """
        raise NotImplementedError("Subclass must implement createWidget")

    def autoHideMouseAfter(self, delay: int) -> None:
        """
        设置鼠标自动隐藏延迟
        
        Args:
            delay: 延迟时间(毫秒)
        """
        raise NotImplementedError("Subclass must implement autoHideMouseAfter")


# 接口ID常量
QTERMWIDGET_INTERFACE_IID = "lxqt.qtermwidget.QTermWidgetInterface/1.5"
