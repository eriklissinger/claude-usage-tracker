import AppKit
import ClaudeUsageTrackerCore

// Generates AppIcon.icns from MascotRenderer (healthy, 0% used) so the app
// icon is always the same creature as the menu bar mascot. Run by
// scripts/build-app.sh at bundle-assembly time:
//
//     cct-icon-gen /path/to/AppIcon.icns

let outPath = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : "AppIcon.icns"
let outURL = URL(fileURLWithPath: outPath)

let iconsetDir = FileManager.default.temporaryDirectory
    .appendingPathComponent("cct-icon-\(UUID().uuidString)", isDirectory: true)
    .appendingPathComponent("AppIcon.iconset", isDirectory: true)
try FileManager.default.createDirectory(at: iconsetDir, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: iconsetDir.deletingLastPathComponent()) }

func writePNG(pixels: Int, to url: URL) throws {
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixels,
        pixelsHigh: pixels,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        fatalError("could not create bitmap rep for \(pixels)px")
    }
    rep.size = NSSize(width: pixels, height: pixels)

    NSGraphicsContext.saveGraphicsState()
    defer { NSGraphicsContext.restoreGraphicsState() }
    guard let gctx = NSGraphicsContext(bitmapImageRep: rep) else {
        fatalError("could not create graphics context for \(pixels)px")
    }
    NSGraphicsContext.current = gctx
    let ctx = gctx.cgContext

    // Mascot fills ~86% of the canvas width, centered. Snap the cell size to
    // whole pixels at sizes where that's possible so the pixel art stays
    // crisp instead of landing on fractional boundaries.
    let (cols, rows) = MascotRenderer.gridSize
    var cell = CGFloat(pixels) * 0.86 / CGFloat(cols)
    if cell >= 2 { cell = cell.rounded(.down) }
    let w = cell * CGFloat(cols)
    let h = cell * CGFloat(rows)
    let rect = CGRect(
        x: ((CGFloat(pixels) - w) / 2).rounded(.down),
        y: ((CGFloat(pixels) - h) / 2).rounded(.down),
        width: w,
        height: h
    )
    MascotRenderer.draw(percentUsed: 0, in: ctx, rect: rect)
    gctx.flushGraphics()

    guard let png = rep.representation(using: .png, properties: [:]) else {
        fatalError("could not encode PNG for \(pixels)px")
    }
    try png.write(to: url)
}

let entries: [(name: String, pixels: Int)] = [
    ("icon_16x16.png", 16),     ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),     ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),  ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),  ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),  ("icon_512x512@2x.png", 1024),
]
for entry in entries {
    try writePNG(pixels: entry.pixels, to: iconsetDir.appendingPathComponent(entry.name))
}

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["-c", "icns", iconsetDir.path, "-o", outURL.path]
try iconutil.run()
iconutil.waitUntilExit()
guard iconutil.terminationStatus == 0 else {
    fatalError("iconutil exited \(iconutil.terminationStatus)")
}
print("wrote \(outURL.path)")
