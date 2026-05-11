# Onboarding Video Compressor

面向团队复用的引导页视频压缩工具。

固定规则：

- 输出尺寸：用户选择，默认推荐 `480x640`
- 压缩强度：用户选择，默认推荐 `CRF 26`
- 视频格式：`.mp4`
- 视频编码：`H.264 / libx264`
- 质量参数：`CRF 26`
- 编码参数：`preset slow`
- 音轨：移除
- 海报：自动生成首帧 `*_poster.jpg`
- 源文件：不覆盖、不修改
- 输出目录：输入目录下的 `output/video_compressed_480x640_no_audio_<timestamp>/`

## 非技术同事用法

优先使用 macOS App：

```bash
./build_macos_app.sh
open "dist/引导页视频压缩工具.app"
```

也可以双击：

```text
压缩引导页视频.command
```

工具会弹出文件夹选择窗口，选择包含视频的目录后自动处理，完成后打开输出目录。
处理前会让用户选择目标视频尺寸和压缩强度，支持预设值和自定义值。

## 体积控制参数

对输出视频大小影响最大的是：

1. 目标尺寸：像素越少，体积通常越小。例如 `360x480` 会明显小于 `720x960`。
2. CRF：同一尺寸下最重要的体积/画质参数。CRF 越高体积越小，画质损失越明显。

工具内置压缩强度：

| 选项 | CRF | 说明 |
|---|---:|---|
| 高清 | 23 | 画质更好，体积较大 |
| 标准 | 26 | 推荐默认值 |
| 更小 | 30 | 体积更小，画质略降 |
| 极小 | 34 | 体积更小，画质下降明显 |

`preset slow` 主要影响编码耗时和压缩效率，默认固定，不面向普通用户暴露。

## 命令行用法

```bash
python3 compress_onboarding_videos.py "/path/to/video-folder" --size 480x640 --crf 26 --open
```

启动图形/文件夹选择模式：

```bash
python3 compress_onboarding_videos.py --gui
```

## 依赖

需要 `python3`、`ffmpeg`、`ffprobe`。

工程机可安装：

```bash
brew install ffmpeg
```

普通同事的 Mac 通常没有 Homebrew、Python、ffmpeg。正式分发版必须让 App 自带 `ffmpeg/ffprobe`。

把可独立运行的 macOS `ffmpeg` 和 `ffprobe` 放到：

```text
bin/ffmpeg
bin/ffprobe
```

然后重新构建：

```bash
./build_macos_app.sh
```

构建脚本会把它们复制到：

```text
dist/引导页视频压缩工具.app/Contents/Resources/bin/
```

注意：不要直接复制 Homebrew 的 `/usr/local/bin/ffmpeg` 给同事分发。Homebrew 版通常依赖大量本机 dylib，在别的电脑上会缺库。应使用静态构建或随 App 一起打包所有依赖。

当前 App launcher 是原生 Swift universal binary，不依赖 Python；但如果没有内置 `ffmpeg/ffprobe`，普通同事打开 App 后会看到“缺少内置依赖”的提示。

## App 图标

图标源文件：

```text
assets/app_icon_1024.png
```

构建脚本会自动生成 macOS `.icns` 文件，并写入：

```text
dist/引导页视频压缩工具.app/Contents/Resources/AppIcon.icns
```

如果要换图标，替换 `assets/app_icon_1024.png` 后重新运行：

```bash
./build_macos_app.sh
```

## 输出内容

每次处理会生成：

```text
output/video_compressed_480x640_crf26_no_audio_<timestamp>/
  videos/
    xxx.mp4
    xxx_poster.jpg
  final_report.tsv
  summary.md
  FFMPEG_PROCESS.md
```

其中 `480x640` 会替换为本次选择的目标尺寸，例如：

```text
output/video_compressed_720x960_crf30_no_audio_<timestamp>/
```

## 文档

完整参数、流程图、时序图见：

```text
docs/video-compress-480x640-no-audio.md
```
