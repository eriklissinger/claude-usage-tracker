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
    }

    private let pollInterval: TimeInterval
    private let queue = DispatchQueue(label: "cct.claude-sync", qos: .utility)
    private var timer: DispatchSourceTimer?
    private let onSync: Callback

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
        guard let orgID = cookies["lastActiveOrg"], !orgID.isEmpty else {
            throw SyncError.missingOrgID
        }

        guard let url = URL(string: "https://claude.ai/api/organizations/\(orgID)/usage") else {
            throw SyncError.malformedResponse("could not construct URL for org \(orgID.prefix(8))…")
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
        return try parse(data)
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
