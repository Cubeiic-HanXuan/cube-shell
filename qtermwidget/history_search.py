#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HistorySearch - 历史搜索功能
从Konsole的HistorySearch.cpp/h转换而来

Copyright 2013 Christian Surlykke
转换为Python PySide6版本
"""

from io import StringIO
from typing import List, Optional, Union

from PySide6.QtCore import QObject, Signal, QRegularExpression

from qtermwidget.terminal_character_decoder import PlainTextDecoder

# 类型别名 - 对应C++的EmulationPtr
EmulationPtr = Union['Emulation', None]


class HistorySearch(QObject):
    """
    历史搜索类 - 在终端历史记录中搜索指定的正则表达式模式
    
    支持前向和后向搜索，使用分块读取避免内存过度使用。
    搜索完成后会发射相应的信号，并自动删除对象。
    
    对应C++: class HistorySearch : public QObject
    """
    
    # 信号定义 - 完全对应C++版本
    matchFound = Signal(int, int, int, int)  # startColumn, startLine, endColumn, endLine
    noMatchFound = Signal()
    
    def __init__(self, emulation: EmulationPtr, regExp: QRegularExpression, 
                 forwards: bool, startColumn: int, startLine: int, 
                 parent: Optional[QObject] = None):
        """
        构造历史搜索对象
        
        Args:
            emulation: 终端模拟器对象
            regExp: 要搜索的正则表达式
            forwards: 是否前向搜索  
            startColumn: 起始列
            startLine: 起始行
            parent: 父对象
            
        对应C++: HistorySearch(EmulationPtr emulation, const QRegularExpression& regExp,
                               bool forwards, int startColumn, int startLine, QObject* parent)
        """
        super().__init__(parent)
        
        # C++风格的成员变量命名
        self.m_emulation = emulation
        self.m_regExp = regExp
        self.m_forwards = forwards
        self.m_startColumn = startColumn
        self.m_startLine = startLine
        
        # 搜索结果 - C++风格命名
        self.m_foundStartColumn = 0
        self.m_foundStartLine = 0
        self.m_foundEndColumn = 0
        self.m_foundEndLine = 0
    
    def __del__(self):
        """
        析构函数
        对应C++: ~HistorySearch()
        """
        pass
    
    def search(self):
        """
        执行搜索操作
        
        根据设置的搜索方向和范围，在历史记录中搜索正则表达式模式。
        搜索完成后发射相应的信号，并自动删除对象。
        
        对应C++: void search()
        """
        found = False
        
        if not self.m_regExp.pattern():
            # 如果正则表达式为空，直接发射未找到信号
            self.noMatchFound.emit()
            self.deleteLater()
            return
        
        if self.m_forwards:
            # 前向搜索：从起始位置到结尾，然后从开头到起始位置
            # 完全对应C++的搜索逻辑
            found = (self._searchRange(self.m_startColumn, self.m_startLine, 
                                     -1, self.m_emulation.lineCount()) or
                    self._searchRange(0, 0, self.m_startColumn, self.m_startLine))
        else:
            # 后向搜索：从开头到起始位置，然后从起始位置到结尾
            found = (self._searchRange(0, 0, self.m_startColumn, self.m_startLine) or
                    self._searchRange(self.m_startColumn, self.m_startLine, 
                                    -1, self.m_emulation.lineCount()))
        
        if found:
            self.matchFound.emit(
                self.m_foundStartColumn, self.m_foundStartLine,
                self.m_foundEndColumn, self.m_foundEndLine)
        else:
            self.noMatchFound.emit()
        
        # 对应C++的deleteLater()调用
        self.deleteLater()
    
    def _searchRange(self, startColumn: int, startLine: int, 
                    endColumn: int, endLine: int) -> bool:
        """
        在指定范围内搜索（私有方法）
        
        Args:
            startColumn: 起始列
            startLine: 起始行
            endColumn: 结束列 (-1表示行尾)
            endLine: 结束行
            
        Returns:
            bool: 是否找到匹配
            
        对应C++: bool search(int startColumn, int startLine, int endColumn, int endLine)
        """
        # 调试输出 - 对应C++的qDebug
        print(f"search from {startColumn},{startLine} to {endColumn},{endLine}")
        
        linesRead = 0
        linesToRead = endLine - startLine + 1
        
        print(f"linesToRead: {linesToRead}")
        
        # 分块读取历史记录，每次最多读取10K行以避免内存过度使用
        # 完全对应C++的分块处理逻辑
        while True:
            blockSize = min(10000, linesToRead - linesRead)
            if blockSize <= 0:
                break
            
            # 创建字符串和解码器 - 对应C++的实现
            string = ""
            searchStream = StringIO()
            decoder = PlainTextDecoder()
            decoder.begin(searchStream)
            decoder.setRecordLinePositions(True)
            
            # 计算要读取的行范围 - 完全对应C++逻辑
            if self.m_forwards:
                blockStartLine = startLine + linesRead
            else:
                blockStartLine = endLine - linesRead - blockSize + 1
            
            chunkEndLine = blockStartLine + blockSize - 1
            
            # 从模拟器读取数据到流中
            self.m_emulation.writeToStream(decoder, blockStartLine, chunkEndLine)
            
            # 获取解码后的字符串
            string = searchStream.getvalue()
            searchStream.close()
            
            # 计算搜索的结束位置 - 对应C++实现
            linePositions = decoder.linePositions()
            numberOfLinesInString = len(linePositions) - 1  # 忽略最后的空行
            
            if numberOfLinesInString > 0 and endColumn > -1:
                endPosition = linePositions[numberOfLinesInString - 1] + endColumn
            else:
                endPosition = len(string)
            
            # 在字符串中搜索正则表达式 - 对应C++的搜索逻辑
            matchStart = -1
            match = None
            
            if self.m_forwards:
                # 前向搜索
                match = self.m_regExp.match(string, startColumn)
                if match.hasMatch():
                    matchStart = match.capturedStart()
                    if matchStart >= endPosition:
                        matchStart = -1
            else:
                # 后向搜索 - 对应C++的lastIndexOf逻辑
                iterator = self.m_regExp.globalMatch(string)
                lastMatch = None
                while iterator.hasNext():
                    currentMatch = iterator.next()
                    currentStart = currentMatch.capturedStart()
                    if (currentStart >= startColumn and 
                        currentStart < endPosition):
                        lastMatch = currentMatch
                
                if lastMatch:
                    match = lastMatch
                    matchStart = match.capturedStart()
                    if matchStart < startColumn:
                        matchStart = -1
            
            if matchStart > -1 and match:
                matchEnd = matchStart + match.capturedLength() - 1
                print(f"Found in string from {matchStart} to {matchEnd}")
                
                # 将字符串中的位置转换为历史记录中的行列位置
                # 完全对应C++的坐标转换逻辑
                startLineNumberInString = self.findLineNumberInString(
                    linePositions, matchStart)
                self.m_foundStartColumn = (matchStart - 
                                         linePositions[startLineNumberInString])
                self.m_foundStartLine = (startLineNumberInString + 
                                       startLine + linesRead)
                
                endLineNumberInString = self.findLineNumberInString(
                    linePositions, matchEnd)
                self.m_foundEndColumn = (matchEnd - 
                                       linePositions[endLineNumberInString])
                self.m_foundEndLine = (endLineNumberInString + 
                                     startLine + linesRead)
                
                # 调试输出 - 对应C++的qDebug
                print(f"m_foundStartColumn {self.m_foundStartColumn}")
                print(f"m_foundStartLine {self.m_foundStartLine}")
                print(f"m_foundEndColumn {self.m_foundEndColumn}")
                print(f"m_foundEndLine {self.m_foundEndLine}")
                
                return True
            
            linesRead += blockSize
        
        print("Not found")
        return False
    
    def findLineNumberInString(self, linePositions: List[int], position: int) -> int:
        """
        在行位置列表中找到指定位置所在的行号
        
        Args:
            linePositions: 行位置列表
            position: 要查找的位置
            
        Returns:
            int: 行号
            
        对应C++: int findLineNumberInString(QList<int> linePositions, int position)
        """
        lineNum = 0
        while (lineNum + 1 < len(linePositions) and 
               linePositions[lineNum + 1] <= position):
            lineNum += 1
        
        return lineNum


# 工厂函数 - 提供便利的创建方法
def createHistorySearch(emulation: EmulationPtr, regExp: QRegularExpression,
                       forwards: bool, startColumn: int, startLine: int,
                       parent: Optional[QObject] = None) -> HistorySearch:
    """
    创建历史搜索对象的工厂函数
    
    Args:
        emulation: 终端模拟器对象
        regExp: 要搜索的正则表达式
        forwards: 是否前向搜索
        startColumn: 起始列
        startLine: 起始行
        parent: 父对象
        
    Returns:
        HistorySearch: 历史搜索对象
    """
    return HistorySearch(emulation, regExp, forwards, startColumn, startLine, parent) 