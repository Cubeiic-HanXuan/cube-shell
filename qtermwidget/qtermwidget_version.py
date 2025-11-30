#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
QTermWidget版本定义
从qtermwidget_version.h.in转换而来

Copyright (C) 2020 Axel Kittenberger (axel.kittenberger@univie.ac.at)
转换为Python PySide6版本
"""

# 版本号定义
QTERMWIDGET_VERSION_MAJOR = 2
QTERMWIDGET_VERSION_MINOR = 2
QTERMWIDGET_VERSION_PATCH = 0

# 完整版本号
QTERMWIDGET_VERSION = f"{QTERMWIDGET_VERSION_MAJOR}.{QTERMWIDGET_VERSION_MINOR}.{QTERMWIDGET_VERSION_PATCH}"

def get_version() -> str:
    """
    获取QTermWidget版本号
    
    Returns:
        str: 版本号字符串
    """
    return QTERMWIDGET_VERSION

def get_version_tuple() -> tuple:
    """
    获取版本号元组
    
    Returns:
        tuple: (major, minor, patch)
    """
    return (QTERMWIDGET_VERSION_MAJOR, QTERMWIDGET_VERSION_MINOR, QTERMWIDGET_VERSION_PATCH)

def get_version_info() -> dict:
    """
    获取详细版本信息
    
    Returns:
        dict: 包含版本信息的字典
    """
    return {
        'major': QTERMWIDGET_VERSION_MAJOR,
        'minor': QTERMWIDGET_VERSION_MINOR,
        'patch': QTERMWIDGET_VERSION_PATCH,
        'version': QTERMWIDGET_VERSION,
        'name': 'QTermWidget',
        'vendor': 'LXQt',
        'copyright': '(C) 2022-2025 LXQt',
        'url': 'https://github.com/lxqt/qtermwidget',
        'license': 'GPLv2'
    }

# 版本比较函数
def version_check(major: int, minor: int, patch: int) -> int:
    """
    检查版本号
    
    Args:
        major: 主版本号
        minor: 次版本号  
        patch: 补丁版本号
        
    Returns:
        int: 版本比较结果
    """
    current = (QTERMWIDGET_VERSION_MAJOR, QTERMWIDGET_VERSION_MINOR, QTERMWIDGET_VERSION_PATCH)
    target = (major, minor, patch)
    
    if current > target:
        return 1
    elif current < target:
        return -1
    else:
        return 0

# 兼容性常量
VERSION_MAJOR = QTERMWIDGET_VERSION_MAJOR
VERSION_MINOR = QTERMWIDGET_VERSION_MINOR  
VERSION_PATCH = QTERMWIDGET_VERSION_PATCH
VERSION = QTERMWIDGET_VERSION

# 版本信息类
class VersionInfo:
    """版本信息类"""
    
    major = QTERMWIDGET_VERSION_MAJOR
    minor = QTERMWIDGET_VERSION_MINOR
    patch = QTERMWIDGET_VERSION_PATCH
    version = QTERMWIDGET_VERSION
    
    @classmethod
    def __str__(cls):
        return cls.version
    
    @classmethod  
    def tuple(cls):
        return (cls.major, cls.minor, cls.patch)
    
    @classmethod
    def dict(cls):
        return get_version_info() 