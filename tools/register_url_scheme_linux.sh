#!/bin/bash
# ============================================================================
#  register_url_scheme_linux.sh
#  注册 jms:// URL Scheme 到 Linux 当前用户桌面环境
#  Register jms:// URL Scheme for current user on Linux (via .desktop + xdg-mime)
# ----------------------------------------------------------------------------
#  用法 / Usage:
#    注册:   ./register_url_scheme_linux.sh [可执行文件路径]
#    卸载:   ./register_url_scheme_linux.sh --uninstall
#
#  如果不指定可执行文件路径，脚本自动检测同目录或上级目录下的 cube-shell.bin
#  If executable path is not specified, auto-detects cube-shell.bin in same/parent dir.
# ============================================================================

set -e

SCHEME="jms"
DESKTOP_FILE_NAME="cube-shell-url-handler.desktop"
DESKTOP_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="${DESKTOP_DIR}/${DESKTOP_FILE_NAME}"

# ---------------------------------------------------------------------------
#  处理卸载模式 / Handle uninstall mode
# ---------------------------------------------------------------------------
if [ "$1" = "--uninstall" ] || [ "$1" = "-u" ]; then
    echo "[卸载] 正在移除 ${SCHEME}:// URL Scheme 注册..."
    echo "[Uninstall] Removing ${SCHEME}:// URL Scheme registration..."

    # 删除 .desktop 文件 / Remove .desktop file
    if [ -f "${DESKTOP_FILE}" ]; then
        rm -f "${DESKTOP_FILE}"
        echo "  已删除 / Removed: ${DESKTOP_FILE}"
    else
        echo "  文件不存在 / File not found: ${DESKTOP_FILE}"
    fi

    # 更新桌面数据库 / Update desktop database
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
    fi

    # 尝试重置 xdg-mime 默认关联 / Try to reset xdg-mime default
    if command -v xdg-mime >/dev/null 2>&1; then
        # 无法直接 unset，但删除 .desktop 后关联自动失效
        echo "  xdg-mime 关联将在 .desktop 文件删除后自动失效"
        echo "  xdg-mime association will be invalidated after .desktop removal"
    fi

    echo ""
    echo "[成功] URL Scheme 已移除。"
    echo "[OK] URL Scheme removed successfully."
    exit 0
fi

# ---------------------------------------------------------------------------
#  确定可执行文件路径 / Determine executable path
# ---------------------------------------------------------------------------
EXE_PATH="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${EXE_PATH}" ]; then
    # 自动检测策略 / Auto-detection strategy:
    #   1. 脚本同目录下的 cube-shell.bin
    #   2. 上级目录下的 cube-shell.bin
    #   3. 上级目录下的 deploy/cube-shell.dist/cube-shell.bin
    if [ -x "${SCRIPT_DIR}/cube-shell.bin" ]; then
        EXE_PATH="${SCRIPT_DIR}/cube-shell.bin"
    elif [ -x "${SCRIPT_DIR}/../cube-shell.bin" ]; then
        EXE_PATH="$(cd "${SCRIPT_DIR}/.." && pwd)/cube-shell.bin"
    elif [ -x "${SCRIPT_DIR}/../deploy/cube-shell.dist/cube-shell.bin" ]; then
        EXE_PATH="$(cd "${SCRIPT_DIR}/../deploy/cube-shell.dist" && pwd)/cube-shell.bin"
    else
        echo "[错误] 未找到 cube-shell.bin，请手动指定路径："
        echo "[Error] cube-shell.bin not found, please specify path:"
        echo ""
        echo "  $0 /path/to/cube-shell.bin"
        echo ""
        exit 1
    fi
fi

# 转换为绝对路径 / Convert to absolute path
EXE_PATH="$(cd "$(dirname "${EXE_PATH}")" && pwd)/$(basename "${EXE_PATH}")"

# 验证可执行文件存在 / Verify executable exists
if [ ! -f "${EXE_PATH}" ]; then
    echo "[错误] 文件不存在: ${EXE_PATH}"
    echo "[Error] File not found: ${EXE_PATH}"
    exit 1
fi

# 确保可执行权限 / Ensure executable permission
if [ ! -x "${EXE_PATH}" ]; then
    chmod +x "${EXE_PATH}"
fi

# 检测图标路径 / Detect icon path
ICON_PATH="$(dirname "${EXE_PATH}")/logo.png"
if [ ! -f "${ICON_PATH}" ]; then
    ICON_PATH="$(dirname "${EXE_PATH}")/icons/logo.png"
fi
if [ ! -f "${ICON_PATH}" ]; then
    ICON_PATH=""
fi

echo "============================================================"
echo " 注册 ${SCHEME}:// URL Scheme"
echo " Registering ${SCHEME}:// URL Scheme"
echo "------------------------------------------------------------"
echo " 可执行文件 / Executable: ${EXE_PATH}"
echo " Desktop 文件 / Desktop file: ${DESKTOP_FILE}"
[ -n "${ICON_PATH}" ] && echo " 图标 / Icon: ${ICON_PATH}"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
#  创建 .desktop 文件 / Create .desktop file
# ---------------------------------------------------------------------------
mkdir -p "${DESKTOP_DIR}"

cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Name=CubeShell
Comment=JumpServer Connection Handler
GenericName=SSH Terminal
Exec=${EXE_PATH} %u
Icon=${ICON_PATH:-cube-shell}
Type=Application
NoDisplay=true
Terminal=false
Categories=Network;RemoteAccess;
MimeType=x-scheme-handler/${SCHEME};
StartupNotify=false
EOF

chmod +x "${DESKTOP_FILE}"
echo "  已创建 / Created: ${DESKTOP_FILE}"

# ---------------------------------------------------------------------------
#  注册为默认处理程序 / Register as default handler
# ---------------------------------------------------------------------------
if command -v xdg-mime >/dev/null 2>&1; then
    xdg-mime default "${DESKTOP_FILE_NAME}" "x-scheme-handler/${SCHEME}"
    echo "  已注册为 ${SCHEME}:// 默认处理程序"
    echo "  Registered as default handler for ${SCHEME}://"
else
    echo "  [警告] xdg-mime 不可用，请手动设置默认程序"
    echo "  [Warning] xdg-mime not available, please set default handler manually"
fi

# ---------------------------------------------------------------------------
#  更新桌面数据库 / Update desktop database
# ---------------------------------------------------------------------------
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
    echo "  桌面数据库已更新 / Desktop database updated"
fi

echo ""
echo "[成功] ${SCHEME}:// URL Scheme 注册完成！"
echo "[OK] ${SCHEME}:// URL Scheme registered successfully!"
echo ""
echo "现在可以通过浏览器打开 jms:// 链接来启动 CubeShell。"
echo "You can now open jms:// links in browser to launch CubeShell."
echo ""
echo "验证 / Verify:"
echo "  xdg-open 'jms://test'"
echo ""
echo "卸载 / Uninstall:"
echo "  $0 --uninstall"
echo ""
