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
ZIP_PATH="$PROJECT_DIR/dist/$APP_NAME.zip"
NOTARIZED_ZIP_PATH="$PROJECT_DIR/dist/$APP_NAME-notarized.zip"
SIGN_IDENTITY="${DEVELOPER_ID_APPLICATION:-${CODESIGN_IDENTITY:--}}"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"

sign_target() {
  local target="$1"
  if [ "$SIGN_IDENTITY" = "-" ]; then
    codesign --force --sign - "$target" >/dev/null
  else
    codesign --force --timestamp --options runtime --sign "$SIGN_IDENTITY" "$target"
  fi
}

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cp "$PROJECT_DIR/compress_onboarding_videos.py" "$RESOURCES_DIR/compress_onboarding_videos.py"
cp "$PROJECT_DIR/Sources/NativeCompressor.swift" "$RESOURCES_DIR/NativeCompressor.swift"

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
else
  echo "Warning: bin/ffmpeg and bin/ffprobe were not found. The app will open, but non-developer machines need bundled ffmpeg/ffprobe to process videos." >&2
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

cat > "$PROJECT_DIR/dist/launcher.c" <<'C'
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int exists_executable(const char *path) {
  return access(path, X_OK) == 0;
}

int main(int argc, char **argv) {
  char exe_path[PATH_MAX];
  ssize_t len = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
  if (len < 0) {
    unsigned int size = sizeof(exe_path);
    if (_NSGetExecutablePath(exe_path, &size) != 0) {
      return 1;
    }
  } else {
    exe_path[len] = '\0';
  }

  char *last_slash = strrchr(exe_path, '/');
  if (!last_slash) {
    return 1;
  }
  *last_slash = '\0';

  char script[PATH_MAX];
  snprintf(script, sizeof(script), "%s/../Resources/compress_onboarding_videos.py", exe_path);

  const char *python = NULL;
  const char *candidates[] = {
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
    NULL
  };
  for (int i = 0; candidates[i] != NULL; i++) {
    if (exists_executable(candidates[i])) {
      python = candidates[i];
      break;
    }
  }

  if (!python) {
    system("osascript -e 'display dialog \"未找到 python3，无法启动工具。\" with title \"启动失败\" buttons {\"好\"} default button \"好\"'");
    return 1;
  }

  execl(python, python, script, "--gui", (char *)NULL);
  return 1;
}
C

if clang -arch arm64 -arch x86_64 -framework CoreFoundation -include mach-o/dyld.h "$PROJECT_DIR/dist/launcher.c" -o "$MACOS_DIR/launcher" 2>/dev/null; then
  :
else
  echo "Warning: failed to build universal launcher; falling back to native architecture." >&2
  clang -framework CoreFoundation -include mach-o/dyld.h "$PROJECT_DIR/dist/launcher.c" -o "$MACOS_DIR/launcher"
fi
rm -f "$PROJECT_DIR/dist/launcher.c"

if command -v swiftc >/dev/null 2>&1; then
  if swiftc -O -parse-as-library -target arm64-apple-macos11 "$PROJECT_DIR/Sources/NativeCompressor.swift" -o "$PROJECT_DIR/dist/native-launcher-arm64" 2>/dev/null \
    && swiftc -O -parse-as-library -target x86_64-apple-macos11 "$PROJECT_DIR/Sources/NativeCompressor.swift" -o "$PROJECT_DIR/dist/native-launcher-x86_64" 2>/dev/null; then
    lipo -create "$PROJECT_DIR/dist/native-launcher-arm64" "$PROJECT_DIR/dist/native-launcher-x86_64" -output "$MACOS_DIR/launcher"
    rm -f "$PROJECT_DIR/dist/native-launcher-arm64" "$PROJECT_DIR/dist/native-launcher-x86_64"
  elif swiftc -O -parse-as-library "$PROJECT_DIR/Sources/NativeCompressor.swift" -o "$MACOS_DIR/launcher" 2>/dev/null; then
    :
  else
    echo "Warning: failed to build native Swift launcher; using Python launcher." >&2
  fi
fi

xattr -cr "$APP_DIR" 2>/dev/null || true

if [ -d "$RESOURCES_DIR/bin" ]; then
  while IFS= read -r -d '' tool; do
    if [ -x "$tool" ]; then
      sign_target "$tool"
    fi
  done < <(find "$RESOURCES_DIR/bin" -type f -print0)
fi

sign_target "$MACOS_DIR/launcher"
if [ "$SIGN_IDENTITY" = "-" ]; then
  codesign --force --deep --sign - "$APP_DIR" >/dev/null
else
  codesign --force --deep --timestamp --options runtime --sign "$SIGN_IDENTITY" "$APP_DIR"
fi

if command -v ditto >/dev/null 2>&1; then
  rm -f "$ZIP_PATH" "$NOTARIZED_ZIP_PATH"
  ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$ZIP_PATH"
fi

if [ -n "$NOTARY_PROFILE" ]; then
  if [ "$SIGN_IDENTITY" = "-" ]; then
    echo "ERROR: notarization requires Developer ID signing. Set DEVELOPER_ID_APPLICATION." >&2
    exit 1
  fi
  if ! command -v xcrun >/dev/null 2>&1; then
    echo "ERROR: xcrun is required for notarization." >&2
    exit 1
  fi
  xcrun notarytool submit "$ZIP_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_DIR"
  xcrun stapler validate "$APP_DIR"
  ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$NOTARIZED_ZIP_PATH"
fi

echo "$APP_DIR"
lipo -info "$MACOS_DIR/launcher" 2>/dev/null || file "$MACOS_DIR/launcher"
codesign --verify --deep --strict "$APP_DIR"
spctl -a -vvv -t exec "$APP_DIR" || true
if [ -f "$NOTARIZED_ZIP_PATH" ]; then
  echo "$NOTARIZED_ZIP_PATH"
elif [ -f "$ZIP_PATH" ]; then
  echo "$ZIP_PATH"
fi
