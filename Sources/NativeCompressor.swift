import AppKit
import Foundation

struct TargetSize {
    let width: Int
    let height: Int
    var label: String { "\(width)x\(height)" }
}

struct QualityPreset {
    let crf: Int
    let label: String
}

struct ResultRow {
    let status: String
    let fileName: String
    let sourceBytes: Int64
    let outputBytes: Int64
    let savedPercent: Double
    let dimension: String
    let audioStreams: Int
    let posterPath: String
    let posterBytes: Int64
    let sourcePath: String
    let outputPath: String
    let error: String
}

let presetSizes: [(TargetSize, String)] = [
    (TargetSize(width: 480, height: 640), "480x640 - 推荐，引导页轻量版"),
    (TargetSize(width: 720, height: 960), "720x960 - 更清晰，体积更大"),
    (TargetSize(width: 1080, height: 1440), "1080x1440 - 接近原始尺寸"),
    (TargetSize(width: 360, height: 480), "360x480 - 更小体积")
]

let qualityPresets: [QualityPreset] = [
    QualityPreset(crf: 23, label: "高清 - CRF 23，体积较大"),
    QualityPreset(crf: 26, label: "标准 - CRF 26，推荐"),
    QualityPreset(crf: 30, label: "更小 - CRF 30，画质略降"),
    QualityPreset(crf: 34, label: "极小 - CRF 34，画质下降明显")
]

func showAlert(title: String, message: String) {
    let alert = NSAlert()
    alert.messageText = title
    alert.informativeText = message
    alert.addButton(withTitle: "好")
    alert.runModal()
}

func humanBytes(_ value: Int64) -> String {
    if value < 1024 { return "\(value) B" }
    let kb = Double(value) / 1024.0
    if kb < 1024 { return String(format: "%.1f KB", kb) }
    return String(format: "%.2f MB", kb / 1024.0)
}

func runProcess(_ executable: String, _ args: [String]) throws -> String {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = args
    let stdout = Pipe()
    let stderr = Pipe()
    process.standardOutput = stdout
    process.standardError = stderr
    try process.run()
    process.waitUntilExit()
    let out = String(data: stdout.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    let err = String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    if process.terminationStatus != 0 {
        throw NSError(domain: "VideoCompressor", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: err.isEmpty ? "命令执行失败" : err])
    }
    return out
}

func bundledTool(_ name: String) -> String? {
    if let resource = Bundle.main.resourceURL {
        let bundled = resource.appendingPathComponent("bin").appendingPathComponent(name).path
        if FileManager.default.isExecutableFile(atPath: bundled) { return bundled }
    }
    for candidate in ["/opt/homebrew/bin/\(name)", "/usr/local/bin/\(name)", "/usr/bin/\(name)"] {
        if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
    }
    return nil
}

func chooseFolder() -> URL? {
    let panel = NSOpenPanel()
    panel.title = "选择包含视频的文件夹"
    panel.canChooseFiles = false
    panel.canChooseDirectories = true
    panel.allowsMultipleSelection = false
    return panel.runModal() == .OK ? panel.url : nil
}

func chooseSettings() -> (TargetSize, Int)? {
    let alert = NSAlert()
    alert.messageText = "选择压缩参数"
    alert.informativeText = "目标尺寸影响最大；同一尺寸下，CRF 越高体积越小、画质越低。"
    alert.addButton(withTitle: "开始")
    alert.addButton(withTitle: "取消")

    let stack = NSStackView()
    stack.orientation = .vertical
    stack.spacing = 12
    stack.translatesAutoresizingMaskIntoConstraints = false

    let sizeLabel = NSTextField(labelWithString: "目标尺寸")
    let sizePopup = NSPopUpButton(frame: .zero, pullsDown: false)
    presetSizes.forEach { sizePopup.addItem(withTitle: $0.1) }
    sizePopup.selectItem(at: 0)

    let qualityLabel = NSTextField(labelWithString: "压缩强度")
    let qualityPopup = NSPopUpButton(frame: .zero, pullsDown: false)
    qualityPresets.forEach { qualityPopup.addItem(withTitle: $0.label) }
    qualityPopup.selectItem(at: 1)

    let customLabel = NSTextField(labelWithString: "自定义尺寸或 CRF 可在命令行工具中使用；普通用户建议使用预设。")
    customLabel.lineBreakMode = .byWordWrapping
    customLabel.maximumNumberOfLines = 2

    stack.addArrangedSubview(sizeLabel)
    stack.addArrangedSubview(sizePopup)
    stack.addArrangedSubview(qualityLabel)
    stack.addArrangedSubview(qualityPopup)
    stack.addArrangedSubview(customLabel)
    stack.widthAnchor.constraint(equalToConstant: 420).isActive = true
    alert.accessoryView = stack

    if alert.runModal() != .alertFirstButtonReturn { return nil }
    return (presetSizes[sizePopup.indexOfSelectedItem].0, qualityPresets[qualityPopup.indexOfSelectedItem].crf)
}

func fileSize(_ url: URL) -> Int64 {
    let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
    return attrs?[.size] as? Int64 ?? 0
}

func videoFiles(in folder: URL) -> [URL] {
    let exts = Set(["mp4", "mov", "m4v", "webm"])
    let urls = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
    return urls.filter { exts.contains($0.pathExtension.lowercased()) }.sorted { $0.lastPathComponent < $1.lastPathComponent }
}

func ffprobeDimension(ffprobe: String, video: URL) throws -> String {
    try runProcess(ffprobe, ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", video.path]).trimmingCharacters(in: .whitespacesAndNewlines)
}

func ffprobeAudioCount(ffprobe: String, video: URL) throws -> Int {
    let out = try runProcess(ffprobe, ["-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", video.path])
    return out.split(separator: "\n").filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.count
}

func writeReports(outRoot: URL, inputFolder: URL, settings: (TargetSize, Int), rows: [ResultRow]) throws {
    let report = outRoot.appendingPathComponent("final_report.tsv")
    var reportText = "status\tfile\tsource_bytes\tsource_human\toutput_bytes\toutput_human\tsaved_percent\tdimension\taudio_streams\tposter_path\tposter_bytes\tposter_human\tsource_path\toutput_path\terror\n"
    for row in rows {
        reportText += "\(row.status)\t\(row.fileName)\t\(row.sourceBytes)\t\(humanBytes(row.sourceBytes))\t\(row.outputBytes)\t\(humanBytes(row.outputBytes))\t\(String(format: "%.2f%%", row.savedPercent))\t\(row.dimension)\t\(row.audioStreams)\t\(row.posterPath)\t\(row.posterBytes)\t\(humanBytes(row.posterBytes))\t\(row.sourcePath)\t\(row.outputPath)\t\(row.error.replacingOccurrences(of: "\n", with: " "))\n"
    }
    try reportText.write(to: report, atomically: true, encoding: .utf8)

    let successes = rows.filter { $0.status == "success" }
    let totalSrc = successes.reduce(Int64(0)) { $0 + $1.sourceBytes }
    let totalOut = successes.reduce(Int64(0)) { $0 + $1.outputBytes }
    let saved = totalSrc > 0 ? Double(totalSrc - totalOut) * 100.0 / Double(totalSrc) : 0
    var summary = "# 视频压缩结果\n\n"
    summary += "输入目录：`\(inputFolder.path)`\n"
    summary += "输出目录：`\(outRoot.appendingPathComponent("videos").path)`\n\n"
    summary += "## 规则\n\n"
    summary += "- 输出尺寸：`\(settings.0.label)`\n"
    summary += "- CRF：`\(settings.1)`\n"
    summary += "- 音轨：移除\n"
    summary += "- 视频编码：`libx264 / preset slow`\n\n"
    summary += "## 汇总\n\n"
    summary += "- 成功：\(successes.count)\n"
    summary += "- 失败：\(rows.count - successes.count)\n"
    summary += "- 视频总大小：`\(humanBytes(totalSrc)) -> \(humanBytes(totalOut))`\n"
    summary += "- 节省：`\(String(format: "%.2f%%", saved))`\n\n"
    summary += "## 明细\n\n| 文件 | 原始大小 | 输出大小 | 节省 | 尺寸 | 音轨 | 海报 | 状态 |\n|---|---:|---:|---:|---:|---:|---:|---|\n"
    for row in rows {
        summary += "| \(row.fileName) | \(humanBytes(row.sourceBytes)) | \(humanBytes(row.outputBytes)) | \(String(format: "%.2f%%", row.savedPercent)) | \(row.dimension.isEmpty ? "-" : row.dimension) | \(row.audioStreams) | \(row.posterBytes > 0 ? humanBytes(row.posterBytes) : "-") | \(row.status) |\n"
    }
    try summary.write(to: outRoot.appendingPathComponent("summary.md"), atomically: true, encoding: .utf8)
}

func process(folder: URL, target: TargetSize, crf: Int, ffmpeg: String, ffprobe: String) throws -> URL {
    let videos = videoFiles(in: folder)
    if videos.isEmpty { throw NSError(domain: "VideoCompressor", code: 2, userInfo: [NSLocalizedDescriptionKey: "没有找到视频文件。支持 mp4/mov/m4v/webm。"]) }
    let formatter = DateFormatter()
    formatter.dateFormat = "yyyyMMdd_HHmmss"
    let runId = formatter.string(from: Date())
    let outRoot = folder.appendingPathComponent("output/video_compressed_\(target.label)_crf\(crf)_no_audio_\(runId)", isDirectory: true)
    let videosDir = outRoot.appendingPathComponent("videos", isDirectory: true)
    try FileManager.default.createDirectory(at: videosDir, withIntermediateDirectories: true)

    var rows: [ResultRow] = []
    for src in videos {
        let sourceBytes = fileSize(src)
        let out = videosDir.appendingPathComponent(src.deletingPathExtension().lastPathComponent).appendingPathExtension("mp4")
        let poster = videosDir.appendingPathComponent(src.deletingPathExtension().lastPathComponent + "_poster.jpg")
        do {
            try runProcess(ffmpeg, ["-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", src.path, "-map", "0:v:0", "-vf", "scale=\(target.width):\(target.height):force_original_aspect_ratio=increase,crop=\(target.width):\(target.height)", "-c:v", "libx264", "-preset", "slow", "-crf", "\(crf)", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", "-map_metadata", "-1", "-map_chapters", "-1", out.path])
            try runProcess(ffmpeg, ["-nostdin", "-v", "error", "-i", out.path, "-f", "null", "-"])
            try runProcess(ffmpeg, ["-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", out.path, "-frames:v", "1", "-q:v", "6", poster.path])
            let outputBytes = fileSize(out)
            let saved = sourceBytes > 0 ? Double(sourceBytes - outputBytes) * 100.0 / Double(sourceBytes) : 0
            rows.append(ResultRow(status: "success", fileName: src.lastPathComponent, sourceBytes: sourceBytes, outputBytes: outputBytes, savedPercent: saved, dimension: try ffprobeDimension(ffprobe: ffprobe, video: out), audioStreams: try ffprobeAudioCount(ffprobe: ffprobe, video: out), posterPath: poster.path, posterBytes: fileSize(poster), sourcePath: src.path, outputPath: out.path, error: ""))
        } catch {
            rows.append(ResultRow(status: "failed", fileName: src.lastPathComponent, sourceBytes: sourceBytes, outputBytes: fileSize(out), savedPercent: 0, dimension: "", audioStreams: -1, posterPath: poster.path, posterBytes: fileSize(poster), sourcePath: src.path, outputPath: out.path, error: error.localizedDescription))
        }
        try writeReports(outRoot: outRoot, inputFolder: folder, settings: (target, crf), rows: rows)
    }
    try writeReports(outRoot: outRoot, inputFolder: folder, settings: (target, crf), rows: rows)
    return outRoot
}

@main
struct AppMain {
    static func main() {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)

        guard let ffmpeg = bundledTool("ffmpeg"), let ffprobe = bundledTool("ffprobe") else {
            showAlert(title: "缺少内置依赖", message: "未找到 ffmpeg/ffprobe。请使用完整分发版，或把 ffmpeg 和 ffprobe 放入 App 的 Contents/Resources/bin/。")
            return
        }
        guard let folder = chooseFolder() else { return }
        guard let settings = chooseSettings() else { return }

        showAlert(title: "开始处理", message: "点击“好”后开始压缩。处理过程中窗口可能暂时无响应，请等待完成。")
        do {
            let outRoot = try process(folder: folder, target: settings.0, crf: settings.1, ffmpeg: ffmpeg, ffprobe: ffprobe)
            NSWorkspace.shared.open(outRoot.appendingPathComponent("videos"))
            showAlert(title: "处理完成", message: "输出目录：\n\(outRoot.appendingPathComponent("videos").path)")
        } catch {
            showAlert(title: "处理失败", message: error.localizedDescription)
        }
    }
}
