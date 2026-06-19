"""
跨平台安装/替换/重启 + 三层兜底。

通用时序:
    detached 启动安装器/脚本 → 当前进程 ``QApplication.quit()``
    → 脚本 ``pgrep`` 轮询等旧进程退出 → 替换 → 启动新进程

任一步失败立即回退兜底(系统默认打开已下载安装包 / 打开 Release 页),
确保任何环节失败都不会卡死。

**重要**:本模块只在主线程被调用(worker 发 ``download_finished`` → 主线程确认
后调用)。绝不在 worker 线程调用任何 QMessageBox / QDesktopServices。
"""
import logging
import os
import platform
import subprocess
import sys

logger = logging.getLogger(__name__)

# Windows 安装包默认安装到 Program Files,需提权;Inno Setup 自带 manifest 触发 UAC
# Linux dist 目录可能装在 /opt 等不可写位置
# macOS bundle 路径从 sys.executable 反推

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ────────────────────────── 自身路径 ──────────────────────────

def _app_executable() -> str:
    """当前进程可执行文件路径(frozen 下即 GUI 本体)。"""
    return sys.executable


def _app_dir() -> str:
    """当前进程所在目录(frozen 下即 cube-shell.dist 或 .app/Contents/MacOS)。"""
    return os.path.dirname(os.path.abspath(sys.executable))


# ────────────────────────── 退出当前进程 ──────────────────────────

def _request_app_quit():
    """请求主窗口退出(主线程安全)。

    用 ``QMetaObject.invokeMethod`` 以 ``QueuedConnection`` 触发
    ``QApplication.quit``,走 closeEvent 正常清理线程,随后进程退出,
    安装脚本接管文件替换。
    """
    try:
        from PySide6.QtCore import QMetaObject, Qt
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            QMetaObject.invokeMethod(app, "quit", Qt.QueuedConnection)
    except Exception as e:
        logger.error(f"请求应用退出失败: {e}")


# ────────────────────────── Windows ──────────────────────────

def _install_windows(installer_path: str) -> bool:
    """Windows 安装:按文件类型分流。

    - ``.exe``:Inno Setup 静默安装(`/VERYSILENT` + `/CLOSEAPPLICATIONS` 自动关闭
      占用进程 + `/RESTARTAPPLICATIONS` 安装完自动重启)。UAC 由 Inno manifest 触发。
    - ``.zip``:解压替换 ``cube-shell.dist`` 目录。Windows 下运行中的 exe 被锁,
      采用"旧 dist 重命名为 .old → 移入新 dist → 启动新 exe → .old 留待下次清理"
      的延迟替换策略,避免文件锁。
    """
    low = (installer_path or "").lower()
    if low.endswith(".exe"):
        return _install_windows_inno(installer_path)
    if low.endswith(".zip"):
        return _install_windows_zip(installer_path)
    logger.warning(f"未知的 Windows 安装包格式: {installer_path}")
    return False


def _install_windows_inno(installer_exe: str) -> bool:
    """Inno Setup .exe 静默安装 + 自动重启。"""
    args = [
        installer_exe, "/VERYSILENT", "/NORESTART", "/NOCANCEL",
        "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS",
    ]
    try:
        subprocess.Popen(
            args, close_fds=True,
            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        )
        _request_app_quit()
        return True
    except Exception as e:
        logger.error(f"Windows Inno 静默安装失败,回退手动安装: {e}")
        return False


def _install_windows_zip(zip_path: str) -> bool:
    """Windows .zip 解压替换 cube-shell.dist。

    Windows 下运行中的 ``cube-shell.exe`` 被锁不能直接删,故用延迟重命名:
    旧 dist → ``cube-shell.dist.old`` → 新 dist 就位 → 启动新 exe →
    ``.old`` 由新版本启动时清理(此处不阻塞,交给 detached 脚本)。
    """
    dist_dir = _app_dir()
    if os.path.basename(dist_dir) != "cube-shell.dist":
        logger.warning(f"当前目录非 cube-shell.dist({dist_dir}),走兜底")
        return False

    parent = os.path.dirname(dist_dir)
    tmp_extract = os.path.join(parent, "_cs_extract_tmp")
    new_dist = os.path.join(tmp_extract, "cube-shell.dist")
    # 先在 Python 进程内解压(用标准库 zipfile),失败走兜底
    try:
        import zipfile
        os.makedirs(tmp_extract, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp_extract)
        if not os.path.isdir(new_dist):
            # 有些 zip 顶层不套 dist 目录,直接是文件集合 → 视为 new_dist 本身
            if os.path.exists(os.path.join(tmp_extract, "cube-shell.exe")):
                new_dist = tmp_extract
            else:
                logger.warning("zip 解压后未找到 cube-shell.dist,走兜底")
                return False
    except Exception as e:
        logger.error(f"Windows zip 解压失败,回退手动安装: {e}")
        return False

    new_exe = os.path.join(new_dist, "cube-shell.exe")
    if not os.path.exists(new_exe):
        logger.warning("zip 内未找到 cube-shell.exe,走兜底")
        return False

    old_dist = dist_dir + ".old"
    # cmd 批处理脚本:等待旧进程退出 → 重命名旧 dist → 移入新 dist → 启动新 exe
    # 用 robocopy/xcopy 而非 mv,因为跨目录移动大量文件更稳;最后清理 .old(尽力)
    script = f'''@echo off
set NEW="{new_dist}"
set DST="{dist_dir}"
set OLD="{old_dist}"
set NEWEXE="{new_exe}"
:wait
timeout /t 1 /nobreak >nul
tasklist /FI "PID eq %1" 2>nul | find "%1" >nul && goto wait
if exist %OLD% rmdir /S /Q %OLD% 2>nul
rename %DST cube-shell.dist.old 2>nul
xcopy %NEW% %DST% /E /I /Y /Q >nul
start "" %NEWEXE%
rmdir /S /Q %OLD% 2>nul
(del "%~f0" 2>nul)
'''
    bat = os.path.join(parent, "_cs_upgrade.cmd")
    try:
        with open(bat, "w", encoding="utf-8") as f:
            f.write(script)
        # detached 启动批处理,把当前 PID 作为参数传进去用于等待退出
        subprocess.Popen(
            ["cmd", "/c", bat, str(os.getpid())], close_fds=True,
            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        )
        _request_app_quit()
        return True
    except Exception as e:
        logger.error(f"Windows zip 替换失败,回退手动安装: {e}")
        return False


# ────────────────────────── macOS ──────────────────────────

def _install_macos(archive_path: str) -> bool:
    """macOS 安装:按文件类型分流。

    - ``.zip``:解压 → 拷贝到 /Applications → 启动新 app(首选)
    - ``.dmg``:挂载 → 拷贝到 /Applications → 启动新 app(兼容旧产物)

    统一安装到 ``/Applications/cube-shell.app``(标准 macOS 应用程序目录),
    等价于用户拖拽安装。
    """
    low = (archive_path or "").lower()
    if low.endswith(".zip"):
        return _install_macos_zip(archive_path)
    if low.endswith(".dmg"):
        return _install_macos_dmg(archive_path)
    logger.warning(f"未知的 macOS 安装包格式: {archive_path}")
    return False


def _install_macos_zip(zip_path: str) -> bool:
    """解压 .zip → 移动到 /Applications 覆盖老程序 → 启动新 app。

    detached bash 脚本:解压 → 等旧进程退出 → 删除旧 app → ditto 移入
    /Applications → 清理临时目录 → 启动。普通用户对 /Applications 有写权限,
    ditto 直接覆盖即可,无需鉴权流程。
    """
    APPS_DIR = "/Applications"
    target_app = os.path.join(APPS_DIR, "cube-shell.app")
    extract_dir = os.path.join(os.path.dirname(zip_path), "_cs_extract_tmp")

    script = f'''#!/bin/bash
# 解压到临时目录(排除 macOS 打包产生的 __MACOSX 元数据垃圾,避免干扰 find)
rm -rf "{extract_dir}"
mkdir -p "{extract_dir}"
unzip -q "{zip_path}" -d "{extract_dir}" -x "__MACOSX/*" "__MACOSX"
# 定位解压出的 cube-shell.app(顶层或套一层目录;排除 __MACOSX 残留)
NEW_APP=$(find "{extract_dir}" -maxdepth 2 -name "cube-shell.app" -not -path "*/__MACOSX/*" | head -1)
[ -z "$NEW_APP" ] && exit 1
# 去隔离属性,降低首次启动 Gatekeeper 拦截
xattr -dr com.apple.quarantine "$NEW_APP" 2>/dev/null || true
# 等待当前 cube-shell 进程退出(最多 15s),避免覆盖正在运行的 bundle
for i in $(seq 1 30); do
  if ! pgrep -f "cube-shell.app/Contents/MacOS/" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
# 覆盖 /Applications 下的老程序(ditto 正确处理 bundle 权限/扩展属性)
rm -rf "{target_app}"
ditto "$NEW_APP" "{target_app}"
# 清理临时目录,启动新版本
rm -rf "{extract_dir}"
open -n "{target_app}"
'''
    sh = os.path.join(os.path.dirname(zip_path), "_cs_upgrade.sh")
    try:
        with open(sh, "w") as f:
            f.write(script)
        os.chmod(sh, 0o755)
        subprocess.Popen(
            ["/bin/bash", sh], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _request_app_quit()
        return True
    except Exception as e:
        logger.error(f"macOS zip 安装失败,回退手动安装: {e}")
        return False


def _install_macos_dmg(dmg_path: str) -> bool:
    """挂载 dmg → 拷贝到 /Applications → 启动新 app。

    兼容旧的 .dmg 产物(当前统一用 .zip,此分支留作兜底兼容)。
    """
    APPS_DIR = "/Applications"
    target_app = os.path.join(APPS_DIR, "cube-shell.app")

    # detached bash 脚本:挂载 → 去隔离 → 等旧进程退出 → ditto 覆盖到 /Applications → 启动
    script = f'''#!/bin/bash
MOUNT=$(hdiutil attach "{dmg_path}" -nobrowse -noautoopen | grep "/Volumes/" | awk '{{print $NF}}' | head -1)
[ -z "$MOUNT" ] && exit 1
APP=$(find "$MOUNT" -maxdepth 2 -name "*.app" | head -1)
[ -z "$APP" ] && exit 1
# 去除下载隔离属性,降低首次启动 Gatekeeper 拦截
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
# 等待当前 cube-shell 进程退出(最多 15s),避免覆盖正在运行的 bundle
for i in $(seq 1 30); do
  if ! pgrep -f "cube-shell.app/Contents/MacOS/" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
# 覆盖 /Applications 下的老程序
rm -rf "{target_app}"
ditto "$APP" "{target_app}"
hdiutil detach "$MOUNT" 2>/dev/null || true
open -n "{target_app}"
'''
    sh = os.path.join(os.path.dirname(dmg_path), "_cs_upgrade.sh")
    try:
        with open(sh, "w") as f:
            f.write(script)
        os.chmod(sh, 0o755)
        subprocess.Popen(
            ["/bin/bash", sh], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _request_app_quit()
        return True
    except Exception as e:
        logger.error(f"macOS dmg 安装失败,回退手动安装: {e}")
        return False


# ────────────────────────── Linux ──────────────────────────

def _install_linux(tarball: str) -> bool:
    """解压 tar.gz/tar.xz → 等旧进程退出 → 替换 cube-shell.dist → 启动新 bin。"""
    dist_dir = _app_dir()
    # 防御:确认确实在 cube-shell.dist 内,且目录可写,否则走兜底
    if os.path.basename(dist_dir) != "cube-shell.dist":
        logger.warning(f"当前目录非 cube-shell.dist({dist_dir}),走兜底")
        return False
    if not os.access(dist_dir, os.W_OK):
        logger.warning(f"dist 目录不可写({dist_dir}),需 root 权限,走兜底")
        return False

    parent = os.path.dirname(dist_dir)
    tmp_extract = os.path.join(parent, "_cs_extract_tmp")
    new_dist = os.path.join(tmp_extract, "cube-shell.dist")
    try:
        import tarfile
        os.makedirs(tmp_extract, exist_ok=True)
        # "r" 自动检测压缩格式,兼容 .tar.gz 与 .tar.xz
        with tarfile.open(tarball, "r") as t:
            t.extractall(tmp_extract)
        if not os.path.isdir(new_dist):
            logger.warning("tar 解压后未找到 cube-shell.dist,走兜底")
            return False
    except Exception as e:
        logger.error(f"Linux 解压失败,回退手动安装: {e}")
        return False

    script = f'''#!/bin/bash
NEW="{new_dist}"
DST="{dist_dir}"
# 等待旧进程退出(最多 15s)
for i in $(seq 1 30); do
  if ! pgrep -f "{dist_dir}/cube-shell.bin" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
rm -rf "$DST"
mv "$NEW" "$DST"
chmod +x "$DST/cube-shell.bin" "$DST/cube-shell.sh" 2>/dev/null || true
nohup "$DST/cube-shell.bin" >/dev/null 2>&1 &
rm -rf "{tmp_extract}"
rm -f "$0"
'''
    sh = os.path.join(parent, "_cs_upgrade.sh")
    try:
        with open(sh, "w") as f:
            f.write(script)
        os.chmod(sh, 0o755)
        subprocess.Popen(
            ["/bin/bash", sh], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _request_app_quit()
        return True
    except Exception as e:
        logger.error(f"Linux 自动替换失败,回退手动安装: {e}")
        return False


# ────────────────────────── 兜底 ──────────────────────────

def _fallback_open(path: str, parent=None) -> bool:
    """系统默认打开已下载安装包,让用户手动完成安装。"""
    from PySide6.QtWidgets import QMessageBox

    try:
        sys_name = platform.system()
        if sys_name == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys_name == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        if parent is not None:
            QMessageBox.information(
                parent, "更新",
                "已为你打开安装包,请手动完成安装后重新启动 cube-shell。"
            )
        return True
    except Exception as e:
        logger.error(f"打开安装包失败: {e}")
        if parent is not None:
            QMessageBox.warning(
                parent, "更新",
                f"无法自动打开安装包,请手动访问下载目录:\n{path}"
            )
        return False


def _fallback_open_release(parent) -> bool:
    """打开 GitHub release 页(无平台包/全失败时的最终兜底)。"""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox

    from .github_api import RELEASE_PAGE
    QDesktopServices.openUrl(QUrl(RELEASE_PAGE))
    QMessageBox.information(
        parent, "更新",
        "未自动匹配到当前平台的安装包,已在浏览器打开 Release 页,请手动下载安装。"
    )
    return False


# ────────────────────────── 主入口 ──────────────────────────

def install_and_restart(installer_path: str, parent_widget) -> bool:
    """安装并重启的主入口。

    :param installer_path: 已下载的安装包路径;为空表示未匹配到平台包,
                           直接打开 Release 页兜底
    :param parent_widget: 父窗口(用于兜底 QMessageBox)
    :return: True 表示已发起安装(进程将退出);False 表示走了兜底或失败
    """
    if not installer_path:
        return _fallback_open_release(parent_widget)

    if not os.path.exists(installer_path):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(parent_widget, "更新", f"安装包不存在:{installer_path}")
        return False

    sys_name = platform.system()
    try:
        if sys_name == "Windows":
            ok = _install_windows(installer_path)
        elif sys_name == "Darwin":
            ok = _install_macos(installer_path)
        elif sys_name == "Linux":
            ok = _install_linux(installer_path)
        else:
            return _fallback_open(installer_path, parent_widget)

        if ok:
            return True  # 已 detached 启动,主线程随后退出,安装接管
        # 自动安装失败 → 回退手动打开
        return _fallback_open(installer_path, parent_widget)
    except Exception as e:
        logger.error(f"自动安装失败,回退手动安装: {e}")
        return _fallback_open(installer_path, parent_widget)
