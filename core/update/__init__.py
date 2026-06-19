"""
cube-shell 软件更新子包。

公共入口:
- ``UpdateWorker``:后台检查/下载线程
- ``compare_versions`` / ``is_newer``:版本比较
- ``installer``:跨平台安装模块(供主线程在下载完成后调用)
"""
from .version import compare_versions, is_newer
from .worker import UpdateWorker

__all__ = ["UpdateWorker", "compare_versions", "is_newer"]
