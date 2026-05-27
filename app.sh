#!/bin/bash

# 激活虚拟环境
source venv/bin/activate
mkdir deploy

echo "1: Installing Nuitka..."
pip install nuitka
echo "2: Installing create-dmg..."
brew install create-dmg
echo "3: Building the application..."
nuitka \
  --macos-create-app-bundle \
  --standalone \
  --static-libpython=no \
  --enable-plugin=pyside6 \
  --follow-imports \
  --macos-app-icon=icons/logo.icns \
  --include-module=qdarktheme \
  --include-module=deepdiff \
  --include-module=pygments \
  --include-module=paramiko \
  --include-module=yaml \
  --include-module=openai \
  --include-module=keyring \
  --include-module=prompt_toolkit \
  --include-module=pygments.formatters.html \
  --include-module=pygments.lexers.shell \
  --include-package=qtermwidget,core,function,style,ui,icons \
  --include-data-dir=conf=conf \
  cube-shell.py

# Step 4: Create tunnel.json file
echo "4: Creating tunnel.json file..."
echo "{}" > cube-shell.app/Contents/MacOS/conf/tunnel.json

# Step 5: Delete config.dat file
echo "5: Deleting config.dat file..."
rm -f cube-shell.app/Contents/MacOS/conf/config.dat

cp -r qtermwidget/color-schemes cube-shell.app/Contents/MacOS
cp -r qtermwidget/kb-layouts cube-shell.app/Contents/MacOS
cp -r qtermwidget/translations cube-shell.app/Contents/MacOS
cp qtermwidget/default.keytab cube-shell.app/Contents/MacOS

# Step 6: Register URL Scheme (jms://) into Info.plist
echo "6: Registering URL schemes..."
bash tools/register_url_scheme.sh cube-shell.app

# Step 7: Ad-hoc codesign
echo "7: Ad-hoc signing..."
codesign -s - --force --deep cube-shell.app

echo "8: create-dmg..."
create-dmg --volname "Cube Shell" \
  --window-size 800 400 \
  --app-drop-link 400 200 \
  deploy/cube-shell.dmg cube-shell.app

rm -rf cube-shell.dist
rm -rf cube-shell.build

# 退出虚拟环境
deactivate