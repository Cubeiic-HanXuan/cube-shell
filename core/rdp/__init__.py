"""RDP 远程桌面模块（基于 aardwolf）。

对外导出可嵌入标签页的 RDPWidget 以及连接 URL 构造工具。
"""
from core.rdp.rdp_client import RDPWidget, RDPClientConsoleSettings, build_rdp_url

__all__ = ["RDPWidget", "RDPClientConsoleSettings", "build_rdp_url"]
