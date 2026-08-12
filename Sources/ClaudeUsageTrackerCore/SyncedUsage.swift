import Foundation

/// Snapshot of usage as reported by claude.ai's own
/// `/api/organizations/{org}/usage` endpoint, fetched in the background via
/// `ClaudeUsageSync`. When fresh, it overrides our calculated approximations.
public struct SyncedUsage: Sendable {
    public let percent5h: Int
    public let percent7d: Int
    public let reset5hAt: Date?
    public let reset7dAt: Date?
    public let syncedAt: Date

    public init(
        percent5h: Int,
        percent7d: Int,
        reset5hAt: Date?,
        reset7dAt: Date?,
        syncedAt: Date
    ) {
        self.percent5h = percent5h
        self.percent7d = percent7d
        self.reset5hAt = reset5hAt
        self.reset7dAt = reset7dAt
        self.syncedAt = syncedAt
    }

    public var ageSeconds: TimeInterval {
        Date().timeIntervalSince(syncedAt)
    }

    /// Considered fresh enough to display as the source of truth.
    public var isFresh: Bool {
        ageSeconds < 15 * 60  // 15 minutes
    }
}
