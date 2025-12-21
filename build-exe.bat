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
nuitka --windows-console-mode=disable --windows-icon-from-ico=icons/logo.ico ^
  --follow-imports ^
  --remove-output ^
  --jobs=4 ^
  --python-flag=no_site ^
  --lto=yes ^
  --mingw64 ^
  --output-dir=deploy ^
  --standalone ^
  --enable-plugin=pyside6 ^
  --include-module=qdarktheme ^
  --include-module=deepdiff ^
  --include-module=pygments ^
  --include-module=paramiko ^
  --include-module=yaml ^
  --include-module=pygments.formatters.html ^
  --include-module=pygments.lexers.shell ^
  --include-package=qtermwidget,core,function,style,ui,icons ^
  --include-data-dir=conf=conf ^
  --include-data-dir=frp=frp ^
  --company-name=HanXuan ^
  --product-name="cubeShell" ^
  --file-version=2.0.3.0 ^
  --product-version=2.0.3 ^
  --file-description="A powerful shell application" ^
  cube-shell.py

REM Step 3: Create tunnel.json file
echo 3: Creating tunnel.json file...
echo {} > deploy\cube-shell.dist\conf\tunnel.json

REM Step 4: Delete config.dat file
echo 4: Deleting config.dat file...
del /Q deploy\cube-shell.dist\conf\config.dat

mkdir "deploy\cube-shell.dist\qtermwidget"
robocopy "qtermwidget\color-schemes" "deploy\cube-shell.dist\qtermwidget\color-schemes" /E /NFL /NDL /NJH /NJS
robocopy "qtermwidget\kb-layouts" "deploy\cube-shell.dist\qtermwidget\kb-layouts" /E /NFL /NDL /NJH /NJS
robocopy "qtermwidget\translations" "deploy\cube-shell.dist\qtermwidget\translations" /E /NFL /NDL /NJH /NJS
copy "qtermwidget\default.keytab" "deploy\cube-shell.dist\qtermwidget\"

REM Step 5: Deploy using Inno Setup
echo 5: Deploying using Inno Setup...
iscc installer.iss

echo Done!
pause
goto :eof