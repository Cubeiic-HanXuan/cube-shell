@echo off & setlocal enabledelayedexpansion
rem ============================================================================
rem  register_url_scheme_windows.bat
rem  注册 jms:// URL Scheme 到 Windows 当前用户注册表
rem  Register jms:// URL Scheme in Windows registry (current user, no admin)
rem ----------------------------------------------------------------------------
rem  用法 / Usage:
rem    注册:   register_url_scheme_windows.bat [exe路径]
rem    卸载:   register_url_scheme_windows.bat /uninstall
rem
rem  如果不指定 exe 路径，脚本自动检测同目录下的 cube-shell.exe
rem  If exe path is not specified, auto-detects cube-shell.exe in same directory.
rem ============================================================================

chcp 65001 >nul 2>&1

set "SCHEME=jms"
set "REG_ROOT=HKCU\Software\Classes\%SCHEME%"

rem ---------------------------------------------------------------------------
rem  处理卸载模式 / Handle uninstall mode
rem ---------------------------------------------------------------------------
if /i "%~1"=="/uninstall" (
    echo [卸载] 正在移除 %SCHEME%:// URL Scheme 注册...
    echo [Uninstall] Removing %SCHEME%:// URL Scheme registration...
    reg delete "%REG_ROOT%" /f >nul 2>&1
    if !errorlevel! equ 0 (
        echo [成功] URL Scheme 已移除。
        echo [OK] URL Scheme removed successfully.
    ) else (
        echo [提示] 注册表项不存在或已被移除。
        echo [Info] Registry key does not exist or already removed.
    )
    goto :eof
)

rem ---------------------------------------------------------------------------
rem  确定 exe 路径 / Determine exe path
rem ---------------------------------------------------------------------------
set "EXE_PATH=%~1"

if "%EXE_PATH%"=="" (
    rem 自动检测：脚本所在目录的上一级 deploy\cube-shell.dist\cube-shell.exe
    rem 或者同目录下的 cube-shell.exe
    set "SCRIPT_DIR=%~dp0"
    
    rem 尝试同目录
    if exist "%SCRIPT_DIR%cube-shell.exe" (
        set "EXE_PATH=%SCRIPT_DIR%cube-shell.exe"
    ) else (
        rem 尝试上级目录
        for %%I in ("%SCRIPT_DIR%..") do set "PARENT_DIR=%%~fI"
        if exist "!PARENT_DIR!\cube-shell.exe" (
            set "EXE_PATH=!PARENT_DIR!\cube-shell.exe"
        ) else if exist "!PARENT_DIR!\deploy\cube-shell.dist\cube-shell.exe" (
            set "EXE_PATH=!PARENT_DIR!\deploy\cube-shell.dist\cube-shell.exe"
        ) else (
            echo [错误] 未找到 cube-shell.exe，请手动指定路径：
            echo [Error] cube-shell.exe not found, please specify path:
            echo.
            echo   %~nx0 "C:\path\to\cube-shell.exe"
            echo.
            goto :eof
        )
    )
)

rem 验证 exe 是否存在 / Verify exe exists
if not exist "%EXE_PATH%" (
    echo [错误] 文件不存在: %EXE_PATH%
    echo [Error] File not found: %EXE_PATH%
    goto :eof
)

rem 转换为绝对路径 / Convert to absolute path
for %%I in ("%EXE_PATH%") do set "EXE_FULL=%%~fI"
for %%I in ("%EXE_FULL%") do set "ICON_PATH=%%~dpIicons\logo.ico"

echo ============================================================
echo  注册 %SCHEME%:// URL Scheme
echo  Registering %SCHEME%:// URL Scheme
echo ------------------------------------------------------------
echo  可执行文件 / Executable: %EXE_FULL%
echo  注册表路径 / Registry:   %REG_ROOT%
echo ============================================================
echo.

rem ---------------------------------------------------------------------------
rem  写入注册表 / Write registry keys
rem ---------------------------------------------------------------------------

rem 创建主键并设置描述 / Create main key with description
reg add "%REG_ROOT%" /ve /d "JumpServer Connection Protocol" /f >nul
if !errorlevel! neq 0 (
    echo [错误] 写入注册表失败。
    echo [Error] Failed to write registry.
    goto :eof
)

rem 设置 URL Protocol 标记（值为空字符串，表明这是一个 URL Scheme）
rem Set URL Protocol flag (empty string indicates this is a URL Scheme)
reg add "%REG_ROOT%" /v "URL Protocol" /d "" /f >nul

rem 设置默认图标 / Set default icon
if exist "%ICON_PATH%" (
    reg add "%REG_ROOT%\DefaultIcon" /ve /d "\"%ICON_PATH%\"" /f >nul
) else (
    reg add "%REG_ROOT%\DefaultIcon" /ve /d "\"%EXE_FULL%,0\"" /f >nul
)

rem 设置打开命令 / Set open command
rem 当用户点击 jms:// 链接时，Windows 将执行: "cube-shell.exe" "jms://..."
rem When user clicks a jms:// link, Windows will execute: "cube-shell.exe" "jms://..."
reg add "%REG_ROOT%\shell" /ve /d "" /f >nul
reg add "%REG_ROOT%\shell\open" /ve /d "" /f >nul
reg add "%REG_ROOT%\shell\open\command" /ve /d "\"%EXE_FULL%\" \"%%1\"" /f >nul

echo.
echo [成功] %SCHEME%:// URL Scheme 注册完成！
echo [OK] %SCHEME%:// URL Scheme registered successfully!
echo.
echo 现在可以通过浏览器打开 jms:// 链接来启动 CubeShell。
echo You can now open jms:// links in browser to launch CubeShell.
echo.
echo 如需卸载 / To uninstall:
echo   %~nx0 /uninstall
echo.

goto :eof
