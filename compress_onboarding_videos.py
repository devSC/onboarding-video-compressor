#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import os
import queue
import shutil
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
DEFAULT_TARGET_W = 480
DEFAULT_TARGET_H = 640
PRESET_SIZES = [
    (480, 640, "480x640 - 推荐，引导页轻量版"),
    (720, 960, "720x960 - 更清晰，体积更大"),
    (1080, 1440, "1080x1440 - 接近原始尺寸"),
    (360, 480, "360x480 - 更小体积"),
]
CUSTOM_SIZE_LABEL = "自定义尺寸..."
DEFAULT_CRF = 26
QUALITY_PRESETS = [
    (23, "高清 - CRF 23，体积较大"),
    (26, "标准 - CRF 26，推荐"),
    (30, "更小 - CRF 30，画质略降"),
    (34, "极小 - CRF 34，画质下降明显"),
]
CUSTOM_CRF_LABEL = "自定义 CRF..."
PRESET = "slow"
POSTER_Q = 6


@dataclass(frozen=True)
class ProcessResult:
    status: str
    file_name: str
    source_path: Path
    output_path: Path
    poster_path: Path
    source_bytes: int
    output_bytes: int
    poster_bytes: int
    saved_percent: float
    dimension: str
    audio_streams: int
    error: str = ""


@dataclass(frozen=True)
class TargetSize:
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class CompressionSettings:
    target_size: TargetSize
    crf: int

    @property
    def output_label(self) -> str:
        return f"{self.target_size.label}_crf{self.crf}"


def human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    kb = n / 1024.0
    if kb < 1024:
        return f"{kb:.1f} KB"
    return f"{kb / 1024.0:.2f} MB"


def parse_target_size(raw: str) -> TargetSize:
    value = raw.strip().lower().replace(" ", "")
    if "x" not in value:
        raise argparse.ArgumentTypeError("尺寸格式应为 WIDTHxHEIGHT，例如 480x640")
    w_s, h_s = value.split("x", 1)
    try:
        width = int(w_s)
        height = int(h_s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("尺寸必须是整数，例如 480x640") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("尺寸必须大于 0")
    if width % 2 != 0 or height % 2 != 0:
        raise argparse.ArgumentTypeError("H.264 输出尺寸必须是偶数")
    return TargetSize(width=width, height=height)


def parse_crf(raw: str) -> int:
    try:
        crf = int(str(raw).strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("CRF 必须是整数，例如 26") from exc
    if crf < 0 or crf > 51:
        raise argparse.ArgumentTypeError("CRF 范围必须是 0..51")
    return crf


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def find_tool(name: str) -> Optional[str]:
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "bin" / name,
        script_dir.parent / "bin" / name,
        script_dir.parent / "Resources" / "bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    found = shutil.which(name)
    return found


def require_tools() -> tuple[str, str]:
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    missing = []
    if not ffmpeg:
        missing.append("ffmpeg")
    if not ffprobe:
        missing.append("ffprobe")
    if missing:
        raise RuntimeError(
            "未找到依赖工具："
            + ", ".join(missing)
            + "\n\n请先安装 ffmpeg，或把 ffmpeg/ffprobe 放到 tools/bin/ 目录。"
            + "\nmacOS 可用：brew install ffmpeg"
        )
    return ffmpeg, ffprobe


def iter_videos(input_dir: Path) -> list[Path]:
    return sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )


def ffprobe_dimension(ffprobe: str, path: Path) -> str:
    cp = run([
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        str(path),
    ])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"ffprobe 读取尺寸失败：{path}")
    return cp.stdout.strip()


def ffprobe_audio_count(ffprobe: str, path: Path) -> int:
    cp = run([
        ffprobe,
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(path),
    ])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"ffprobe 读取音轨失败：{path}")
    return len([line for line in cp.stdout.splitlines() if line.strip()])


def encode_video(ffmpeg: str, src: Path, dst: Path, settings: CompressionSettings) -> None:
    cp = run([
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(src),
        "-map", "0:v:0",
        "-vf",
        (
            f"scale={settings.target_size.width}:{settings.target_size.height}:force_original_aspect_ratio=increase,"
            f"crop={settings.target_size.width}:{settings.target_size.height}"
        ),
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", str(settings.crf),
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        str(dst),
    ])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"ffmpeg 编码失败：{src}")


def verify_decode(ffmpeg: str, path: Path) -> None:
    cp = run([
        ffmpeg,
        "-nostdin",
        "-v", "error",
        "-i", str(path),
        "-f", "null",
        "-",
    ])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"解码校验失败：{path}")


def generate_poster(ffmpeg: str, video: Path, poster: Path) -> None:
    cp = run([
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", str(POSTER_Q),
        str(poster),
    ])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"海报生成失败：{video}")


def write_report(report_path: Path, results: Iterable[ProcessResult]) -> None:
    with report_path.open("w", encoding="utf-8") as fp:
        fp.write(
            "status\tfile\tsource_bytes\tsource_human\toutput_bytes\toutput_human\t"
            "saved_percent\tdimension\taudio_streams\tposter_path\tposter_bytes\t"
            "poster_human\tsource_path\toutput_path\terror\n"
        )
        for result in results:
            fp.write(
                f"{result.status}\t"
                f"{result.file_name}\t"
                f"{result.source_bytes}\t{human_bytes(result.source_bytes)}\t"
                f"{result.output_bytes}\t{human_bytes(result.output_bytes)}\t"
                f"{result.saved_percent:.2f}%\t"
                f"{result.dimension}\t{result.audio_streams}\t"
                f"{result.poster_path}\t{result.poster_bytes}\t{human_bytes(result.poster_bytes)}\t"
                f"{result.source_path}\t{result.output_path}\t"
                f"{result.error.replace(chr(9), ' ').replace(chr(10), ' ')}\n"
            )


def write_summary_md(
    summary_path: Path,
    input_dir: Path,
    out_root: Path,
    results: list[ProcessResult],
    settings: CompressionSettings,
) -> None:
    success = [r for r in results if r.status == "success"]
    failed = [r for r in results if r.status != "success"]
    total_src = sum(r.source_bytes for r in success)
    total_out = sum(r.output_bytes for r in success)
    saved = ((total_src - total_out) * 100 / total_src) if total_src else 0.0

    lines = [
        "# 视频压缩结果",
        "",
        f"输入目录：`{input_dir}`",
        f"输出目录：`{out_root / 'videos'}`",
        "",
        "## 规则",
        "",
        f"- 输出尺寸：`{settings.target_size.label}`",
        "- 音轨：移除",
        f"- 视频编码：`libx264 / CRF {settings.crf} / preset {PRESET}`",
        "- 海报：首帧 JPG",
        "- 源文件：不覆盖、不修改",
        "",
        "## 汇总",
        "",
        f"- 成功：{len(success)}",
        f"- 失败：{len(failed)}",
        f"- 视频总大小：`{human_bytes(total_src)} -> {human_bytes(total_out)}`",
        f"- 节省：`{saved:.2f}%`",
        "",
        "## 明细",
        "",
        "| 文件 | 原始大小 | 输出大小 | 节省 | 尺寸 | 音轨 | 海报 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        poster = human_bytes(result.poster_bytes) if result.poster_bytes else "-"
        lines.append(
            f"| {result.file_name} | {human_bytes(result.source_bytes)} | "
            f"{human_bytes(result.output_bytes)} | {result.saved_percent:.2f}% | "
            f"{result.dimension or '-'} | {result.audio_streams} | {poster} | {result.status} |"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_process_doc(doc_path: Path, input_dir: Path, out_root: Path, settings: CompressionSettings) -> None:
    doc_path.write_text(f"""# {settings.target_size.label} 无音轨视频压缩处理说明

输入目录：`{input_dir}`
输出目录：`{out_root / "videos"}`
目标尺寸：`{settings.target_size.label}`
CRF：`{settings.crf}`

## 参数

```bash
ffmpeg \\
  -nostdin \\
  -hide_banner \\
  -loglevel error \\
  -y \\
  -i "input.mp4" \\
  -map 0:v:0 \\
  -vf "scale={settings.target_size.width}:{settings.target_size.height}:force_original_aspect_ratio=increase,crop={settings.target_size.width}:{settings.target_size.height}" \\
  -c:v libx264 \\
  -preset slow \\
  -crf {settings.crf} \\
  -pix_fmt yuv420p \\
  -an \\
  -movflags +faststart \\
  -map_metadata -1 \\
  -map_chapters -1 \\
  "output.mp4"
```

## 海报

```bash
ffmpeg \\
  -nostdin \\
  -hide_banner \\
  -loglevel error \\
  -y \\
  -i "output.mp4" \\
  -frames:v 1 \\
  -q:v 6 \\
  "output_poster.jpg"
```

## 流程

```mermaid
flowchart TD
  A["选择视频文件夹"] --> B["扫描视频文件"]
  B --> C["选择目标尺寸"]
  C --> D["逐个处理"]
  D --> E["缩放并裁剪为 {settings.target_size.label}"]
  E --> F["libx264 / CRF {settings.crf} / preset slow 编码"]
  F --> G["移除音轨"]
  G --> H["解码校验"]
  H --> I["生成首帧海报"]
  I --> J["写入报告"]
  J --> K["打开输出目录"]
```
""", encoding="utf-8")


def process_folder(
    input_dir: Path,
    settings: CompressionSettings,
    log: Callable[[str], None] = print,
) -> Path:
    input_dir = input_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise RuntimeError(f"输入目录不存在：{input_dir}")

    ffmpeg, ffprobe = require_tools()
    videos = iter_videos(input_dir)
    if not videos:
        raise RuntimeError(f"没有找到视频文件：{input_dir}")

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = input_dir / "output" / f"video_compressed_{settings.output_label}_no_audio_{run_id}"
    videos_dir = out_root / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    log(f"输入目录：{input_dir}")
    log(f"输出目录：{videos_dir}")
    log(f"目标尺寸：{settings.target_size.label}")
    log(f"压缩强度：CRF {settings.crf}")
    log(f"共找到 {len(videos)} 个视频")

    results: list[ProcessResult] = []
    for idx, src in enumerate(videos, start=1):
        log(f"[{idx}/{len(videos)}] 处理：{src.name}")
        out = videos_dir / f"{src.stem}.mp4"
        poster = videos_dir / f"{src.stem}_poster.jpg"
        source_bytes = src.stat().st_size
        try:
            encode_video(ffmpeg, src, out, settings)
            verify_decode(ffmpeg, out)
            generate_poster(ffmpeg, out, poster)

            output_bytes = out.stat().st_size
            poster_bytes = poster.stat().st_size
            dimension = ffprobe_dimension(ffprobe, out)
            audio_streams = ffprobe_audio_count(ffprobe, out)
            saved_percent = ((source_bytes - output_bytes) * 100 / source_bytes) if source_bytes else 0.0

            result = ProcessResult(
                status="success",
                file_name=src.name,
                source_path=src,
                output_path=out,
                poster_path=poster,
                source_bytes=source_bytes,
                output_bytes=output_bytes,
                poster_bytes=poster_bytes,
                saved_percent=saved_percent,
                dimension=dimension,
                audio_streams=audio_streams,
            )
            log(
                f"完成：{src.name}  {human_bytes(source_bytes)} -> "
                f"{human_bytes(output_bytes)}，节省 {saved_percent:.2f}%，"
                f"尺寸 {dimension}，音轨 {audio_streams}"
            )
        except Exception as exc:
            result = ProcessResult(
                status="failed",
                file_name=src.name,
                source_path=src,
                output_path=out,
                poster_path=poster,
                source_bytes=source_bytes,
                output_bytes=out.stat().st_size if out.exists() else 0,
                poster_bytes=poster.stat().st_size if poster.exists() else 0,
                saved_percent=0.0,
                dimension="",
                audio_streams=-1,
                error=str(exc),
            )
            log(f"失败：{src.name}：{exc}")
        results.append(result)
        write_report(out_root / "final_report.tsv", results)

    write_report(out_root / "final_report.tsv", results)
    write_summary_md(out_root / "summary.md", input_dir, out_root, results, settings)
    write_process_doc(out_root / "FFMPEG_PROCESS.md", input_dir, out_root, settings)

    success = [r for r in results if r.status == "success"]
    total_src = sum(r.source_bytes for r in success)
    total_out = sum(r.output_bytes for r in success)
    saved = ((total_src - total_out) * 100 / total_src) if total_src else 0.0
    log("")
    log(f"处理完成：成功 {len(success)} 个，失败 {len(results) - len(success)} 个")
    log(f"总大小：{human_bytes(total_src)} -> {human_bytes(total_out)}，节省 {saved:.2f}%")
    log(f"报告：{out_root / 'final_report.tsv'}")
    log(f"说明：{out_root / 'FFMPEG_PROCESS.md'}")
    return out_root


def open_in_finder(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)


def choose_folder_with_osascript() -> Optional[Path]:
    if sys.platform != "darwin":
        return None
    cp = run([
        "osascript",
        "-e",
        'POSIX path of (choose folder with prompt "请选择包含视频的文件夹")',
    ])
    if cp.returncode != 0:
        return None
    raw = cp.stdout.strip()
    if not raw:
        return None
    return Path(raw)


def choose_target_size_with_osascript() -> Optional[TargetSize]:
    if sys.platform != "darwin":
        return TargetSize(DEFAULT_TARGET_W, DEFAULT_TARGET_H)
    items = ", ".join([*(f'"{label}"' for _, _, label in PRESET_SIZES), f'"{CUSTOM_SIZE_LABEL}"'])
    cp = run([
        "osascript",
        "-e",
        (
            f'choose from list {{{items}}} '
            'with title "选择目标视频尺寸" '
            'with prompt "请选择压缩后的视频尺寸：" '
            f'default items {{"{PRESET_SIZES[0][2]}"}} '
            'OK button name "继续" cancel button name "取消"'
        ),
    ])
    if cp.returncode != 0:
        return None
    raw = cp.stdout.strip()
    if not raw or raw == "false":
        return None
    if raw == CUSTOM_SIZE_LABEL:
        custom = run([
            "osascript",
            "-e",
            (
                'text returned of (display dialog "请输入目标尺寸，格式如 480x640：" '
                'with title "自定义目标尺寸" default answer "480x640" '
                'buttons {"取消", "继续"} default button "继续" cancel button "取消")'
            ),
        ])
        if custom.returncode != 0:
            return None
        try:
            return parse_target_size(custom.stdout.strip())
        except Exception as exc:
            show_macos_dialog("尺寸格式错误", str(exc))
            return None
    for width, height, label in PRESET_SIZES:
        if raw == label:
            return TargetSize(width, height)
    return TargetSize(DEFAULT_TARGET_W, DEFAULT_TARGET_H)


def choose_crf_with_osascript() -> Optional[int]:
    if sys.platform != "darwin":
        return DEFAULT_CRF
    items = ", ".join([*(f'"{label}"' for _, label in QUALITY_PRESETS), f'"{CUSTOM_CRF_LABEL}"'])
    cp = run([
        "osascript",
        "-e",
        (
            f'choose from list {{{items}}} '
            'with title "选择压缩强度" '
            'with prompt "同一尺寸下，CRF 越高体积越小、画质越低。请选择：" '
            f'default items {{"{QUALITY_PRESETS[1][1]}"}} '
            'OK button name "继续" cancel button name "取消"'
        ),
    ])
    if cp.returncode != 0:
        return None
    raw = cp.stdout.strip()
    if not raw or raw == "false":
        return None
    if raw == CUSTOM_CRF_LABEL:
        custom = run([
            "osascript",
            "-e",
            (
                'text returned of (display dialog "请输入 CRF，范围 0..51。数值越高体积越小，推荐 26：" '
                'with title "自定义 CRF" default answer "26" '
                'buttons {"取消", "继续"} default button "继续" cancel button "取消")'
            ),
        ])
        if custom.returncode != 0:
            return None
        try:
            return parse_crf(custom.stdout.strip())
        except Exception as exc:
            show_macos_dialog("CRF 格式错误", str(exc))
            return None
    for crf, label in QUALITY_PRESETS:
        if raw == label:
            return crf
    return DEFAULT_CRF


def show_macos_dialog(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display dialog "{safe_message}" with title "{safe_title}" buttons {{"好"}} default button "好"',
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_macos_folder_picker_flow() -> int:
    folder = choose_folder_with_osascript()
    if folder is None:
        print("未选择文件夹，已取消。")
        return 1
    target_size = choose_target_size_with_osascript()
    if target_size is None:
        print("未选择目标尺寸，已取消。")
        return 1
    crf = choose_crf_with_osascript()
    if crf is None:
        print("未选择压缩强度，已取消。")
        return 1
    settings = CompressionSettings(target_size=target_size, crf=crf)
    try:
        out_root = process_folder(folder, settings)
    except Exception as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        show_macos_dialog("处理失败", str(exc))
        return 1
    open_in_finder(out_root / "videos")
    show_macos_dialog("处理完成", f"视频已输出到：\n{out_root / 'videos'}")
    return 0


def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:
        if sys.platform == "darwin":
            print(f"Tkinter 图形界面不可用，改用 macOS 文件夹选择器：{exc}")
            return run_macos_folder_picker_flow()
        print(f"无法启动图形界面：{exc}", file=sys.stderr)
        return 1

    root = tk.Tk()
    root.title("引导页视频压缩工具")
    root.geometry("760x560")
    root.minsize(680, 500)

    selected_dir = tk.StringVar(value="")
    selected_size = tk.StringVar(value=PRESET_SIZES[0][2])
    custom_size = tk.StringVar(value="")
    selected_quality = tk.StringVar(value=QUALITY_PRESETS[1][1])
    custom_crf = tk.StringVar(value="")
    status_text = tk.StringVar(value="请选择包含视频的文件夹。")
    output_root: dict[str, Path] = {}
    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    title = ttk.Label(frame, text="引导页视频压缩工具", font=("TkDefaultFont", 18, "bold"))
    title.pack(anchor="w")

    rule = ttk.Label(
        frame,
        text="规则：选择目标尺寸 / 无音轨 / 自动生成海报 / 自动生成报告 / 不修改源文件",
    )
    rule.pack(anchor="w", pady=(6, 14))

    size_row = ttk.Frame(frame)
    size_row.pack(fill="x", pady=(0, 12))
    ttk.Label(size_row, text="目标尺寸：").pack(side="left")
    size_combo = ttk.Combobox(
        size_row,
        textvariable=selected_size,
        values=[label for _, _, label in PRESET_SIZES],
        state="readonly",
        width=34,
    )
    size_combo.pack(side="left")

    custom_row = ttk.Frame(frame)
    custom_row.pack(fill="x", pady=(0, 12))
    ttk.Label(custom_row, text="自定义尺寸：").pack(side="left")
    custom_entry = ttk.Entry(custom_row, textvariable=custom_size, width=18)
    custom_entry.pack(side="left")
    ttk.Label(custom_row, text="可选，例如 640x960；填写后优先使用").pack(side="left", padx=(8, 0))

    quality_row = ttk.Frame(frame)
    quality_row.pack(fill="x", pady=(0, 12))
    ttk.Label(quality_row, text="压缩强度：").pack(side="left")
    quality_combo = ttk.Combobox(
        quality_row,
        textvariable=selected_quality,
        values=[label for _, label in QUALITY_PRESETS],
        state="readonly",
        width=34,
    )
    quality_combo.pack(side="left")

    custom_crf_row = ttk.Frame(frame)
    custom_crf_row.pack(fill="x", pady=(0, 12))
    ttk.Label(custom_crf_row, text="自定义 CRF：").pack(side="left")
    custom_crf_entry = ttk.Entry(custom_crf_row, textvariable=custom_crf, width=18)
    custom_crf_entry.pack(side="left")
    ttk.Label(custom_crf_row, text="可选，0..51；越高越小，填写后优先使用").pack(side="left", padx=(8, 0))

    picker = ttk.Frame(frame)
    picker.pack(fill="x")
    entry = ttk.Entry(picker, textvariable=selected_dir)
    entry.pack(side="left", fill="x", expand=True)

    def choose_dir() -> None:
        chosen = filedialog.askdirectory(title="选择视频文件夹")
        if chosen:
            selected_dir.set(chosen)
            status_text.set("已选择文件夹，可以开始压缩。")

    ttk.Button(picker, text="选择视频文件夹", command=choose_dir).pack(side="left", padx=(8, 0))

    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x", pady=(16, 8))

    status_label = ttk.Label(frame, textvariable=status_text)
    status_label.pack(anchor="w")

    log_box = tk.Text(frame, height=18, wrap="word")
    log_box.pack(fill="both", expand=True, pady=(12, 8))
    log_box.configure(state="disabled")

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    start_button = ttk.Button(buttons, text="开始压缩")
    start_button.pack(side="left")

    open_output_button = ttk.Button(buttons, text="打开输出目录", state="disabled")
    open_output_button.pack(side="left", padx=(8, 0))

    open_report_button = ttk.Button(buttons, text="打开报告", state="disabled")
    open_report_button.pack(side="left", padx=(8, 0))

    def append_log(text: str) -> None:
        log_box.configure(state="normal")
        log_box.insert("end", text + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def current_target_size() -> TargetSize:
        raw_custom = custom_size.get().strip()
        if raw_custom:
            return parse_target_size(raw_custom)
        label = selected_size.get()
        for width, height, item_label in PRESET_SIZES:
            if label == item_label:
                return TargetSize(width, height)
        return TargetSize(DEFAULT_TARGET_W, DEFAULT_TARGET_H)

    def current_crf() -> int:
        raw_custom = custom_crf.get().strip()
        if raw_custom:
            return parse_crf(raw_custom)
        label = selected_quality.get()
        for crf, item_label in QUALITY_PRESETS:
            if label == item_label:
                return crf
        return DEFAULT_CRF

    def worker(folder: Path, settings: CompressionSettings) -> None:
        try:
            out_root = process_folder(folder, settings, log=lambda msg: event_queue.put(("log", msg)))
            event_queue.put(("done", out_root))
        except Exception as exc:
            event_queue.put(("error", f"{exc}\n\n{traceback.format_exc()}"))

    def start() -> None:
        raw = selected_dir.get().strip()
        if not raw:
            messagebox.showwarning("请选择文件夹", "请先选择包含视频的文件夹。")
            return
        folder = Path(raw)
        if not folder.is_dir():
            messagebox.showerror("文件夹不存在", f"找不到文件夹：\n{folder}")
            return
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")
        start_button.configure(state="disabled")
        open_output_button.configure(state="disabled")
        open_report_button.configure(state="disabled")
        status_text.set("处理中...")
        progress.start(10)
        try:
            target_size = current_target_size()
            settings = CompressionSettings(target_size=target_size, crf=current_crf())
        except Exception as exc:
            progress.stop()
            start_button.configure(state="normal")
            messagebox.showerror("参数格式错误", str(exc))
            return
        threading.Thread(target=worker, args=(folder, settings), daemon=True).start()

    def poll_queue() -> None:
        try:
            while True:
                kind, payload = event_queue.get_nowait()
                if kind == "log":
                    append_log(str(payload))
                elif kind == "done":
                    out_root = payload
                    assert isinstance(out_root, Path)
                    output_root["path"] = out_root
                    progress.stop()
                    start_button.configure(state="normal")
                    open_output_button.configure(state="normal")
                    open_report_button.configure(state="normal")
                    status_text.set("处理完成。")
                    open_in_finder(out_root / "videos")
                    messagebox.showinfo("处理完成", f"视频已输出到：\n{out_root / 'videos'}")
                elif kind == "error":
                    progress.stop()
                    start_button.configure(state="normal")
                    status_text.set("处理失败。")
                    append_log(str(payload))
                    messagebox.showerror("处理失败", str(payload).splitlines()[0])
        except queue.Empty:
            pass
        root.after(150, poll_queue)

    def open_output() -> None:
        out_root = output_root.get("path")
        if out_root:
            open_in_finder(out_root / "videos")

    def open_report() -> None:
        out_root = output_root.get("path")
        if out_root:
            open_in_finder(out_root / "summary.md")

    start_button.configure(command=start)
    open_output_button.configure(command=open_output)
    open_report_button.configure(command=open_report)

    root.after(150, poll_queue)
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compress onboarding videos to selected-size no-audio MP4.")
    parser.add_argument("input_dir", nargs="?", type=Path, help="包含视频文件的输入目录")
    parser.add_argument(
        "--size",
        type=parse_target_size,
        default=TargetSize(DEFAULT_TARGET_W, DEFAULT_TARGET_H),
        help="目标视频尺寸，格式 WIDTHxHEIGHT，例如 480x640、720x960",
    )
    parser.add_argument(
        "--crf",
        type=parse_crf,
        default=DEFAULT_CRF,
        help="压缩质量参数，0..51；越高体积越小、画质越低，默认 26",
    )
    parser.add_argument("--gui", action="store_true", help="启动图形界面")
    parser.add_argument("--open", action="store_true", help="处理完成后打开输出目录")
    args = parser.parse_args()

    if args.gui or args.input_dir is None:
        return run_gui()

    out_root = process_folder(args.input_dir, CompressionSettings(target_size=args.size, crf=args.crf))
    if args.open:
        open_in_finder(out_root / "videos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
