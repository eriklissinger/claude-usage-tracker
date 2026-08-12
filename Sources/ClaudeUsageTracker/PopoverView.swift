import SwiftUI
import ClaudeUsageTrackerCore

struct PopoverView: View {
    let snapshot: UsageSnapshot
    let syncError: String?
    let needsLogin: Bool
    let onLogin: () -> Void
    let onRefresh: () -> Void
    let onQuit: () -> Void

    /// Drives live countdown updates while the popover is open.
    @State private var tickNow: Date = Date()
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            if needsLogin {
                loginBanner
            }
            Divider()
            accountSection
            if let err = syncError, snapshot.synced == nil, !needsLogin {
                Text(err)
                    .font(.system(size: 10))
                    .foregroundStyle(.orange)
            }
            if !modelBreakdown.isEmpty || !projectBreakdown.isEmpty {
                Divider()
                claudeCodeSection
            }
            Divider()
            footer
        }
        .padding(16)
        .frame(width: 320)
        .onReceive(ticker) { now in tickNow = now }
    }

    // MARK: - Sections

    /// Shown when sync fails because the claude.ai session expired (the
    /// sessionKey cookie lives ~28 days). Usage data is unavailable until the
    /// user logs back in via Chrome — no fallback is displayed by design.
    private var loginBanner: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                Text("claude.ai session expired")
                    .font(.system(size: 12, weight: .semibold))
            }
            Text("Usage data is paused until you log in again. Sync resumes automatically within a minute of logging in.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Open claude.ai in Chrome") { onLogin() }
                .controlSize(.small)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(Color.orange.opacity(0.12))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .strokeBorder(Color.orange.opacity(0.4), lineWidth: 1)
        )
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(nsImage: MascotRenderer.image(percentUsed: snapshot.displayDrivingPercent, pointHeight: 40))
                .interpolation(.none)
            VStack(alignment: .leading, spacing: 2) {
                Text("Claude Usage")
                    .font(.system(size: 14, weight: .semibold))
                HStack(spacing: 6) {
                    if let s = snapshot.synced, s.isFresh {
                        let age = Int(s.ageSeconds)
                        let ageStr = age < 60 ? "\(age)s" : "\(age / 60)m"
                        Text("· live (\(ageStr) ago)")
                            .font(.system(size: 10))
                            .foregroundStyle(Color.green)
                    }
                }
            }
            Spacer()
        }
    }

    /// The limit meters. These come from claude.ai's own usage endpoint, which
    /// is account-wide — the caption says so, because the only labelled
    /// sections used to say "Claude Code" and made the whole popover read as
    /// Claude Code usage.
    private var accountSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionLabel("ALL CLAUDE USAGE")
            caption("Desktop, web, mobile and Claude Code · share of your limit")
            meter(title: "5-hour block", percent: snapshot.displayPercent5h, reset: blockResetText)
            meter(title: "Weekly window", percent: snapshot.displayPercent7d, reset: weeklyResetText)
        }
    }

    /// Breakdowns parsed from local `~/.claude/projects` transcripts, so they
    /// see Claude Code only. Their percentages are shares of that activity, not
    /// shares of the limit — sitting under the meters above, they'd otherwise
    /// read as the same unit.
    private var claudeCodeSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionLabel("CLAUDE CODE ONLY")
            caption("Share of this block's Claude Code activity, not of your limit")
            if !modelBreakdown.isEmpty {
                subsectionLabel("By model")
                ForEach(modelBreakdown, id: \.0) { (label, _, share) in
                    BreakdownRow(label: label, value: formatShare(share), share: share)
                }
            }
            if !projectBreakdown.isEmpty {
                subsectionLabel("Top projects")
                ForEach(projectBreakdown, id: \.0) { (label, _, share) in
                    BreakdownRow(label: label, value: formatShare(share), share: share)
                }
            }
        }
    }

    private func meter(title: String, percent: Int, reset: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 11, weight: .medium))
            ProgressBar(percent: percent)
            HStack(spacing: 8) {
                Spacer()
                Text(reset)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var footer: some View {
        HStack {
            Button("Refresh") { onRefresh() }
                .buttonStyle(.plain)
                .keyboardShortcut("r", modifiers: [.command])
            Spacer()
            Text("Updated \(formatTimeAgo(snapshot.asOf, now: tickNow))")
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
            Spacer()
            Button("Quit") { onQuit() }
                .buttonStyle(.plain)
                .keyboardShortcut("q", modifiers: [.command])
        }
        .font(.system(size: 11))
    }

    // MARK: - Derived

    private var blockResetText: String {
        guard let resetAt = snapshot.displayBlockResetAt else { return "no active block" }
        let remaining = max(0, resetAt.timeIntervalSince(tickNow))
        return "resets in \(formatRemaining(remaining)) · \(formatAbsoluteReset(resetAt, now: tickNow))"
    }

    private var weeklyResetText: String {
        guard let resetAt = snapshot.displayWeekResetAt else { return "no active week" }
        let remaining = max(0, resetAt.timeIntervalSince(tickNow))
        return "resets in \(formatRemaining(remaining)) · \(formatAbsoluteReset(resetAt, now: tickNow))"
    }

    private var modelBreakdown: [(String, Double, Double)] {
        guard let block = snapshot.activeBlock else { return [] }
        var byFamily: [ModelFamily: Double] = [:]
        for entry in block.entries {
            byFamily[ModelFamily.from(model: entry.model), default: 0] += entry.ncu
        }
        let total = byFamily.values.reduce(0, +)
        guard total > 0 else { return [] }
        let order: [ModelFamily] = [.fable, .opus, .sonnet, .haiku, .unknown]
        return order.compactMap { family in
            guard let ncu = byFamily[family], ncu > 0 else { return nil }
            return (family.rawValue.capitalized, ncu, ncu / total)
        }
    }

    private var projectBreakdown: [(String, Double, Double)] {
        guard let block = snapshot.activeBlock else { return [] }
        var byCwd: [String: Double] = [:]
        for entry in block.entries {
            let key = projectName(from: entry.cwd) ?? "unknown"
            byCwd[key, default: 0] += entry.ncu
        }
        let total = byCwd.values.reduce(0, +)
        guard total > 0 else { return [] }
        return byCwd
            .sorted { $0.value > $1.value }
            .prefix(3)
            .map { ($0.key, $0.value, $0.value / total) }
    }

    // MARK: - Helpers

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(.secondary)
            .tracking(0.6)
    }

    private func subsectionLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(.secondary)
    }

    /// Scope note under a section label: what the numbers below actually cover.
    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10))
            .foregroundStyle(.tertiary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - Subcomponents

private struct ProgressBar: View {
    let percent: Int

    private static let cellCount = 20

    var body: some View {
        let filled = max(0, min(Self.cellCount, Int((Double(percent) / 100.0) * Double(Self.cellCount).rounded())))
        HStack(spacing: 2) {
            ForEach(0..<Self.cellCount, id: \.self) { i in
                RoundedRectangle(cornerRadius: 2)
                    .fill(i < filled ? barColor : Color.secondary.opacity(0.18))
                    .frame(height: 10)
            }
            Text("\(percent)%")
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .frame(width: 40, alignment: .trailing)
        }
    }

    private var barColor: Color {
        switch percent {
        case ..<50: return .green
        case ..<75: return .yellow
        case ..<95: return .orange
        default:    return .red
        }
    }
}

private struct BreakdownRow: View {
    let label: String
    let value: String
    let share: Double

    var body: some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.system(size: 11))
                .frame(width: 90, alignment: .leading)
                .lineLimit(1)
                .truncationMode(.middle)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.secondary.opacity(0.15))
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.accentColor.opacity(0.7))
                        .frame(width: max(2, geo.size.width * share))
                }
            }
            .frame(height: 6)
            Text(value)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 80, alignment: .trailing)
        }
    }
}

// MARK: - Formatters

private func formatNCU(_ ncu: Double) -> String {
    String(format: "%.1f", ncu)
}

private func formatShare(_ share: Double) -> String {
    "\(Int((share * 100).rounded()))%"
}

private let timeOnlyFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "h:mm a"
    return f
}()

private let dayTimeFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "EEE h:mm a"
    return f
}()

/// Absolute reset time: time-only when reset is today, day+time otherwise.
private func formatAbsoluteReset(_ date: Date, now: Date) -> String {
    let cal = Calendar.current
    if cal.isDate(date, inSameDayAs: now) {
        return timeOnlyFormatter.string(from: date)
    }
    return dayTimeFormatter.string(from: date)
}

private func formatRemaining(_ secs: TimeInterval) -> String {
    let s = max(0, Int(secs))
    let d = s / 86400
    let h = (s % 86400) / 3600
    let m = (s % 3600) / 60
    let sec = s % 60
    if d > 0 { return "\(d)d \(h)h" }
    if h > 0 { return "\(h)h \(m)m" }
    if m > 0 { return "\(m)m \(sec)s" }
    return "\(sec)s"
}

private func formatTimeAgo(_ date: Date, now: Date) -> String {
    let secs = Int(now.timeIntervalSince(date))
    if secs < 60   { return "\(secs)s ago" }
    if secs < 3600 { return "\(secs / 60)m ago" }
    return "\(secs / 3600)h ago"
}

private func projectName(from cwd: String?) -> String? {
    guard let cwd, !cwd.isEmpty else { return nil }
    return (cwd as NSString).lastPathComponent
}
