"""
堡垒机（JumpServer）连接客户端模块

负责：
- 解析 URL Scheme 中的连接信息
- 编排自动连接流程（创建 Tab → 设置状态 → 发起 SSH 连接）
- URL 事件过滤器（UrlEventFilter）
- 启动阶段 URL 扫描与延迟处理辅助函数

从 cube-shell.py MainDialog 中提取，保持行为不变。
"""
import time

from PySide6.QtCore import QTimer, QObject, QEvent

from core.url_dispatch.url_handler import parse_jms_url, parse_ssh_url, parse_cubeshell_url
from function import util


class UrlEventFilter(QObject):
    """事件过滤器：拦截 QFileOpenEvent，比 event() 覆盖更可靠（兼容 Nuitka 编译）

    Nuitka 编译后，Python 对 QApplication 虚方法 event() 的重写可能被 shiboken
    的 C++ 虚派发机制绕过。EventFilter 注册在 Qt 事件分发管道中，不依赖虚方法覆盖，
    因此在编译后仍然可靠工作。
    """

    def __init__(self, app):
        super().__init__(app)
        self._app = app

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FileOpen:
            # 优先用 file() 获取原始字符串，避免 QUrl 对长 Base64 URL 验证失败
            url = event.file()
            if not url:
                url = event.url().toString()
            if not url:
                try:
                    encoded = event.url().toEncoded()
                    if encoded:
                        url = bytes(encoded).decode('utf-8', errors='replace')
                except Exception:
                    pass

            print(f"[UrlEventFilter] FileOpen intercepted, URL: {url[:80] if url else 'EMPTY'}...")

            if url and (url.startswith('jms://') or url.startswith('ssh://') or url.startswith('cubeshell://')):
                if hasattr(self._app, 'main_window') and self._app.main_window:
                    print(f"[UrlEventFilter] Dispatching to handle_open_url")
                    self._app.main_window.handle_open_url(url)
                else:
                    print(f"[UrlEventFilter] Caching as pending_url")
                    self._app.pending_url = url
                return True
        return super().eventFilter(obj, event)


def create_url_event_filter(app):
    """创建并注册 URL 事件过滤器，返回 filter 实例"""
    url_filter = UrlEventFilter(app)
    app.installEventFilter(url_filter)
    return url_filter


def scan_argv_for_url(argv):
    """扫描 sys.argv 中的 jms:// 或 ssh:// URL，返回 connection_info 或 None

    处理以下情况：
    1. argparse 未识别的 remaining 参数中包含 URL
    2. sys.argv 直接扫描（Nuitka .app 打包后 URL Scheme 启动）
    3. macOS .app 传递的 -url 参数
    """
    for i, arg in enumerate(argv[1:], start=1):
        if arg.startswith('jms://') or arg.startswith('ssh://') or arg.startswith('cubeshell://'):
            print(f"[BastionClient] Found URL in argv: {arg[:50]}...")
            if arg.startswith('jms://'):
                return parse_jms_url(arg)
            elif arg.startswith('ssh://'):
                return parse_ssh_url(arg)
            elif arg.startswith('cubeshell://'):
                return parse_cubeshell_url(arg)
        # 处理 -url flag 格式
        if arg == '-url' and i + 1 < len(argv):
            url_val = argv[i + 1]
            if url_val.startswith('jms://') or url_val.startswith('ssh://') or url_val.startswith('cubeshell://'):
                print(f"[BastionClient] Found URL via -url flag: {url_val[:50]}...")
                if url_val.startswith('jms://'):
                    return parse_jms_url(url_val)
                elif url_val.startswith('ssh://'):
                    return parse_ssh_url(url_val)
                elif url_val.startswith('cubeshell://'):
                    return parse_cubeshell_url(url_val)
    return None


def setup_deferred_url_check(app, window, connection_info):
    """设置 QTimer 延迟检查 pending URL（解决 macOS FileOpen 事件时机问题）

    处理两种情况：
    1. pending URL 已在窗口创建前到达 → 立即处理
    2. pending URL 可能在 app.exec() 后才到达 → 500ms 延迟检查
    """
    # 立即处理已到达的 pending URL
    if app.pending_url and not connection_info:
        print(f"[BastionClient] Processing pending URL after window ready: {app.pending_url[:50]}...")
        window.handle_open_url(app.pending_url)
        app.pending_url = None

    # 延迟检查：macOS FileOpen 事件可能在 app.exec() 启动事件循环后才到达
    if not connection_info:
        def _check_pending_url():
            if app.pending_url:
                print(f"[BastionClient] Deferred pending URL processing: {app.pending_url[:50]}...")
                window.handle_open_url(app.pending_url)
                app.pending_url = None
            else:
                print(f"[BastionClient] Deferred check: no pending URL found after 500ms")
        QTimer.singleShot(500, _check_pending_url)


class BastionClient:
    """封装堡垒机连接逻辑，通过 main_window 引用操作 UI"""

    def __init__(self, main_window):
        """
        Args:
            main_window: MainDialog 实例，提供 add_new_tab / _connect_with_qterm_widget 等方法
        """
        self._main_window = main_window

    def handle_url(self, url: str):
        """
        处理 URL Scheme 打开事件（应用已运行时）

        解析 jms:// 或 ssh:// URL，提取连接信息后发起自动连接。

        Args:
            url: 完整的 URL 字符串，如 jms://... 或 ssh://user@host:port
        """
        print(f"[BastionClient] handle_url called with: {url}")

        connection_info = None
        if url.startswith('jms://'):
            connection_info = parse_jms_url(url)
        elif url.startswith('ssh://'):
            connection_info = parse_ssh_url(url)

        print(f"[BastionClient] Parsed connection_info: {connection_info}")

        if connection_info:
            self.auto_connect(connection_info)

    def auto_connect(self, connection_info: dict):
        """
        通过连接信息自动发起 SSH 连接

        处理逻辑：
        1. 解析 host/port/user/password 等参数
        2. 处理 JumpServer token 模式
        3. 创建新 Tab 并发起 SSH 连接

        Args:
            connection_info: 连接参数字典，包含 host/port/user/password 等字段
        """
        print(f"[BastionClient] auto_connect called with: {connection_info}")
        if not connection_info:
            return

        info = connection_info
        host = info.get('host')
        port = info.get('port', 22)
        user = info.get('user')
        password = info.get('password')
        key_type = info.get('key_type', '')
        key_file = info.get('key_file', '')
        token = info.get('token')
        server = info.get('server')

        # JumpServer token 模式：通过 token 连接 JumpServer SSH 代理（koko）
        if not host and token and server:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(server)
                host = parsed.hostname
                port = 2222  # JumpServer koko SSH 代理默认端口
                user = f"JMS-{token}"
                password = ''
                print(f"[BastionClient] JumpServer token mode: host={host}, port={port}, user={user}")
            except Exception as e:
                print(f"[BastionClient] Failed to parse JumpServer server URL: {e}")
                return

        if not host:
            print("[BastionClient] auto_connect: no host provided, skipping")
            util.logger.warning("auto_connect: no host provided, skipping")
            return

        mw = self._main_window
        try:
            # 构造 Tab 名称
            tab_name = f"{user}@{host}" if user else host

            # 创建新 Tab 并获取终端
            tab_index, terminal = mw.add_new_tab(tab_name)
            if tab_index == -1 or terminal is None:
                util.logger.error("auto_connect: failed to create new tab")
                return

            # 设置连接状态
            mw.is_connecting_lock = True
            mw._last_connect_attempt_ts = int(time.time() * 1000)
            mw._set_connecting_ui(True)

            # 复用现有连接逻辑
            mw._connect_with_qterm_widget(
                host, port, user or '', password or '',
                key_type, key_file, terminal
            )

            # 超时保护
            QTimer.singleShot(10000,
                              lambda: mw._release_connecting_state() if mw.is_connecting_lock else None)

        except Exception as e:
            util.logger.error(f"Auto-connect failed: {e}")
            mw._release_connecting_state()
