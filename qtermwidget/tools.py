"""
QTermWidget工具模块 - 提供键盘布局和颜色方案目录管理功能

这个模块是从Qt C++代码转换而来，提供了：
- 获取键盘布局目录
- 管理自定义颜色方案目录  
- 获取颜色方案目录列表
- 日志记录功能

版权信息：对应原始C++文件 tools.cpp 和 tools.h
"""

import logging
import os
import sys
from typing import List

from PySide6.QtCore import QCoreApplication, QDir

# 设置日志记录器 - 对应C++: Q_LOGGING_CATEGORY(qtermwidgetLogger, "qtermwidget", QtWarningMsg)
qtermwidgetLogger = logging.getLogger("qtermwidget")
qtermwidgetLogger.setLevel(logging.WARNING)

# 为了兼容性，添加snake_case别名
qtermwidget_logger = qtermwidgetLogger

# 默认指向我们的qtermwidget_python包内的color-schemes目录
_package_dir = os.path.dirname(os.path.abspath(__file__))

# 模拟C++中的编译时宏常量
# 这些常量通常在编译时通过-D参数定义，这里使用环境变量作为替代
_default_kb_layouts_dir = os.path.join(_package_dir, 'kb-layouts')
KB_LAYOUT_DIR = os.environ.get('KB_LAYOUT_DIR', _default_kb_layouts_dir)

# 修改：设置正确的默认颜色方案目录路径
_default_colorschemes_dir = os.path.join(_package_dir, 'color-schemes')
COLORSCHEMES_DIR = os.environ.get('COLORSCHEMES_DIR', _default_colorschemes_dir)

# 存储自定义颜色方案目录 - 对应C++: namespace { QStringList custom_color_schemes_dirs; }
_custom_color_schemes_dirs: List[str] = []


def getKbLayoutDir() -> str:
    """
    获取键盘布局文件的可能位置的辅助函数。
    默认使用 KB_LAYOUT_DIR (linux/BSD/macports)。
    但在某些情况下（Apple bundle）可能有更多位置。
    
    Returns:
        str: 键盘布局目录路径，如果未找到则返回空字符串
        
    对应C++: QString get_kb_layout_dir()
    """
    # 对应C++: QString rval = QString();
    rval = ""
    # 对应C++: QString k(QLatin1String(KB_LAYOUT_DIR));
    k = KB_LAYOUT_DIR
    # 对应C++: QDir d(k);
    d = QDir(k)
    
    # 对应C++: if (d.exists())
    if d.exists():
        # 对应C++: rval = k.append(QLatin1Char('/'));
        # 注意：C++这里直接修改了k，但我们需要避免副作用
        rval = k + '/' if not k.endswith('/') else k
        return rval
    
    # 对应C++: #ifdef Q_OS_MAC
    if sys.platform == 'darwin':
        # 对应C++: d.setPath(QCoreApplication::applicationDirPath() + QLatin1String("/kb-layouts/"));
        app_dir_path = QCoreApplication.applicationDirPath()
        kb_layouts_path = app_dir_path + "/kb-layouts/"
        d.setPath(kb_layouts_path)
        
        # 对应C++: if (d.exists()) return QCoreApplication::applicationDirPath() + QLatin1String("/kb-layouts/");
        if d.exists():
            return kb_layouts_path
        
        # 对应C++: d.setPath(QCoreApplication::applicationDirPath() + QLatin1String("/../Resources/kb-layouts/"));
        resources_path = app_dir_path + "/../Resources/kb-layouts/"
        d.setPath(resources_path)
        
        # 对应C++: if (d.exists()) return QCoreApplication::applicationDirPath() + QLatin1String("/../Resources/kb-layouts/");
        if d.exists():
            return resources_path
    
    # 对应C++: return QString();
    return ""


def addCustomColorSchemeDir(customDir: str) -> None:
    """
    添加自定义颜色方案位置的辅助函数。
    
    Args:
        customDir: 要添加的自定义目录路径
        
    对应C++: void add_custom_color_scheme_dir(const QString& custom_dir)
    """
    global _custom_color_schemes_dirs
    # 对应C++: if (!custom_color_schemes_dirs.contains(custom_dir))
    if customDir not in _custom_color_schemes_dirs:
        # 对应C++: custom_color_schemes_dirs << custom_dir;
        _custom_color_schemes_dirs.append(customDir)


# 为了兼容性，添加snake_case版本的函数名
def add_custom_color_scheme_dir(customDir: str) -> None:
    """snake_case版本的addCustomColorSchemeDir，用于向后兼容"""
    return addCustomColorSchemeDir(customDir)


def getColorSchemesDirs() -> List[str]:
    """
    获取颜色方案可能位置的辅助函数。
    默认使用 COLORSCHEMES_DIR (linux/BSD/macports)。
    但在某些情况下（Apple bundle）可能有更多位置。
    
    Returns:
        List[str]: 颜色方案目录路径列表
        
    对应C++: const QStringList get_color_schemes_dirs()
    """
    # 对应C++: QStringList rval;
    rval = []
    # 对应C++: QString k(QLatin1String(COLORSCHEMES_DIR));
    k = COLORSCHEMES_DIR
    # 对应C++: QDir d(k);
    d = QDir(k)

    # 对应C++: if (d.exists()) rval << k.append(QLatin1Char('/'));
    if d.exists():
        # 注意：C++这里直接修改了k，我们需要复制这个行为
        k_with_slash = k + '/' if not k.endswith('/') else k
        rval.append(k_with_slash)

    # 对应C++: #ifdef Q_OS_MAC
    if sys.platform == 'darwin':
        app_dir_path = QCoreApplication.applicationDirPath()

        # 对应C++: d.setPath(QCoreApplication::applicationDirPath() + QLatin1String("/color-schemes/"));
        color_schemes_path = app_dir_path + "/color-schemes/"
        d.setPath(color_schemes_path)

        # 对应C++: if (d.exists()) { if (!rval.isEmpty()) rval.clear(); rval << (...); }
        if d.exists():
            if rval:  # 对应C++: if (!rval.isEmpty())
                rval.clear()
            rval.append(color_schemes_path)

        # 对应C++: d.setPath(QCoreApplication::applicationDirPath() + QLatin1String("/../Resources/color-schemes/"));
        resources_path = app_dir_path + "/../Resources/color-schemes/"
        d.setPath(resources_path)

        # 对应C++: if (d.exists()) { if (!rval.isEmpty()) rval.clear(); rval << (...); }
        if d.exists():
            if rval:  # 对应C++: if (!rval.isEmpty())
                rval.clear()
            rval.append(resources_path)

    # 对应C++: for (const QString& custom_dir : std::as_const(custom_color_schemes_dirs))
    for customDir in _custom_color_schemes_dirs:
        # 对应C++: d.setPath(custom_dir);
        d.setPath(customDir)
        # 对应C++: if (d.exists()) rval << custom_dir;
        if d.exists():
            rval.append(customDir)

    # 对应C++: #ifdef QT_DEBUG
    if qtermwidgetLogger.isEnabledFor(logging.DEBUG):
        # 对应C++: if(!rval.isEmpty()) { qDebug() << "Using color-schemes: " << rval; }
        if rval:
            qtermwidgetLogger.debug(f"Using color-schemes: {rval}")
        else:
            # 对应C++: qDebug() << "Cannot find color-schemes in any location!";
            qtermwidgetLogger.debug("Cannot find color-schemes in any location!")

    return rval


# 为了兼容性，添加snake_case版本的函数名
def get_color_schemes_dirs() -> List[str]:
    """snake_case版本的getColorSchemesDirs，用于向后兼容"""
    return getColorSchemesDirs()

def get_kb_layout_dir() -> str:
    """snake_case版本的getKbLayoutDir，用于向后兼容"""
    return getKbLayoutDir()


def clearCustomColorSchemeDirs() -> None:
    """
    清除所有自定义颜色方案目录。
    这是Python版本新增的便利函数，C++原版中没有对应实现。

    Note:
        Python扩展方法 - C++版本无对应
    """
    global _custom_color_schemes_dirs
    _custom_color_schemes_dirs.clear()


def getCustomColorSchemeDirs() -> List[str]:
    """
    获取当前注册的所有自定义颜色方案目录。
    这是Python版本新增的便利函数，C++原版中没有对应实现。

    Returns:
        List[str]: 自定义颜色方案目录列表的副本

    Note:
        Python扩展方法 - C++版本无对应
        返回副本以防止意外修改内部状态
    """
    return _custom_color_schemes_dirs.copy()


# 导出的函数和变量 - 使用C++风格命名
__all__ = [
    # 主要函数 - C++风格
    'getKbLayoutDir',
    'getColorSchemesDirs', 
    'addCustomColorSchemeDir',
    'clearCustomColorSchemeDirs',
    'getCustomColorSchemeDirs',
    
    # 兼容性别名 - snake_case风格
    'get_kb_layout_dir',
    'get_color_schemes_dirs',
    'add_custom_color_scheme_dir',
    
    # 日志记录器
    'qtermwidgetLogger',
    'qtermwidget_logger',
    
    # 常量
    'KB_LAYOUT_DIR',
    'COLORSCHEMES_DIR'
]