import Foundation
import CommonCrypto

/// Reads and decrypts cookies from Chrome's macOS cookie SQLite store.
///
/// Chrome on macOS encrypts cookie values with AES-128-CBC. The key is derived
/// (PBKDF2-SHA1, 1003 iterations, salt "saltysalt") from a password that lives
/// in the macOS Keychain under service "Chrome Safe Storage" / account
/// "Chrome". The IV is 16 spaces. Encrypted blobs are prefixed with "v10" or
/// "v11"; both use the same scheme.
///
/// The first time this runs, the user gets one Keychain prompt
/// ("ClaudeUsageTracker wants to use your confidential information…") and can
/// click "Always Allow" to silence future prompts. If they deny, throws
/// `keychainAccessDenied`.
///
/// macOS-only. Chrome / Brave / Edge use the same scheme; Safari and Firefox
/// do not and aren't supported here.
public enum ChromeCookieReader {
    public enum CookieError: Error, CustomStringConvertible {
        case chromeNotInstalled
        case keychainAccessDenied
        case cookieDBLocked
        case cookieNotFound(String)
        case decryptionFailed(String)

        public var description: String {
            switch self {
            case .chromeNotInstalled:    return "Chrome cookies DB not found"
            case .keychainAccessDenied:  return "Keychain access denied for Chrome Safe Storage"
            case .cookieDBLocked:        return "Chrome cookies DB is locked"
            case .cookieNotFound(let n): return "Cookie \(n) not found in Chrome"
            case .decryptionFailed(let r): return "Decrypt failed: \(r)"
            }
        }
    }

    private static var chromeDir: String {
        NSString(string: "~/Library/Application Support/Google/Chrome").expandingTildeInPath
    }

    /// Chrome profile directories holding a cookie DB, most-recently-used
    /// first. Reading only "Default" misses the session whenever the signed-in
    /// claude.ai profile is a secondary one ("Profile 1", "Profile 2", …).
    private static var profileDirs: [String] {
        let fm = FileManager.default
        let all = ((try? fm.contentsOfDirectory(atPath: chromeDir)) ?? [])
            .filter { $0 == "Default" || $0.hasPrefix("Profile ") }
            .filter { fm.fileExists(atPath: "\(chromeDir)/\($0)/Cookies") }
            .sorted()
        guard let lastUsed = lastUsedProfile, all.contains(lastUsed) else { return all }
        return [lastUsed] + all.filter { $0 != lastUsed }
    }

    /// `profile.last_used` from Chrome's Local State — the profile whose window
    /// was frontmost last, and so the one the user thinks of as "logged in".
    private static var lastUsedProfile: String? {
        guard let data = FileManager.default.contents(atPath: "\(chromeDir)/Local State"),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let profile = json["profile"] as? [String: Any],
              let lastUsed = profile["last_used"] as? String
        else { return nil }
        return lastUsed
    }

    /// Searches every Chrome profile and returns the first whose cookies carry
    /// a `sessionKey` — the profile the user is actually signed in to. Falls
    /// back to the richest result so the "logged out" error still surfaces.
    static func readAllCookies(forDomain domain: String) throws -> [String: String] {
        let profiles = profileDirs
        guard !profiles.isEmpty else { throw CookieError.chromeNotInstalled }

        let key = try keychainDerivedKey()
        var best: [String: String] = [:]
        for profile in profiles {
            let cookies = try readAllCookies(
                forDomain: domain,
                cookiesPath: "\(chromeDir)/\(profile)/Cookies",
                key: key
            )
            if cookies["sessionKey"]?.isEmpty == false { return cookies }
            if cookies.count > best.count { best = cookies }
        }
        return best
    }

    /// Read every cookie for the given host (and its `.host` parent) out of one
    /// profile's DB, decrypt, return as `name -> value`. Pulls all cookies so we
    /// can replay full browser auth state (sessionKey, cf_clearance,
    /// lastActiveOrg, etc.).
    private static func readAllCookies(
        forDomain domain: String,
        cookiesPath: String,
        key: Data
    ) throws -> [String: String] {

        // Copy DB to temp so we don't fight Chrome's lock.
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("cct_cookies_\(UUID().uuidString).sqlite").path
        try? FileManager.default.removeItem(atPath: tmp)
        do {
            try FileManager.default.copyItem(atPath: cookiesPath, toPath: tmp)
        } catch {
            throw CookieError.cookieDBLocked
        }
        defer { try? FileManager.default.removeItem(atPath: tmp) }

        // Pull both `domain` and `.domain` rows.
        let escaped = domain.replacingOccurrences(of: "'", with: "''")
        let query = """
            SELECT name, quote(encrypted_value)
            FROM cookies
            WHERE host_key = '\(escaped)' OR host_key = '.\(escaped)';
        """
        let raw = run(["/usr/bin/sqlite3", tmp, query])
        var out: [String: String] = [:]
        var rowCount = 0
        var decryptFails = 0
        var firstFailReason = ""
        for line in raw.split(separator: "\n") {
            rowCount += 1
            // Format: name|X'AABBCC...'
            let parts = line.split(separator: "|", maxSplits: 1).map(String.init)
            guard parts.count == 2 else { continue }
            let name = parts[0]
            let blobStr = parts[1].trimmingCharacters(in: .whitespacesAndNewlines)
            guard blobStr.hasPrefix("X'"), blobStr.hasSuffix("'") else { continue }
            let hex = String(blobStr.dropFirst(2).dropLast())
            guard let blob = hexToData(hex) else { continue }
            do {
                let plaintext = try decryptCookieValue(blob, key: key)
                out[name] = plaintext
            } catch {
                decryptFails += 1
                if firstFailReason.isEmpty { firstFailReason = "\(error)" }
            }
        }
        if out.isEmpty && decryptFails > 0 {
            NSLog("[CCT] cookie decrypt: %d/%d failed. first reason: %@", decryptFails, rowCount, firstFailReason)
        }
        return out
    }

    // MARK: - Internals

    private static func keychainDerivedKey() throws -> Data {
        let result = runWithStatus(["/usr/bin/security",
                                    "find-generic-password",
                                    "-w",
                                    "-s", "Chrome Safe Storage",
                                    "-a", "Chrome"])
        // `security` exits 0 on success, 51 on user denial, 44 if the item is missing.
        // Checking the exit code (not just empty stdout) means a real failure isn't
        // misdiagnosed as "no Chrome installed" further up the stack.
        let password = result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard result.exitCode == 0, !password.isEmpty else {
            throw CookieError.keychainAccessDenied
        }
        return pbkdf2(password: password)
    }

    private static func pbkdf2(password: String) -> Data {
        let salt = Array("saltysalt".utf8)
        let pwd  = Array(password.utf8)
        var key  = [UInt8](repeating: 0, count: 16)
        _ = CCKeyDerivationPBKDF(
            CCPBKDFAlgorithm(kCCPBKDF2),
            password, pwd.count,
            salt,     salt.count,
            CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA1),
            1003,
            &key, key.count
        )
        return Data(key)
    }

    private static func decryptCookieValue(_ encrypted: Data, key: Data) throws -> String {
        guard encrypted.count > 3 else {
            throw CookieError.decryptionFailed("blob too short")
        }
        let prefix = String(data: encrypted.prefix(3), encoding: .utf8) ?? "?"
        guard prefix == "v10" || prefix == "v11" else {
            throw CookieError.decryptionFailed("unsupported prefix \(prefix) — Chrome may be using App-Bound Encryption (v20+)")
        }
        let ct = encrypted.dropFirst(3)
        let iv = Data(repeating: 0x20, count: 16)  // 16 spaces

        let outCapacity = ct.count + kCCBlockSizeAES128
        var out = Data(count: outCapacity)
        var outLen = 0
        let ctCount = ct.count
        let status: CCCryptorStatus = ct.withUnsafeBytes { ctPtr in
            key.withUnsafeBytes { keyPtr in
                iv.withUnsafeBytes { ivPtr in
                    out.withUnsafeMutableBytes { outPtr in
                        CCCrypt(
                            CCOperation(kCCDecrypt),
                            CCAlgorithm(kCCAlgorithmAES128),
                            CCOptions(kCCOptionPKCS7Padding),
                            keyPtr.baseAddress, 16,
                            ivPtr.baseAddress,
                            ctPtr.baseAddress, ctCount,
                            outPtr.baseAddress, outCapacity,
                            &outLen
                        )
                    }
                }
            }
        }
        guard status == kCCSuccess else {
            throw CookieError.decryptionFailed("CCCrypt status \(status)")
        }
        out.removeSubrange(outLen..<out.count)

        // Chrome 105+ on macOS prefixes v10 cookie plaintexts with a 32-byte
        // SHA-256 of the cookie's host (anti-swap hardening). Strip it if
        // present — try UTF-8 first; if it fails, drop 32 bytes and retry.
        if let plaintext = String(data: out, encoding: .utf8) {
            return plaintext
        }
        if out.count > 32, let plaintext = String(data: out.dropFirst(32), encoding: .utf8) {
            return plaintext
        }
        throw CookieError.decryptionFailed("not utf8 after prefix strip")
    }

    private static func run(_ args: [String]) -> String {
        runWithStatus(args).stdout
    }

    private static func runWithStatus(_ args: [String]) -> (stdout: String, exitCode: Int32) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: args[0])
        process.arguments = Array(args.dropFirst())
        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return ("", -1)
        }
        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
        return (String(data: data, encoding: .utf8) ?? "", process.terminationStatus)
    }

    private static func hexToData(_ hex: String) -> Data? {
        guard hex.count % 2 == 0 else { return nil }
        var data = Data(capacity: hex.count / 2)
        var idx = hex.startIndex
        while idx < hex.endIndex {
            let next = hex.index(idx, offsetBy: 2)
            guard let byte = UInt8(hex[idx..<next], radix: 16) else { return nil }
            data.append(byte)
            idx = next
        }
        return data
    }
}
