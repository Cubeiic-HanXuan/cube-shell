"""基于 aardwolf 的 RDP 客户端，提供可嵌入标签页的 RDPWidget。

本模块从 tests/aardpclient_pyside6.py 移植并重构而来：
- RDPInterfaceThread：连接管理 worker，asyncio 事件循环跑在独立线程，
  视频帧经 Qt Signal 回主线程，键鼠/剪贴板输入经 queue.Queue 下发（逻辑保持一致）。
- RDPClientQTGUI(QMainWindow) → RDPWidget(QWidget)：改为可嵌入 ShellTab 的控件，
  支持键盘+鼠标、剪贴板文本同步(Ctrl+V)、画面自适应缩放、拖拽传文件。
"""
import asyncio
import hashlib
import os
import pickle
import queue
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import quote

import pyperclip
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from aardwolf import logger
from aardwolf.commons.factory import RDPConnectionFactory
from aardwolf.commons.iosettings import RDPIOSettings
from aardwolf.commons.queuedata import RDPDATATYPE
from aardwolf.commons.queuedata.clipboard import RDP_CLIPBOARD_DATA_TXT
from aardwolf.commons.queuedata.constants import MOUSEBUTTON
from aardwolf.commons.queuedata.keyboard import RDP_KEYBOARD_SCANCODE, RDP_KEYBOARD_UNICODE
from aardwolf.commons.queuedata.mouse import RDP_MOUSE
from aardwolf.extensions.RDPECLIP.protocol.formatlist import CLIPBRD_FORMAT
from aardwolf.keyboard import VK_MODIFIERS

# 确保 :remote.png 等资源已注册（与 ui 模块一致的引用方式）
import icons.icons  # noqa: F401

# ============== ASN.1 codec 预编译缓存（修复 RDP 首屏卡 ~15s 的根因）==============
# aardwolf.connection 每次连接都用 asn1tools.compile_string 现场编译 3 个 ASN.1 schema。
# 这是纯 Python 的 CPU 重活：独立小脚本里约 0.2s，但在 cube-shell 这种多线程 GUI 进程里
# 会被 GIL 争用拖到 ~15s（实测 3.6s+3.6s+8.5s）。直接在进程内（即便后台线程）编译会长时间
# 占住 GIL，拖慢整个 GUI 甚至启动。因此采用「子进程编译 + 磁盘缓存」：
#   1) 编译结果（可 pickle，每个约 48KB）按 (schema, codec) 全局缓存，连接时直接命中；
#   2) 缓存的生成放到独立子进程里完成（不抢 GUI 的 GIL），结果落地磁盘；
#   3) 之后每次启动直接从磁盘 unpickle（毫秒级），永不再编译。
# 预热线程全程只做子进程/磁盘 I/O，等待时释放 GIL，GUI 不卡。
_asn1_cache = {}
_asn1_cache_lock = threading.Lock()


def _install_asn1_cache():
    """拦截 aardwolf 的 asn1tools.compile_string，命中缓存则直接返回，避免进程内重复编译。"""
    if getattr(_install_asn1_cache, "_done", False):
        return
    _install_asn1_cache._done = True
    try:
        import aardwolf.connection as _rdpconn
        _orig_compile = _rdpconn.asn1tools.compile_string

        def cached_compile_string(spec, codec='ber', *args, **kwargs):
            # spec 为 aardwolf 模块级常量字符串，对象恒定，可用 id() 作键
            key = (id(spec), codec)
            cached = _asn1_cache.get(key)
            if cached is not None:
                return cached
            with _asn1_cache_lock:
                cached = _asn1_cache.get(key)
                if cached is not None:
                    return cached
                # 兜底：预热失败时这里仍只会编译一次（会卡这一次，但之后命中），
                # 并把结果落盘，使下次启动可直接从磁盘加载（冻结打包环境的自愈路径）。
                result = _orig_compile(spec, codec, *args, **kwargs)
                _asn1_cache[key] = result
                _save_cache_to_disk()
                return result

        _rdpconn.asn1tools.compile_string = cached_compile_string
    except Exception as e:
        logger.warning('[RDP] 安装 ASN.1 缓存失败: %s' % e)


def _install_read_diag():
    """诊断：unicomm UniConnection.read() 在异常时 yield None，把真实异常吞掉，
    导致 __x224_reader 只看到 'cannot unpack NoneType'。这里替换为会打印真实异常的版本，
    用于区分"服务端 RST(ConnectionResetError)"与"解密/解析出错(crypto desync/坏包)"。
    定位完滚轮问题后可移除。
    """
    if getattr(_install_read_diag, "_done", False):
        return
    _install_read_diag._done = True
    try:
        from asysocks.unicomm.common.connection import UniConnection

        async def read_diag(self):
            try:
                data = None
                while self.closing is False:
                    async for result in self.packetizer.data_in(data):
                        if result is None:
                            break
                        yield result
                    data = await self.reader.read(self.packetizer.buffer_size)
                    if data == b'':
                        break
                data = None
                async for result in self.packetizer.data_in(data):
                    if result is None:
                        break
                    yield result
            except Exception as e:
                logger.error('[RDP-diag] read 真实异常(被吞前): %r' % e)
                yield None

        UniConnection.read = read_diag
    except Exception as e:
        logger.warning('[RDP] read 诊断补丁失败: %s' % e)


def _install_wheel_steps_patch():
    """替换 aardwolf 的 RDPConnection.send_mouse，修正滚轮两个问题：

    1. __external_reader 派发 MOUSE 时不传 steps(旋转量恒为 0)→ 服务端不滚动。
       滚轮键 steps 为 0 时补 120(WHEEL_DELTA，一格)。
    2. aardwolf 原版 WHEEL_DOWN 分支只设 WHEEL_NEGATIVE(0x0100)，漏设 WHEEL(0x0200)。
       按 RDP 规范垂直滚轮事件必须带 PTRFLAGS_WHEEL，缺失则指针标志为无效组合，
       Windows RDP 服务端校验失败会直接 RST 断连(实测发一个 WHEEL_DOWN 即被 reset)。
       WHEEL_UP 原本就带 WHEEL 故正常。这里给 WHEEL_DOWN 补上 WHEEL 标志。

    用替换整方法而非包装：bug 在原方法内部的标志位构建，包装层无法改。

    滚轮事件必须经 in_q 由 __external_reader 串行处理，不能像 clipboard 那样用
    run_coroutine_threadsafe 直连 conn.send_mouse —— RDP 用 RC4 有状态流加密，
    并发 send_mouse 会让 PacketCount/RC4 流错乱，服务端解密失败直接 RST 断连。
    """
    if getattr(_install_wheel_steps_patch, "_done", False):
        return
    _install_wheel_steps_patch._done = True
    try:
        import aardwolf.connection as _rdpconn
        from aardwolf.connection import RDPConnection
        # 从 aardwolf.connection 命名空间取出构造报文所需的类型(均已在其中导入)
        TS_SHAREDATAHEADER = _rdpconn.TS_SHAREDATAHEADER
        STREAM_TYPE = _rdpconn.STREAM_TYPE
        PDUTYPE2 = _rdpconn.PDUTYPE2
        TS_POINTER_EVENT = _rdpconn.TS_POINTER_EVENT
        PTRFLAGS = _rdpconn.PTRFLAGS
        TS_INPUT_EVENT = _rdpconn.TS_INPUT_EVENT
        TS_INPUT_PDU_DATA = _rdpconn.TS_INPUT_PDU_DATA
        SEC_HDR_FLAG = _rdpconn.SEC_HDR_FLAG
        TS_SECURITY_HEADER = _rdpconn.TS_SECURITY_HEADER
        _wheel_seq = {'n': 0}  # 滚轮发送计数(诊断用，确认后可删)

        async def send_mouse_fixed(self, button, xPos, yPos, is_pressed, steps=0):
            try:
                if xPos < 0 or yPos < 0:
                    return True, None

                # 滚轮旋转量补回(队列派发不传 steps)
                if steps == 0 and button in (MOUSEBUTTON.MOUSEBUTTON_WHEEL_UP,
                                             MOUSEBUTTON.MOUSEBUTTON_WHEEL_DOWN):
                    steps = 120  # WHEEL_DELTA：一格滚轮，与 Qt angleDelta 单位一致

                data_hdr = TS_SHAREDATAHEADER()
                data_hdr.shareID = 0x103EA
                data_hdr.streamID = STREAM_TYPE.MED
                data_hdr.pduType2 = PDUTYPE2.INPUT

                mouse = TS_POINTER_EVENT()
                mouse.pointerFlags = 0
                if is_pressed is True:
                    mouse.pointerFlags |= PTRFLAGS.DOWN
                if button == MOUSEBUTTON.MOUSEBUTTON_LEFT:
                    mouse.pointerFlags |= PTRFLAGS.BUTTON1
                if button == MOUSEBUTTON.MOUSEBUTTON_RIGHT:
                    mouse.pointerFlags |= PTRFLAGS.BUTTON2
                if button == MOUSEBUTTON.MOUSEBUTTON_MIDDLE:
                    mouse.pointerFlags |= PTRFLAGS.BUTTON3
                if button == MOUSEBUTTON.MOUSEBUTTON_HOVER:
                    mouse.pointerFlags |= PTRFLAGS.MOVE
                if button == MOUSEBUTTON.MOUSEBUTTON_WHEEL_UP:
                    mouse.pointerFlags |= PTRFLAGS.WHEEL
                    mouse.pointerFlags |= (PTRFLAGS.WheelRotationMask & steps)
                if button == MOUSEBUTTON.MOUSEBUTTON_WHEEL_DOWN:
                    # 修正 aardwolf bug：必须同时设 WHEEL，否则服务端判为无效标志组合 RST
                    mouse.pointerFlags |= PTRFLAGS.WHEEL
                    mouse.pointerFlags |= PTRFLAGS.WHEEL_NEGATIVE
                    mouse.pointerFlags |= (PTRFLAGS.WheelRotationMask & steps)

                mouse.xPos = xPos
                mouse.yPos = yPos

                if button in (MOUSEBUTTON.MOUSEBUTTON_WHEEL_UP,
                              MOUSEBUTTON.MOUSEBUTTON_WHEEL_DOWN):
                    _wheel_seq['n'] += 1
                    logger.error('[RDP-diag] 滚轮发送 #%d button=%s steps=%d flags=0x%04x'
                                 % (_wheel_seq['n'], button.name, steps, int(mouse.pointerFlags)))

                clii_mouse = TS_INPUT_EVENT.from_input(mouse)
                cli_input = TS_INPUT_PDU_DATA()
                cli_input.slowPathInputEvents.append(clii_mouse)

                sec_hdr = None
                if self.cryptolayer is not None:
                    sec_hdr = TS_SECURITY_HEADER()
                    sec_hdr.flags = SEC_HDR_FLAG.ENCRYPT
                    sec_hdr.flagsHi = 0

                # __joined_channels 是 RDPConnection 内部双下划线属性，外部访问需用改名
                joined = getattr(self, '_RDPConnection__joined_channels', None)
                mcs_channel_id = joined['MCS'].channel_id if joined is not None else 0x03EB
                await self.handle_out_data(cli_input, sec_hdr, data_hdr, None,
                                           mcs_channel_id, False)
            except Exception as e:
                logger.error(f"[RDP-diag] send_mouse_fixed 异常: {e}, {traceback.format_exc()}")
                return None, e

        RDPConnection.send_mouse = send_mouse_fixed
    except Exception as e:
        logger.warning('[RDP] 安装滚轮补丁失败: %s' % e)


def _asn1_cache_file():
    base = os.path.expanduser('~/.cube-shell')
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    return os.path.join(base, 'rdp_asn1_cache.pkl')


def _asn1_fingerprint():
    # schema 内容变了（aardwolf 升级）就让磁盘缓存失效，重新编译
    h = hashlib.sha256()
    h.update(MCSPDU_ver_2.encode('utf-8'))
    h.update(GCCPDU.encode('utf-8'))
    return h.hexdigest()


def _asn1_tag_map():
    return {
        ('mcs', 'ber'): (id(MCSPDU_ver_2), 'ber'),
        ('mcs', 'per'): (id(MCSPDU_ver_2), 'per'),
        ('gcc', 'per'): (id(GCCPDU), 'per'),
    }


def _populate_cache_from_codecs(codecs):
    """codecs: {('mcs','ber'):..,('mcs','per'):..,('gcc','per'):..} → 映射到本进程 id() 键。"""
    with _asn1_cache_lock:
        for tag, key in _asn1_tag_map().items():
            if tag in codecs:
                _asn1_cache[key] = codecs[tag]


def _save_cache_to_disk():
    """把当前内存里的 3 个 codec 落盘（best-effort，原子替换）。仅在三者齐全时写。"""
    try:
        codecs = {}
        for tag, key in _asn1_tag_map().items():
            if key in _asn1_cache:
                codecs[tag] = _asn1_cache[key]
        if len(codecs) != 3:
            return
        cache_path = _asn1_cache_file()
        tmp = cache_path + '.save'
        with open(tmp, 'wb') as f:
            pickle.dump({'fp': _asn1_fingerprint(), 'codecs': codecs}, f)
        os.replace(tmp, cache_path)
    except Exception:
        pass


# 子进程脚本：只 import asn1tools（轻量），读入 schema 字符串，编译后把结果 pickle 落盘。
# 在独立进程里跑，CPU/GIL 与 GUI 完全隔离。
_PREWARM_CHILD = (
    "import sys, pickle, asn1tools\n"
    "inp = pickle.load(open(sys.argv[1], 'rb'))\n"
    "codecs = {\n"
    "  ('mcs','ber'): asn1tools.compile_string(inp['mcs'], 'ber'),\n"
    "  ('mcs','per'): asn1tools.compile_string(inp['mcs'], 'per'),\n"
    "  ('gcc','per'): asn1tools.compile_string(inp['gcc'], 'per'),\n"
    "}\n"
    "pickle.dump({'fp': inp['fp'], 'codecs': codecs}, open(sys.argv[2], 'wb'))\n"
)


def _prewarm_asn1():
    """后台预热：磁盘命中则直接读；否则子进程编译并落盘。全程只做 I/O，不占 GUI 的 GIL。"""
    try:
        fp = _asn1_fingerprint()
        cache_path = _asn1_cache_file()

        # 1) 磁盘缓存命中 → 直接 unpickle（毫秒级）
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    blob = pickle.load(f)
                if blob.get('fp') == fp:
                    _populate_cache_from_codecs(blob['codecs'])
                    logger.info('[RDP] ASN.1 codec 已从磁盘缓存加载')
                    return
            except Exception:
                pass  # 缓存损坏/不兼容，走重编译

        # 2) 子进程编译（独立进程，不抢 GUI 的 GIL），结果落盘。
        # 冻结打包(PyInstaller 等)环境下 sys.executable 是 GUI 本体，用 -c 会重启整个程序，
        # 此时退回到「连接时进程内编译并落盘」的自愈路径（首次连接卡一次，之后命中）。
        if getattr(sys, 'frozen', False):
            logger.info('[RDP] 冻结环境跳过子进程预编译，改由首次连接时按需编译并缓存')
            return
        in_path = cache_path + '.in'
        out_path = cache_path + '.tmp'
        with open(in_path, 'wb') as f:
            pickle.dump({'mcs': MCSPDU_ver_2, 'gcc': GCCPDU, 'fp': fp}, f)
        try:
            proc = subprocess.run(
                [sys.executable, '-c', _PREWARM_CHILD, in_path, out_path],
                capture_output=True, timeout=120)
            if os.path.exists(out_path):
                with open(out_path, 'rb') as f:
                    blob = pickle.load(f)
                _populate_cache_from_codecs(blob['codecs'])
                os.replace(out_path, cache_path)  # 原子落地，下次启动直接命中
                logger.info('[RDP] ASN.1 codec 子进程预编译完成并已缓存')
            else:
                err = (proc.stderr or b'')[-300:].decode('utf-8', 'replace')
                logger.warning('[RDP] ASN.1 子进程预编译失败，将在首次连接时回退编译: %s' % err)
        finally:
            for p in (in_path, out_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
    except Exception as e:
        logger.warning('[RDP] ASN.1 预热失败: %s' % e)


# 在主线程同步导入 schema 模块（仅加载字符串常量，开销极小，避免后台线程并发 import 死锁）。
from aardwolf.protocol.T125.MCSPDU_ver_2 import MCSPDU_ver_2  # noqa: E402
from aardwolf.protocol.T124.GCCPDU import GCCPDU  # noqa: E402

_install_asn1_cache()
_install_wheel_steps_patch()
_install_read_diag()
threading.Thread(target=_prewarm_asn1, name='rdp-asn1-prewarm', daemon=True).start()


def build_rdp_url(host: str, port, username: str = "", password: str = "",
                  domain: str = "", auth: str = "ntlm") -> str:
    """构造 aardwolf 可识别的 RDP 连接 URL。

    - auth == "ntlm"：rdp+ntlm-password://[domain\\]user:<pwd>@host:port （支持 NLA）
    - auth == "plain"：rdp://[domain\\]user:<pwd>@host:port （仅 NLA 关闭时可用）

    密码做完整 percent-encoding，IPv6 主机自动加方括号。
    """
    scheme = "rdp+ntlm-password" if auth == "ntlm" else "rdp"

    userinfo = ""
    if username:
        user = f"{domain}\\{username}" if domain else username
        # 保留反斜杠（aardwolf 用 DOMAIN\\user 形式），其余按 userinfo 规则转义
        userinfo = quote(user, safe="\\")
        if password:
            userinfo += ":" + quote(password, safe="")
        userinfo += "@"

    host = str(host).strip()
    # 裸 IPv6 地址加方括号
    if host.count(":") >= 2 and not host.startswith("["):
        host = f"[{host}]"

    return f"{scheme}://{userinfo}{host}:{port}"


class RDPClientConsoleSettings:
    def __init__(self, url: str, iosettings: RDPIOSettings):
        self.mhover: bool = True
        self.keyboard: bool = True
        self.url: str = url
        self.iosettings: RDPIOSettings = iosettings
        # ducky 脚本文件路径（未使用）
        self.ducky_file = None
        self.ducky_autostart_delay = 5


class RDPImage:
    def __init__(self, x, y, image, width, height):
        self.x = x
        self.y = y
        self.image = image
        self.width = width
        self.height = height


class RDPInterfaceThread(QObject):
    """连接管理 worker：在独立 asyncio 事件循环里维护 aardwolf 连接。"""
    result = Signal(RDPImage)
    connection_terminated = Signal()
    connection_error = Signal(str)

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.settings: RDPClientConsoleSettings = None
        self.conn = None
        self.in_q = None
        self.loop = None
        self.loop_started_evt = threading.Event()
        self.gui_stopped_evt = threading.Event()
        self.asyncthread: threading.Thread = None
        self.rdp_connection_task = None

    def set_settings(self, settings, in_q):
        self.settings = settings
        self.in_q = in_q

    def inputhandler(self, loop: asyncio.AbstractEventLoop):
        while not self.conn.disconnected_evt.is_set():
            data = self.in_q.get()
            loop.call_soon_threadsafe(self.conn.ext_in_queue.put_nowait, data)
            if data is None:
                break
        logger.debug('inputhandler terminating')

    async def rdpconnection(self):
        input_handler_thread = None
        try:
            t_start = time.perf_counter()
            rdpurl = RDPConnectionFactory.from_url(self.settings.url, self.settings.iosettings)
            self.conn = rdpurl.get_connection(self.settings.iosettings)
            _, err = await self.conn.connect()
            if err is not None:
                self.connection_error.emit(str(err))
                return
            logger.info('[RDP] connect() 完成，耗时 %.2fs' % (time.perf_counter() - t_start))

            input_handler_thread = asyncio.get_event_loop().run_in_executor(
                None, self.inputhandler, asyncio.get_event_loop())
            self.loop_started_evt.set()

            first_frame = True
            while not self.gui_stopped_evt.is_set():
                data = await self.conn.ext_out_queue.get()
                if data is None:
                    return
                if data.type == RDPDATATYPE.VIDEO:
                    if first_frame:
                        first_frame = False
                        logger.info('[RDP] 首帧画面到达，自连接起共 %.2fs'
                                    % (time.perf_counter() - t_start))
                    ri = RDPImage(data.x, data.y, data.data, data.width, data.height)
                    if not self.gui_stopped_evt.is_set():
                        self.result.emit(ri)
                    else:
                        return
                elif data.type in (RDPDATATYPE.CLIPBOARD_READY,
                                   RDPDATATYPE.CLIPBOARD_NEW_DATA_AVAILABLE,
                                   RDPDATATYPE.CLIPBOARD_CONSUMED,
                                   RDPDATATYPE.CLIPBOARD_DATA_TXT):
                    continue
                else:
                    logger.debug('Unknown incoming data: %s' % data)

        except asyncio.CancelledError:
            return
        except Exception as e:
            traceback.print_exc()
            if not self.gui_stopped_evt.is_set():
                self.connection_error.emit(str(e))
        finally:
            if self.conn is not None:
                await self.conn.terminate()
            if input_handler_thread is not None:
                input_handler_thread.cancel()
            if not self.gui_stopped_evt.is_set():
                self.connection_terminated.emit()

    def starter(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.rdp_connection_task = self.loop.create_task(self.rdpconnection())
            self.loop.run_until_complete(self.rdp_connection_task)
            self.loop.close()
        except Exception:
            pass

    @Slot()
    def start(self):
        # 单独线程跑 asyncio，否则会阻塞、无法回传事件
        self.asyncthread = threading.Thread(target=self.starter, args=(), daemon=True)
        self.asyncthread.start()

    @Slot()
    def stop(self):
        self.gui_stopped_evt.set()
        if self.conn is not None and self.loop is not None and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.conn.terminate(), self.loop)
            except Exception:
                pass
        time.sleep(0.1)  # 等待连接终止
        try:
            if self.rdp_connection_task is not None:
                self.rdp_connection_task.cancel()
            if self.loop is not None:
                self.loop.stop()
        except Exception:
            pass

    @Slot(list)
    def clipboard_send_files(self, files):
        try:
            asyncio.run_coroutine_threadsafe(self.conn.set_current_clipboard_files(files), self.loop)
        except Exception:
            pass


class RDPWidget(QWidget):
    """可嵌入标签页的 RDP 远程桌面视图。"""
    connection_terminated = Signal()
    connection_error = Signal(str)

    def __init__(self, settings: RDPClientConsoleSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.mhover = settings.mhover
        self.keyboard = settings.keyboard
        self.is_rdp = settings.url.lower().startswith('rdp')

        self._video_w = settings.iosettings.video_width
        self._video_h = settings.iosettings.video_height
        self._has_frame = False  # 是否已收到首帧画面（用于区分"未连上"和"连上后断开"）
        self._error = None  # 连接错误信息

        # 当前帧缓冲(QPixmap)：随服务端矩形更新而不断刷新。
        # 用 QPixmap 而非 QImage，避免每次刷新都把整张大图(屏幕分辨率)重新转换一遍，
        # 局部矩形更新只触碰对应小区域，刷新时直接缩放，CPU 开销低。
        self._buffer = QPixmap(self._video_w, self._video_h)
        self._buffer.fill(Qt.GlobalColor.black)
        # 帧合并(coalescing)：服务端每次屏幕变化会推送大量小矩形，逐个 setPixmap
        # 会把主线程刷爆导致卡顿/连接观感慢。矩形只更新缓冲并置脏，由定时器统一刷新。
        self._frame_dirty = False
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(16)  # ≈60fps 上限，无论来多少矩形都只刷这么多次
        self._repaint_timer.timeout.connect(self._flush_frame)
        self._repaint_timer.start()

        # 画面显示控件：保持宽高比缩放并居中（letterbox），不强行拉伸 → 不变形。
        # 注意：不再使用 setScaledContents(True)（那会无视宽高比直接拉伸），
        # 改为在 _flush_frame 里用 KeepAspectRatio 手动缩放。
        self._label = QLabel(self)
        self._label.setMinimumSize(1, 1)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #cccccc; background-color: #1e1e1e;")
        self._label.setText(self.tr("正在连接远程桌面，请稍候…"))
        # 让鼠标事件穿透到本控件统一处理（坐标再映射回画面分辨率）
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 单箭头模式：远程桌面区域始终显示标准箭头光标，跟手且不闪烁
        self.setCursor(Qt.CursorShape.ArrowCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._label)

        # 接收键鼠输入
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        # 键鼠输入下发队列
        self.in_q = queue.Queue()

        # 滚轮残差累积：触控板/平滑滚轮 angleDelta 可能小于一个 detent，累积到
        # 120(WHEEL_DELTA)再发一次，避免小增量被服务端忽略而无法滚动。
        self._wheel_resid = 0

        # worker 放入 QThread
        self._thread = QThread()
        self._threaded = RDPInterfaceThread()
        self._threaded.set_settings(self.settings, self.in_q)
        self._threaded.result.connect(self.updateImage)
        self._threaded.connection_terminated.connect(self._on_connection_terminated)
        self._threaded.connection_error.connect(self._on_connection_error)
        self._threaded.moveToThread(self._thread)
        self._thread.started.connect(self._threaded.start)
        self._stopped = False
        self._thread.start()

        self._build_key_maps()

    def had_frame(self) -> bool:
        """是否成功显示过远程画面。"""
        return self._has_frame

    # ---------------- 键鼠映射表（适配 macOS） ----------------
    def _build_key_maps(self):
        self.qtkey_to_vk = {
            Qt.Key.Key_Escape: 'VK_ESCAPE', Qt.Key.Key_Tab: 'VK_TAB',
            Qt.Key.Key_Backspace: 'VK_BACK', Qt.Key.Key_Return: 'VK_RETURN',
            Qt.Key.Key_Enter: 'VK_RETURN',
            # 修饰键用带 L 前缀的虚拟键：aardwolf 的 __vk_to_sc 表只有 VK_LSHIFT/
            # VK_LCONTROL/VK_LMENU，VK_SHIFT/VK_CONTROL/VK_MENU 不在表中会退化为扫描码 0，
            # 导致 Shift/Ctrl/Alt 在远程不生效。扫描码路径不携带修饰键状态(服务端靠独立按键
            # 事件跟踪)，修饰键必须能正确发出，否则 Shift+字母变小写、IME 切换失效。
            Qt.Key.Key_Shift: 'VK_LSHIFT', Qt.Key.Key_Control: 'VK_LCONTROL',
            Qt.Key.Key_Alt: 'VK_LMENU', Qt.Key.Key_Meta: 'VK_LWIN',
            Qt.Key.Key_Menu: 'VK_APPS',
            Qt.Key.Key_CapsLock: 'VK_CAPITAL', Qt.Key.Key_NumLock: 'VK_NUMLOCK',
            Qt.Key.Key_ScrollLock: 'VK_SCROLL',
            Qt.Key.Key_Up: 'VK_UP', Qt.Key.Key_Down: 'VK_DOWN',
            Qt.Key.Key_Left: 'VK_LEFT', Qt.Key.Key_Right: 'VK_RIGHT',
            Qt.Key.Key_Home: 'VK_HOME', Qt.Key.Key_End: 'VK_END',
            Qt.Key.Key_PageUp: 'VK_PRIOR', Qt.Key.Key_PageDown: 'VK_NEXT',
            Qt.Key.Key_Insert: 'VK_INSERT', Qt.Key.Key_Delete: 'VK_DELETE',
            Qt.Key.Key_Print: 'VK_SNAPSHOT', Qt.Key.Key_Pause: 'VK_PAUSE',
        }
        for i in range(1, 13):
            self.qtkey_to_vk[getattr(Qt.Key, f'Key_F{i}')] = f'VK_F{i}'
        # 小键盘运算符
        self.qtkey_to_vk.update({
            Qt.Key.Key_Slash: 'VK_DIVIDE', Qt.Key.Key_Asterisk: 'VK_MULTIPLY',
            Qt.Key.Key_Minus: 'VK_SUBTRACT', Qt.Key.Key_Plus: 'VK_ADD',
            Qt.Key.Key_Period: 'VK_DECIMAL',
        })
        for i in range(10):
            self.qtkey_to_vk[getattr(Qt.Key, f'Key_{i}')] = f'VK_NUMPAD{i}'

        self._qtbutton_to_rdp = {
            Qt.MouseButton.LeftButton: MOUSEBUTTON.MOUSEBUTTON_LEFT,
            Qt.MouseButton.RightButton: MOUSEBUTTON.MOUSEBUTTON_RIGHT,
            Qt.MouseButton.MiddleButton: MOUSEBUTTON.MOUSEBUTTON_MIDDLE,
        }

    # ---------------- 生命周期 ----------------
    def stop(self):
        """停止 worker 并退出线程（供 tab 关闭/窗口关闭调用）。"""
        if self._stopped:
            return
        self._stopped = True
        try:
            self._repaint_timer.stop()
        except Exception:
            pass
        try:
            self.in_q.put(None)
        except Exception:
            pass
        try:
            self._threaded.stop()
        except Exception:
            pass
        try:
            self._thread.quit()
            self._thread.wait(1500)
        except Exception:
            pass

    def _on_connection_terminated(self):
        self.connection_terminated.emit()

    def _on_connection_error(self, msg: str):
        self._error = msg
        # 未连上时把错误展示在画面区域，避免用户面对空白标签页
        if not self._has_frame:
            self._label.setText(self.tr("RDP 连接失败：\n") + (msg or self.tr("未知错误")))
        self.connection_error.emit(msg)

    def closeEvent(self, event):
        self.stop()
        event.accept()

    # ---------------- 画面渲染 ----------------
    def updateImage(self, event: RDPImage):
        # 只做便宜的缓冲区合并，真正的 setPixmap/缩放交给 _flush_frame 定时批量执行
        rect = ImageQt(event.image)  # QImage
        if event.width == self._video_w and event.height == self._video_h:
            self._buffer = QPixmap.fromImage(rect)
        else:
            # 局部矩形：只在缓冲对应位置绘制该小块，不动其余区域
            with QPainter(self._buffer) as qp:
                qp.drawImage(event.x, event.y, rect, 0, 0, event.width, event.height)
        self._has_frame = True
        self._frame_dirty = True

    def _flush_frame(self):
        """定时器回调：若缓冲有更新则刷新一次画面（合并大量小矩形为单次渲染）。

        关键(去模糊)：按设备像素比(Retina)渲染到「物理像素」目标尺寸，再 setDevicePixelRatio，
        让 Qt 在高分屏上 1:1 输出而非二次放大；同时保持宽高比(KeepAspectRatio)。
        由于连接分辨率取自屏幕物理像素，窗口内恒为 downscale → 锐利不糊。
        """
        if not self._frame_dirty:
            return
        self._frame_dirty = False
        pm = self._buffer  # 已是 QPixmap，无需再从 QImage 转换
        dpr = self.devicePixelRatioF() or 1.0
        # 目标用物理像素，保证高分屏清晰
        tw = max(1, int(round(self._label.width() * dpr)))
        th = max(1, int(round(self._label.height() * dpr)))
        scaled = pm.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self._label.setPixmap(scaled)

    def resizeEvent(self, event):
        # 窗口缩放时即使没有新帧也要按新尺寸重绘（保持宽高比）
        super().resizeEvent(event)
        if self._has_frame:
            self._frame_dirty = True

    # ---------------- 键盘 ----------------
    # 非扩展键的扫描码映射表。
    # aardwolf 的 send_key_virtualkey(connection.py) 对 __vk_to_sc 里的所有键
    # 无差别强制 is_extended=True(即 E0 前缀)。但 Backspace(VK_BACK,0x0E)、Tab、Esc、
    # Enter、F1-F12、Shift 等并非扩展键,带 E0 前缀后服务端无法识别 —— 这正是
    # macOS 的 delete 键(实为退格)在远程编辑器里失效的根因。
    # 这些键改为直接走扫描码 + is_extended=False(进入 __external_reader 的 else 分支,
    # 该分支会如实使用 is_extended),绕开 aardwolf 的强制扩展。
    _NON_EXTENDED_VK_SC = {
        'VK_BACK': 14, 'VK_ESCAPE': 1, 'VK_TAB': 15, 'VK_RETURN': 28,
        'VK_F1': 59, 'VK_F2': 60, 'VK_F3': 61, 'VK_F4': 62, 'VK_F5': 63,
        'VK_F6': 64, 'VK_F7': 65, 'VK_F8': 66, 'VK_F9': 67, 'VK_F10': 68,
        'VK_F11': 87, 'VK_F12': 88,
        'VK_LSHIFT': 42, 'VK_RSHIFT': 54, 'VK_LCONTROL': 29, 'VK_LMENU': 56,
        'VK_SCROLL': 70, 'VK_NUMLOCK': 69, 'VK_CAPITAL': 58,
        'VK_MULTIPLY': 55, 'VK_ADD': 78, 'VK_SUBTRACT': 74,
    }

    # Qt.Key -> PS/2 Set1 扫描码(US 键盘物理位置)，用于把可打印键以物理扫描码下发，
    # 使远程 IME 能拦截。值已按 PS/2 Set1 make code 校对(A=0x1E, Space=0x39, ','=0x33 等)。
    #
    # 不使用 nativeScanCode():macOS 上 Qt 常把它返回为 0(不填充)，若用 ADB 键码表查 0
    # 会命中 'A'(扫描码 30) → 所有键都变成 a/啊。Qt.Key 是确定性的、按键可区分的，故改用它。
    # 局限:假设本地为 US/QWERTY(含中文输入法所用的 US 布局)；Shift+符号键 Qt 会报成
    # Key_Underscore/Key_Plus 等(不在表内) → 回退 Unicode 路径(对 IME 无影响)。
    _QTKEY_TO_PS2 = {
        Qt.Key.Key_Space: 57,
        # 字母:Shift 不改变 Key_A..Key_Z，大小写都由此覆盖，Shift 状态经独立按键事件传递
        Qt.Key.Key_A: 30, Qt.Key.Key_B: 48, Qt.Key.Key_C: 46, Qt.Key.Key_D: 32,
        Qt.Key.Key_E: 18, Qt.Key.Key_F: 33, Qt.Key.Key_G: 34, Qt.Key.Key_H: 35,
        Qt.Key.Key_I: 23, Qt.Key.Key_J: 36, Qt.Key.Key_K: 37, Qt.Key.Key_L: 38,
        Qt.Key.Key_M: 50, Qt.Key.Key_N: 49, Qt.Key.Key_O: 24, Qt.Key.Key_P: 25,
        Qt.Key.Key_Q: 16, Qt.Key.Key_R: 19, Qt.Key.Key_S: 31, Qt.Key.Key_T: 20,
        Qt.Key.Key_U: 22, Qt.Key.Key_V: 47, Qt.Key.Key_W: 17, Qt.Key.Key_X: 45,
        Qt.Key.Key_Y: 21, Qt.Key.Key_Z: 44,
        # 数字行(未按 Shift 时 Qt 报 Key_0..Key_9)
        Qt.Key.Key_0: 11, Qt.Key.Key_1: 2, Qt.Key.Key_2: 3, Qt.Key.Key_3: 4,
        Qt.Key.Key_4: 5, Qt.Key.Key_5: 6, Qt.Key.Key_6: 7, Qt.Key.Key_7: 8,
        Qt.Key.Key_8: 9, Qt.Key.Key_9: 10,
        # 标点(未按 Shift 时)，让 IME 可拦截(如 , -> ，  . -> 。  / -> 、)
        Qt.Key.Key_QuoteLeft: 41, Qt.Key.Key_Minus: 12, Qt.Key.Key_Equal: 13,
        Qt.Key.Key_BracketLeft: 26, Qt.Key.Key_BracketRight: 27,
        Qt.Key.Key_Semicolon: 39, Qt.Key.Key_Apostrophe: 40,
        Qt.Key.Key_Backslash: 43, Qt.Key.Key_Comma: 51, Qt.Key.Key_Period: 52,
        Qt.Key.Key_Slash: 53,
    }

    def _mac_ps2_scancode(self, e):
        """macOS 下把按键转成 PS/2 Set1 物理扫描码，供远程 IME 拦截。

        返回 (scancode, is_extended) 或 None。仅 darwin 生效；其余平台返回 None，
        仍走原有 Unicode / 虚拟键路径。用 Qt.Key -> PS/2 表(确定且按键可区分)，
        不依赖 nativeScanCode(macOS 上 Qt 常返回 0，会导致所有键被查成同一个扫描码)。
        查不到的键(如 Shift+数字/符号产生的 Key_Plus 等)返回 None，回退 Unicode 路径。
        """
        if sys.platform != 'darwin':
            return None
        sc = self._QTKEY_TO_PS2.get(e.key())
        if sc is None:
            return None
        return sc, False

    def send_key(self, e, is_pressed):
        if not self.keyboard:
            return

        # Ctrl+V：把本地剪贴板文本同步到远程
        if is_pressed and (e.modifiers() & Qt.ControlModifier) and e.key() == Qt.Key.Key_V:
            ki = RDP_CLIPBOARD_DATA_TXT()
            ki.datatype = CLIPBRD_FORMAT.CF_UNICODETEXT
            ki.data = pyperclip.paste()
            self.in_q.put(ki)
            return

        modifiers = VK_MODIFIERS(0)
        qt_modifiers = e.modifiers()
        if qt_modifiers & Qt.ShiftModifier and e.key() != Qt.Key.Key_Shift:
            modifiers |= VK_MODIFIERS.VK_SHIFT
        if qt_modifiers & Qt.ControlModifier and e.key() != Qt.Key.Key_Control:
            modifiers |= VK_MODIFIERS.VK_CONTROL
        if qt_modifiers & Qt.AltModifier and e.key() != Qt.Key.Key_Alt:
            modifiers |= VK_MODIFIERS.VK_MENU
        if qt_modifiers & Qt.KeypadModifier and e.key() != Qt.Key.Key_NumLock:
            modifiers |= VK_MODIFIERS.VK_NUMLOCK
        if qt_modifiers & Qt.MetaModifier and e.key() != Qt.Key.Key_Meta:
            modifiers |= VK_MODIFIERS.VK_WIN

        # macOS：可打印键改走物理扫描码(ADB 键码 -> PS/2 Set1)，让远程输入法能拦截。
        # 此前用 Unicode 键盘事件(TS_UNICODE_KEYBOARD_EVENT)会绕过 IME 直接落字，
        # 导致远程已切到中文输入法时仍输入英文字母。物理扫描码由远程按自身布局/IME
        # 解释，IME 才能介入转换。修饰键状态由服务端跟踪(见上 VK_LSHIFT 等映射)。
        ps2 = self._mac_ps2_scancode(e)
        if ps2 is not None:
            sc, is_ext = ps2
            ki = RDP_KEYBOARD_SCANCODE()
            ki.keyCode = sc
            ki.is_extended = is_ext
            ki.vk_code = None  # 走 send_key_scancode，如实使用 is_extended
            ki.is_pressed = is_pressed
            ki.modifiers = modifiers
            self.in_q.put(ki)
            return

        # 可打印字符走 Unicode 事件（非 macOS 或无法映射物理键时的回退）
        text = e.text()
        if text and text.isprintable() and len(text) == 1:
            ki = RDP_KEYBOARD_UNICODE()
            ki.char = text
            ki.is_pressed = is_pressed
            self.in_q.put(ki)
            return

        # 功能键/修饰键走扫描码 + 虚拟键码映射
        ki = RDP_KEYBOARD_SCANCODE()
        vk = self.qtkey_to_vk.get(e.key())
        if vk in self._NON_EXTENDED_VK_SC:
            # 非扩展键(Backspace/Tab/Esc/Enter/F键/Shift 等):直接用扫描码 +
            # is_extended=False,绕开 aardwolf 对 vk_code 强制 E0 前缀的 bug。
            ki.keyCode = self._NON_EXTENDED_VK_SC[vk]
            ki.is_extended = False
            ki.vk_code = None
        elif vk is not None:
            # 扩展键(方向键/Insert/Delete/Home/End/PageUp/Down 等):仍走 vk_code,
            # 由 aardwolf 补上正确的 E0 前缀。
            ki.vk_code = vk
            ki.keyCode = 0
        else:
            ki.keyCode = e.nativeScanCode()
            logger.warning(f"Unmapped key: {e.key()}, using native scancode {ki.keyCode}")
        ki.is_pressed = is_pressed
        ki.modifiers = modifiers
        self.in_q.put(ki)

    def keyPressEvent(self, e):
        self.send_key(e, True)

    def keyReleaseEvent(self, e):
        self.send_key(e, False)

    # ---------------- 鼠标 ----------------
    def _map_pos(self, e):
        """把控件坐标映射回画面分辨率。

        画面按 KeepAspectRatio 居中显示（可能有黑边），需扣除黑边偏移并按实际缩放比
        换算，否则点击位置会偏。
        """
        lw = max(1, self._label.width())
        lh = max(1, self._label.height())
        # 与 _flush_frame 一致：等比缩放，取较小的缩放比
        scale = min(lw / self._video_w, lh / self._video_h)
        disp_w = self._video_w * scale
        disp_h = self._video_h * scale
        off_x = (lw - disp_w) / 2.0  # 居中产生的左右黑边
        off_y = (lh - disp_h) / 2.0  # 居中产生的上下黑边
        x = int((e.position().x() - off_x) / scale)
        y = int((e.position().y() - off_y) / scale)
        x = min(max(0, x), self._video_w - 1)
        y = min(max(0, y), self._video_h - 1)
        return x, y

    def send_mouse(self, e, is_pressed, is_hover=False):
        if is_hover and not self.settings.mhover:
            return
        if is_hover:
            button = MOUSEBUTTON.MOUSEBUTTON_HOVER
        else:
            button = self._qtbutton_to_rdp.get(e.button())
            if button is None:
                return
        x, y = self._map_pos(e)
        mi = RDP_MOUSE()
        mi.xPos = x
        mi.yPos = y
        mi.button = button
        mi.is_pressed = is_pressed if not is_hover else False
        self.in_q.put(mi)

    def mouseMoveEvent(self, e):
        self.send_mouse(e, False, True)

    def mousePressEvent(self, e):
        self.setFocus()
        self.send_mouse(e, True)

    def mouseReleaseEvent(self, e):
        self.send_mouse(e, False)

    # ---------------- 滚轮 ----------------
    def wheelEvent(self, e):
        # 累积 angleDelta，每满一个 detent(120) 发一次滚轮事件。
        # 120 同时是 RDP WHEEL_DELTA 与 Qt angleDelta 的单位：鼠标滚轮一格=±120，
        # 触控板连续滑动为小增量，靠 _wheel_resid 累积到 120 再发，避免被服务端忽略。
        #
        # 必须经 in_q 串行派发(与键鼠同一通道)：RDP 用 RC4 有状态流加密，若像剪贴板那样
        # 用 run_coroutine_threadsafe 直连 conn.send_mouse，多个滚轮事件并发会让
        # PacketCount/RC4 流错乱，服务端解密失败直接 RST 断连。in_q 由 __external_reader
        # 单任务串行处理，RC4 状态有序推进。__external_reader 派发时不传 steps(旋转量)，
        # 由模块级 _install_wheel_steps_patch 把滚轮的 steps 补回 120。
        delta = e.angleDelta().y()
        if delta == 0:
            return
        self._wheel_resid += delta
        x, y = self._map_pos(e)
        notch = 120
        while abs(self._wheel_resid) >= notch:
            if self._wheel_resid > 0:
                self._wheel_resid -= notch
                button = MOUSEBUTTON.MOUSEBUTTON_WHEEL_UP
            else:
                self._wheel_resid += notch
                button = MOUSEBUTTON.MOUSEBUTTON_WHEEL_DOWN
            mi = RDP_MOUSE()
            mi.xPos = x
            mi.yPos = y
            mi.button = button
            mi.is_pressed = False  # 滚轮不按下，仅旋转
            self.in_q.put(mi)
            if not getattr(self, '_wheel_logged', False):
                self._wheel_logged = True
                logger.error('[RDP-diag] 滚轮走 in_q 串行派发(新代码已加载) button=%s' % button.name)

    # ---------------- 拖拽传文件 ----------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if not files:
            return
        self._threaded.clipboard_send_files(files)
