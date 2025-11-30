"""
ShellCommand模块 - 从Konsole终端模拟器转换而来

这个模块提供ShellCommand类，用于解析和提取shell命令信息。

原始文件：
- ShellCommand.h
- ShellCommand.cpp

版权信息：
Copyright (C) 2007 by Robert Knight <robertknight@gmail.com>
Rewritten for QT4 by e_k <e_k at users.sourceforge.net>, Copyright (C)2008

转换为Python PySide6版本
"""

import os
import shutil
from typing import List, overload


class ShellCommand:
    """
    用于解析和提取shell命令信息的类。
    
    ShellCommand可以用于：
    
    - 获取命令行（如"/bin/sh -c /path/to/my/script"）并将其分割为
      组成部分（如命令"/bin/sh"和参数"-c", "/path/to/my/script"）
    - 获取命令和参数列表并将它们组合成完整的命令行
    - 确定命令指定的二进制文件是否存在于用户的PATH中
    - 确定命令行是否指定使用su/sudo等以root用户身份执行另一个命令
    
    对应C++: class ShellCommand
    """
    
    @overload
    def __init__(self, fullCommand: str): ...
    
    @overload
    def __init__(self, command: str, arguments: List[str]): ...
    
    def __init__(self, *args):
        """
        构造ShellCommand对象
        
        Args:
            如果传入1个参数：完整的命令行字符串
            如果传入2个参数：命令和参数列表
            
        对应C++: ShellCommand(const QString & fullCommand)
                ShellCommand(const QString & command, const QStringList & arguments)
        """
        if len(args) == 1:
            # 从完整命令行构造
            self._initFromFullCommand(args[0])
        elif len(args) == 2:
            # 从命令和参数构造  
            self._initFromCommandAndArgs(args[0], args[1])
        else:
            raise ValueError("ShellCommand requires 1 or 2 arguments")
    
    def _initFromFullCommand(self, fullCommand: str):
        """
        从完整命令行字符串初始化
        
        Args:
            fullCommand: 要解析的命令行
            
        对应C++: ShellCommand::ShellCommand(const QString & fullCommand)
        """
        self._arguments: List[str] = []
        
        # 严格按照C++实现逻辑 - 逐字符复制C++代码行为
        inQuotes = False
        builder = ""
        
        for i in range(len(fullCommand)):
            ch = fullCommand[i]
            
            isLastChar = (i == len(fullCommand) - 1)
            isQuote = (ch == "'" or ch == '"')
            
            if not isLastChar and isQuote:
                inQuotes = not inQuotes
            else:
                if (not ch.isspace() or inQuotes) and not isQuote:
                    builder += ch
                
                if (ch.isspace() and not inQuotes) or (i == len(fullCommand) - 1):
                    # C++行为：总是添加builder，即使为空 
                    self._arguments.append(builder)
                    builder = ""
    
    def _initFromCommandAndArgs(self, command: str, arguments: List[str]):
        """
        从命令和参数列表初始化
        
        Args:
            command: 命令
            arguments: 参数列表
            
        对应C++: ShellCommand::ShellCommand(const QString & command, const QStringList & arguments)
        """
        # 严格对应C++逻辑：
        # : _arguments(arguments)
        # if ( !_arguments.isEmpty() ) {
        #     _arguments[0] = command;
        # }
        self._arguments = arguments.copy() if arguments else []
        if self._arguments:  # 如果参数列表不为空
            self._arguments[0] = command
        # 如果参数列表为空，则_arguments保持为空
        # 这会导致command()返回空字符串（与C++行为一致）
    
    def fullCommand(self) -> str:
        """
        返回完整的命令行
        
        Returns:
            str: 完整命令行
            
        对应C++: QString ShellCommand::fullCommand() const
        """
        return ' '.join(self._arguments)
    
    def command(self) -> str:
        """
        返回命令
        
        Returns:
            str: 命令，如果没有参数则返回空字符串
            
        对应C++: QString ShellCommand::command() const
        """
        if self._arguments:
            return self._arguments[0]
        else:
            return ""
    
    def arguments(self) -> List[str]:
        """
        返回参数列表
        
        Returns:
            List[str]: 参数列表
            
        对应C++: QStringList ShellCommand::arguments() const
        """
        return self._arguments.copy()
    
    def isRootCommand(self) -> bool:
        """
        返回是否为root命令
        
        Returns:
            bool: 如果是root命令返回True
            
        对应C++: bool ShellCommand::isRootCommand() const
        
        注意：C++版本中此方法未实现（Q_ASSERT(0)），Python版本提供完整实现
        """
        # 检查是否使用了提升权限的命令
        if not self._arguments:
            return False
            
        cmd = self.command().lower()
        
        # 更全面的root命令检测
        rootCommands = [
            'sudo', 'su', 'pkexec', 'gksu', 'kdesu', 'kdesudo',
            'doas', 'run0'  # 添加更多现代的提升权限命令
        ]
        
        # 检查命令本身是否是提升权限的命令
        for rootCmd in rootCommands:
            if cmd.endswith(rootCmd) or cmd == rootCmd:
                return True
        
        return False
    
    def isAvailable(self) -> bool:
        """
        返回命令指定的程序是否存在
        
        Returns:
            bool: 如果程序存在返回True
            
        对应C++: bool ShellCommand::isAvailable() const
        
        注意：C++版本中此方法未实现（Q_ASSERT(0)），Python版本提供完整实现
        """
        if not self._arguments:
            return False
            
        command = self.command()
        if not command:
            return False
        
        # 如果是绝对路径，直接检查文件是否存在
        if os.path.isabs(command):
            return os.path.isfile(command) and os.access(command, os.X_OK)
        
        # 否则在PATH中查找
        return shutil.which(command) is not None
    
    @staticmethod  
    def expand(text_or_items):
        """
        扩展文本中的环境变量
        
        Args:
            text_or_items: 包含环境变量的文本或字符串列表
            
        Returns:
            str或List[str]: 扩展后的文本或字符串列表
            
        对应C++: QString ShellCommand::expand(const QString & text)
                QStringList ShellCommand::expand(const QStringList & items)
        """
        if isinstance(text_or_items, str):
            return ShellCommand._expandEnv(text_or_items)
        elif isinstance(text_or_items, list):
            result = []
            for item in text_or_items:
                result.append(ShellCommand._expandEnv(item))
            return result
        else:
            raise TypeError("expand() requires str or List[str]")
    
    @staticmethod
    def _expandEnv(text: str) -> str:
        """
        扩展文本中的环境变量。被转义的'$'字符会被忽略。
        
        Args:
            text: 要处理的文本
            
        Returns:
            str: 扩展后的文本
            
        对应C++: static bool expandEnv(QString & text)
        
        注意：C++版本返回bool表示是否有变量被扩展，Python版本直接返回结果文本
        """
        if not text:
            return text
        
        result = text
        pos = 0
        
        while True:
            # 查找下一个 '$' - 对应C++: pos = text.indexOf(QLatin1Char('$'), pos)
            pos = result.find('$', pos)
            if pos == -1:
                break
            
            # 跳过转义的 '$' - 对应C++: if ( pos > 0 && text.at(pos-1) == QLatin1Char('\\') )
            if pos > 0 and result[pos-1] == '\\':
                pos += 1
                continue
            
            # 找到变量的结束位置 - 对应C++: pos2 = text.indexOf( QLatin1Char(' '), pos+1 );
            pos2Space = result.find(' ', pos + 1)
            pos2Slash = result.find('/', pos + 1)
            
            # 对应C++逻辑：选择最小的非-1值，或者字符串长度
            if pos2Space == -1 and pos2Slash == -1:
                pos2 = len(result)
            elif pos2Space == -1:
                pos2 = pos2Slash
            elif pos2Slash == -1:
                pos2 = pos2Space
            else:
                pos2 = min(pos2Space, pos2Slash)
            
            # 如果找到了变量的结束位置
            if pos2 >= 0:
                varLen = pos2 - pos
                key = result[pos + 1:pos2]  # 对应C++: QString key = text.mid( pos+1, len-1);
                
                # 获取环境变量的值 - 对应C++: QString::fromLocal8Bit( qgetenv(key.toLocal8Bit().constData()) )
                value = os.environ.get(key, None)
                
                if value is not None:  # 对应C++: if ( !value.isEmpty() )
                    # 替换变量 - 对应C++: text.replace( pos, len, value );
                    result = result[:pos] + value + result[pos2:]
                    pos = pos + len(value)  # 对应C++: pos = pos + value.length();
                else:
                    # 如果变量不存在，不替换，跳过到下一个位置
                    pos = pos2
            else:
                break
        
        return result
    
    def __str__(self) -> str:
        """
        返回字符串表示
        
        Returns:
            str: 完整命令行
        """
        return self.fullCommand()
    
    def __repr__(self) -> str:
        """
        返回对象的字符串表示
        
        Returns:
            str: 对象表示
        """
        return f"ShellCommand({self.fullCommand()!r})"
    
    def __eq__(self, other) -> bool:
        """
        比较两个ShellCommand对象是否相等
        
        Args:
            other: 另一个ShellCommand对象
            
        Returns:
            bool: 是否相等
        """
        if not isinstance(other, ShellCommand):
            return False
        return self._arguments == other._arguments
    
    def __hash__(self) -> int:
        """
        返回对象的哈希值
        
        Returns:
            int: 哈希值
        """
        return hash(tuple(self._arguments)) 