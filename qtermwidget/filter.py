"""
Filter模块 - 从Konsole终端模拟器转换而来

这个模块提供了文本过滤器系统，用于在终端文本中识别和处理特定模式
如URL、链接、标记等，并创建可交互的热点。

原始文件：
- Filter.h
- Filter.cpp

版权信息：
Copyright 2007-2008 by Robert Knight <robertknight@gmail.com>

转换为Python PySide6版本
"""

import re
from abc import abstractmethod
from enum import Enum
from typing import List, Optional, Dict

from PySide6.QtCore import QObject, Signal, QUrl, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from qtermwidget.character import Character, LineProperty, LINE_DEFAULT, LINE_WRAPPED
from qtermwidget.wcwidth import string_width


class Filter(QObject):
    """
    过滤器处理文本块，寻找特定模式（如URL或关键词列表）
    并将匹配过滤器模式的区域标记为'热点'。
    
    每个热点都有一个关联的类型标识符（如链接或高亮部分）和一个动作。
    当用户在热点区域执行某些活动（如鼠标点击）时，应该调用热点的activate()方法。
    
    对应C++: class Filter : public QObject
    """
    
    class HotSpot:
        """
        表示匹配特定过滤器模式的文本区域。
        
        每个热点都有一个关联的类型标识符和动作。
        当用户在热点区域执行活动时，热点的activate()方法会被调用。
        
        对应C++: class Filter::HotSpot
        """
        
        class Type(Enum):
            """热点类型枚举"""
            NotSpecified = 0   # 未指定类型 - C++风格命名
            Link = 1           # 可点击链接
            Marker = 2         # 标记
            Highlight = 3      # 自定义高亮 (新增)

        def __init__(self, startLine: int, startColumn: int, endLine: int, endColumn: int):
            """
            构造一个覆盖从(startLine, startColumn)到(endLine, endColumn)区域的热点
            
            Args:
                startLine: 起始行 - C++风格参数命名
                startColumn: 起始列
                endLine: 结束行  
                endColumn: 结束列
                
            对应C++: HotSpot(int startLine, int startColumn, int endLine, int endColumn)
            """
            self._startLine = startLine
            self._startColumn = startColumn
            self._endLine = endLine
            self._endColumn = endColumn
            self._type = self.Type.NotSpecified
            self._foregroundColor = None
            self._backgroundColor = None
        
        def foregroundColor(self):
            """返回前景色 (用于 Highlight 类型)"""
            return self._foregroundColor
            
        def backgroundColor(self):
            """返回背景色 (用于 Highlight 类型)"""
            return self._backgroundColor
            
        def setColors(self, fg=None, bg=None):
            """设置颜色 (用于 Highlight 类型)"""
            self._foregroundColor = fg
            self._backgroundColor = bg
            self.setType(self.Type.Highlight)
        
        def startLine(self) -> int:
            """返回热点区域开始的行 - C++风格方法命名"""
            return self._startLine
        
        def endLine(self) -> int:
            """返回热点区域结束的行"""
            return self._endLine
        
        def startColumn(self) -> int:
            """返回热点区域在起始行的开始列"""
            return self._startColumn
        
        def endColumn(self) -> int:
            """返回热点区域在结束行的结束列"""
            return self._endColumn
        
        def type(self) -> 'Filter.HotSpot.Type':
            """返回热点类型"""
            return self._type
        
        def setType(self, hotType: 'Filter.HotSpot.Type'):
            """设置热点类型 - C++风格方法命名"""
            self._type = hotType
        
        @abstractmethod
        def activate(self, action: str = ""):
            """
            触发与热点关联的动作
            
            Args:
                action: 要触发的动作，通常为空（执行默认动作）或actions()列表中的对象名
                
            对应C++: virtual void activate(const QString& action = QString()) = 0
            """
            pass
        
        def actions(self) -> List[QAction]:
            """
            返回与热点关联的动作列表，可用于菜单或工具栏
            
            Returns:
                QAction列表
                
            对应C++: virtual QList<QAction*> actions()
            """
            return []
    
    def __init__(self):
        """
        构造新的过滤器
        
        对应C++: Filter()
        """
        super().__init__()
        # 使用QMultiHash的等价结构：Dict[int, List[HotSpot]]
        self._hotspots: Dict[int, List[Filter.HotSpot]] = {}  # line -> list of hotspots
        self._hotspotList: List[Filter.HotSpot] = []
        self._linePositions: Optional[List[int]] = None
        self._buffer: Optional[str] = None
    
    @abstractmethod
    def process(self):
        """
        使过滤器处理当前在其内部缓冲区中的文本块
        
        对应C++: virtual void process() = 0
        """
        pass
    
    def reset(self):
        """
        清空过滤器的内部缓冲区并将行计数重置为0。
        删除所有热点。
        
        对应C++: void reset()
        """
        # C++版本: qDeleteAll(_hotspotList); _hotspots.clear(); _hotspotList.clear();
        self._hotspots.clear()
        self._hotspotList.clear()
    
    def hotSpotAt(self, line: int, column: int) -> Optional['Filter.HotSpot']:
        """
        返回覆盖给定行和列的热点，如果没有热点覆盖该区域则返回None
        
        Args:
            line: 行号
            column: 列号
            
        Returns:
            热点对象或None
            
        对应C++: HotSpot* hotSpotAt(int line, int column) const
        """
        if line not in self._hotspots:
            return None
        
        # 模拟C++的QListIterator<HotSpot*> spotIter(_hotspots.values(line))
        for spot in self._hotspots[line]:
            if spot.startLine() == line and spot.startColumn() > column:
                continue
            if spot.endLine() == line and spot.endColumn() < column:
                continue
            return spot
        
        return None
    
    def hotSpots(self) -> List['Filter.HotSpot']:
        """
        返回过滤器识别的热点列表
        
        Returns:
            热点列表
            
        对应C++: QList<HotSpot*> hotSpots() const
        """
        return self._hotspotList.copy()
    
    def hotSpotsAtLine(self, line: int) -> List['Filter.HotSpot']:
        """
        返回过滤器在给定行识别的热点列表
        
        Args:
            line: 行号
            
        Returns:
            该行的热点列表
            
        对应C++: QList<HotSpot*> hotSpotsAtLine(int line) const
        """
        return self._hotspots.get(line, []).copy()
    
    def setBuffer(self, buffer: str, linePositions: List[int]):
        """
        设置缓冲区和行位置
        
        Args:
            buffer: 文本缓冲区
            linePositions: 行位置列表
            
        对应C++: void setBuffer(const QString* buffer, const QList<int>* linePositions)
        """
        self._buffer = buffer
        self._linePositions = linePositions
    
    def addHotSpot(self, spot: 'Filter.HotSpot'):
        """
        向列表添加新热点
        
        Args:
            spot: 热点对象
            
        对应C++: void addHotSpot(HotSpot*)
        """
        self._hotspotList.append(spot)
        
        # C++版本的逻辑：for (int line = spot->startLine() ; line <= spot->endLine() ; line++)
        for line in range(spot.startLine(), spot.endLine() + 1):
            if line not in self._hotspots:
                self._hotspots[line] = []
            self._hotspots[line].append(spot)
    
    def buffer(self) -> Optional[str]:
        """
        返回内部缓冲区
        
        Returns:
            缓冲区字符串
            
        对应C++: const QString* buffer()
        """
        return self._buffer
    
    def getLineColumn(self, position: int) -> tuple[int, int]:
        """
        将buffer()中的字符位置转换为行和列
        
        Args:
            position: 字符位置
            
        Returns:
            (行号, 列号)元组
            
        对应C++: void getLineColumn(int position, int& startLine, int& startColumn)
        """
        if not self._linePositions or not self._buffer:
            return 0, 0
        
        # 精确复制C++逻辑
        for i in range(len(self._linePositions)):
            if i == len(self._linePositions) - 1:
                nextLine = len(self._buffer) + 1
            else:
                nextLine = self._linePositions[i + 1]
            
            if self._linePositions[i] <= position < nextLine:
                startLine = i
                text_segment = self._buffer[self._linePositions[i]:position]
                startColumn = string_width(text_segment)
                return startLine, startColumn
        
        return 0, 0


class RegExpFilter(Filter):
    """
    搜索匹配正则表达式的文本部分并为其创建RegExpFilter::HotSpot实例的过滤器。
    
    子类可以重新实现newHotSpot()来在找到正则表达式匹配时返回自定义热点类型。
    
    对应C++: class RegExpFilter : public Filter
    """
    
    class HotSpot(Filter.HotSpot):
        """
        RegExpFilter创建的热点类型。
        可以使用capturedTexts()方法找到过滤器正则表达式匹配的文本。
        
        对应C++: class RegExpFilter::HotSpot : public Filter::HotSpot
        """
        
        def __init__(self, startLine: int, startColumn: int, endLine: int, endColumn: int):
            """
            构造RegExp热点
            
            对应C++: HotSpot(int startLine, int startColumn, int endLine, int endColumn)
            """
            super().__init__(startLine, startColumn, endLine, endColumn)
            self.setType(Filter.HotSpot.Type.Marker)
            self._capturedTexts: List[str] = []
        
        def activate(self, action: str = ""):
            """
            激活热点（默认实现为空）
            
            对应C++: void activate(const QString& action = QString()) override
            """
            pass
        
        def setCapturedTexts(self, texts: List[str]):
            """
            设置与此热点关联的捕获文本
            
            Args:
                texts: 捕获的文本列表
                
            对应C++: void setCapturedTexts(const QStringList& texts)
            """
            self._capturedTexts = texts.copy()
        
        def capturedTexts(self) -> List[str]:
            """
            返回过滤器匹配正则表达式时找到的文本
            
            Returns:
                捕获的文本列表
                
            对应C++: QStringList capturedTexts() const
            """
            return self._capturedTexts.copy()
    
    def __init__(self):
        """
        构造新的正则表达式过滤器
        
        对应C++: RegExpFilter()
        """
        super().__init__()
        self._searchText: Optional[re.Pattern] = None
    
    def setRegExp(self, regExp: re.Pattern):
        """
        设置过滤器在文本块中搜索的正则表达式
        
        Args:
            regExp: 编译后的正则表达式模式
            
        对应C++: void setRegExp(const QRegularExpression& text)
        """
        self._searchText = regExp
    
    def regExp(self) -> Optional[re.Pattern]:
        """
        返回过滤器在文本块中搜索的正则表达式
        
        Returns:
            正则表达式模式
            
        对应C++: QRegularExpression regExp() const
        """
        return self._searchText

    def newHotSpot(self, startLine: int, startColumn: int, 
                   endLine: int, endColumn: int) -> 'RegExpFilter.HotSpot':
        """
        当遇到正则表达式匹配时调用。子类应重新实现此方法以返回自定义热点类型
        
        Args:
            startLine: 起始行
            startColumn: 起始列
            endLine: 结束行
            endColumn: 结束列
            
        Returns:
            新的热点实例
            
        对应C++: virtual RegExpFilter::HotSpot* newHotSpot(int,int,int,int)
        """
        return RegExpFilter.HotSpot(startLine, startColumn, endLine, endColumn)

    def process(self):
        """
        处理文本缓冲区，查找正则表达式匹配
        
        对应C++: void process() override
        """
        if not self._searchText or not self.buffer():
            return

        text = self.buffer()
        for match in self._searchText.finditer(text):
            # 获取匹配位置
            start = match.start()
            end = match.end()
            
            # 转换为行/列
            startLine, startColumn = self.getLineColumn(start)
            endLine, endColumn = self.getLineColumn(end)
            
            # 创建热点
            hotspot = self.newHotSpot(startLine, startColumn, endLine, endColumn)
            
            # 设置捕获文本
            captured = [match.group(i) for i in range(match.lastindex + 1)] if match.lastindex is not None else [match.group(0)]
            if isinstance(hotspot, RegExpFilter.HotSpot):
                hotspot.setCapturedTexts(captured)
            
            self.addHotSpot(hotspot)
    
class HighlightFilter(RegExpFilter):
    """
    自定义高亮过滤器，用于根据正则表达式高亮显示文本
    """
    
    def __init__(self, regex_pattern, fg_color=None, bg_color=None):
        super().__init__()
        self.setRegExp(re.compile(regex_pattern))
        self._fg_color = fg_color
        self._bg_color = bg_color

    def newHotSpot(self, startLine, startColumn, endLine, endColumn):
        hotspot = super().newHotSpot(startLine, startColumn, endLine, endColumn)
        # 设置颜色属性
        hotspot.setColors(self._fg_color, self._bg_color)
        return hotspot
        
class PermissionHighlightFilter(RegExpFilter):
    """
    权限字符串高亮过滤器 (drwxr-xr-x)
    d -> 紫色, r -> 蓝色, w -> 黄色, x -> 红色
    """
    
    def __init__(self):
        super().__init__()
        # 匹配像 drwxr-xr-x. 这样的权限字符串
        self.setRegExp(re.compile(r'[-d](?:[-r][-w][-x]){3}[\.\+]?'))
        
    def newHotSpot(self, startLine, startColumn, endLine, endColumn):
        # 创建一个普通热点，但在 paintEvent 中我们会特殊处理它
        hotspot = super().newHotSpot(startLine, startColumn, endLine, endColumn)
        hotspot.setColors(None, None) # 不设置统一颜色，而是使用特殊标记
        hotspot.setType(Filter.HotSpot.Type.Highlight)
        # 我们利用 type 来标记这是一个权限字符串，在绘制时再细分颜色
        # 但由于 Filter 架构的限制，我们可能需要扩展 HotSpot 或者在 paintEvent 中重新解析
        # 为了简化，我们这里创建一个特殊的子类热点
        return PermissionHotSpot(startLine, startColumn, endLine, endColumn)

class PermissionHotSpot(RegExpFilter.HotSpot):
    """权限字符串专用热点"""
    def __init__(self, startLine, startColumn, endLine, endColumn):
        super().__init__(startLine, startColumn, endLine, endColumn)
        self.setType(Filter.HotSpot.Type.Highlight)


class FilterObject(QObject):
    """
    辅助类用于处理过滤器信号
    
    对应C++: class FilterObject : public QObject
    """
    
    activated = Signal(QUrl, bool)  # (url, fromContextMenu)
    
    def __init__(self, hotSpot: Filter.HotSpot):
        """
        构造FilterObject
        
        Args:
            hotSpot: 关联的热点
        """
        super().__init__()
        self._filter = hotSpot  # C++版本使用_filter命名
    
    def emitActivated(self, url: QUrl, fromContextMenu: bool):
        """
        发射activated信号
        
        Args:
            url: URL
            fromContextMenu: 是否来自上下文菜单
            
        对应C++: void emitActivated(const QUrl& url, bool fromContextMenu)
        """
        self.activated.emit(url, fromContextMenu)
    
    @Slot()
    def activate(self):
        """
        激活热点
        
        对应C++: public slots: void activate()
        """
        sender = self.sender()
        actionName = sender.objectName() if sender else ""
        self._filter.activate(actionName)


class UrlFilter(RegExpFilter):
    """
    匹配文本块中URL的过滤器
    
    对应C++: class UrlFilter : public RegExpFilter
    """
    
    activated = Signal(QUrl, bool)  # (url, fromContextMenu)
    
    # 正则表达式常量 - 与C++完全匹配
    # C++: "(www\\.(?!\\.)|[a-z][a-z0-9+.-]*://)[^\\s<>'\"]+[^!,\\.\\s<>'\"\\]]"
    FullUrlRegExp = re.compile(r"(www\.(?!\.)|[a-z][a-z0-9+.-]*://)[^\s<>'\"]+[^!,\.\s<>'\"\\]")
    # C++: "\\b(\\w|\\.|-)+@(\\w|\\.|-)+\\.\\w+\\b"  
    EmailAddressRegExp = re.compile(r"\b(\w|\.|-)+@(\w|\.|-)+\.\w+\b")
    # 组合正则表达式：匹配完整URL或邮件地址
    CompleteUrlRegExp = re.compile(r"((www\.(?!\.)|[a-z][a-z0-9+.-]*://)[^\s<>'\"]+[^!,\.\s<>'\"\\]|\b(\w|\.|-)+@(\w|\.|-)+\.\w+\b)")
    
    class HotSpot(RegExpFilter.HotSpot):
        """
        UrlFilter实例创建的热点类型。
        调用activate()方法时会在给定URL上打开网页浏览器。
        
        对应C++: class UrlFilter::HotSpot : public RegExpFilter::HotSpot
        """
        
        class UrlType(Enum):
            """URL类型枚举"""
            StandardUrl = 0    # C++风格命名
            Email = 1
            Unknown = 2
        
        def __init__(self, startLine: int, startColumn: int, endLine: int, endColumn: int):
            """
            构造URL热点
            
            对应C++: HotSpot(int startLine, int startColumn, int endLine, int endColumn)
            """
            super().__init__(startLine, startColumn, endLine, endColumn)
            self.setType(Filter.HotSpot.Type.Link)
            self._urlObject = FilterObject(self)
        
        def urlType(self) -> 'UrlFilter.HotSpot.UrlType':
            """
            确定URL类型
            
            Returns:
                URL类型
                
            对应C++: UrlType urlType() const
            """
            if not self.capturedTexts():
                return self.UrlType.Unknown
            
            url = self.capturedTexts()[0]
            
            if UrlFilter.FullUrlRegExp.search(url):
                return self.UrlType.StandardUrl
            elif UrlFilter.EmailAddressRegExp.search(url):
                return self.UrlType.Email
            else:
                return self.UrlType.Unknown
        
        def activate(self, actionName: str = ""):
            """
            在当前URL打开网页浏览器
            
            Args:
                actionName: 动作名称
                
            对应C++: void activate(const QString& action = QString()) override
            """
            if not self.capturedTexts():
                return
            
            url = self.capturedTexts()[0]
            kind = self.urlType()
            
            if actionName == "copy-action":
                QApplication.clipboard().setText(url)
                return
            
            if not actionName or actionName in ["open-action", "click-action"]:
                if kind == self.UrlType.StandardUrl:
                    if "://" not in url:
                        url = "http://" + url
                elif kind == self.UrlType.Email:
                    url = "mailto:" + url
                
                # 使用StrictMode解析URL，如C++版本
                qurl = QUrl()
                qurl.setUrl(url, QUrl.ParsingMode.StrictMode)
                self._urlObject.emitActivated(qurl, actionName != "click-action")
        
        def getUrlObject(self) -> FilterObject:
            """
            获取URL对象
            
            Returns:
                FilterObject实例
                
            对应C++: FilterObject* getUrlObject() const
            """
            return self._urlObject
        
        def actions(self) -> List[QAction]:
            """
            返回动作列表
            
            Returns:
                QAction列表
                
            对应C++: QList<QAction*> actions() override
            """
            actionsList = []
            kind = self.urlType()
            
            if kind in [self.UrlType.StandardUrl, self.UrlType.Email]:
                openAction = QAction(self._urlObject)
                copyAction = QAction(self._urlObject)
                
                if kind == self.UrlType.StandardUrl:
                    openAction.setText("打开链接")
                    copyAction.setText("复制链接地址")
                elif kind == self.UrlType.Email:
                    openAction.setText("发送邮件到...")
                    copyAction.setText("复制邮件地址")
                
                openAction.setObjectName("open-action")
                copyAction.setObjectName("copy-action")
                
                openAction.triggered.connect(self._urlObject.activate)
                copyAction.triggered.connect(self._urlObject.activate)
                
                actionsList.extend([openAction, copyAction])
            
            return actionsList
    
    def __init__(self):
        """
        构造URL过滤器
        
        对应C++: UrlFilter()
        """
        super().__init__()
        self.setRegExp(self.CompleteUrlRegExp)
    
    def newHotSpot(self, startLine: int, startColumn: int, 
                   endLine: int, endColumn: int) -> 'UrlFilter.HotSpot':
        """
        创建新的URL热点
        
        对应C++: RegExpFilter::HotSpot* newHotSpot(int,int,int,int) override
        """
        spot = UrlFilter.HotSpot(startLine, startColumn, endLine, endColumn)
        spot.getUrlObject().activated.connect(self.activated)
        return spot


class FilterChain(list):
    """
    允许将一组过滤器作为一个整体处理的链。
    链拥有添加到其中的过滤器，并在链本身被销毁时删除它们。
    
    修复：正确继承自list以匹配C++的QList<Filter*>行为
    
    对应C++: class FilterChain : protected QList<Filter*>
    """
    
    def __init__(self):
        """
        构造过滤器链
        
        对应C++: FilterChain()
        """
        super().__init__()
    
    def addFilter(self, filterObj: Filter):
        """
        向链中添加新过滤器。链将在销毁时删除此过滤器
        
        Args:
            filterObj: 过滤器对象
            
        对应C++: void addFilter(Filter* filter)
        """
        self.append(filterObj)
    
    def removeFilter(self, filterObj: Filter):
        """
        从链中移除过滤器
        
        Args:
            filterObj: 要移除的过滤器
            
        对应C++: void removeFilter(Filter* filter)
        """
        # C++: removeAll(filter)
        while filterObj in self:
            self.remove(filterObj)
    
    def containsFilter(self, filterObj: Filter) -> bool:
        """
        返回链是否包含指定过滤器
        
        Args:
            filterObj: 过滤器对象
            
        Returns:
            是否包含
            
        对应C++: bool containsFilter(Filter* filter)
        """
        return filterObj in self
    
    def clear(self):
        """
        从链中移除所有过滤器
        
        对应C++: void clear()
        """
        super().clear()
    
    def reset(self):
        """
        重置链中的每个过滤器
        
        对应C++: void reset()
        """
        for filterObj in self:
            filterObj.reset()
    
    def process(self):
        """
        处理链中的每个过滤器
        
        对应C++: void process()
        """
        for filterObj in self:
            filterObj.process()
    
    def setBuffer(self, buffer: str, linePositions: List[int]):
        """
        为链中的每个过滤器设置要处理的缓冲区
        
        Args:
            buffer: 文本缓冲区
            linePositions: 行位置列表
            
        对应C++: void setBuffer(const QString* buffer, const QList<int>* linePositions)
        """
        for filterObj in self:
            filterObj.setBuffer(buffer, linePositions)
    
    def hotSpotAt(self, line: int, column: int) -> Optional[Filter.HotSpot]:
        """
        返回在指定位置出现的第一个热点
        
        Args:
            line: 行号
            column: 列号
            
        Returns:
            热点对象或None
            
        对应C++: Filter::HotSpot* hotSpotAt(int line, int column) const
        """
        for filterObj in self:
            spot = filterObj.hotSpotAt(line, column)
            if spot:
                return spot
        return None
    
    def hotSpots(self) -> List[Filter.HotSpot]:
        """
        返回所有链中过滤器的所有热点列表
        
        Returns:
            热点列表
            
        对应C++: QList<Filter::HotSpot*> hotSpots() const
        """
        allSpots = []
        for filterObj in self:
            allSpots.extend(filterObj.hotSpots())
        return allSpots
    
    def hotSpotsAtLine(self, line: int) -> List[Filter.HotSpot]:
        """
        返回所有链中过滤器在指定行的热点列表
        
        注意：C++版本返回QList<Filter::HotSpot>（对象），不是指针
        
        Args:
            line: 行号
            
        Returns:
            热点对象列表
            
        对应C++: QList<Filter::HotSpot> hotSpotsAtLine(int line) const
        """
        allSpots = []
        for filterObj in self:
            spots = filterObj.hotSpotsAtLine(line)
            allSpots.extend(spots)
        return allSpots
    
    def empty(self) -> bool:
        """
        返回过滤器链是否为空
        
        Returns:
            是否为空
        """
        return len(self) == 0


class TerminalImageFilterChain(FilterChain):
    """
    处理来自终端显示的字符图像的过滤器链
    
    对应C++: class TerminalImageFilterChain : public FilterChain
    """
    
    def __init__(self):
        """
        构造终端图像过滤器链
        
        对应C++: TerminalImageFilterChain()
        """
        super().__init__()
        self._buffer: Optional[str] = None
        self._linePositions: Optional[List[int]] = None
    
    def __del__(self):
        """
        析构函数 - 清理内存
        
        对应C++: ~TerminalImageFilterChain()
        """
        # Python的垃圾回收会自动处理内存，但我们可以显式清理
        self._buffer = None
        self._linePositions = None
    
    def setImage(self, image: List[Character], lines: int, columns: int, 
                lineProperties: List[LineProperty]):
        """
        设置当前终端图像
        
        Args:
            image: 终端图像字符数组
            lines: 图像中的行数
            columns: 图像中的列数
            lineProperties: 要为图像设置的行属性
            
        对应C++: void setImage(const Character* const image, int lines, int columns,
                              const QVector<LineProperty>& lineProperties)
        """
        if self.empty():
            return
        
        # 重置所有过滤器和热点
        self.reset()
        
        # 为过滤器设置新的共享缓冲区
        newBuffer = ""
        newLinePositions = []
        
        # 更新缓冲区引用
        self.setBuffer(newBuffer, newLinePositions)
        
        # 释放旧缓冲区
        self._buffer = newBuffer
        self._linePositions = newLinePositions
        
        # 处理每一行
        for i in range(lines):
            self._linePositions.append(len(self._buffer))
            
            # 解码该行
            lineStart = i * columns
            lineChars = image[lineStart:lineStart + columns] if lineStart + columns <= len(image) else image[lineStart:]
            
            # 确保我们有足够的字符
            if len(lineChars) < columns:
                # 用空字符填充不足的部分
                lineChars.extend([Character() for _ in range(columns - len(lineChars))])
            
            # 简化的字符解码逻辑 - 直接转换为字符串，包含尾随空白
            lineText = self._decodeLineToString(lineChars, columns, True)
            self._buffer += lineText
            
            # 假装每行都以换行符结尾
            # 这可以防止出现在一行末尾的链接被视为出现在下一行开头的链接的一部分
            #
            # 缺点是跨多行的链接不会被高亮显示
            #
            # TODO - 使用与终端图像中的行关联的"line wrapped"属性
            # 来避免为换行的行添加这个虚构的字符
            lineProp = lineProperties[i] if i < len(lineProperties) else LINE_DEFAULT
            if not (lineProp & LINE_WRAPPED):
                self._buffer += '\n'
        
        # 设置缓冲区给所有过滤器
        self.setBuffer(self._buffer, self._linePositions)
    
    def _decodeLineToString(self, characters: List[Character], count: int, includeTrailingWhitespace: bool) -> str:
        """
        简化的字符行解码函数，将字符列表转换为字符串
        
        Args:
            characters: 字符列表
            count: 字符数量
            includeTrailingWhitespace: 是否包含尾随空白
            
        Returns:
            解码后的字符串
        """
        if not characters:
            return ""
        
        # 构建字符串而不是逐字符写入流，这样更高效
        plainTextParts = []
        
        outputCount = count
        
        # 如果禁用尾随空白，则找到行的结尾
        if not includeTrailingWhitespace:
            for i in range(count - 1, -1, -1):
                if not characters[i].isSpace():
                    break
                else:
                    outputCount -= 1
        
        i = 0
        while i < outputCount:
            char = characters[i]
            
            # 检查是否为扩展字符（如果有扩展字符表）
            if hasattr(char, 'rendition') and char.rendition & 0x20000000:  # RE_EXTENDED_CHAR
                # 处理扩展字符 - 如果有扩展字符表的话
                try:
                    from .character import extended_char_table_instance
                    extendedCharLength, chars = extended_char_table_instance.lookupExtendedChar(char.character)
                    if chars:
                        charStr = ""
                        for nchar in range(extendedCharLength):
                            charStr += chr(chars[nchar])
                        plainTextParts.append(charStr)
                        i += max(1, string_width(charStr))
                    else:
                        i += 1
                except (ImportError, AttributeError):
                    # 如果没有扩展字符表，就当普通字符处理
                    plainTextParts.append(chr(char.character if hasattr(char, 'character') else ord(' ')))
                    i += 1
            else:
                # 普通字符
                charCode = char.character if hasattr(char, 'character') else ord(' ')
                try:
                    # 确保字符代码是有效的Unicode
                    if 0 <= charCode <= 0x10FFFF:
                        plainTextParts.append(chr(charCode))
                    else:
                        plainTextParts.append(' ')  # 无效字符用空格替代
                except (ValueError, OverflowError):
                    plainTextParts.append(' ')  # 异常时用空格替代
                
                # 考虑字符宽度（如果可用的话）
                try:
                    i += max(1, string_width(chr(charCode)) if 0 <= charCode <= 0x10FFFF else 1)
                except:
                    i += 1
        
        # 连接所有字符
        return "".join(plainTextParts)
    
    # 兼容性方法
    def set_image(self, image: List[Character], lines: int, columns: int, 
                 line_properties: List[LineProperty]):
        """兼容性方法：snake_case版本"""
        return self.setImage(image, lines, columns, line_properties) 