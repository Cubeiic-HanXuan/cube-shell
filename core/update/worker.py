"""
UpdateWorker(QThread):检查并下载更新的后台线程。

设计要点:检查与下载**都在 worker 线程执行**,避免阻塞主线程 UI。

- ``check()``:主线程调用 → 置检查模式 → ``start()`` 启线程 → ``run()`` 做
  检查,完成后发 ``checked`` 信号。
- ``download()``:主线程在用户确认后调用 → 置下载模式 → ``start()`` 启线程
  → ``run()`` 做下载,期间发 ``progress_updated`` / ``status_updated``,
  完成发 ``download_finished``。
- 安装阶段(``installer.install_and_restart``)回到主线程执行,worker 线程绝不
  持有 GUI 对象。

信号通过 Qt 的队列连接(QueuedConnection)自动回到主线程处理,故下载期间主
线程事件循环畅通,进度条平滑刷新、窗口可响应(含取消)。
"""
import os

from PySide6.QtCore import QThread, Signal

from core.frp_manager import download_with_progress, get_platform_key

from .github_api import GitHubApiError, RateLimitError, ReleaseInfo, fetch_latest_release
from .platform_match import build_download_path, select_asset
from .version import is_newer

_MODE_CHECK = "check"
_MODE_DOWNLOAD = "download"


class UpdateWorker(QThread):
    """检查并下载更新的后台线程。"""

    # 阶段 1:检查完成
    # payload: (has_update, remote_version, local_version, release_info_or_None, error_msg_or_None)
    checked = Signal(bool, str, str, object, str)
    # 阶段 2:下载进度 0-100
    progress_updated = Signal(int)
    # 阶段 2:状态文本
    status_updated = Signal(str)
    # 阶段 2:下载完成,待用户确认安装。payload: installer_path(空串表示未匹配平台包)
    download_finished = Signal(str)
    # 全流程错误(检查或下载阶段)。payload: 可读错误消息(空串表示走兜底而非弹错误)
    error = Signal(str)

    def __init__(self, local_version: str, parent=None):
        super().__init__(parent)
        self._local = local_version
        self._release: ReleaseInfo | None = None
        self._asset = None
        self._installer_path: str | None = None
        self._cancel = False
        self._mode = _MODE_CHECK

    def request_cancel(self):
        """主线程请求取消下载(检查阶段不可取消)。"""
        self._cancel = True

    def check(self):
        """主线程调用:启动检查阶段(在 worker 线程执行)。"""
        self._mode = _MODE_CHECK
        self._cancel = False
        self.start()

    def download(self):
        """主线程调用:启动下载阶段(在 worker 线程执行)。

        需先完成检查阶段(``check()``)并持有 ``self._release``。
        未匹配到平台包时发 ``download_finished("")`` 让主线程走 Release 页兜底。
        """
        # 检查线程可能刚 emit 完 checked 信号、run() 已返回但线程对象尚未清理
        # → wait 一下确保可以再次 start()(QThread 不允许在 running 时 start)
        if self.isRunning():
            self.wait(5000)
        self._mode = _MODE_DOWNLOAD
        self._cancel = False
        self.start()

    def run(self):
        if self._mode == _MODE_CHECK:
            self._run_check()
        elif self._mode == _MODE_DOWNLOAD:
            self._run_download()

    # ────────────────────────── 阶段 1:检查 ──────────────────────────

    def _run_check(self):
        try:
            self.status_updated.emit("正在检查更新…")
            rel = fetch_latest_release(timeout=15.0)
            self._release = rel
            remote = rel.tag_name
            has = is_newer(remote, self._local)
            # 即便无更新也把 release 传回(便于 UI 显示"已是最新")
            self.checked.emit(has, remote, self._local, rel, "")
        except RateLimitError as e:
            self.checked.emit(False, "", self._local, None, str(e))
        except GitHubApiError as e:
            self.checked.emit(False, "", self._local, None, str(e))
        except Exception as e:
            self.checked.emit(False, "", self._local, None, f"检查更新失败:{e}")

    # ────────────────────────── 阶段 2:下载 ──────────────────────────

    def _run_download(self):
        if not self._release:
            return
        self._asset = select_asset(self._release.assets, get_platform_key())
        if self._asset is None:
            # 未匹配到平台包:发空串,主线程走 openUrl 兜底
            self.download_finished.emit("")
            return

        dest = build_download_path(self._asset)
        self.status_updated.emit(f"正在下载 {self._asset.name} …")

        def cb(done, total):
            if self._cancel:
                raise KeyboardInterrupt  # urlretrieve 不原生支持取消,抛异常中断
            if total > 0:
                self.progress_updated.emit(int(done * 100 / total))

        try:
            ok = download_with_progress(self._asset.browser_download_url, dest, cb)
        except KeyboardInterrupt:
            self._safe_remove(dest)
            self.error.emit("下载已取消。")
            return
        except Exception as e:
            self._safe_remove(dest)
            self.error.emit(f"下载失败:{e}")
            return

        if not ok or not os.path.exists(dest):
            self.error.emit("下载失败,请检查网络后重试。")
            return
        # 校验:下载大小与 asset.size 一致(无校验和则只比大小)
        if self._asset.size > 0 and os.path.getsize(dest) != self._asset.size:
            self._safe_remove(dest)
            self.error.emit("下载文件大小不匹配,可能已损坏,请重试。")
            return
        self._installer_path = dest
        self.download_finished.emit(dest)

    @property
    def installer_path(self) -> str | None:
        """已下载的安装包路径(供主线程在用户拒绝立即安装时展示)。"""
        return self._installer_path

    @staticmethod
    def _safe_remove(p):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
