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
TARGET_W = 480
TARGET_H = 640
CRF = 26
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


def human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    kb = n / 1024.0
    if kb < 1024:
        return f"{kb:.1f} KB"
    return f"{kb / 1024.0:.2f} MB"


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


def encode_video(ffmpeg: str, src: Path, dst: Path) -> None:
    cp = run([
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(src),
        "-map", "0:v:0",
        "-vf", f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,crop={TARGET_W}:{TARGET_H}",
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", str(CRF),
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


def write_summary_md(summary_path: Path, input_dir: Path, out_root: Path, results: list[ProcessResult]) -> None:
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
        f"- 输出尺寸：`{TARGET_W}x{TARGET_H}`",
        "- 音轨：移除",
        f"- 视频编码：`libx264 / CRF {CRF} / preset {PRESET}`",
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


def write_process_doc(doc_path: Path, input_dir: Path, out_root: Path) -> None:
    doc_path.write_text(f"""# 480x640 无音轨视频压缩处理说明

输入目录：`{input_dir}`
输出目录：`{out_root / "videos"}`

## 参数

```bash
ffmpeg \\
  -nostdin \\
  -hide_banner \\
  -loglevel error \\
  -y \\
  -i "input.mp4" \\
  -map 0:v:0 \\
  -vf "scale=480:640:force_original_aspect_ratio=increase,crop=480:640" \\
  -c:v libx264 \\
  -preset slow \\
  -crf 26 \\
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
  B --> C["逐个处理"]
  C --> D["缩放并裁剪为 480x640"]
  D --> E["libx264 / CRF 26 / preset slow 编码"]
  E --> F["移除音轨"]
  F --> G["解码校验"]
  G --> H["生成首帧海报"]
  H --> I["写入报告"]
  I --> J["打开输出目录"]
```
""", encoding="utf-8")


def process_folder(input_dir: Path, log: Callable[[str], None] = print) -> Path:
    input_dir = input_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise RuntimeError(f"输入目录不存在：{input_dir}")

    ffmpeg, ffprobe = require_tools()
    videos = iter_videos(input_dir)
    if not videos:
        raise RuntimeError(f"没有找到视频文件：{input_dir}")

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = input_dir / "output" / f"video_compressed_480x640_no_audio_{run_id}"
    videos_dir = out_root / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    log(f"输入目录：{input_dir}")
    log(f"输出目录：{videos_dir}")
    log(f"共找到 {len(videos)} 个视频")

    results: list[ProcessResult] = []
    for idx, src in enumerate(videos, start=1):
        log(f"[{idx}/{len(videos)}] 处理：{src.name}")
        out = videos_dir / f"{src.stem}.mp4"
        poster = videos_dir / f"{src.stem}_poster.jpg"
        source_bytes = src.stat().st_size
        try:
            encode_video(ffmpeg, src, out)
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
    write_summary_md(out_root / "summary.md", input_dir, out_root, results)
    write_process_doc(out_root / "FFMPEG_PROCESS.md", input_dir, out_root)

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
    try:
        out_root = process_folder(folder)
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
    status_text = tk.StringVar(value="请选择包含视频的文件夹。")
    output_root: dict[str, Path] = {}
    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    title = ttk.Label(frame, text="引导页视频压缩工具", font=("TkDefaultFont", 18, "bold"))
    title.pack(anchor="w")

    rule = ttk.Label(
        frame,
        text="规则：480x640 / 无音轨 / 自动生成海报 / 自动生成报告 / 不修改源文件",
    )
    rule.pack(anchor="w", pady=(6, 14))

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

    def worker(folder: Path) -> None:
        try:
            out_root = process_folder(folder, log=lambda msg: event_queue.put(("log", msg)))
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
        threading.Thread(target=worker, args=(folder,), daemon=True).start()

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
    parser = argparse.ArgumentParser(description="Compress onboarding videos to 480x640 no-audio MP4.")
    parser.add_argument("input_dir", nargs="?", type=Path, help="包含视频文件的输入目录")
    parser.add_argument("--gui", action="store_true", help="启动图形界面")
    parser.add_argument("--open", action="store_true", help="处理完成后打开输出目录")
    args = parser.parse_args()

    if args.gui or args.input_dir is None:
        return run_gui()

    out_root = process_folder(args.input_dir)
    if args.open:
        open_in_finder(out_root / "videos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
