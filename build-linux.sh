#!/bin/bash
# ============================================================================
# cube-shell Linux (Ubuntu) Nuitka 打包脚本
# ----------------------------------------------------------------------------
# 用法：
#   1) 赋予执行权限：  chmod +x build-linux.sh
#   2) 运行脚本：      ./build-linux.sh
#
# 说明：
#   - 适用 Ubuntu / Debian 系发行版（依赖 apt-get）
#   - 需要已存在虚拟环境目录 venv/
#   - 产物输出到 deploy/cube-shell.dist/ 以及 deploy/cube-shell-linux-x86_64.tar.gz
# ============================================================================

set -e  # 任意命令失败立即退出
set -o pipefail

# ---------------------------------------------------------------------------
# 项目 / 版本信息
# ---------------------------------------------------------------------------
APP_NAME="cube-shell"
APP_VERSION="2.7.0"
COMPANY_NAME="HanXuan"
PRODUCT_NAME="cubeShell"
FILE_DESC="A powerful shell application"

DEPLOY_DIR="deploy"
DIST_DIR="${DEPLOY_DIR}/${APP_NAME}.dist"
BUILD_DIR="${DEPLOY_DIR}/${APP_NAME}.build"
TARBALL="${DEPLOY_DIR}/${APP_NAME}-linux-x86_64.tar.gz"

# ---------------------------------------------------------------------------
# 1. 安装系统依赖（patchelf / ccache / 基础编译工具 / Qt 运行依赖）
# ---------------------------------------------------------------------------
echo "1: Installing system dependencies (apt)..."
SYS_PKGS=(
  patchelf
  ccache
  build-essential
  python3-dev
  libffi-dev
  libssl-dev
  libxcb-cursor0           # PySide6 在 Linux 下常需的 XCB 依赖
  libxkbcommon-x11-0
  libegl1
  libgl1
  tar
)

# 仅在缺失时安装，避免每次都触发 sudo
MISSING=()
for pkg in "${SYS_PKGS[@]}"; do
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    MISSING+=("$pkg")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "   Missing packages: ${MISSING[*]}"
  sudo apt-get update
  sudo apt-get install -y "${MISSING[@]}"
else
  echo "   All required system packages already installed."
fi

# ---------------------------------------------------------------------------
# 2. 激活 Python 虚拟环境
# ---------------------------------------------------------------------------
echo "2: Activating virtual environment..."
if [ ! -f "venv/bin/activate" ]; then
  echo "   ERROR: venv/bin/activate not found. Please create venv first:"
  echo "          python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

# ---------------------------------------------------------------------------
# 3. 安装 / 升级 Nuitka
# ---------------------------------------------------------------------------
echo "3: Installing Nuitka..."
pip install --upgrade nuitka

# ---------------------------------------------------------------------------
# 4. 准备 deploy 目录
# ---------------------------------------------------------------------------
echo "4: Preparing deploy directory..."
mkdir -p "${DEPLOY_DIR}"
# 清理上一次的中间产物，避免污染
rm -rf "${DIST_DIR}" "${BUILD_DIR}"

# ---------------------------------------------------------------------------
# 5. Nuitka 编译
# ---------------------------------------------------------------------------
echo "5: Building the application with Nuitka..."
nuitka \
  --standalone \
  --enable-plugin=pyside6 \
  --follow-imports \
  --remove-output \
  --jobs=4 \
  --lto=yes \
  --output-dir="${DEPLOY_DIR}" \
  --linux-icon=icons/logo.ico \
  --include-module=qdarktheme \
  --include-module=deepdiff \
  --include-module=pygments \
  --include-module=paramiko \
  --include-module=yaml \
  --include-module=openai \
  --include-module=keyring \
  --include-module=prompt_toolkit \
  --include-package=unicrypto \
  --include-module=pygments.formatters.html \
  --include-module=pygments.lexers.shell \
  --include-package=qtermwidget,core,function,style,ui,icons \
  --include-data-dir=conf=conf \
  --company-name="${COMPANY_NAME}" \
  --product-name="${PRODUCT_NAME}" \
  --file-version="${APP_VERSION}.0" \
  --product-version="${APP_VERSION}" \
  --file-description="${FILE_DESC}" \
  cube-shell.py

# ---------------------------------------------------------------------------
# 6. 后处理：tunnel.json / 删除 config.dat / 复制 qtermwidget 资源
# ---------------------------------------------------------------------------
echo "6: Post-processing resources..."
if [ ! -d "${DIST_DIR}" ]; then
  echo "   ERROR: Build output not found at ${DIST_DIR}"
  exit 1
fi

# 6.1 创建空 tunnel.json
mkdir -p "${DIST_DIR}/conf"
echo "{}" > "${DIST_DIR}/conf/tunnel.json"

# 6.2 移除敏感 / 不需要的配置
rm -f "${DIST_DIR}/conf/config.dat"

# 6.3 复制 qtermwidget 资源（与 macOS 脚本保持一致）
cp -r qtermwidget/color-schemes "${DIST_DIR}/"
cp -r qtermwidget/kb-layouts    "${DIST_DIR}/"
cp -r qtermwidget/translations  "${DIST_DIR}/"
cp    qtermwidget/default.keytab "${DIST_DIR}/"

# 6.4 确保主程序可执行
chmod +x "${DIST_DIR}/${APP_NAME}.bin" 2>/dev/null || true

# 6.5 复制应用图标（PNG 格式，用于 Linux 桌面显示）
if [ -f "icons/logo.png" ]; then
  cp icons/logo.png "${DIST_DIR}/"
else
  echo "   WARNING: icons/logo.png not found, desktop icon may be missing."
fi

# 6.6 生成 .desktop 桌面入口文件（路径占位，由启动脚本首次运行时修正为绝对路径）
DESKTOP_FILE="${DIST_DIR}/${APP_NAME}.desktop"
cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=Cube Shell
Comment=${FILE_DESC}
Exec=${APP_NAME}.bin
Icon=logo.png
Terminal=false
Categories=Development;System;Utility;
StartupNotify=true
StartupWMClass=cubeShell
EOF
chmod +x "${DESKTOP_FILE}"

# 6.7 生成一个便捷启动脚本（可直接 ./cube-shell.sh 运行）
#     首次运行时自动将 .desktop 中的 Exec/Icon 修正为绝对路径，便于复制到 ~/.local/share/applications/
LAUNCHER="${DIST_DIR}/${APP_NAME}.sh"
cat > "${LAUNCHER}" <<'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"

# 自动修正 .desktop 文件中的路径（每次运行均会刷新，确保移动目录后仍可用）
DESKTOP="${DIR}/cube-shell.desktop"
if [ -f "${DESKTOP}" ]; then
  sed -i "s|^Exec=.*|Exec=${DIR}/cube-shell.bin|" "${DESKTOP}"
  sed -i "s|^Icon=.*|Icon=${DIR}/logo.png|" "${DESKTOP}"
fi

exec "${DIR}/cube-shell.bin" "$@"
EOF
chmod +x "${LAUNCHER}"

# ---------------------------------------------------------------------------
# 7. 打包为 tar.gz
# ---------------------------------------------------------------------------
echo "7: Creating tarball..."
rm -f "${TARBALL}"
tar -czf "${TARBALL}" -C "${DEPLOY_DIR}" "$(basename "${DIST_DIR}")"
echo "   -> ${TARBALL}"

# ---------------------------------------------------------------------------
# 8. 清理构建中间文件（保留 .dist 和 tar.gz）
# ---------------------------------------------------------------------------
echo "8: Cleaning intermediate build files..."
rm -rf "${BUILD_DIR}"
# Nuitka 在 --remove-output 下通常会自动清理 .build，这里再兜底删除项目根的残留
rm -rf "${APP_NAME}.build" "${APP_NAME}.dist" "${APP_NAME}.onefile-build" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 9. 退出虚拟环境
# ---------------------------------------------------------------------------
echo "9: Deactivating virtual environment..."
deactivate || true

echo ""
echo "============================================================"
echo " Build finished."
echo "   App dir : ${DIST_DIR}"
echo "   Tarball : ${TARBALL}"
echo "   Run     : ${DIST_DIR}/${APP_NAME}.sh"
echo "   Install : run ${APP_NAME}.sh once, then"
echo "             cp ${DIST_DIR}/${APP_NAME}.desktop ~/.local/share/applications/"
echo "============================================================"
