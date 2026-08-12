import Foundation

/// Pulls live usage from claude.ai's `/api/organizations/{org}/usage` endpoint
/// using cookies extracted from the user's local Chrome profile. Polls on a
/// timer, exposes the latest result via `latest`, and notifies a callback on
/// each successful sync.
public final class ClaudeUsageSync {
    public typealias Callback = (Result<SyncedUsage, Error>) -> Void

    public enum SyncError: Error, CustomStringConvertible {
        case missingSessionKey
        case missingOrgID
        case sessionExpired
        case httpStatus(Int, String?)
        case malformedResponse(String)

        public var description: String {
            switch self {
            case .missingSessionKey:    return "Chrome has no claude.ai sessionKey (logged out?)"
            case .missingOrgID:         return "Chrome has no lastActiveOrg cookie"
            case .sessionExpired:       return "Visit claude.ai in Chrome to refresh your session"
            case .httpStatus(let c, let body):
                return "claude.ai returned \(c)\(body.map { ": \($0)" } ?? "")"
            case .malformedResponse(let r): return "Bad JSON: \(r)"
            }
        }

        /// True when the fix is the user re-authenticating at claude.ai in
        /// Chrome — the sessionKey cookie expired and was purged (it lives
        /// ~28 days), or the server rejected it. Drives the "log in" call to
        /// action in the UI.
        public var needsLogin: Bool {
            switch self {
            case .missingSessionKey, .sessionExpired: return true
            default: return false
            }
        }
    }

    private let pollInterval: TimeInterval
    private let queue = DispatchQueue(label: "cct.claude-sync", qos: .utility)
    private var timer: DispatchSourceTimer?
    private let onSync: Callback

    /// How long a resolved org is trusted before we re-probe. Keeps the normal
    /// poll to a single request while still noticing an org switch.
    private let orgResolveInterval: TimeInterval = 600

    /// The org we report usage for, plus when we picked it. Accessed only from
    /// `queue`, which is serial.
    private var resolvedOrgID: String?
    private var orgResolvedAt: Date?
    private var knownOrgCount = 0

    /// Latest successful sync. Nil until the first one lands.
    public private(set) var latest: SyncedUsage?

    public init(pollInterval: TimeInterval = 60, onSync: @escaping Callback) {
        self.pollInterval = pollInterval
        self.onSync = onSync
    }

    public func start() {
        syncOnce()
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + pollInterval, repeating: pollInterval)
        t.setEventHandler { [weak self] in self?.syncOnce() }
        t.resume()
        timer = t
    }

    public func stop() {
        timer?.cancel()
        timer = nil
    }

    public func refreshNow() {
        queue.async { [weak self] in self?.syncOnce() }
    }

    private func syncOnce() {
        do {
            let synced = try fetch()
            latest = synced
            DispatchQueue.main.async { [onSync] in onSync(.success(synced)) }
        } catch {
            DispatchQueue.main.async { [onSync] in onSync(.failure(error)) }
        }
    }

    private func fetch() throws -> SyncedUsage {
        let cookies = try ChromeCookieReader.readAllCookies(forDomain: "claude.ai")
        guard let sessionKey = cookies["sessionKey"], !sessionKey.isEmpty else {
            throw SyncError.missingSessionKey
        }

        let orgID = try resolveOrgID(cookies: cookies)
        let usage = try parse(get("organizations/\(orgID)/usage", cookies: cookies))

        // An org reading all-zero is the symptom of tracking the wrong one, so
        // drop the cache and re-probe next poll. Single-org accounts can't be
        // wrong, and re-probing an idle account every minute is just noise.
        if knownOrgCount > 1, usage.percent5h == 0, usage.percent7d == 0 {
            resolvedOrgID = nil
        }
        return usage
    }

    /// Which org's usage to report.
    ///
    /// `lastActiveOrg` alone is wrong on multi-org accounts: it tracks the org
    /// switcher in claude.ai's web UI, so switching to a personal org makes the
    /// app silently report 0% while a team seat is actually burning down. Probe
    /// every org the account belongs to and keep whichever one has usage on it.
    private func resolveOrgID(cookies: [String: String]) throws -> String {
        if let cached = resolvedOrgID, let at = orgResolvedAt,
           Date().timeIntervalSince(at) < orgResolveInterval {
            return cached
        }

        let lastActive = cookies["lastActiveOrg"].flatMap { $0.isEmpty ? nil : $0 }
        let candidates = (try? orgUUIDs(cookies: cookies)) ?? []
        knownOrgCount = candidates.count

        let chosen: String
        if candidates.count <= 1 {
            // Nothing to disambiguate — trust the list, else the cookie.
            guard let only = candidates.first ?? lastActive else {
                throw SyncError.missingOrgID
            }
            chosen = only
        } else {
            // The org you actually work in is the one with a window burning
            // down. A tie (genuinely idle account) falls back to the cookie.
            var best: (uuid: String, score: Int)?
            for uuid in candidates {
                guard let u = try? parse(get("organizations/\(uuid)/usage", cookies: cookies)) else { continue }
                let score = max(u.percent5h, u.percent7d)
                if score > (best?.score ?? -1) { best = (uuid, score) }
            }
            if let best, best.score > 0 {
                chosen = best.uuid
            } else if let lastActive, candidates.contains(lastActive) {
                chosen = lastActive
            } else if let best {
                chosen = best.uuid
            } else {
                throw SyncError.missingOrgID
            }
        }

        resolvedOrgID = chosen
        orgResolvedAt = Date()
        return chosen
    }

    private func orgUUIDs(cookies: [String: String]) throws -> [String] {
        struct Org: Decodable { let uuid: String }
        let data = try get("organizations", cookies: cookies)
        do {
            return try JSONDecoder().decode([Org].self, from: data).filter { !$0.uuid.isEmpty }.map(\.uuid)
        } catch {
            // Body intentionally omitted — see note in get() below.
            throw SyncError.malformedResponse("decode org list: \(error)")
        }
    }

    /// GET `https://claude.ai/api/<path>`, replaying Chrome's cookie jar.
    private func get(_ path: String, cookies: [String: String]) throws -> Data {
        guard let url = URL(string: "https://claude.ai/api/\(path)") else {
            throw SyncError.malformedResponse("could not construct URL for \(path.prefix(16))…")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        // Skip zstd; URLSession handles gzip natively.
        req.setValue("gzip, deflate", forHTTPHeaderField: "Accept-Encoding")
        req.setValue("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                     forHTTPHeaderField: "User-Agent")
        req.setValue("https://claude.ai/settings/usage", forHTTPHeaderField: "Referer")
        // Replay the full Chrome cookie set so Cloudflare sees a "real" session.
        let cookieHeader = cookies.map { "\($0.key)=\($0.value)" }.joined(separator: "; ")
        req.setValue(cookieHeader, forHTTPHeaderField: "Cookie")

        // Synchronous fetch via a semaphore — we're already off the main thread.
        var responseData: Data?
        var responseError: Error?
        var statusCode = 0
        let sema = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { data, response, error in
            responseData = data
            responseError = error
            if let http = response as? HTTPURLResponse {
                statusCode = http.statusCode
            }
            sema.signal()
        }.resume()
        sema.wait()

        if let err = responseError { throw err }
        guard (200..<300).contains(statusCode) else {
            if statusCode == 403 { throw SyncError.sessionExpired }
            // Don't include the response body — it can echo session cookies / org IDs
            // from Cloudflare or Anthropic error pages, and errors get NSLogged.
            throw SyncError.httpStatus(statusCode, nil)
        }
        guard let data = responseData else {
            throw SyncError.malformedResponse("empty body")
        }
        return data
    }

    private func parse(_ data: Data) throws -> SyncedUsage {
        struct Window: Decodable {
            let utilization: Double?
            let resets_at: String?
        }
        struct Envelope: Decodable {
            let five_hour: Window?
            let seven_day: Window?
            let seven_day_sonnet: Window?
        }
        let env: Envelope
        do {
            env = try JSONDecoder().decode(Envelope.self, from: data)
        } catch {
            // Body intentionally omitted — see note in fetch() above.
            throw SyncError.malformedResponse("decode: \(error)")
        }

        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let fNoFrac = ISO8601DateFormatter()
        fNoFrac.formatOptions = [.withInternetDateTime]

        func parseDate(_ s: String?) -> Date? {
            guard let s = s else { return nil }
            return f.date(from: s) ?? fNoFrac.date(from: s)
        }

        return SyncedUsage(
            percent5h: Int((env.five_hour?.utilization ?? 0).rounded()),
            percent7d: Int((env.seven_day?.utilization ?? 0).rounded()),
            reset5hAt: parseDate(env.five_hour?.resets_at),
            reset7dAt: parseDate(env.seven_day?.resets_at),
            percent7dSonnet: env.seven_day_sonnet?.utilization.map { Int($0.rounded()) },
            syncedAt: Date()
        )
    }
}
