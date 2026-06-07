"""
macOS Finder 右键菜单集成模块

提供安装/卸载 Finder "快速操作" (Quick Action) 的功能，
使用户可在 Finder 中右键点击文件夹，选择"在 CubeShell 中打开终端"。
"""
import os
import platform
import shutil
import logging

logger = logging.getLogger(__name__)

WORKFLOW_NAME = "Open in CubeShell"
WORKFLOW_DIR = os.path.expanduser(f"~/Library/Services/{WORKFLOW_NAME}.workflow")


def is_supported():
    """是否为支持的平台（仅 macOS）"""
    return platform.system() == 'Darwin'


def is_installed():
    """检查 Finder 快速操作是否已安装"""
    return os.path.isdir(WORKFLOW_DIR)


def install():
    """
    安装 Finder 快速操作 workflow。
    创建 ~/Library/Services/Open in CubeShell.workflow 目录结构。

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    contents_dir = os.path.join(WORKFLOW_DIR, "Contents")

    try:
        # 如果已存在先删除
        if os.path.isdir(WORKFLOW_DIR):
            shutil.rmtree(WORKFLOW_DIR)

        os.makedirs(contents_dir, exist_ok=True)

        # 写入 Info.plist
        info_plist = '<?xml version="1.0" encoding="UTF-8"?>\n'
        info_plist += '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        info_plist += '<plist version="1.0">\n'
        info_plist += '<dict>\n'
        info_plist += '\t<key>NSServices</key>\n'
        info_plist += '\t<array>\n'
        info_plist += '\t\t<dict>\n'
        info_plist += '\t\t\t<key>NSMenuItem</key>\n'
        info_plist += '\t\t\t<dict>\n'
        info_plist += '\t\t\t\t<key>default</key>\n'
        info_plist += '\t\t\t\t<string>在 CubeShell 中打开终端</string>\n'
        info_plist += '\t\t\t</dict>\n'
        info_plist += '\t\t\t<key>NSMessage</key>\n'
        info_plist += '\t\t\t<string>runWorkflowAsService</string>\n'
        info_plist += '\t\t\t<key>NSSendFileTypes</key>\n'
        info_plist += '\t\t\t<array>\n'
        info_plist += '\t\t\t\t<string>public.folder</string>\n'
        info_plist += '\t\t\t\t<string>public.file-url</string>\n'
        info_plist += '\t\t\t</array>\n'
        info_plist += '\t\t</dict>\n'
        info_plist += '\t</array>\n'
        info_plist += '</dict>\n'
        info_plist += '</plist>'

        with open(os.path.join(contents_dir, "Info.plist"), "w", encoding="utf-8") as f:
            f.write(info_plist)

        # 写入 document.wflow
        shell_script = ('for f in "$@"; do\n'
                       '    if [ -d "$f" ]; then\n'
                       '        ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=\'/\'))" "$f")\n'
                       '        open "cubeshell://open-local?path=$ENCODED"\n'
                       '    fi\n'
                       'done')

        document_wflow = '<?xml version="1.0" encoding="UTF-8"?>\n'
        document_wflow += '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        document_wflow += '<plist version="1.0">\n'
        document_wflow += '<dict>\n'
        document_wflow += '\t<key>AMApplicationBuild</key>\n'
        document_wflow += '\t<string>523</string>\n'
        document_wflow += '\t<key>AMApplicationVersion</key>\n'
        document_wflow += '\t<string>2.10</string>\n'
        document_wflow += '\t<key>AMDocumentVersion</key>\n'
        document_wflow += '\t<string>2</string>\n'
        document_wflow += '\t<key>actions</key>\n'
        document_wflow += '\t<array>\n'
        document_wflow += '\t\t<dict>\n'
        document_wflow += '\t\t\t<key>action</key>\n'
        document_wflow += '\t\t\t<dict>\n'
        document_wflow += '\t\t\t\t<key>AMAccepts</key>\n'
        document_wflow += '\t\t\t\t<dict>\n'
        document_wflow += '\t\t\t\t\t<key>Container</key>\n'
        document_wflow += '\t\t\t\t\t<string>List</string>\n'
        document_wflow += '\t\t\t\t\t<key>Optional</key>\n'
        document_wflow += '\t\t\t\t\t<true/>\n'
        document_wflow += '\t\t\t\t\t<key>Types</key>\n'
        document_wflow += '\t\t\t\t\t<array>\n'
        document_wflow += '\t\t\t\t\t\t<string>com.apple.cocoa.path</string>\n'
        document_wflow += '\t\t\t\t\t</array>\n'
        document_wflow += '\t\t\t\t</dict>\n'
        document_wflow += '\t\t\t\t<key>AMActionVersion</key>\n'
        document_wflow += '\t\t\t\t<string>1.0.2</string>\n'
        document_wflow += '\t\t\t\t<key>AMApplication</key>\n'
        document_wflow += '\t\t\t\t<array>\n'
        document_wflow += '\t\t\t\t\t<string>Automator</string>\n'
        document_wflow += '\t\t\t\t</array>\n'
        document_wflow += '\t\t\t\t<key>AMCategory</key>\n'
        document_wflow += '\t\t\t\t<string>AMCategoryUtilities</string>\n'
        document_wflow += '\t\t\t\t<key>AMIconName</key>\n'
        document_wflow += '\t\t\t\t<string>Run Shell Script</string>\n'
        document_wflow += '\t\t\t\t<key>AMKeywords</key>\n'
        document_wflow += '\t\t\t\t<array>\n'
        document_wflow += '\t\t\t\t\t<string>Shell</string>\n'
        document_wflow += '\t\t\t\t\t<string>Script</string>\n'
        document_wflow += '\t\t\t\t</array>\n'
        document_wflow += '\t\t\t\t<key>AMName</key>\n'
        document_wflow += '\t\t\t\t<string>Run Shell Script</string>\n'
        document_wflow += '\t\t\t\t<key>AMProvides</key>\n'
        document_wflow += '\t\t\t\t<dict>\n'
        document_wflow += '\t\t\t\t\t<key>Container</key>\n'
        document_wflow += '\t\t\t\t\t<string>List</string>\n'
        document_wflow += '\t\t\t\t\t<key>Types</key>\n'
        document_wflow += '\t\t\t\t\t<array>\n'
        document_wflow += '\t\t\t\t\t\t<string>com.apple.cocoa.path</string>\n'
        document_wflow += '\t\t\t\t\t</array>\n'
        document_wflow += '\t\t\t\t</dict>\n'
        document_wflow += '\t\t\t\t<key>AMRequiredResources</key>\n'
        document_wflow += '\t\t\t\t<array/>\n'
        document_wflow += '\t\t\t\t<key>ActionBundlePath</key>\n'
        document_wflow += '\t\t\t\t<string>/System/Library/Automator/Run Shell Script.action</string>\n'
        document_wflow += '\t\t\t\t<key>ActionName</key>\n'
        document_wflow += '\t\t\t\t<string>Run Shell Script</string>\n'
        document_wflow += '\t\t\t\t<key>ActionParameters</key>\n'
        document_wflow += '\t\t\t\t<dict>\n'
        document_wflow += '\t\t\t\t\t<key>COMMAND_STRING</key>\n'
        document_wflow += f'\t\t\t\t\t<string>{shell_script}</string>\n'
        document_wflow += '\t\t\t\t\t<key>CheckedForUserDefaultShell</key>\n'
        document_wflow += '\t\t\t\t\t<true/>\n'
        document_wflow += '\t\t\t\t\t<key>inputMethod</key>\n'
        document_wflow += '\t\t\t\t\t<integer>1</integer>\n'
        document_wflow += '\t\t\t\t\t<key>shell</key>\n'
        document_wflow += '\t\t\t\t\t<string>/bin/bash</string>\n'
        document_wflow += '\t\t\t\t\t<key>source</key>\n'
        document_wflow += '\t\t\t\t\t<string></string>\n'
        document_wflow += '\t\t\t\t</dict>\n'
        document_wflow += '\t\t\t\t<key>BundleIdentifier</key>\n'
        document_wflow += '\t\t\t\t<string>com.apple.RunShellScript</string>\n'
        document_wflow += '\t\t\t\t<key>CFBundleVersion</key>\n'
        document_wflow += '\t\t\t\t<string>1.0.2</string>\n'
        document_wflow += '\t\t\t\t<key>CanShowSelectedItemsWhenRun</key>\n'
        document_wflow += '\t\t\t\t<false/>\n'
        document_wflow += '\t\t\t\t<key>CanShowWhenRun</key>\n'
        document_wflow += '\t\t\t\t<true/>\n'
        document_wflow += '\t\t\t\t<key>Category</key>\n'
        document_wflow += '\t\t\t\t<array>\n'
        document_wflow += '\t\t\t\t\t<string>AMCategoryUtilities</string>\n'
        document_wflow += '\t\t\t\t</array>\n'
        document_wflow += '\t\t\t\t<key>Class Name</key>\n'
        document_wflow += '\t\t\t\t<string>RunShellScriptAction</string>\n'
        document_wflow += '\t\t\t\t<key>InputUUID</key>\n'
        document_wflow += '\t\t\t\t<string>A7E1E2E1-4F5B-4C8D-9B1A-3E5F7A8C9D0E</string>\n'
        document_wflow += '\t\t\t\t<key>Keywords</key>\n'
        document_wflow += '\t\t\t\t<array>\n'
        document_wflow += '\t\t\t\t\t<string>Shell</string>\n'
        document_wflow += '\t\t\t\t\t<string>Script</string>\n'
        document_wflow += '\t\t\t\t</array>\n'
        document_wflow += '\t\t\t\t<key>OutputUUID</key>\n'
        document_wflow += '\t\t\t\t<string>B8F2F3F2-5G6C-5D9E-0C2B-4F6G8B9D0E1F</string>\n'
        document_wflow += '\t\t\t\t<key>UUID</key>\n'
        document_wflow += '\t\t\t\t<string>C9G3G4G3-6H7D-6E0F-1D3C-5G7H9C0E1F2G</string>\n'
        document_wflow += '\t\t\t\t<key>UnlocalizedApplications</key>\n'
        document_wflow += '\t\t\t\t<array>\n'
        document_wflow += '\t\t\t\t\t<string>Automator</string>\n'
        document_wflow += '\t\t\t\t</array>\n'
        document_wflow += '\t\t\t</dict>\n'
        document_wflow += '\t\t\t<key>isViewVisible</key>\n'
        document_wflow += '\t\t\t<integer>1</integer>\n'
        document_wflow += '\t\t</dict>\n'
        document_wflow += '\t</array>\n'
        document_wflow += '\t<key>connectors</key>\n'
        document_wflow += '\t<dict/>\n'
        document_wflow += '\t<key>workflowMetaData</key>\n'
        document_wflow += '\t<dict>\n'
        document_wflow += '\t\t<key>applicationBundleIDsByPath</key>\n'
        document_wflow += '\t\t<dict/>\n'
        document_wflow += '\t\t<key>applicationPaths</key>\n'
        document_wflow += '\t\t<array/>\n'
        document_wflow += '\t\t<key>inputTypeIdentifier</key>\n'
        document_wflow += '\t\t<string>com.apple.Automator.fileSystemObject</string>\n'
        document_wflow += '\t\t<key>outputTypeIdentifier</key>\n'
        document_wflow += '\t\t<string>com.apple.Automator.nothing</string>\n'
        document_wflow += '\t\t<key>presentationMode</key>\n'
        document_wflow += '\t\t<integer>15</integer>\n'
        document_wflow += '\t\t<key>processesInput</key>\n'
        document_wflow += '\t\t<integer>0</integer>\n'
        document_wflow += '\t\t<key>serviceApplicationGroupName</key>\n'
        document_wflow += '\t\t<string>Finder</string>\n'
        document_wflow += '\t\t<key>serviceApplicationPath</key>\n'
        document_wflow += '\t\t<string>/System/Library/CoreServices/Finder.app</string>\n'
        document_wflow += '\t\t<key>serviceInputTypeIdentifier</key>\n'
        document_wflow += '\t\t<string>com.apple.Automator.fileSystemObject</string>\n'
        document_wflow += '\t\t<key>serviceOutputTypeIdentifier</key>\n'
        document_wflow += '\t\t<string>com.apple.Automator.nothing</string>\n'
        document_wflow += '\t\t<key>workflowTypeIdentifier</key>\n'
        document_wflow += '\t\t<string>com.apple.Automator.servicesMenu</string>\n'
        document_wflow += '\t</dict>\n'
        document_wflow += '</dict>\n'
        document_wflow += '</plist>'

        with open(os.path.join(contents_dir, "document.wflow"), "w", encoding="utf-8") as f:
            f.write(document_wflow)

        logger.info("Finder 快速操作 workflow 安装成功: %s", WORKFLOW_DIR)
        return True, None

    except Exception as e:
        logger.error("安装 Finder 快速操作失败: %s", e)
        return False, str(e)


def uninstall():
    """
    卸载 Finder 快速操作 workflow。

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    try:
        if os.path.isdir(WORKFLOW_DIR):
            shutil.rmtree(WORKFLOW_DIR)
        logger.info("Finder 快速操作 workflow 已卸载: %s", WORKFLOW_DIR)
        return True, None
    except Exception as e:
        logger.error("卸载 Finder 快速操作失败: %s", e)
        return False, str(e)
