# claude-usage-tracker

macOS menu bar widget that shows your Claude usage in real time, mirrored from `claude.ai/settings/usage`. The icon is a Claude-mascot "battery" that drains as you burn through your 5-hour block.

> **Disclaimer:** Not affiliated with, endorsed by, or sponsored by Anthropic. Claude is a trademark of Anthropic PBC. This app calls an undocumented internal endpoint that Anthropic could change or block at any time.

## Install

**Before you start:** make sure you're logged into [claude.ai](https://claude.ai) in Chrome — the app reads your Chrome cookies to authenticate.

1. Download **[ClaudeUsageTracker.zip](https://github.com/eriklissinger/claude-usage-tracker/releases/latest)** from the latest release
2. Unzip and drag `ClaudeUsageTracker.app` to your `/Applications` folder
3. Right-click the app → **Open** (required once — macOS warns on first launch because the app isn't notarized)
4. The icon appears in your menu bar immediately

**To launch on login:** System Settings → General → Login Items → add `ClaudeUsageTracker`.

## Requirements

- macOS 13+
- Google Chrome (or Brave / Edge — same cookie scheme; Safari and Firefox don't work)
- Logged in to `claude.ai` in Chrome

## First-launch Keychain prompt

On first sync you'll see:

> "ClaudeUsageTracker wants to use your confidential information stored in 'Chrome Safe Storage' in your keychain."

Click **Always Allow** to silence it permanently. This is how the app reads your Chrome cookies to authenticate with claude.ai — no credentials are stored by the app.

## What it shows

- **5-hour block** — same percentage as `claude.ai/settings/usage`, updated every 60s
- **Weekly window** — same, account-wide (claude.ai, Claude Code, MCP, etc.)
- **Per-model and top-project breakdown** for the current block (Claude Code only — from local transcripts, shown as a share of that activity rather than of your limit)
- **Reset countdowns** with absolute reset time

## Right-click menu

- **Sync now** — force an immediate poll
- **Refresh transcripts** — force a re-scan of local JSONL files

## How it works

On launch and every 60s the app reads cookies from your local Chrome profile, decrypts them via the macOS Keychain, and calls the same endpoint `claude.ai/settings/usage` uses. Local Claude Code transcripts (`~/.claude/projects/**/*.jsonl`) are watched with FSEvents for the model/project breakdown rows.

Usage is per-organization. If your account belongs to more than one org (say a personal one plus a team), the app probes each and reports whichever has usage on it, re-checking every 10 minutes. It deliberately doesn't just follow the `lastActiveOrg` cookie: that tracks the org switcher on claude.ai, so switching orgs in the browser would otherwise make the app report 0% while your real seat is burning down.

If sync fails (logged out, Chrome not installed, endpoint changes), the widget shows `—` until it can connect again.

## Build from source

Requires Swift / Xcode Command Line Tools.

```sh
git clone https://github.com/eriklissinger/claude-usage-tracker
cd claude-usage-tracker
./scripts/build-app.sh release
open ./build/ClaudeUsageTracker.app
```

## License

[MIT](./LICENSE)
