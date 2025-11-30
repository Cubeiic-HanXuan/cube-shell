"""
块数组模块 - 从Konsole终端模拟器转换而来

Copyright (C) 2000 by Stephan Kulow <coolo@kde.org>
Rewritten for QT4 by e_k <e_k at users.sourceforge.net>, Copyright (C)2008

转换为Python PySide6版本
"""

import os
import tempfile
from typing import Optional

# 常量定义 - 对应C++中的宏定义
QTERMWIDGET_BLOCKSIZE = 1 << 12  # 4096 bytes
ENTRIES = QTERMWIDGET_BLOCKSIZE - 8  # 减去size_t的大小 (在Python中用8字节)

# 全局静态变量 - 对应C++中的static int blocksize = 0;
_global_blocksize = 0


class Block:
    """
    表示一个数据块
    对应C++中的struct Block
    """
    
    def __init__(self):
        """
        构造新的Block
        对应C++: struct Block { unsigned char data[ENTRIES] = {}; size_t size = 0; };
        """
        self.data = bytearray(ENTRIES)  # 对应C++: unsigned char data[ENTRIES]
        self.size = 0                   # 对应C++: size_t size


class BlockArray:
    """
    块数组类 - 管理历史文件的块数组
    
    创建一个历史文件来保存最大数量的块。如果请求更多块，
    则丢弃较早添加的块。
    
    对应C++: class BlockArray
    """
    
    def __init__(self):
        """
        构造BlockArray
        对应C++: BlockArray::BlockArray()
        """
        global _global_blocksize
        
        # 对应C++中的私有成员变量
        self.size = 0                    # 对应C++: size_t size
        self.current = self._maxSizeT()  # 对应C++: size_t current (初始化为size_t(-1))
        self.index = self._maxSizeT()    # 对应C++: size_t index (初始化为size_t(-1))
        self.lastmap = None              # 对应C++: Block * lastmap
        self.lastmap_index = self._maxSizeT()  # 对应C++: size_t lastmap_index (初始化为size_t(-1))
        self.lastblock = None            # 对应C++: Block * lastblock
        self.ion = -1                    # 对应C++: int ion
        self.length = 0                  # 对应C++: size_t length
        
        # 计算块大小 - 对应C++中的静态变量blocksize计算
        # C++: if (blocksize == 0) { blocksize = ((sizeof(Block) / getpagesize()) + 1) * getpagesize(); }
        if _global_blocksize == 0:
            import resource
            try:
                page_size = resource.getpagesize()
            except:
                page_size = 4096
            
            # 计算Block结构体的大小：ENTRIES + size_t大小
            block_struct_size = ENTRIES + 8  # 8 bytes for size_t in Python
            _global_blocksize = ((block_struct_size // page_size) + 1) * page_size
        
        self.blocksize = _global_blocksize
        
        # 临时文件对象
        self._temp_file = None
    
    def __del__(self):
        """
        析构函数
        对应C++: BlockArray::~BlockArray()
        """
        try:
            self.setHistorySize(0)
        except:
            pass
    
    def _maxSizeT(self) -> int:
        """
        返回size_t的最大值（在Python中模拟size_t(-1)）
        对应C++: size_t(-1)
        """
        return (1 << 32) - 1  # 使用32位最大值，更安全
    
    def append(self, block: Block) -> int:
        """
        在历史末尾添加块。这可能会丢弃其他块。
        
        块的所有权被转移。返回一个唯一的索引号，
        用于以后访问它（如果尚未丢弃）。
        
        注意，如果历史记录已关闭，块可能会被完全丢弃。
        
        Args:
            block: 要添加的块
            
        Returns:
            int: 块的索引，如果失败则返回_maxSizeT()
            
        对应C++: size_t BlockArray::append(Block * block)
        """
        if not self.size:
            return self._maxSizeT()
        
        # 对应C++: ++current;
        if self.current == self._maxSizeT():
            self.current = 0
        else:
            self.current = (self.current + 1) % self.size
        
        try:
            # 对应C++: rc = lseek(ion, current * blocksize, SEEK_SET);
            os.lseek(self.ion, self.current * self.blocksize, os.SEEK_SET)
            
            # 准备要写入的数据
            data_to_write = bytearray(self.blocksize)
            # 复制块数据
            data_len = min(len(block.data), ENTRIES)
            data_to_write[:data_len] = block.data[:data_len]
            # 在末尾写入size
            size_bytes = block.size.to_bytes(8, byteorder='little')
            data_to_write[-8:] = size_bytes
            
            # 对应C++: rc = write(ion, block, blocksize);
            os.write(self.ion, data_to_write)
            
        except OSError as e:
            print(f"HistoryBuffer::add error: {e}")  # 使用与C++相同的错误信息
            self.setHistorySize(0)
            return self._maxSizeT()
        
        # 对应C++: length++;
        self.length += 1
        if self.length > self.size:
            self.length = self.size
        
        # 对应C++: ++index;
        if self.index == self._maxSizeT():
            self.index = 0
        else:
            self.index += 1
        
        # 对应C++: delete block; (Python中不需要手动删除)
        # 注意：C++返回current，但我们的索引逻辑返回index更合适
        return self.current
    
    def newBlock(self) -> int:
        """
        创建新块
        对应C++: size_t BlockArray::newBlock()
        """
        if not self.size:
            return self._maxSizeT()
        
        if self.lastblock:
            self.append(self.lastblock)
        
        self.lastblock = Block()
        return self.index + 1
    
    def lastBlock(self) -> Optional[Block]:
        """
        返回最后一个块
        对应C++: Block * BlockArray::lastBlock() const
        """
        return self.lastblock
    
    def has(self, i: int) -> bool:
        """
        检查是否有指定索引的块
        对应C++: bool BlockArray::has(size_t i) const
        """
        if i == self.index + 1:
            return True
        
        if i > self.index or self.index == self._maxSizeT():
            return False
        
        if self.index - i >= self.length:
            return False
        
        return True
    
    def at(self, i: int) -> Optional[Block]:
        """
        获取指定索引的块
        对应C++: const Block * BlockArray::at(size_t i)
        """
        if i == self.index + 1:
            return self.lastblock
        
        if i == self.lastmap_index:
            return self.lastmap
        
        if i > self.index or self.index == self._maxSizeT():
            print(f"BlockArray::at() i > index")
            return None
        
        # 对应C++中的复杂索引计算
        # C++: size_t j = i; // (current - (index - i) + (index/size+1)*size) % size ;
        # 实际上应该使用更复杂的计算，但在简单情况下 j = i 是正确的
        j = i
        
        # 但是为了与C++版本完全一致，我们需要更复杂的计算
        if self.index >= self.length:
            # 当数组已经环绕时，需要重新计算位置
            steps_back = self.index - i
            j = (self.current - steps_back + self.size) % self.size
        else:
            # 当数组还没有环绕时，直接使用i
            j = i
        
        if j >= self.size:
            return None
        
        # 确保j在有效范围内
        j = j % self.size
        
        self.unmap()
        
        try:
            # 对应C++的mmap操作，这里使用文件读取
            # C++: Block * block = (Block *)mmap(nullptr, blocksize, PROT_READ, MAP_PRIVATE, ion, j * blocksize);
            with open(self.ion, 'rb') as f:
                f.seek(j * self.blocksize)
                data = f.read(self.blocksize)
                
                if len(data) < self.blocksize:
                    return None
                
                # 创建新的Block并填充数据
                block = Block()
                data_size = min(len(data) - 8, ENTRIES)
                block.data[:data_size] = data[:data_size]
                # 读取size
                if len(data) >= 8:
                    block.size = int.from_bytes(data[-8:], byteorder='little')
                
                self.lastmap = block
                self.lastmap_index = i
                
                return block
                
        except (OSError, IOError) as e:
            print(f"mmap error: {e}")  # 使用与C++相同的错误信息
            return None
    
    def unmap(self):
        """
        取消映射
        对应C++: void BlockArray::unmap()
        """
        # 在Python版本中，我们不需要手动取消映射
        # 但我们可以清除引用
        self.lastmap = None
        self.lastmap_index = self._maxSizeT()
    
    def setSize(self, newsize: int) -> bool:
        """
        以KB为单位设置大小的便利函数
        对应C++: bool BlockArray::setSize(size_t newsize)
        """
        # 对应C++: return setHistorySize(newsize * 1024 / blocksize);
        if self.blocksize == 0:
            return False
        
        # 计算需要的块数
        blocks_needed = newsize * 1024 // self.blocksize
        # 确保至少有1个块（这是为了处理blocksize比1KB大的情况）
        if blocks_needed == 0 and newsize > 0:
            blocks_needed = 1
            
        return self.setHistorySize(blocks_needed)
    
    def setHistorySize(self, newsize: int) -> bool:
        """
        根据需要重新排序块。如果newsize为0，则完全清空历史记录。
        append返回的索引不会改变其语义，但在此调用后可能无效。
        
        Args:
            newsize: 新的大小（以块为单位）
            
        Returns:
            bool: 是否成功
            
        对应C++: bool BlockArray::setHistorySize(size_t newsize)
        """
        if self.size == newsize:
            return False
        
        self.unmap()
        
        if not newsize:
            # 对应C++: delete lastblock;
            self.lastblock = None
            
            if self.ion >= 0:
                try:
                    os.close(self.ion)
                except:
                    pass
                self.ion = -1
            
            if self._temp_file:
                try:
                    self._temp_file.close()
                except:
                    pass
                self._temp_file = None
            
            self.current = self._maxSizeT()
            self.index = self._maxSizeT()
            self.length = 0
            self.size = 0
            return True
        
        if not self.size:
            # 创建临时文件 - 对应C++: FILE * tmp = tmpfile();
            try:
                self._temp_file = tempfile.NamedTemporaryFile(delete=False)
                self.ion = os.dup(self._temp_file.fileno())
                self._temp_file.close()  # 关闭Python的文件对象，但保留底层fd
            except OSError as e:
                print(f"konsole: cannot open temp file: {e}")  # 使用与C++相同的错误信息
                return False
            
            # 对应C++: Q_ASSERT(!lastblock);
            if not self.lastblock:
                self.lastblock = Block()
            self.size = newsize
            return False
        
        if newsize > self.size:
            self.increaseBuffer()
            self.size = newsize
            return False
        else:
            self.decreaseBuffer(newsize)
            try:
                os.ftruncate(self.ion, self.length * self.blocksize)
            except:
                pass
            self.size = newsize
            return True
    
    def moveBlock(self, file_obj, cursor: int, newpos: int, buffer: bytearray):
        """
        移动块的辅助函数
        对应C++中的moveBlock函数
        """
        try:
            # 对应C++: fseek(fion, cursor * blocksize, SEEK_SET);
            file_obj.seek(cursor * self.blocksize)
            # 对应C++: fread(buffer2, blocksize, 1, fion);
            data = file_obj.read(self.blocksize)
            if len(buffer) < len(data):
                buffer.extend([0] * (len(data) - len(buffer)))
            buffer[:len(data)] = data
            
            # 对应C++: fseek(fion, newpos * blocksize, SEEK_SET);
            file_obj.seek(newpos * self.blocksize)
            # 对应C++: fwrite(buffer2, blocksize, 1, fion);
            file_obj.write(buffer[:self.blocksize])
        except (OSError, IOError) as e:
            print(f"move block error: {e}")
    
    def decreaseBuffer(self, newsize: int):
        """
        减少缓冲区
        对应C++: void BlockArray::decreaseBuffer(size_t newsize)
        """
        if self.index == self._maxSizeT() or self.index < newsize:
            return
        
        offset = (self.current - (newsize - 1) + self.size) % self.size
        
        if not offset:
            return
        
        buffer = bytearray(self.blocksize)
        
        try:
            # 使用文件描述符创建文件对象
            with os.fdopen(os.dup(self.ion), 'r+b') as file_obj:
                if self.current <= newsize:
                    firstblock = self.current + 1
                else:
                    firstblock = 0
                
                cursor = firstblock
                for i in range(newsize):
                    oldpos = (self.size + cursor + offset) % self.size
                    self.moveBlock(file_obj, oldpos, cursor, buffer)
                    if oldpos < newsize:
                        cursor = oldpos
                    else:
                        cursor += 1
                
                self.current = newsize - 1
                self.length = newsize
                
        except (OSError, IOError) as e:
            print(f"decrease buffer error: {e}")
    
    def increaseBuffer(self):
        """
        增加缓冲区
        对应C++: void BlockArray::increaseBuffer()
        """
        if self.index == self._maxSizeT() or self.index < self.size:
            return
        
        offset = (self.current + self.size + 1) % self.size
        if not offset:
            return
        
        buffer1 = bytearray(self.blocksize)
        buffer2 = bytearray(self.blocksize)
        
        runs = 1
        bpr = self.size  # blocks per run
        
        if self.size % offset == 0:
            bpr = self.size // offset
            runs = offset
        
        try:
            with os.fdopen(os.dup(self.ion), 'r+b') as file_obj:
                for i in range(runs):
                    # 释放链中的一个块
                    firstblock = (offset + i) % self.size
                    file_obj.seek(firstblock * self.blocksize)
                    data = file_obj.read(self.blocksize)
                    buffer1[:len(data)] = data
                    
                    cursor = firstblock
                    for j in range(1, bpr):
                        cursor = (cursor + offset) % self.size
                        newpos = (cursor - offset + self.size) % self.size
                        self.moveBlock(file_obj, cursor, newpos, buffer2)
                    
                    file_obj.seek(i * self.blocksize)
                    file_obj.write(buffer1[:self.blocksize])
                
                self.current = self.size - 1
                self.length = self.size
                
        except (OSError, IOError) as e:
            print(f"increase buffer error: {e}")
    
    def len(self) -> int:
        """
        返回长度
        对应C++: size_t len() const
        """
        return self.length
    
    def getCurrent(self) -> int:
        """
        返回当前位置
        对应C++: size_t getCurrent() const
        """
        return self.current 