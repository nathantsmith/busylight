#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BUILD_VENV="$ROOT_DIR/.venv"
BUILD_PYTHON="$BUILD_VENV/bin/python"

if [[ ! -x "$BUILD_PYTHON" ]]; then
  echo "Missing .venv/bin/python. Run: uv sync"
  exit 1
fi

echo "Checking app dependencies..."
"$BUILD_PYTHON" -c "import rumps, PIL, govee_local_api, inquirer"
if ! "$BUILD_PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "Installing PyInstaller..."
  uv pip install --python "$BUILD_PYTHON" pyinstaller
fi

rm -rf dist/Busylights dist/Busylights.app build/pyinstaller
"$BUILD_PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name Busylights \
  --icon assets/app_icon.icns \
  --osx-bundle-identifier com.busylights.app \
  --add-data "assets:assets" \
  --hidden-import busylights \
  --hidden-import busylights_menubar \
  --hidden-import busylights_gui \
  --hidden-import mic_status \
  --hidden-import govee_local_api \
  --hidden-import rumps \
  --copy-metadata readchar \
  --distpath dist \
  --workpath build/pyinstaller \
  main.py

set_plist_string() {
  local key="$1"
  local value="$2"
  /usr/libexec/PlistBuddy -c "Set :$key $value" dist/Busylights.app/Contents/Info.plist 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Add :$key string $value" dist/Busylights.app/Contents/Info.plist
}

set_plist_string CFBundleShortVersionString 1.0.0
set_plist_string CFBundleVersion 1.0.0
/usr/libexec/PlistBuddy -c "Set :LSUIElement true" dist/Busylights.app/Contents/Info.plist 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" dist/Busylights.app/Contents/Info.plist
codesign --force --deep --sign - dist/Busylights.app >/dev/null

echo
echo "Built dist/Busylights.app"
