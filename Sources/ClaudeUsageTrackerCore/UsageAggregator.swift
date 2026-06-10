import Foundation

public struct UsageTotals: Sendable {
    public let entryCount: Int
    public let inputTokens: Int
    public let cacheCreationTokens: Int
    public let cacheReadTokens: Int
    public let outputTokens: Int
    public let ncu: Double

    public var totalRawTokens: Int {
        inputTokens + cacheCreationTokens + cacheReadTokens + outputTokens
    }

    public static let zero = UsageTotals(
        entryCount: 0,
        inputTokens: 0,
        cacheCreationTokens: 0,
        cacheReadTokens: 0,
        outputTokens: 0,
        ncu: 0
    )

    public init(
        entryCount: Int,
        inputTokens: Int,
        cacheCreationTokens: Int,
        cacheReadTokens: Int,
        outputTokens: Int,
        ncu: Double
    ) {
        self.entryCount = entryCount
        self.inputTokens = inputTokens
        self.cacheCreationTokens = cacheCreationTokens
        self.cacheReadTokens = cacheReadTokens
        self.outputTokens = outputTokens
        self.ncu = ncu
    }
}

public enum UsageAggregator {
    public static func totals(for entries: [UsageEntry]) -> UsageTotals {
        var input = 0, cacheCreate = 0, cacheRead = 0, output = 0
        var ncu = 0.0
        for e in entries {
            input += e.inputTokens
            cacheCreate += e.cacheCreationTokens
            cacheRead += e.cacheReadTokens
            output += e.outputTokens
            ncu += e.ncu
        }
        return UsageTotals(
            entryCount: entries.count,
            inputTokens: input,
            cacheCreationTokens: cacheCreate,
            cacheReadTokens: cacheRead,
            outputTokens: output,
            ncu: ncu
        )
    }

    public static func totals(
        for entries: [UsageEntry],
        in window: TimeInterval,
        now: Date = Date()
    ) -> UsageTotals {
        let cutoff = now.addingTimeInterval(-window)
        let filtered = entries.filter { $0.timestamp >= cutoff && $0.timestamp <= now }
        return totals(for: filtered)
    }

    /// Group entries by model family (fable / opus / sonnet / haiku / unknown).
    public static func totalsByFamily(
        for entries: [UsageEntry],
        in window: TimeInterval,
        now: Date = Date()
    ) -> [(ModelFamily, UsageTotals)] {
        let cutoff = now.addingTimeInterval(-window)
        let filtered = entries.filter { $0.timestamp >= cutoff && $0.timestamp <= now }
        var buckets: [ModelFamily: [UsageEntry]] = [:]
        for e in filtered {
            buckets[ModelFamily.from(model: e.model), default: []].append(e)
        }
        let order: [ModelFamily] = [.fable, .opus, .sonnet, .haiku, .unknown]
        return order.compactMap { family in
            guard let bucket = buckets[family], !bucket.isEmpty else { return nil }
            return (family, totals(for: bucket))
        }
    }
}
