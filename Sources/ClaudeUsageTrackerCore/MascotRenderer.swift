import AppKit

/// Claude mascot rendered as a draining "battery" — body fills with peach
/// when the budget is full, drains top→bottom as % used grows, and tints
/// toward red as it nears empty. Same metaphor as the macOS battery icon
/// (full → empty), just vertical and creature-shaped.
///
/// Lives in Core (despite being UI) so both the menu bar app and
/// `cct-icon-gen` render the same creature — the app icon is generated from
/// this code at build time and can't drift.
public enum MascotRenderer {
    private struct CacheKey: Hashable {
        let percent: Int
        let pixelHeight: Int
    }
    private static var cache: [CacheKey: NSImage] = [:]

    /// Grid dimensions (cols, rows) — for callers that need to compute an
    /// aspect-correct rect before calling `draw`.
    public static var gridSize: (cols: Int, rows: Int) {
        let cols = (grid.first ?? "").replacingOccurrences(of: " ", with: "").count
        return (cols, grid.count)
    }

    /// Render the mascot at `pointHeight` points tall. Width is derived from
    /// the grid's aspect ratio so cells stay square.
    public static func image(percentUsed: Int, pointHeight: CGFloat) -> NSImage {
        let percent = max(0, min(100, percentUsed))
        let scale = NSScreen.main?.backingScaleFactor ?? 2.0
        let pixelHeight = Int((pointHeight * scale).rounded())
        let key = CacheKey(percent: percent, pixelHeight: pixelHeight)
        if let cached = cache[key] { return cached }
        let image = render(percentUsed: percent, pointHeight: pointHeight)
        cache[key] = image
        return image
    }

    /// 18-wide × 11-tall mascot, sampled directly from the reference image.
    /// Body is 14 wide (cols 2-15); rows 5-6 extend the full 18 width to
    /// produce the natural side-nub shoulders. Eyes are 1-wide × 3-tall
    /// vertical bars at cols 4 and 13 (symmetric around the body's centerline
    /// at col 8.5). Four legs in 1-2-1 grouping at cols 3, 5, 12, 14.
    /// `X` = body (drains), `K` = eye (always black), `.` = transparent.
    private static let grid: [String] = [
        ". . X X X X X X X X X X X X X X . .",
        ". . X X X X X X X X X X X X X X . .",
        ". . X X K X X X X X X X X K X X . .",
        ". . X X K X X X X X X X X K X X . .",
        ". . X X K X X X X X X X X K X X . .",
        "X X X X X X X X X X X X X X X X X X",
        "X X X X X X X X X X X X X X X X X X",
        ". . X X X X X X X X X X X X X X . .",
        ". . X X X X X X X X X X X X X X . .",
        ". . . X . X . . . . . . X . X . . .",
        ". . . X . X . . . . . . X . X . . .",
    ]

    /// Draw the mascot into `rect` of `ctx` (bottom-left origin, AppKit
    /// convention). `rect` should match the grid's aspect ratio — use
    /// `gridSize` to compute it; cells are sized independently per axis so a
    /// mismatched rect stretches rather than clips.
    public static func draw(percentUsed: Int, in ctx: CGContext, rect: CGRect) {
        let percent = max(0, min(100, percentUsed))
        let rows = grid.count
        let cols = gridSize.cols
        let cellW = rect.width / CGFloat(cols)
        let cellH = rect.height / CGFloat(rows)

        let percentRemaining = 100 - percent
        // Number of body rows still "filled," counted from the bottom. The
        // legs (last two rows) drain last, which feels right — the creature
        // shrinks down to its feet before disappearing.
        let filledRows = max(0, min(rows, (rows * percentRemaining + 50) / 100))
        let drainedRows = rows - filledRows

        let filledColor = filledFillColor(percentUsed: percent)
        let drainedColor = NSColor(white: 0.55, alpha: 0.45)
        let eyeColor = NSColor.black

        ctx.interpolationQuality = .none
        for (rowIdx, row) in grid.enumerated() {
            let chars = Array(row.replacingOccurrences(of: " ", with: ""))
            for (colIdx, ch) in chars.enumerated() {
                let color: NSColor?
                switch ch {
                case "X": color = (rowIdx < drainedRows) ? drainedColor : filledColor
                case "K": color = eyeColor
                default:  color = nil
                }
                guard let c = color else { continue }
                let x = rect.minX + CGFloat(colIdx) * cellW
                let y = rect.minY + rect.height - CGFloat(rowIdx + 1) * cellH
                ctx.setFillColor(c.cgColor)
                ctx.fill(CGRect(x: x, y: y, width: cellW, height: cellH))
            }
        }
    }

    private static func render(percentUsed: Int, pointHeight: CGFloat) -> NSImage {
        let (cols, rows) = gridSize
        let cellSize = pointHeight / CGFloat(rows)
        let pointWidth = cellSize * CGFloat(cols)

        let image = NSImage(size: NSSize(width: pointWidth, height: pointHeight))
        image.lockFocus()
        defer { image.unlockFocus() }

        guard let ctx = NSGraphicsContext.current?.cgContext else { return image }
        draw(
            percentUsed: percentUsed,
            in: ctx,
            rect: CGRect(x: 0, y: 0, width: pointWidth, height: pointHeight)
        )
        return image
    }

    /// Filled portion tint shifts from peach (healthy) → burnt orange → red as
    /// the budget nears empty. Drained portion stays neutral grey regardless.
    private static func filledFillColor(percentUsed: Int) -> NSColor {
        switch percentUsed {
        case ..<50:  return NSColor(red: 0.89, green: 0.48, blue: 0.37, alpha: 1) // peach
        case ..<75:  return NSColor(red: 0.89, green: 0.55, blue: 0.30, alpha: 1) // warm
        case ..<95:  return NSColor(red: 0.85, green: 0.40, blue: 0.20, alpha: 1) // burnt
        default:     return NSColor(red: 0.78, green: 0.18, blue: 0.18, alpha: 1) // danger
        }
    }
}
