import AppKit
import SwiftUI
import ClaudeUsageTrackerCore

final class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    private var statusItem: NSStatusItem!
    private var monitor: UsageMonitor!
    private var sync: ClaudeUsageSync!
    private var snapshot: UsageSnapshot = .empty
    private var lastSyncError: String?
    /// Set when the sync failure is an auth problem (expired/purged
    /// sessionKey) — the fix is logging into claude.ai in Chrome, so the UI
    /// switches to a "log in" call to action instead of a silent "‒".
    private var needsLogin = false

    private var popover: NSPopover!
    private var hostingController: NSHostingController<PopoverView>!
    private var eventMonitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.isVisible = true
        render(snapshot: .empty)
        wireStatusButton()

        popover = NSPopover()
        popover.behavior = .transient
        popover.animates = true
        popover.delegate = self
        hostingController = NSHostingController(rootView: makePopoverView())
        popover.contentViewController = hostingController

        monitor = UsageMonitor(tickInterval: 30) { [weak self] snap in
            self?.snapshot = snap
            self?.render(snapshot: snap)
            self?.refreshPopoverContentIfNeeded()
        }
        monitor.start()

        // Background sync from claude.ai's own usage endpoint. Uses cookies
        // from Chrome (one-time Keychain prompt). Falls back silently if Chrome
        // isn't installed, the user is logged out, or the cookie is expired —
        // we keep showing our calculated approximation in that case.
        sync = ClaudeUsageSync(pollInterval: 60) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let s):
                self.lastSyncError = nil
                self.needsLogin = false
                self.monitor.updateSynced(s)
                // Quiet on success — at 60s polls this would be 1,440 log lines/day.
                // The popover shows "live (Ns ago)" for visual confirmation.
            case .failure(let e):
                self.lastSyncError = "\(e)"
                self.needsLogin = (e as? ClaudeUsageSync.SyncError)?.needsLogin ?? false
                NSLog("[CCT] sync failed: %@", "\(e)")
                // Failures don't flow through the monitor, so re-render here —
                // otherwise the "log in" cue waits for the next snapshot tick.
                self.render(snapshot: self.snapshot)
                self.refreshPopoverContentIfNeeded()
            }
        }
        sync.start()

        NSLog("[CCT] launched")
    }

    // MARK: - Status item

    private func wireStatusButton() {
        guard let button = statusItem.button else { return }
        button.target = self
        button.action = #selector(statusButtonClicked(_:))
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
    }

    @objc private func statusButtonClicked(_ sender: NSStatusBarButton) {
        let event = NSApp.currentEvent
        let isRightClick =
            event?.type == .rightMouseUp ||
            (event?.type == .leftMouseUp && event?.modifierFlags.contains(.control) == true)
        if isRightClick {
            showRightClickMenu()
        } else {
            togglePopover()
        }
    }

    private func render(snapshot snap: UsageSnapshot) {
        guard let button = statusItem.button else { return }
        let pct = snap.displayDrivingPercent
        let mascot = MascotRenderer.image(percentUsed: pct, pointHeight: 16)
        mascot.isTemplate = false
        button.image = mascot
        button.imagePosition = .imageLeft
        button.imageHugsTitle = true
        if snap.displayBucket == .noData {
            // Auth failure outranks the generic dash — the user can act on it.
            button.title = needsLogin ? " ⚠︎ log in" : " ‒"
        } else {
            button.title = " \(pct)%"
        }
    }

    /// Open claude.ai in Chrome specifically — the sync reads Chrome's cookie
    /// jar, so logging in via the default browser wouldn't fix anything.
    @objc private func openClaudeLogin() {
        guard let url = URL(string: "https://claude.ai") else { return }
        if let chrome = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.google.Chrome") {
            NSWorkspace.shared.open(
                [url],
                withApplicationAt: chrome,
                configuration: NSWorkspace.OpenConfiguration()
            )
        } else {
            NSWorkspace.shared.open(url)
        }
    }

    // MARK: - Popover

    private func makePopoverView() -> PopoverView {
        PopoverView(
            snapshot: snapshot,
            syncError: snapshot.synced == nil ? lastSyncError : nil,
            needsLogin: needsLogin,
            onLogin: { [weak self] in self?.openClaudeLogin() },
            onRefresh: { [weak self] in self?.monitor.refreshNow() },
            onQuit: { NSApp.terminate(nil) }
        )
    }

    private func togglePopover() {
        if popover.isShown {
            popover.performClose(nil)
            return
        }
        guard let button = statusItem.button else { return }
        hostingController.rootView = makePopoverView()
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
        installOutsideClickMonitor()
    }

    private func refreshPopoverContentIfNeeded() {
        guard popover.isShown else { return }
        hostingController.rootView = makePopoverView()
    }

    private func installOutsideClickMonitor() {
        if let m = eventMonitor { NSEvent.removeMonitor(m); eventMonitor = nil }
        eventMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            self?.popover.performClose(nil)
        }
    }

    func popoverDidClose(_ notification: Notification) {
        if let m = eventMonitor { NSEvent.removeMonitor(m); eventMonitor = nil }
    }

    // MARK: - Right-click menu

    private func showRightClickMenu() {
        let menu = NSMenu()

        if let s = snapshot.synced {
            let age = Int(s.ageSeconds)
            let ageStr = age < 60 ? "\(age)s" : "\(age / 60)m"
            menu.addItem(disabledItem("claude.ai sync: live (\(ageStr) ago)"))
        } else if let err = lastSyncError {
            menu.addItem(disabledItem("claude.ai sync: \(err)"))
        } else {
            menu.addItem(disabledItem("claude.ai sync: pending…"))
        }
        if needsLogin {
            let login = NSMenuItem(
                title: "⚠︎ Session expired — open claude.ai to log in",
                action: #selector(openClaudeLogin),
                keyEquivalent: "l"
            )
            login.target = self
            menu.addItem(login)
        }
        let syncNow = NSMenuItem(title: "Sync now", action: #selector(syncNow), keyEquivalent: "s")
        syncNow.target = self
        menu.addItem(syncNow)

        menu.addItem(.separator())

        let refresh = NSMenuItem(title: "Refresh transcripts", action: #selector(refreshNow), keyEquivalent: "r")
        refresh.target = self
        menu.addItem(refresh)

        if UserDefaults.standard.bool(forKey: "cct.debugMenu") {
            menu.addItem(.separator())
            menu.addItem(disabledItem("Debug — force bucket"))
            for (i, bucket) in HealthBucket.allCases.enumerated() {
                let item = NSMenuItem(
                    title: "  \(bucket.placeholderFace)  \(bucket.displayName)",
                    action: #selector(forceBucket(_:)),
                    keyEquivalent: i < 9 ? "\(i + 1)" : ""
                )
                item.target = self
                item.tag = bucket.rawValue
                menu.addItem(item)
            }
        }

        menu.addItem(.separator())
        menu.addItem(NSMenuItem(
            title: "Quit",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        ))

        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil  // detach so subsequent left-clicks go back to popover
    }

    private func disabledItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }

    @objc private func refreshNow() { monitor.refreshNow() }
    @objc private func syncNow() { sync.refreshNow() }

    @objc private func forceBucket(_ sender: NSMenuItem) {
        guard let bucket = HealthBucket(rawValue: sender.tag) else { return }
        let fakeSnap = UsageSnapshot(
            asOf: Date(),
            entryCount: snapshot.entryCount,
            activeBlock: nil,
            activeWeek: nil,
            synced: SyncedUsage(
                percent5h: bucket.demoPercent,
                percent7d: bucket.demoPercent,
                reset5hAt: nil,
                reset7dAt: nil,
                syncedAt: Date()
            )
        )
        snapshot = fakeSnap
        render(snapshot: fakeSnap)
    }
}

@main
enum Main {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
