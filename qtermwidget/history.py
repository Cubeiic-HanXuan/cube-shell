"""
历史记录模块 - 从Konsole终端模拟器转换而来

Copyright 1997,1998 by Lars Doelle <lars.doelle@on-line.de>

转换为Python PySide6版本
"""

import mmap
import os
import sys
from typing import Optional, List, Dict

from PySide6.QtCore import QTemporaryFile, QBitArray

from qtermwidget.block_array import BlockArray, ENTRIES
from qtermwidget.character import Character, CharacterColor

# 常量定义
LINE_SIZE = 1024
MAP_THRESHOLD = -1000  # 当读写平衡低于此阈值时自动mmap文件


class HistoryFile:
    """
    基于临时文件的可扩展缓冲区。
    对应C++: class HistoryFile
    """
    
    def __init__(self):
        """
        构造函数。
        对应C++: HistoryFile::HistoryFile()
        """
        self.ion = -1
        self.length = 0
        self.fileMap: Optional[mmap.mmap] = None
        self.readWriteBalance = 0
        self.tmpFile = QTemporaryFile()
        
        if self.tmpFile.open():
            self.tmpFile.setAutoRemove(True)
            self.ion = self.tmpFile.handle()
    
    def __del__(self):
        """
        析构函数。
        对应C++: void HistoryFile::unmap()
        """
        if self.fileMap:
            self.unmap()
    
    def map(self):
        """
        将文件映射到内存中（只读模式）。
        对应C++: void HistoryFile::map()
        """
        assert self.fileMap is None
        
        try:
            # 在Python中，我们使用mmap模块来实现内存映射
            if self.ion >= 0 and self.length > 0:
                self.fileMap = mmap.mmap(self.ion, self.length, access=mmap.ACCESS_READ)
        except (OSError, ValueError) as e:
            # 如果mmap失败，回退到读-定位组合
            self.readWriteBalance = 0
            self.fileMap = None
            print(f"警告: mmap历史文件失败. 错误: {e}")
    
    def unmap(self):
        """
        取消文件内存映射。
        对应C++: void HistoryFile::unmap()
        """
        if self.fileMap:
            self.fileMap.close()
            self.fileMap = None
    
    def isMapped(self) -> bool:
        """
        返回文件是否已映射。
        对应C++: bool HistoryFile::isMapped() const
        """
        return self.fileMap is not None
    
    def add(self, bytesData: bytes):
        """
        向文件添加数据。
        
        Args:
            bytesData: 要添加的字节数据
            
        对应C++: void HistoryFile::add(const unsigned char* bytes, int len)
        """
        if self.fileMap:
            self.unmap()
        
        self.readWriteBalance += 1
        
        try:
            # 定位到文件末尾
            os.lseek(self.ion, self.length, os.SEEK_SET)
            # 写入数据
            written = os.write(self.ion, bytesData)
            self.length += written
        except OSError as e:
            print(f"HistoryFile::add 写入错误: {e}")
    
    def get(self, length: int, loc: int) -> bytes:
        """
        从文件获取数据。
        
        Args:
            length: 要读取的字节数
            loc: 读取位置
            
        Returns:
            bytes: 读取的数据
            
        对应C++: void HistoryFile::get(unsigned char* bytes, int len, int loc)
        """
        # 计算get()调用次数与add()调用次数的比较
        self.readWriteBalance -= 1
        if not self.fileMap and self.readWriteBalance < MAP_THRESHOLD:
            self.map()
        
        if self.fileMap:
            # 使用内存映射读取
            if loc >= 0 and length >= 0 and loc + length <= self.length:
                return self.fileMap[loc:loc + length]
            else:
                print(f"getHist(...,{length},{loc}): 无效参数.")
                return b''
        else:
            # 使用传统的定位-读取方式
            try:
                if loc < 0 or length < 0 or loc + length > self.length:
                    print(f"getHist(...,{length},{loc}): 无效参数.")
                    return b''
                
                os.lseek(self.ion, loc, os.SEEK_SET)
                return os.read(self.ion, length)
            except OSError as e:
                print(f"HistoryFile::get 读取错误: {e}")
                return b''
    
    def len(self) -> int:
        """
        返回文件长度。
        对应C++: int HistoryFile::len() const
        """
        return self.length


class HistoryType:
    """
    历史类型抽象基类。
    对应C++: class HistoryType
    """
    
    def __init__(self):
        """
        构造函数。
        对应C++: HistoryType::HistoryType()
        """
        pass
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: virtual bool isEnabled() const = 0
        """
        raise NotImplementedError
    
    def isUnlimited(self) -> bool:
        """
        返回历史大小是否无限制。
        对应C++: bool isUnlimited() const
        """
        return self.maximumLineCount() == 0
    
    def maximumLineCount(self) -> int:
        """
        返回此历史类型可以存储的最大行数。
        对应C++: virtual int maximumLineCount() const = 0
        """
        raise NotImplementedError
    
    def scroll(self, old: Optional['HistoryScroll']) -> 'HistoryScroll':
        """
        创建或更新历史滚动对象。
        对应C++: virtual HistoryScroll* scroll(HistoryScroll *) const = 0
        """
        raise NotImplementedError


class HistoryScroll:
    """
    历史滚动抽象基类。
    对应C++: class HistoryScroll
    """
    
    def __init__(self, histType: HistoryType):
        """
        构造函数。
        
        Args:
            histType: 历史类型对象
            
        对应C++: HistoryScroll::HistoryScroll(HistoryType*)
        """
        self.m_histType = histType
    
    def __del__(self):
        """
        析构函数。
        对应C++: HistoryScroll::~HistoryScroll()
        """
        # Python中由垃圾回收自动处理
        pass
    
    def hasScroll(self) -> bool:
        """
        返回是否有滚动功能。
        对应C++: bool HistoryScroll::hasScroll() const
        """
        return True
    
    def getLines(self) -> int:
        """
        获取行数。
        对应C++: virtual int getLines() const = 0
        """
        raise NotImplementedError
    
    def getLineLen(self, lineno: int) -> int:
        """
        获取指定行的长度。
        对应C++: virtual int getLineLen(int lineno) const = 0
        """
        raise NotImplementedError
    
    def getCells(self, lineno: int, colno: int, count: int) -> List[Character]:
        """
        获取指定位置的字符。
        对应C++: virtual void getCells(int lineno, int colno, int count, Character res[]) const = 0
        """
        raise NotImplementedError
    
    def isWrappedLine(self, lineno: int) -> bool:
        """
        检查指定行是否是换行的。
        对应C++: virtual bool isWrappedLine(int lineno) const = 0
        """
        raise NotImplementedError
    
    def getCell(self, lineno: int, colno: int) -> Character:
        """
        获取单个字符（向后兼容）。
        对应C++: Character getCell(int lineno, int colno) const
        """
        cells = self.getCells(lineno, colno, 1)
        return cells[0] if cells else Character()
    
    def addCells(self, cells: List[Character]):
        """
        添加字符。
        对应C++: virtual void addCells(const Character a[], int count) = 0
        """
        raise NotImplementedError
    
    def addCellsVector(self, cells: List[Character]):
        """
        添加字符向量（便利方法）。
        对应C++: virtual void addCellsVector(const QVector<Character>& cells)
        """
        self.addCells(cells)
    
    def addLine(self, previousWrapped: bool = False):
        """
        添加行。
        对应C++: virtual void addLine(bool previousWrapped=false) = 0
        """
        raise NotImplementedError
    
    def getType(self) -> HistoryType:
        """
        获取历史类型。
        对应C++: const HistoryType& getType() const
        """
        return self.m_histType


class HistoryScrollFile(HistoryScroll):
    """
    基于文件的历史滚动（如文件日志，长度无限制）。
    对应C++: class HistoryScrollFile : public HistoryScroll
    """
    
    def __init__(self, logFileName: str):
        """
        构造函数。
        
        Args:
            logFileName: 日志文件名
            
        对应C++: HistoryScrollFile::HistoryScrollFile(const QString &logFileName)
        """
        super().__init__(HistoryTypeFile(logFileName))
        self.m_logFileName = logFileName
        self.index = HistoryFile()  # 行索引
        self.cells = HistoryFile()  # 文本内容
        self.lineflags = HistoryFile()  # 行标志
    
    def getLines(self) -> int:
        """
        获取行数。
        对应C++: int HistoryScrollFile::getLines() const
        """
        return self.index.len() // 4  # sizeof(int) = 4
    
    def getLineLen(self, lineno: int) -> int:
        """
        获取指定行的长度。
        对应C++: int HistoryScrollFile::getLineLen(int lineno) const
        """
        start_pos = self.startOfLine(lineno)
        end_pos = self.startOfLine(lineno + 1)
        return (end_pos - start_pos) // Character.sizeOf()
    
    def isWrappedLine(self, lineno: int) -> bool:
        """
        检查指定行是否是换行的。
        对应C++: bool HistoryScrollFile::isWrappedLine(int lineno) const
        """
        if 0 <= lineno <= self.getLines():
            flag_data = self.lineflags.get(1, lineno)
            if flag_data:
                return bool(flag_data[0])
        return False
    
    def startOfLine(self, lineno: int) -> int:
        """
        获取指定行的起始位置。
        对应C++: int HistoryScrollFile::startOfLine(int lineno) const
        """
        if lineno <= 0:
            return 0
        if lineno <= self.getLines():
            if not self.index.isMapped():
                self.index.map()
            
            res_data = self.index.get(4, (lineno - 1) * 4)  # sizeof(int) = 4
            if res_data and len(res_data) >= 4:
                return int.from_bytes(res_data, byteorder=sys.byteorder)
        return self.cells.len()
    
    def getCells(self, lineno: int, colno: int, count: int) -> List[Character]:
        """
        获取指定位置的字符。
        对应C++: void HistoryScrollFile::getCells(int lineno, int colno, int count, Character res[]) const
        """
        start_pos = self.startOfLine(lineno) + colno * Character.sizeOf()
        data = self.cells.get(count * Character.sizeOf(), start_pos)
        
        result = []
        for i in range(count):
            offset = i * Character.sizeOf()
            if offset + Character.sizeOf() <= len(data):
                char_data = data[offset:offset + Character.sizeOf()]
                char = Character.fromBytes(char_data)
                result.append(char)
            else:
                result.append(Character())
        
        return result
    
    def addCells(self, cells: List[Character]):
        """
        添加字符。
        对应C++: void HistoryScrollFile::addCells(const Character text[], int count)
        """
        data = b''.join(char.toBytes() for char in cells)
        self.cells.add(data)
    
    def addLine(self, previousWrapped: bool = False):
        """
        添加行。
        对应C++: void HistoryScrollFile::addLine(bool previousWrapped)
        """
        if self.index.isMapped():
            self.index.unmap()
        
        loc = self.cells.len()
        loc_bytes = loc.to_bytes(4, byteorder=sys.byteorder)
        self.index.add(loc_bytes)
        
        flags = 0x01 if previousWrapped else 0x00
        self.lineflags.add(bytes([flags]))


class HistoryScrollBuffer(HistoryScroll):
    """
    基于缓冲区的历史滚动（限制到固定行数）。
    对应C++: class HistoryScrollBuffer : public HistoryScroll
    """
    
    def __init__(self, maxLineCount: int = 1000):
        """
        构造函数。
        
        Args:
            maxLineCount: 最大行数
            
        对应C++: HistoryScrollBuffer::HistoryScrollBuffer(unsigned int maxLineCount)
        """
        super().__init__(HistoryTypeBuffer(maxLineCount))
        self._historyBuffer: List[List[Character]] = []
        self._wrappedLine = QBitArray()
        self._maxLineCount = 0
        self._usedLines = 0
        self._head = 0
        
        self.setMaxNbLines(maxLineCount)
    
    def __del__(self):
        """
        析构函数。
        对应C++: HistoryScrollBuffer::~HistoryScrollBuffer()
        """
        # Python中由垃圾回收自动处理
        pass
    
    def addCellsVector(self, cells: List[Character]):
        """
        添加字符向量。
        对应C++: void HistoryScrollBuffer::addCellsVector(const QVector<Character>& cells)
        """
        # 完全按照C++逻辑实现
        self._head += 1
        if self._usedLines < self._maxLineCount:
            self._usedLines += 1
        
        if self._head >= self._maxLineCount:
            self._head = 0
        
        # 使用C++相同的缓冲区索引计算
        buffer_idx = self.bufferIndex(self._usedLines - 1)
        
        # 存储数据到正确的缓冲区位置
        self._historyBuffer[buffer_idx] = cells.copy()
        
        # 初始化为未换行
        self._wrappedLine.setBit(buffer_idx, False)
    
    def addCells(self, cells: List[Character]):
        """
        添加字符。
        对应C++: void HistoryScrollBuffer::addCells(const Character a[], int count)
        """
        newLine = cells.copy()
        self.addCellsVector(newLine)
    
    def addLine(self, previousWrapped: bool = False):
        """
        添加行。
        对应C++: void HistoryScrollBuffer::addLine(bool previousWrapped)
        """
        buffer_idx = self.bufferIndex(self._usedLines - 1)
        if buffer_idx < self._wrappedLine.size():
            self._wrappedLine.setBit(buffer_idx, previousWrapped)
    
    def getLines(self) -> int:
        """
        获取行数。
        对应C++: int HistoryScrollBuffer::getLines() const
        """
        return self._usedLines
    
    def getLineLen(self, lineNumber: int) -> int:
        """
        获取指定行的长度。
        对应C++: int HistoryScrollBuffer::getLineLen(int lineNumber) const
        """
        assert 0 <= lineNumber < self._maxLineCount
        
        if lineNumber < self._usedLines:
            buffer_idx = self.bufferIndex(lineNumber)
            if buffer_idx < len(self._historyBuffer):
                return len(self._historyBuffer[buffer_idx])
        return 0
    
    def isWrappedLine(self, lineNumber: int) -> bool:
        """
        检查指定行是否是换行的。
        对应C++: bool HistoryScrollBuffer::isWrappedLine(int lineNumber) const
        """
        assert 0 <= lineNumber < self._maxLineCount
        
        if lineNumber < self._usedLines:
            buffer_idx = self.bufferIndex(lineNumber)
            if buffer_idx < self._wrappedLine.size():
                return self._wrappedLine.at(buffer_idx)
        return False
    
    def getCells(self, lineNumber: int, startColumn: int, count: int) -> List[Character]:
        """
        获取指定位置的字符。
        对应C++: void HistoryScrollBuffer::getCells(int lineNumber, int startColumn, int count, Character buffer[]) const
        """
        if count == 0:
            return []
        
        assert lineNumber < self._maxLineCount
        
        if lineNumber >= self._usedLines:
            return [Character() for _ in range(count)]
        
        buffer_idx = self.bufferIndex(lineNumber)
        if buffer_idx >= len(self._historyBuffer):
            return [Character() for _ in range(count)]
        
        line = self._historyBuffer[buffer_idx]
        
        assert startColumn + count <= len(line)
        
        return line[startColumn:startColumn + count]
    
    def setMaxNbLines(self, lineCount: int):
        """
        设置最大行数。
        对应C++: void HistoryScrollBuffer::setMaxNbLines(unsigned int lineCount)
        """
        oldBuffer = self._historyBuffer
        
        # 预分配新缓冲区的所有位置，模拟C++的预分配数组行为
        newBuffer = [[] for _ in range(lineCount)]
        
        # 按照C++逻辑复制数据：将数据复制到新缓冲区的连续位置
        copyLines = min(self._usedLines, lineCount)
        for i in range(copyLines):
            if oldBuffer:
                oldIdx = self.bufferIndex(i)
                if oldIdx < len(oldBuffer):
                    newBuffer[i] = oldBuffer[oldIdx]  # 关键：复制到连续位置i
        
        self._usedLines = min(self._usedLines, lineCount)
        self._maxLineCount = lineCount
        # 按照C++逻辑设置head
        if self._usedLines == self._maxLineCount:
            self._head = 0
        else:
            self._head = self._usedLines - 1 if self._usedLines > 0 else 0
        
        self._historyBuffer = newBuffer
        
        self._wrappedLine.resize(lineCount)
    
    def maxNbLines(self) -> int:
        """
        获取最大行数。
        对应C++: unsigned int maxNbLines() const
        """
        return self._maxLineCount
    
    def bufferIndex(self, lineNumber: int) -> int:
        """
        获取缓冲区索引。
        对应C++: int HistoryScrollBuffer::bufferIndex(int lineNumber) const
        """
        assert lineNumber >= 0
        assert lineNumber < self._maxLineCount
        assert (self._usedLines == self._maxLineCount) or lineNumber <= self._head
        
        if self._usedLines == self._maxLineCount:
            return (self._head + lineNumber + 1) % self._maxLineCount
        else:
            return lineNumber


class HistoryScrollNone(HistoryScroll):
    """
    无历史记录的历史滚动。
    对应C++: class HistoryScrollNone : public HistoryScroll
    """
    
    def __init__(self):
        """
        构造函数。
        对应C++: HistoryScrollNone::HistoryScrollNone()
        """
        super().__init__(HistoryTypeNone())
    
    def hasScroll(self) -> bool:
        """
        返回是否有滚动功能。
        对应C++: bool HistoryScrollNone::hasScroll() const
        """
        return False
    
    def getLines(self) -> int:
        """
        获取行数。
        对应C++: int HistoryScrollNone::getLines() const
        """
        return 0
    
    def getLineLen(self, lineno: int) -> int:
        """
        获取指定行的长度。
        对应C++: int HistoryScrollNone::getLineLen(int) const
        """
        return 0
    
    def isWrappedLine(self, lineno: int) -> bool:
        """
        检查指定行是否是换行的。
        对应C++: bool HistoryScrollNone::isWrappedLine(int) const
        """
        return False
    
    def getCells(self, lineno: int, colno: int, count: int) -> List[Character]:
        """
        获取指定位置的字符。
        对应C++: void HistoryScrollNone::getCells(int, int, int, Character []) const
        """
        return []
    
    def addCells(self, cells: List[Character]):
        """
        添加字符。
        对应C++: void HistoryScrollNone::addCells(const Character [], int)
        """
        pass
    
    def addLine(self, previousWrapped: bool = False):
        """
        添加行。
        对应C++: void HistoryScrollNone::addLine(bool)
        """
        pass


class HistoryScrollBlockArray(HistoryScroll):
    """
    基于块数组的历史滚动。
    对应C++: class HistoryScrollBlockArray : public HistoryScroll
    """
    
    def __init__(self, size: int):
        """
        构造函数。
        
        Args:
            size: 块数组大小
            
        对应C++: HistoryScrollBlockArray::HistoryScrollBlockArray(size_t size)
        """
        super().__init__(HistoryTypeBlockArray(size))
        self.m_blockArray = BlockArray()
        self.m_lineLengths: Dict[int, int] = {}
        
        self.m_blockArray.setHistorySize(size)
    
    def getLines(self) -> int:
        """
        获取行数。
        对应C++: int HistoryScrollBlockArray::getLines() const
        """
        return len(self.m_lineLengths)
    
    def getLineLen(self, lineno: int) -> int:
        """
        获取指定行的长度。
        对应C++: int HistoryScrollBlockArray::getLineLen(int lineno) const
        """
        return self.m_lineLengths.get(lineno, 0)
    
    def isWrappedLine(self, lineno: int) -> bool:
        """
        检查指定行是否是换行的。
        对应C++: bool HistoryScrollBlockArray::isWrappedLine(int) const
        """
        return False
    
    def getCells(self, lineno: int, colno: int, count: int) -> List[Character]:
        """
        获取指定位置的字符。
        对应C++: void HistoryScrollBlockArray::getCells(int lineno, int colno, int count, Character res[]) const
        """
        if not count:
            return []
        
        block = self.m_blockArray.at(lineno)
        if not block:
            return [Character() for _ in range(count)]
        
        # 验证边界
        charSize = Character.sizeOf()
        if (colno + count) * charSize > ENTRIES:
            return [Character() for _ in range(count)]
        
        # 从块数据中提取字符
        startOffset = colno * charSize
        result = []
        for i in range(count):
            offset = startOffset + i * charSize
            if offset + charSize <= len(block.data):
                charData = block.data[offset:offset + charSize]
                char = Character.fromBytes(charData)
                result.append(char)
            else:
                result.append(Character())
        
        return result
    
    def addCells(self, cells: List[Character]):
        """
        添加字符。
        对应C++: void HistoryScrollBlockArray::addCells(const Character a[], int count)
        """
        block = self.m_blockArray.lastBlock()
        if not block:
            return
        
        # 将字符放入块数据中
        charSize = Character.sizeOf()
        totalSize = len(cells) * charSize
        
        if totalSize >= ENTRIES:
            return
        
        # 清空块数据
        block.data = bytearray(ENTRIES)
        
        # 复制字符数据
        for i, char in enumerate(cells):
            offset = i * charSize
            charBytes = char.toBytes()
            block.data[offset:offset + len(charBytes)] = charBytes
        
        block.size = totalSize
        
        res = self.m_blockArray.newBlock()
        assert res > 0
        
        self.m_lineLengths[self.m_blockArray.getCurrent()] = len(cells)
    
    def addLine(self, previousWrapped: bool = False):
        """
        添加行。
        对应C++: void HistoryScrollBlockArray::addLine(bool)
        """
        pass


# 历史类型实现类

class HistoryTypeNone(HistoryType):
    """
    无历史记录类型。
    对应C++: class HistoryTypeNone : public HistoryType
    """
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeNone::isEnabled() const
        """
        return False
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeNone::maximumLineCount() const
        """
        return 0
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeNone::scroll(HistoryScroll *old) const
        """
        if old:
            del old
        return HistoryScrollNone()


class HistoryTypeBlockArray(HistoryType):
    """
    块数组历史记录类型。
    对应C++: class HistoryTypeBlockArray : public HistoryType
    """
    
    def __init__(self, size: int):
        """
        构造函数。
        
        Args:
            size: 块数组大小
            
        对应C++: HistoryTypeBlockArray::HistoryTypeBlockArray(size_t size)
        """
        super().__init__()
        self.m_size = size
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeBlockArray::isEnabled() const
        """
        return True
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeBlockArray::maximumLineCount() const
        """
        return self.m_size
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeBlockArray::scroll(HistoryScroll *old) const
        """
        if old:
            del old
        return HistoryScrollBlockArray(self.m_size)


class HistoryTypeFile(HistoryType):
    """
    文件历史记录类型。
    对应C++: class HistoryTypeFile : public HistoryType
    """
    
    def __init__(self, fileName: str = ""):
        """
        构造函数。
        
        Args:
            fileName: 文件名
            
        对应C++: HistoryTypeFile::HistoryTypeFile(const QString& fileName)
        """
        super().__init__()
        self.m_fileName = fileName
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeFile::isEnabled() const
        """
        return True
    
    def getFileName(self) -> str:
        """
        获取文件名。
        对应C++: const QString& HistoryTypeFile::getFileName() const
        """
        return self.m_fileName
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeFile::maximumLineCount() const
        """
        return 0  # 无限制
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeFile::scroll(HistoryScroll *old) const
        """
        if isinstance(old, HistoryScrollFile):
            return old  # 无变化
        
        newScroll = HistoryScrollFile(self.m_fileName)
        
        if old:
            # 复制旧历史到新历史
            lines = old.getLines()
            for i in range(lines):
                size = old.getLineLen(i)
                if size > 0:
                    cells = old.getCells(i, 0, size)
                    newScroll.addCells(cells)
                    newScroll.addLine(old.isWrappedLine(i))
            del old
        
        return newScroll


class HistoryTypeBuffer(HistoryType):
    """
    缓冲区历史记录类型。
    对应C++: class HistoryTypeBuffer : public HistoryType
    """
    
    def __init__(self, nbLines: int):
        """
        构造函数。
        
        Args:
            nbLines: 行数
            
        对应C++: HistoryTypeBuffer::HistoryTypeBuffer(unsigned int nbLines)
        """
        super().__init__()
        self.m_nbLines = nbLines
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeBuffer::isEnabled() const
        """
        return True
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeBuffer::maximumLineCount() const
        """
        return self.m_nbLines
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeBuffer::scroll(HistoryScroll *old) const
        """
        if old:
            if isinstance(old, HistoryScrollBuffer):
                old.setMaxNbLines(self.m_nbLines)
                return old
            
            # 创建新的缓冲区并复制旧数据
            newScroll = HistoryScrollBuffer(self.m_nbLines)
            lines = old.getLines()
            startLine = 0
            if lines > self.m_nbLines:
                startLine = lines - self.m_nbLines
            
            for i in range(startLine, lines):
                size = old.getLineLen(i)
                if size > 0:
                    cells = old.getCells(i, 0, size)
                    newScroll.addCells(cells)
                    newScroll.addLine(old.isWrappedLine(i))
            
            del old
            return newScroll
        
        return HistoryScrollBuffer(self.m_nbLines)


# 紧凑历史存储相关类 - 完整实现

# 将TextLine定义为Character列表的别名
TextLine = List[Character]

class CharacterFormat:
    """
    字符格式。
    对应C++: class CharacterFormat
    """
    
    def __init__(self):
        """构造函数"""
        self.fgColor = CharacterColor()
        self.bgColor = CharacterColor()
        self.startPos = 0
        self.rendition = 0
    
    def equalsFormat(self, other) -> bool:
        """
        比较格式是否相等。
        对应C++: bool equalsFormat(const CharacterFormat &other) const
        """
        if isinstance(other, CharacterFormat):
            return (other.rendition == self.rendition and 
                    other.fgColor == self.fgColor and 
                    other.bgColor == self.bgColor)
        elif isinstance(other, Character):
            return (other.rendition == self.rendition and 
                    other.foregroundColor == self.fgColor and 
                    other.backgroundColor == self.bgColor)
        return False
    
    def setFormat(self, char: Character):
        """
        从字符设置格式。
        对应C++: void setFormat(const Character& c)
        """
        self.rendition = char.rendition
        self.fgColor = char.foregroundColor
        self.bgColor = char.backgroundColor


class CompactHistoryBlock:
    """
    紧凑历史块。
    对应C++: class CompactHistoryBlock
    """
    
    def __init__(self):
        """
        构造函数。
        对应C++: CompactHistoryBlock::CompactHistoryBlock()
        """
        self.blockLength = 4096 * 64  # 256KB
        # 在Python中使用bytearray模拟内存分配
        self.blockStart = bytearray(self.blockLength)
        self.head = 0
        self.tail = 0
        self.allocCount = 0
    
    def __del__(self):
        """
        析构函数。
        对应C++: virtual ~CompactHistoryBlock()
        """
        # Python中由垃圾回收自动处理
        pass
    
    def remaining(self) -> int:
        """
        返回剩余空间。
        对应C++: virtual unsigned int remaining()
        """
        return self.blockLength - self.tail
    
    def length(self) -> int:
        """
        返回块长度。
        对应C++: virtual unsigned length()
        """
        return self.blockLength
    
    def allocate(self, length: int) -> Optional[int]:
        """
        分配内存。
        
        Args:
            length: 要分配的长度
            
        Returns:
            分配的偏移量，失败时返回None
            
        对应C++: virtual void* allocate(size_t length)
        """
        assert length > 0
        if self.tail + length > self.blockLength:
            return None
        
        block_offset = self.tail
        self.tail += length
        self.allocCount += 1
        return block_offset
    
    def contains(self, offset: int) -> bool:
        """
        检查偏移量是否在此块中。
        
        Args:
            offset: 偏移量
            
        Returns:
            是否包含
            
        对应C++: virtual bool contains(void *addr)
        """
        return 0 <= offset < self.blockLength
    
    def deallocate(self):
        """
        释放内存。
        对应C++: virtual void deallocate()
        """
        self.allocCount -= 1
        assert self.allocCount >= 0
    
    def isInUse(self) -> bool:
        """
        检查是否正在使用。
        对应C++: virtual bool isInUse()
        """
        return self.allocCount != 0


class CompactHistoryBlockList:
    """
    紧凑历史块列表。
    对应C++: class CompactHistoryBlockList
    """
    
    def __init__(self):
        """
        构造函数。
        对应C++: CompactHistoryBlockList::CompactHistoryBlockList()
        """
        self.list: List[CompactHistoryBlock] = []
    
    def __del__(self):
        """
        析构函数。
        对应C++: CompactHistoryBlockList::~CompactHistoryBlockList()
        """
        self.list.clear()
    
    def allocate(self, size: int) -> Optional[tuple[CompactHistoryBlock, int]]:
        """
        分配内存。
        
        Args:
            size: 要分配的大小
            
        Returns:
            (块对象, 偏移量)元组，失败时返回None
            
        对应C++: void *allocate(size_t size)
        """
        if not self.list or self.list[-1].remaining() < size:
            block = CompactHistoryBlock()
            self.list.append(block)
        else:
            block = self.list[-1]
        
        offset = block.allocate(size)
        if offset is not None:
            return (block, offset)
        return None
    
    def deallocate(self, block: CompactHistoryBlock, offset: int):
        """
        释放内存。
        
        Args:
            block: 块对象
            offset: 偏移量
            
        对应C++: void deallocate(void *)
        """
        assert self.list
        
        # 找到包含此偏移量的块
        found_index = -1
        for i, list_block in enumerate(self.list):
            if list_block is block and list_block.contains(offset):
                found_index = i
                break
        
        assert found_index >= 0
        
        block.deallocate()
        
        if not block.isInUse():
            self.list.pop(found_index)
    
    def length(self) -> int:
        """
        返回块列表长度。
        对应C++: int length()
        """
        return len(self.list)


class CompactHistoryLine:
    """
    紧凑历史行。
    对应C++: class CompactHistoryLine
    """
    
    def __init__(self, line: TextLine, blockList: CompactHistoryBlockList):
        """
        构造函数。
        
        Args:
            line: 文本行
            blockList: 块列表
            
        对应C++: CompactHistoryLine(const TextLine&, CompactHistoryBlockList& blockList)
        """
        self.blockList = blockList
        self.formatLength = 0
        self.length = len(line)
        self.wrapped = False
        self.formatArray: Optional[List[CharacterFormat]] = None
        self.text: Optional[List[int]] = None
        self.formatArrayAlloc: Optional[tuple[CompactHistoryBlock, int]] = None
        self.textAlloc: Optional[tuple[CompactHistoryBlock, int]] = None
        
        if line:
            self.formatLength = 1
            k = 1
            
            # 计算此文本行中不同格式的数量
            c = line[0]
            while k < self.length:
                if not line[k].equalsFormat(c):
                    self.formatLength += 1  # 检测到格式变化
                    c = line[k]
                k += 1
            
            # 分配格式数组
            format_alloc = self.blockList.allocate(self.formatLength * 32)  # 估计的CharacterFormat大小
            if format_alloc:
                self.formatArrayAlloc = format_alloc
                self.formatArray = [CharacterFormat() for _ in range(self.formatLength)]
            
            # 分配文本数组
            text_alloc = self.blockList.allocate(len(line) * 2)  # 每个字符2字节
            if text_alloc:
                self.textAlloc = text_alloc
                self.text = []
            
            if self.formatArray and self.text is not None:
                # 记录格式及其在格式数组中的位置
                c = line[0]
                self.formatArray[0].setFormat(c)
                self.formatArray[0].startPos = 0
                
                k = 1
                j = 1
                while k < self.length and j < self.formatLength:
                    if not line[k].equalsFormat(c):
                        c = line[k]
                        self.formatArray[j].setFormat(c)
                        self.formatArray[j].startPos = k
                        j += 1
                    k += 1
                
                # 复制字符值
                for i in range(len(line)):
                    self.text.append(line[i].character)
    
    def __del__(self):
        """
        析构函数。
        对应C++: CompactHistoryLine::~CompactHistoryLine()
        """
        if self.length > 0:
            if self.textAlloc:
                self.blockList.deallocate(*self.textAlloc)
            if self.formatArrayAlloc:
                self.blockList.deallocate(*self.formatArrayAlloc)
    
    def getCharacter(self, index: int) -> Character:
        """
        获取指定索引的字符。
        
        Args:
            index: 字符索引
            
        Returns:
            字符对象
            
        对应C++: void getCharacter(int index, Character &r)
        """
        assert index < self.length
        
        if not self.formatArray or not self.text:
            return Character()
        
        formatPos = 0
        while ((formatPos + 1) < self.formatLength and 
               index >= self.formatArray[formatPos + 1].startPos):
            formatPos += 1
        
        r = Character()
        r.character = self.text[index]
        r.rendition = self.formatArray[formatPos].rendition
        r.foregroundColor = self.formatArray[formatPos].fgColor
        r.backgroundColor = self.formatArray[formatPos].bgColor
        
        return r
    
    def getCharacters(self, length: int, startColumn: int) -> List[Character]:
        """
        获取字符数组。
        
        Args:
            length: 长度
            startColumn: 起始列
            
        Returns:
            字符列表
            
        对应C++: void getCharacters(Character* array, int length, int startColumn)
        """
        assert startColumn >= 0 and length >= 0
        assert startColumn + length <= self.getLength()
        
        result = []
        for i in range(startColumn, length + startColumn):
            result.append(self.getCharacter(i))
        
        return result
    
    def isWrapped(self) -> bool:
        """
        检查是否换行。
        对应C++: virtual bool isWrapped() const
        """
        return self.wrapped
    
    def setWrapped(self, isWrapped: bool):
        """
        设置换行状态。
        对应C++: virtual void setWrapped(bool isWrapped)
        """
        self.wrapped = isWrapped
    
    def getLength(self) -> int:
        """
        获取长度。
        对应C++: virtual unsigned int getLength() const
        """
        return self.length


class CompactHistoryScroll(HistoryScroll):
    """
    紧凑历史滚动。
    对应C++: class CompactHistoryScroll : public HistoryScroll
    """
    
    def __init__(self, maxLineCount: int = 1000):
        """
        构造函数。
        
        Args:
            maxLineCount: 最大行数
            
        对应C++: CompactHistoryScroll(unsigned int maxLineCount)
        """
        super().__init__(CompactHistoryType(maxLineCount))
        self.lines: List[CompactHistoryLine] = []
        self.blockList = CompactHistoryBlockList()
        self._maxLineCount = 0
        
        self.setMaxNbLines(maxLineCount)
    
    def __del__(self):
        """
        析构函数。
        对应C++: CompactHistoryScroll::~CompactHistoryScroll()
        """
        self.lines.clear()
    
    def addCellsVector(self, cells: TextLine):
        """
        添加字符向量。
        对应C++: void addCellsVector(const TextLine& cells)
        """
        line = CompactHistoryLine(cells, self.blockList)
        
        if len(self.lines) > self._maxLineCount:
            # 删除最旧的行
            if self.lines:
                del self.lines[0]
        
        self.lines.append(line)
    
    def addCells(self, cells: List[Character]):
        """
        添加字符。
        对应C++: void addCells(const Character a[], int count)
        """
        newLine = cells.copy()
        self.addCellsVector(newLine)
    
    def addLine(self, previousWrapped: bool = False):
        """
        添加行。
        对应C++: void addLine(bool previousWrapped)
        """
        if self.lines:
            line = self.lines[-1]
            line.setWrapped(previousWrapped)
    
    def getLines(self) -> int:
        """
        获取行数。
        对应C++: int getLines() const
        """
        return len(self.lines)
    
    def getLineLen(self, lineNumber: int) -> int:
        """
        获取指定行的长度。
        对应C++: int getLineLen(int lineNumber) const
        """
        assert 0 <= lineNumber < len(self.lines)
        line = self.lines[lineNumber]
        return line.getLength()
    
    def getCells(self, lineNumber: int, startColumn: int, count: int) -> List[Character]:
        """
        获取指定位置的字符。
        对应C++: void getCells(int lineNumber, int startColumn, int count, Character buffer[]) const
        """
        if count == 0:
            return []
        
        assert lineNumber < len(self.lines)
        line = self.lines[lineNumber]
        assert startColumn >= 0
        assert startColumn + count <= line.getLength()
        
        return line.getCharacters(count, startColumn)
    
    def setMaxNbLines(self, lineCount: int):
        """
        设置最大行数。
        对应C++: void setMaxNbLines(unsigned int lineCount)
        """
        self._maxLineCount = lineCount
        
        while len(self.lines) > lineCount:
            del self.lines[0]
    
    def maxNbLines(self) -> int:
        """
        获取最大行数。
        对应C++: unsigned int maxNbLines() const
        """
        return self._maxLineCount
    
    def isWrappedLine(self, lineNumber: int) -> bool:
        """
        检查指定行是否是换行的。
        对应C++: bool isWrappedLine(int lineNumber) const
        """
        assert lineNumber < len(self.lines)
        return self.lines[lineNumber].isWrapped()


# 历史类型实现类

class HistoryTypeNone(HistoryType):
    """
    无历史记录类型。
    对应C++: class HistoryTypeNone : public HistoryType
    """
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeNone::isEnabled() const
        """
        return False
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeNone::maximumLineCount() const
        """
        return 0
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeNone::scroll(HistoryScroll *old) const
        """
        if old:
            del old
        return HistoryScrollNone()


class HistoryTypeBlockArray(HistoryType):
    """
    块数组历史记录类型。
    对应C++: class HistoryTypeBlockArray : public HistoryType
    """
    
    def __init__(self, size: int):
        """
        构造函数。
        
        Args:
            size: 块数组大小
            
        对应C++: HistoryTypeBlockArray::HistoryTypeBlockArray(size_t size)
        """
        super().__init__()
        self.m_size = size
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeBlockArray::isEnabled() const
        """
        return True
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeBlockArray::maximumLineCount() const
        """
        return self.m_size
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeBlockArray::scroll(HistoryScroll *old) const
        """
        if old:
            del old
        return HistoryScrollBlockArray(self.m_size)


class HistoryTypeFile(HistoryType):
    """
    文件历史记录类型。
    对应C++: class HistoryTypeFile : public HistoryType
    """
    
    def __init__(self, fileName: str = ""):
        """
        构造函数。
        
        Args:
            fileName: 文件名
            
        对应C++: HistoryTypeFile::HistoryTypeFile(const QString& fileName)
        """
        super().__init__()
        self.m_fileName = fileName
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeFile::isEnabled() const
        """
        return True
    
    def getFileName(self) -> str:
        """
        获取文件名。
        对应C++: const QString& HistoryTypeFile::getFileName() const
        """
        return self.m_fileName
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeFile::maximumLineCount() const
        """
        return 0  # 无限制
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeFile::scroll(HistoryScroll *old) const
        """
        if isinstance(old, HistoryScrollFile):
            return old  # 无变化
        
        newScroll = HistoryScrollFile(self.m_fileName)
        
        if old:
            # 复制旧历史到新历史
            lines = old.getLines()
            for i in range(lines):
                size = old.getLineLen(i)
                if size > 0:
                    cells = old.getCells(i, 0, size)
                    newScroll.addCells(cells)
                    newScroll.addLine(old.isWrappedLine(i))
            del old
        
        return newScroll


class HistoryTypeBuffer(HistoryType):
    """
    缓冲区历史记录类型。
    对应C++: class HistoryTypeBuffer : public HistoryType
    """
    
    def __init__(self, nbLines: int):
        """
        构造函数。
        
        Args:
            nbLines: 行数
            
        对应C++: HistoryTypeBuffer::HistoryTypeBuffer(unsigned int nbLines)
        """
        super().__init__()
        self.m_nbLines = nbLines
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool HistoryTypeBuffer::isEnabled() const
        """
        return True
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int HistoryTypeBuffer::maximumLineCount() const
        """
        return self.m_nbLines
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* HistoryTypeBuffer::scroll(HistoryScroll *old) const
        """
        if old:
            if isinstance(old, HistoryScrollBuffer):
                old.setMaxNbLines(self.m_nbLines)
                return old
            
            # 创建新的缓冲区并复制旧数据
            newScroll = HistoryScrollBuffer(self.m_nbLines)
            lines = old.getLines()
            startLine = 0
            if lines > self.m_nbLines:
                startLine = lines - self.m_nbLines
            
            for i in range(startLine, lines):
                size = old.getLineLen(i)
                if size > 0:
                    cells = old.getCells(i, 0, size)
                    newScroll.addCells(cells)
                    newScroll.addLine(old.isWrappedLine(i))
            
            del old
            return newScroll
        
        return HistoryScrollBuffer(self.m_nbLines)


class CompactHistoryType(HistoryType):
    """
    紧凑历史记录类型。
    对应C++: class CompactHistoryType : public HistoryType
    """
    
    def __init__(self, nbLines: int):
        """
        构造函数。
        
        Args:
            nbLines: 行数
            
        对应C++: CompactHistoryType::CompactHistoryType(unsigned int nbLines)
        """
        super().__init__()
        self.m_nbLines = nbLines
    
    def isEnabled(self) -> bool:
        """
        返回历史记录是否启用。
        对应C++: bool CompactHistoryType::isEnabled() const
        """
        return True
    
    def maximumLineCount(self) -> int:
        """
        返回最大行数。
        对应C++: int CompactHistoryType::maximumLineCount() const
        """
        return self.m_nbLines
    
    def scroll(self, old: Optional[HistoryScroll]) -> HistoryScroll:
        """
        创建历史滚动对象。
        对应C++: HistoryScroll* CompactHistoryType::scroll(HistoryScroll *old) const
        """
        if old:
            if isinstance(old, CompactHistoryScroll):
                old.setMaxNbLines(self.m_nbLines)
                return old
            del old
        return CompactHistoryScroll(self.m_nbLines) 