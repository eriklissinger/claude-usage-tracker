import Foundation

public enum ModelFamily: String, Sendable {
    case fable
    case opus
    case sonnet
    case haiku
    case unknown

    public var weight: Double {
        switch self {
        // Fable 5 ($10/$50 per MTok) is priced at exactly 2× Opus 4.8
        // ($5/$25), so anchor it at 2× the opus weight until a calibration
        // pass against claude.ai's reported % says otherwise.
        case .fable:   return 10.0
        case .opus:    return 5.0
        case .sonnet:  return 1.0
        case .haiku:   return 0.25
        case .unknown: return 1.0
        }
    }

    public static func from(model: String) -> ModelFamily {
        let lower = model.lowercased()
        if lower.contains("fable")  { return .fable }
        if lower.contains("opus")   { return .opus }
        if lower.contains("sonnet") { return .sonnet }
        if lower.contains("haiku")  { return .haiku }
        return .unknown
    }
}

public enum NCUWeights {
    public static let inputWeight: Double = 1.00
    public static let cacheCreationWeight: Double = 1.25
    /// Cache reads don't count toward the API's published rate limits
    /// (per docs), and observed claude.ai "% used" is consistent with cache
    /// reads being free against the plan cap too. Dropped from 0.10 → 0.0
    /// after the 4/28 calibration showed our % was ~1.6× Anthropic's on a
    /// cache-read-heavy block.
    public static let cacheReadWeight: Double = 0.00
    public static let outputWeight: Double = 5.00

    public static func ncu(for entry: UsageEntry) -> Double {
        let modelWeight = ModelFamily.from(model: entry.model).weight
        let weightedTokens =
            inputWeight         * Double(entry.inputTokens)
          + cacheCreationWeight * Double(entry.cacheCreationTokens)
          + cacheReadWeight     * Double(entry.cacheReadTokens)
          + outputWeight        * Double(entry.outputTokens)
        return modelWeight * weightedTokens / 1_000_000.0
    }
}
