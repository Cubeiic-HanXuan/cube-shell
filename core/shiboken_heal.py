"""
ARM shiboken6 None 引用计数泄漏全局修复模块

根因：ARM 架构上 shiboken6 对 QPainter/QFont 等 void 方法的包装器
每次调用都会多执行一次 Py_DECREF(Py_None)，导致 None 引用计数
持续下降，最终触发 CPython fatal error: none_dealloc。

诊断数据证实：
  H.29 fillRect | NoneRC=16  → painter.save()    泄漏 -1
  H.30 restore  | NoneRC=15  → painter.fillRect() 泄漏 -1
  H.40 setPen   | NoneRC=14  → painter.restore()  泄漏 -1
  ...每次 void shiboken6 调用泄漏 1 个 NoneRC

修复方案：
  - 在 QApplication 创建后立即执行一次大量 Py_IncRef(None) 预充
  - 启动 200ms 周期定时器持续检测并补充
  - 覆盖所有 widget 的所有事件路径，无需逐个 widget 添加保护
"""

import sys
import ctypes

_heal_initialized = False
_heal_available = False
_heal_timer = None  # 持有引用防止 GC


def _heal_none_refcount(amount=1000000):
    """永久增加 None 的引用计数，抵消 shiboken6 的累积泄漏。
    使用直接内存写入（O(1)），而非循环调用 Py_IncRef。
    None 是单例对象，生命周期等同进程，增加引用计数无副作用。
    """
    global _heal_initialized, _heal_available
    if not _heal_initialized:
        _heal_initialized = True
        try:
            # 验证 ob_refcnt 在偏移量 0 处（标准 CPython 布局）
            addr = id(None)
            direct = ctypes.c_ssize_t.from_address(addr).value
            via_sys = sys.getrefcount(None) - 1  # getrefcount 自己加 1
            # 允许小范围偏差（多线程环境）
            if abs(direct - via_sys) < 100:
                _heal_available = True
            else:
                print(f"[shiboken_heal] ob_refcnt 偏移验证失败: direct={direct}, sys={via_sys}")
                _heal_available = False
        except Exception as e:
            print(f"[shiboken_heal] 初始化失败: {e}")
            _heal_available = False
    if not _heal_available:
        return
    try:
        refcnt = ctypes.c_ssize_t.from_address(id(None))
        refcnt.value += amount
    except Exception:
        pass


def check_and_heal_none():
    """检查 None 引用计数，低于阈值时自动补充"""
    if sys.getrefcount(None) < 200000:
        _heal_none_refcount()


def install_global_heal(app):
    """在 QApplication 上安装全局 None 引用计数保护。
    
    1. 立即执行一次预充（+50000）
    2. 启动 200ms 周期定时器持续补充
    
    调用时机：QApplication 创建后、任何 widget 创建前。
    """
    from PySide6.QtCore import QTimer

    global _heal_timer

    # 立即预充一次（+1000000，O(1) 直接内存写入，纳秒级）
    _heal_none_refcount()
    print(f"[shiboken_heal] None refcount healed to: {sys.getrefcount(None)}")

    # 启动周期定时器（每 100ms 检查一次）
    _heal_timer = QTimer(app)
    _heal_timer.setInterval(100)
    _heal_timer.timeout.connect(check_and_heal_none)
    _heal_timer.start()
