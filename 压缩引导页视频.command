#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "启动引导页视频压缩工具..."
echo "如果图形界面不可用，会自动使用 macOS 文件夹选择弹窗。"
echo

python3 "$SCRIPT_DIR/compress_onboarding_videos.py" --gui

