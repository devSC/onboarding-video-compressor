#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="引导页视频压缩工具"
APP_DIR="$PROJECT_DIR/dist/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
ICON_SOURCE="$PROJECT_DIR/assets/app_icon_1024.png"
ICONSET_DIR="$PROJECT_DIR/dist/AppIcon.iconset"
ICON_FILE_NAME="AppIcon.icns"

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cp "$PROJECT_DIR/compress_onboarding_videos.py" "$RESOURCES_DIR/compress_onboarding_videos.py"

if [ -f "$ICON_SOURCE" ]; then
  rm -rf "$ICONSET_DIR"
  mkdir -p "$ICONSET_DIR"
  sips -z 16 16 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  cp "$ICON_SOURCE" "$ICONSET_DIR/icon_512x512@2x.png"
  iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/$ICON_FILE_NAME"
  rm -rf "$ICONSET_DIR"
fi

if [ -x "$PROJECT_DIR/bin/ffmpeg" ] || [ -x "$PROJECT_DIR/bin/ffprobe" ]; then
  mkdir -p "$RESOURCES_DIR/bin"
  [ -x "$PROJECT_DIR/bin/ffmpeg" ] && cp "$PROJECT_DIR/bin/ffmpeg" "$RESOURCES_DIR/bin/ffmpeg"
  [ -x "$PROJECT_DIR/bin/ffprobe" ] && cp "$PROJECT_DIR/bin/ffprobe" "$RESOURCES_DIR/bin/ffprobe"
fi

cat > "$CONTENTS_DIR/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>引导页视频压缩工具</string>
  <key>CFBundleExecutable</key>
  <string>launcher</string>
  <key>CFBundleIdentifier</key>
  <string>com.guru.tools.onboarding-video-compressor</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>引导页视频压缩工具</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>10.15</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$MACOS_DIR/launcher" <<'SH'
#!/bin/bash
set -euo pipefail

APP_MACOS_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES_DIR="$(cd "$APP_MACOS_DIR/../Resources" && pwd)"
SCRIPT="$RESOURCES_DIR/compress_onboarding_videos.py"

PYTHON_BIN=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$candidate" ]; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  osascript -e 'display dialog "未找到 python3，无法启动工具。" with title "启动失败" buttons {"好"} default button "好"'
  exit 1
fi

"$PYTHON_BIN" "$SCRIPT" --gui
SH

chmod +x "$MACOS_DIR/launcher"

echo "$APP_DIR"
