#!/bin/bash
# 在 Nuitka 构建完成后运行此脚本，向 .app 的 Info.plist 注入 URL Scheme 配置
# 用法: ./tools/register_url_scheme.sh /path/to/CubeShell.app
#
# 注册的 URL Scheme:
#   - jms://        (JumpServer 连接，默认启用)
#   - cubeshell://  (CubeShell 本地终端唤起，默认启用)
#   - ssh://        (SSH 连接，默认不启用，避免与系统 Terminal.app 冲突)
#
# 若需同时注册 ssh://，请取消下方相关行的注释

set -e

APP_PATH="$1"
if [ -z "$APP_PATH" ]; then
    echo "Usage: $0 /path/to/CubeShell.app"
    exit 1
fi

INFO_PLIST="$APP_PATH/Contents/Info.plist"
if [ ! -f "$INFO_PLIST" ]; then
    echo "Error: Info.plist not found at $INFO_PLIST"
    exit 1
fi

echo "Registering URL schemes in $INFO_PLIST ..."

# 如果 CFBundleURLTypes 已存在则先删除，确保幂等
/usr/libexec/PlistBuddy -c "Delete :CFBundleURLTypes" "$INFO_PLIST" 2>/dev/null || true

# 创建 CFBundleURLTypes 数组
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes array" "$INFO_PLIST"

# 添加 jms:// scheme
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0 dict" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLName string 'JumpServer Connection'" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string jms" "$INFO_PLIST"

# 添加 cubeshell:// scheme
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:1 dict" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:1:CFBundleURLName string 'CubeShell Local Terminal'" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:1:CFBundleURLSchemes array" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:1:CFBundleURLSchemes:0 string cubeshell" "$INFO_PLIST"

# [可选] 添加 ssh:// scheme — 取消以下注释以启用
# 注意: macOS Terminal.app 默认处理 ssh://，启用此项可能导致系统级冲突
# /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:2 dict" "$INFO_PLIST"
# /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:2:CFBundleURLName string 'SSH Connection'" "$INFO_PLIST"
# /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:2:CFBundleURLSchemes array" "$INFO_PLIST"
# /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:2:CFBundleURLSchemes:0 string ssh" "$INFO_PLIST"

echo "URL schemes registered successfully for $APP_PATH"

# 刷新 Launch Services 数据库，使系统立即识别新注册的 URL Scheme
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_PATH"

echo "Launch Services database updated."
