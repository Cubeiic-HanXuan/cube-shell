@echo off & setlocal enabledelayedexpansion
rem cube-shell windows exe.bat

rem dos utf-8 encode
chcp 65001

REM Step 0: Load MSVC ARM64 environment
call "C:\Program Files\Microsoft Visual Studio\18\Insiders\VC\Auxiliary\Build\vcvarsall.bat" arm64

REM Step 1: Install Nuitka
echo 1: Installing Nuitka...
echo pip install nuitka --no-cache-dir
pip install nuitka --no-cache-dir

REM Step 2: Build the application
echo 2: Building the application...
set VSLANG=1033
nuitka --msvc=latest --windows-console-mode=disable --windows-icon-from-ico=icons/logo.ico ^
  --follow-imports ^
  --remove-output ^
  --jobs=4 ^
  --python-flag=no_site ^
  --lto=yes ^
  --output-dir=deploy ^
  --standalone ^
  --enable-plugin=pyside6 ^
  --include-module=qdarktheme ^
  --include-module=deepdiff ^
  --include-module=pygments ^
  --include-module=paramiko ^
  --include-module=yaml ^
  --include-module=openai ^
  --include-module=keyring ^
  --include-module=prompt_toolkit ^
  --include-module=pygments.formatters.html ^
  --include-module=pygments.lexers.shell ^
  --include-package=qtermwidget,core,function,style,ui,icons ^
  --include-data-dir=conf=conf ^
  --company-name=HanXuan ^
  --product-name="cubeShell" ^
  --file-version=2.7.0.0 ^
  --product-version=2.7.0 ^
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

REM Step 5: Self-signed code signing
echo 5: Self-signed code signing...
powershell -Command "if (-not (Get-ChildItem Cert:\CurrentUser\My | Where-Object {$_.Subject -eq 'CN=CubeShell'})) { New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=CubeShell' -CertStoreLocation Cert:\CurrentUser\My }"
for /f "tokens=*" %%i in ('powershell -Command "(Get-ChildItem Cert:\CurrentUser\My | Where-Object {$_.Subject -eq 'CN=CubeShell'}).Thumbprint"') do set THUMBPRINT=%%i
if defined THUMBPRINT (
    signtool sign /fd SHA256 /sha1 %THUMBPRINT% /t http://timestamp.digicert.com "deploy\cube-shell.dist\cube-shell.exe"
    echo    Signed successfully.
) else (
    echo    [Warning] Certificate not found, skipping signing.
)

REM Step 6: Deploy using Inno Setup
echo 6: Deploying using Inno Setup...
iscc installer.iss

echo Done!
pause
goto :eof