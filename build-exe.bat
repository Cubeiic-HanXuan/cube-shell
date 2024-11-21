@echo off & setlocal enabledelayedexpansion
rem cube-shell windows exe.bat

rem dos utf-8 encode
chcp 65001

REM Step 1: Install Nuitka
echo 1: Installing Nuitka...
echo pip install nuitka
pip install nuitka

REM Step 2: Build the application
echo 2: Building the application...
nuitka --windows-console-mode=disable --windows-icon-from-ico=icons/logo.ico --output-dir=deploy --standalone --enable-plugin=pyside6 --follow-imports --include-module=qdarktheme --include-module=deepdiff --include-module=pygments --include-module=paramiko --include-module=pyte --include-module=pygments.formatters.html --include-module=pygments.lexers.python --include-package=core,function,style,ui,icons --include-data-dir=conf=conf --include-data-dir=frp=frp cube-shell.py

REM Step 3: Create tunnel.json file
echo 3: Creating tunnel.json file...
echo {} > deploy\cube-shell.dist\conf\tunnel.json

REM Step 4: Delete config.dat file
echo 4: Deleting config.dat file...
del /Q deploy\cube-shell.dist\conf\config.dat

REM Step 5: Deploy using Inno Setup
echo 5: Deploying using Inno Setup...
iscc installer.iss

echo Done!
pause
goto :eof