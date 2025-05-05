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
  --enable-plugin=pyside6 \
  --follow-imports \
  --macos-app-icon=icons/logo.icns \
  --include-module=qdarktheme \
  --include-module=deepdiff \
  --include-module=pygments \
  --include-module=paramiko \
  --include-module=pyte \
  --include-module=yaml \
  --include-module=pygments.formatters.html \
  --include-module=pygments.lexers.python \
  --include-package=core,function,style,ui,icons \
  --include-data-dir=conf=conf \
  --include-data-dir=frp=frp \
  cube-shell.py

# Step 4: Create tunnel.json file
echo "4: Creating tunnel.json file..."
echo "{}" > cube-shell.app/Contents/MacOS/conf/tunnel.json

# Step 5: Delete config.dat file
echo "5: Deleting config.dat file..."
rm -f cube-shell.app/Contents/MacOS/conf/config.dat

echo "5: create-dmg..."
create-dmg --volname "Cube Shell" \
  --window-size 800 400 \
  --app-drop-link 400 200 \
  deploy/cube-shell.dmg cube-shell.app

rm -rf cube-shell.dist
rm -rf cube-shell.build

# 退出虚拟环境
deactivate