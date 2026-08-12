# Design Doc — claude-usage-tracker

**Status:** v0.4 — parts superseded, see note below
**Author:** Erik Lissinger
**Last updated:** 2026-08-12

> **Superseded since v0.3.** Percentages now come from claude.ai's own usage endpoint
> (`ClaudeUsageSync`), not from a local NCU sum measured against a guessed cap. Plan tiers, NCU
> caps, and their calibration were removed in `4a9cff4`; there is no Settings window, no pause,
> and no local fallback. NCU survives only as a relative weight behind the Claude Code breakdown
> rows, where it decides shares and never a percentage of a limit.
>
> §7.4, §10.5, §10.6, §11 and the cap rows in §14 describe the original design and are kept as
> history, not as spec. §2, §7, §8, §10.3, §10.4 and §10.12 have been updated to match what ships.

---

## 1. Summary

A macOS menu bar widget that shows real-time Claude usage synced live from `claude.ai/settings/usage`. The icon is a Claude-mascot "battery" that drains as you burn through your 5-hour block. Usage percentages come directly from claude.ai's internal API (polled every 60s via Chrome cookie replay), so the widget always agrees with the website. Local Claude Code transcripts are also parsed for per-model and per-project breakdowns within the current block.

## 2. Goals

- **Glanceable cap proximity.** A user should know in <1 second whether they're safe, warm, or about to hit the wall.
- **Exact match with claude.ai.** Percentages are pulled from the same endpoint the settings page uses — no approximation, no drift.
- **Lightweight.** Idles at <1% CPU and <50MB RAM. Doesn't slow down login or hog the menu bar.
- **Honest degradation.** If sync fails (logged out, Chrome missing, endpoint changes), the widget shows `—` and says why — an expired session gets a log-in prompt. It deliberately does *not* fall back to a local approximation: a plausible-looking wrong number is worse than no number.

## 3. Non-goals (v1)

- Animated mascot (idle blinking, reactions) → v2.
- Anthropic API console / Admin API spend tracking → different audience (API users, not Plan subscribers).
- Push notifications when crossing thresholds → easy to add later.
- Multi-machine usage aggregation → assumes one Mac per user.
- Historical charts beyond the active windows → v2.
- Safari / Firefox cookie support → Chrome/Brave/Edge only (same AES-128-CBC scheme).

## 4. Background

Claude Code writes one JSONL file per session at `~/.claude/projects/<sanitized-cwd>/<session-uuid>.jsonl`. Every assistant turn line includes a timestamp, the model used, and a `usage` block:

```json
{
  "type": "assistant",
  "timestamp": "2026-04-22T10:00:00.123Z",
  "message": {
    "model": "claude-opus-4-7",
    "usage": {
      "input_tokens": 6,
      "cache_creation_input_tokens": 33497,
      "cache_read_input_tokens": 0,
      "output_tokens": 385,
      "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 }
    }
  }
}
```

This is enough to reconstruct usage over any time window without touching the network. The community tool [ccusage](https://github.com/ryoppippi/ccusage) does exactly this and is our reference implementation for parsing semantics and plan coefficients.

Anthropic does not publish exact token caps for Pro / Max plans — they publish "approximate message counts." This means our caps are **calibrated heuristics**, not contract values, and must be user-overridable.

## 5. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                ClaudeUsageTracker.app  (LSUIElement)           │
│                                                                │
│  ┌────────────────┐        ┌────────────────────────────┐     │
│  │ FSEventsWatcher│───────▶│ TranscriptScanner          │     │
│  │  (kernel hook) │        │  - walks ~/.claude/projects│     │
│  └────────────────┘        │  - byte-offset table       │     │
│                            └──────────┬─────────────────┘     │
│                                       │ new JSONL lines       │
│                                       ▼                        │
│                            ┌────────────────────────────┐     │
│                            │ JSONLParser                │     │
│                            │  - stream parse, defensive │     │
│                            │  - emits UsageEntry        │     │
│                            └──────────┬─────────────────┘     │
│                                       ▼                        │
│                            ┌────────────────────────────┐     │
│                            │ UsageAggregator            │     │
│                            │  - in-memory ring buffer   │     │
│                            │  - 5h + 7d sliding sums    │     │
│                            │  - per-model normalization │     │
│                            └──────────┬─────────────────┘     │
│                                       ▼                        │
│                            ┌────────────────────────────┐     │
│                            │ HealthModel                │     │
│                            │  used / cap → bucket 0..5  │     │
│                            └──────────┬─────────────────┘     │
│                                       ▼                        │
│           ┌───────────────────────────┴───────────────┐       │
│           ▼                                           ▼       │
│  ┌─────────────────┐                    ┌─────────────────────┐
│  │ MenuBarView     │                    │ DetailPopover       │
│  │ NSStatusItem    │                    │ SwiftUI             │
│  │ face + % label  │                    │ bars, breakdown     │
│  └─────────────────┘                    └─────────────────────┘
└────────────────────────────────────────────────────────────────┘
```

### Module responsibilities

| Module | Responsibility | Key dependencies |
|---|---|---|
| `FSEventsWatcher` | Subscribe to filesystem events for `~/.claude/projects/`. Debounce bursts. | `FSEventStreamCreate` |
| `TranscriptScanner` | Walk project tree on launch and on FS events. Track per-file byte offsets. Read only new bytes since last offset. | `FileHandle`, `OffsetStore` |
| `JSONLParser` | Parse one JSONL line at a time. Tolerate unknown fields, missing keys, schema drift. Skip non-assistant lines. | `JSONDecoder` with custom keyed strategy |
| `UsageAggregator` | Append-only ring of `UsageEntry`. Drop entries older than 7d. Compute 5h and 7d sums on demand (or maintain incrementally). | — |
| `PlanConfig` | Plan-tier presets (Pro, Max 5×, Max 20×, Custom) → cap values in normalized cost units. Per-model multipliers. | `UserDefaults` for overrides |
| `HealthModel` | Maps `used / cap` to an enum `HealthBucket` (0..5 + special states `dead`, `evilGrin`). | — |
| `MenuBarController` | Owns `NSStatusItem`. Updates icon + optional label on `HealthModel` changes. Wires popover. | `AppKit` |
| `DetailPopover` | SwiftUI view shown on click. Two progress bars (5h, 7d), reset countdowns, model split, top sessions in last 5h. | `SwiftUI` |
| `SettingsView` | Plan picker, custom caps, refresh interval, show/hide label, launch-at-login toggle. | `SMAppService` |
| `OffsetStore` | Persists per-file byte offsets to disk so we don't re-parse on relaunch. | `Codable` JSON file |

## 6. Data model

```swift
struct UsageEntry: Codable {
    let timestamp: Date
    let model: String              // "claude-opus-4-7", "claude-sonnet-4-6", ...
    let inputTokens: Int
    let cacheCreationTokens: Int
    let cacheReadTokens: Int
    let outputTokens: Int
}

enum HealthBucket: Int {
    case healthy        // 0–20%   used
    case scuffed        // 20–50%
    case bruised        // 50–75%
    case bloody         // 75–95%
    case critical       // 95–100%
    case dead           // ≥100%
    case evilGrin       // transient: shown for ~3s after window resets
}

struct PlanConfig {
    let tier: PlanTier              // .pro, .max5x, .max20x, .custom
    let cap5h: Double               // normalized cost units
    let cap7d: Double
    let modelWeights: [String: Double]
}
```

## 7. Normalization (relative shares only)

We collapse heterogeneous token types and models into a single scalar — **normalized cost units (NCU)** — that approximates Anthropic's billable cost. This lets us compare models and turn types on one axis.

NCU is now used **only for the relative breakdown rows** ("Opus 56% / Sonnet 44%" within a block). Those are ratios, so they hold even though NCU's absolute scale is uncalibrated. Nothing derives a percentage of a limit from NCU any more — the meters come from claude.ai.

### 7.1 Token-type weights (per million tokens, relative to Sonnet input)

| Token type | Weight |
|---|---|
| `input_tokens` | 1.0 |
| `cache_creation_input_tokens` | 1.25 |
| `cache_read_input_tokens` | 0.00 |
| `output_tokens` | 5.0 |

### 7.2 Model weights (multiplied on top)

| Model family | Weight |
|---|---|
| `*fable*` | 10.0 |
| `claude-opus-*` | 5.0 |
| `claude-sonnet-*` | 1.0 |
| `claude-haiku-*` | 0.25 |
| Unknown | 1.0 (logged) |

### 7.3 Per-entry NCU

```
ncu(entry) = modelWeight(entry.model)
           * ( 1.00 * entry.inputTokens
             + 1.25 * entry.cacheCreationTokens
             + 0.00 * entry.cacheReadTokens
             + 5.00 * entry.outputTokens )
           / 1_000_000
```

### 7.4 Default caps — HISTORICAL (removed in `4a9cff4`)

The tiers and calibration below drove the meters before we sourced percentages from claude.ai.
They are recorded because they explain the token weights above (notably why `cache_read` is 0.0),
and because they document why the approach was abandoned: no weighted token sum reproduced
Anthropic's "% used" across blocks. `PlanConfig.swift` is now a tombstone.

| Plan | 5h cap (NCU) | 7d cap (NCU) |
|---|---|---|
| Pro | 6 | 70 |
| Max 5× | 30 | 350 |
| Max 20× | 120 | 1400 |

**Calibration math (Max 5× anchor):** three dogfooding observations from claude.ai/settings/usage. The third sample exposed that our `cache_read` weight of 0.10 was way too high — Anthropic's docs explicitly say cache reads don't count toward rate limits, and the % cap behaves the same way. Dropping `cache_read` weight to 0.0 (see §7.1) and re-anchoring:

| Moment | Our NCU (post-fix) | Anthropic % | Implied cap |
|---|---|---|---|
| 2026-04-23 17:00 UTC | (cache-heavy block, didn't recompute) | 96% | — |
| 2026-04-28 (cache-heavy block) | 8.66 | 29% | **29.9** |

We anchor 5h Max 5× at **30 NCU**; Pro and Max 20× scale 1×/4×. Weekly caps unchanged for now — no fresh "All models" weekly % data point to anchor against.

**Limitation:** Anthropic's "% used" doesn't appear to be a strictly linear function of any weighted token sum (different blocks produce different implied caps even after fixing cache_read). Best we can do without API access is approximate; the user can recalibrate the weekly window via the menu, and we may revisit the 5h formula if drift returns.

**Future refinement:**
1. Re-anchor whenever Anthropic publishes any numeric cap.
2. Settings UI: "calibrate from claude.ai screenshot" — let users paste their current % and back-solve their cap.
3. Custom caps as an escape hatch.

## 8. Rolling window algorithm

> **Superseded for display (2026-08).** The percentages and reset countdowns in the popover come
> from claude.ai's usage endpoint, which reports the real windows. `BlockDetector` and
> `WeeklyWindowDetector` still run, but only to decide which transcript entries belong to the
> current block so the Claude Code breakdown rows have a window to group by. The reverse
> engineering below stands as the record of how the windows actually behave.

Anthropic's actual semantics: a 5h timer starts on the *first* message of a fresh window. The 7d window appears to be a fixed weekly reset. We approximate both as **sliding sums** — simpler and never under-reports.

> **M2 finding (2026-04-23):** Cross-checking against `ccusage`, Anthropic's 5h cap is actually an *anchored block*, not a sliding window. A block begins on the first message after a 5h gap and runs for exactly 5 hours; once it expires, the next message starts a new block. The sliding-sum approximation always over-reports relative to the real block, so it stays "safe" (never under-reports), but M3 should switch to true block detection so the popover's "resets in N" countdown matches Anthropic's UI exactly.

> **M2 finding (2026-04-23):** Claude Code re-emits identical assistant turns into multiple JSONL files when sessions are resumed or branched. The aggregator must dedupe on `(message.id, requestId)` — without this we over-count by ~2×. Implemented in `TranscriptScanner.deduplicate`.

> **M6 finding (2026-04-27):** The 7-day cap is **NOT** a fixed weekly reset and **NOT** a rolling 7d sum. Per Anthropic docs + community reverse-engineering ([HN 45696713](https://news.ycombinator.com/item?id=45696713)): a weekly window opens on the first message after the previous window expired and runs exactly 7 days. So the user's reset day drifts forward whenever they go quiet across a window boundary. Same shape as the 5h block algorithm but no idle-gap rule and no hour-flooring. Implemented in `WeeklyWindowDetector`.
>
> Caveat: our auto-detected weekly anchor walks chronologically from the user's first transcript, which can land on a different alignment than Anthropic's actual cycle (Anthropic counts from subscription start, may have shifted resets we never observed, etc.). When the user pastes their next reset time from claude.ai, we anchor to that exact end and ignore auto-detection — `WeeklyWindowDetector.windowAnchored(endingAt:)`. The override re-rolls forward by 7 days when it expires, so the user only enters it once until Anthropic shifts it.

```swift
func sum(window: TimeInterval, now: Date = .now) -> Double {
    let cutoff = now.addingTimeInterval(-window)
    return entries
        .reversed()                    // entries are append-time-sorted
        .prefix(while: { $0.timestamp >= cutoff })
        .map(ncu)
        .reduce(0, +)
}
```

Complexity: O(k) where k = entries inside the window. With ~100 turns/day a Max user has ~700 entries in a 7d ring — negligible.

**Reset detection:** when 5h sum transitions from >0 to 0, emit `evilGrin` for 3s, then settle to `healthy`.

## 9. File watching & incremental parsing

```
~/.claude/projects/
  └── -Users-eriklissinger-Documents-foo/
        ├── 9028f201-....jsonl   ← active session, grows over time
        └── e1a4b7c2-....jsonl   ← finished session, immutable
```

### Strategy

1. On launch: walk the tree, load `OffsetStore` from `~/Library/Application Support/ClaudeUsageTracker/offsets.json`.
2. For each JSONL file: open with `FileHandle`, seek to stored offset, read to EOF, parse line by line, append to `UsageAggregator`, save new offset.
3. Subscribe to FSEvents on `~/.claude/projects/`. Debounce events with a 500ms trailing window (Claude Code can flush several lines in quick succession).
4. On event: re-scan changed files only (FSEvents gives us paths).
5. Backfill on first launch ever: parse last 7 days of files in full.

### Edge cases

| Case | Handling |
|---|---|
| Truncated last line (write in flight) | Fail-soft: don't advance offset past the partial line; retry on next event. |
| File deleted | Drop offset entry. |
| File renamed | FSEvents emits `kFSEventStreamEventFlagItemRenamed`; treat as delete + new. |
| Clock skew (timestamp in future) | Clamp to `now` for window calc; log warning. |
| Schema drift (new model, new keys) | `JSONDecoder` ignores unknown keys; unknown model gets weight 1.0 + logged. |
| Multiple Claude Code processes writing concurrently | Each writes to its own file; no cross-file coordination needed. |

## 10. UI / UX

### 10.1 Design philosophy

It's a **HUD, not a dashboard.** Glanceable first, browsable second, configurable third. Every interaction should answer "how close am I to the wall?" in under a second. Anything that takes more thought belongs in Settings.

Two visual languages live side by side:

- **Doom HUD aesthetic** for the face itself and the popover's segmented progress bars — chunky pixel art, intentional 1980s-FPS feel. This is the joke and we lean into it.
- **Native macOS chrome** for everything else — system fonts (SF Pro), system materials (`.regularMaterial` blur), rounded corners, dark/light mode-aware colors. We don't fight the OS.

Color is purposeful and restrained. Red means budget burn. Outside the face sprites and the bar fills, we stay neutral.

### 10.2 Menu bar icon

**Anatomy**

```
       ┌──────────────────────┐
       │  ▒ ▒ … ⓘ 🔍  [😐 73%] │   ← icon + optional % label, right-aligned in menu bar
       └──────────────────────┘
                       ↑
                  our status item
```

| Property | Value |
|---|---|
| Icon size | 22 × 22 pt (44 × 44 px @2×) |
| Padding from label | 4 pt |
| Label font | SF Pro Text, 12 pt, monospaced digits, system foreground |
| Label format | `73%` — integer percent of `max(5h%, 7d%)` |
| Status item length | `NSStatusItem.variableLength` |
| Click behavior | Toggle popover |
| Right-click | Show context NSMenu |
| Hover tooltip | `5h: 73% · 7d: 41% · resets in 1h 12m` |

**Visual states**

| State | Trigger | Face | Label | Tooltip suffix |
|---|---|---|---|---|
| `healthy` | 0–20% used | grinning, untouched | `12%` | `you're fine` |
| `scuffed` | 20–50% | small bruise | `34%` | (none) |
| `bruised` | 50–75% | visible damage | `62%` | (none) |
| `bloody` | 75–95% | bloodied | `81%` | `getting tight` |
| `critical` | 95–100% | barely standing | `97%` | `slow down` |
| `dead` | ≥100% (cap hit) | `STFDEAD0` skull | `MAX` | `cap hit · resets in N` |
| `evilGrin` | window just reset | `STFEVL0` | `0%` | `fresh window — go nuts` |
| `noData` | first launch, before backfill | greyscale healthy face | `—` | `gathering data…` |
| `paused` | user paused updates | greyscale healthy face | `‖` | `paused` |
| `error` | can't read JSONL | greyscale healthy face with `?` overlay | `!` | `can't read transcripts — click for details` |

Whichever window (5h or 7d) has the higher used % drives the bucket and the label, so the user always sees their tightest constraint.

### 10.3 Detail popover (left-click)

```
╭──────────────────────────────────────────────╮
│                                              │
│   [mascot]  Claude Usage                     │
│             · live (12s ago)                  │
│                                              │
│   ─────────────────────────────────────────  │
│                                              │
│   ALL CLAUDE USAGE                           │
│   Desktop, web, mobile and Claude Code ·     │
│   share of your limit                        │
│                                              │
│   5-hour block                               │
│   ▓▓▓▓░░░░░░░░░░░░░░░░  11%                  │
│                  resets in 1h 27m · 12:10 PM │
│   Weekly window                              │
│   ▓▓▓▓▓▓▓░░░░░░░░░░░░░  31%                  │
│                  resets in 2d 3h · Fri 2 PM  │
│                                              │
│   ─────────────────────────────────────────  │
│                                              │
│   CLAUDE CODE ONLY                           │
│   Share of this block's Claude Code          │
│   activity, not of your limit                │
│   By model                                   │
│     Opus       ▓▓▓▓▓▓░░░░       56%          │
│     Sonnet     ▓▓▓▓░░░░░░       44%          │
│   Top projects                               │
│     WEEV Main  ▓▓▓▓▓▓▓▓░░       79%          │
│     industr…   ▓░░░░░░░░░       14%          │
│                                              │
│   ─────────────────────────────────────────  │
│   Refresh      Updated 21s ago       Quit    │
╰──────────────────────────────────────────────╯
```

**Layout & sizing**

| Property | Value |
|---|---|
| Width | 320 pt |
| Height | adapts to content (~420 pt typical) |
| Material | `.popover` (system blur) |
| Padding | 16 pt all sides |
| Section gap | 16 pt |
| Header face | 40 pt tall, the same sprite as the menu bar, nearest-neighbour scaled |
| Bar style | rounded rect, 10 pt tall, segmented (20 cells) for Doom feel |
| Bar fill color | `green` <50%, `yellow` 50–75%, `orange` 75–95%, `red` ≥95% |
| Numbers | SF Mono, 11 pt semibold |
| Section headers | SF Pro, 10 pt, semibold, secondary, uppercase, 0.6 tracking |
| Section captions | SF Pro, 10 pt, tertiary — what the numbers below actually cover |
| Footer buttons | borderless `.plain` style, system tinted |

**Component breakdown**

1. **Header** — mascot sprite (matches menu bar), title `Claude Usage`, and `· live (Ns ago)` while a fresh sync backs the numbers. When the claude.ai session has expired, a banner with an **Open claude.ai in Chrome** button takes the place of the numbers' credibility.
2. **`ALL CLAUDE USAGE`** — two meters (5-hour block, weekly window) straight from claude.ai's endpoint, so they cover every surface: desktop, web, mobile and Claude Code. Reset countdowns tick every second while the popover is open. The caption states the scope, because the labelled sections below say "Claude Code" and made the whole popover read as Claude Code usage.
3. **`CLAUDE CODE ONLY`** — by-model and top-project rows for the active block, parsed from local transcripts, so Claude Code is all they can see. Their percentages are **shares of that activity, not of your limit**; the caption says so, since sitting under a limit meter they'd otherwise read as the same unit. Whole section hidden when the block has no Claude Code activity.
4. **Footer** — Refresh (`⌘R`), last-updated stamp, Quit (`⌘Q`).

**Interactions**

| Trigger | Result |
|---|---|
| `Esc` | Dismiss popover |
| Click outside | Dismiss popover |
| `⌘R` | Force a sync + re-scan |
| `⌘Q` | Quit |

### 10.4 Right-click menu

```
claude.ai sync: live (12s ago)          ← status line, disabled
⚠︎ Session expired — open claude.ai…    ← only when the sessionKey lapsed
Sync now                            ⌘S
─────────────────────────
Refresh transcripts                 ⌘R
─────────────────────────
Quit                                ⌘Q
```

The status line reports `live (Ns ago)`, the last sync error, or `pending…`. Setting the
`cct.debugMenu` user default adds a **Debug — force bucket** group for cycling the mascot through
every health bucket. There is no pause and no Settings window — see the note at the top of the doc.

### 10.5 Settings window — HISTORICAL (never built)

A standalone window (not a sheet on the popover — popover dismisses on focus loss, which makes settings forms maddening). Opens centered, 480 × 360 pt, non-resizable, single tabless pane.

```
╭──────────────────────────────────────────────────╮
│  Settings                                        │
│  ──────────────────────────────────────────────  │
│                                                  │
│   Plan tier        ( • Pro                    )  │
│                    (   Max 5×                  ) │
│                    (   Max 20×                 ) │
│                    (   Custom                  ) │
│                                                  │
│   5-hour cap        [   50.0  ] NCU              │
│   7-day cap         [  350.0  ] NCU              │
│                                                  │
│   Refresh every     ( 5 seconds         ▾   )    │
│                                                  │
│   ☑  Show % label in menu bar                    │
│   ☐  Launch at login                             │
│   ☐  Notify when 5h crosses 80% (v2)             │
│                                                  │
│   ──────────────────────────────────────────     │
│                                                  │
│   Calibration                                    │
│   Hit your cap? Click below to set your caps     │
│   to your current usage levels.                  │
│                                                  │
│   [ Calibrate to current usage ]                 │
│                                                  │
│   ──────────────────────────────────────────     │
│                                                  │
│   About · Reset to defaults             [Done]   │
╰──────────────────────────────────────────────────╯
```

**Behavior**

- 5-hour cap and 7-day cap fields are **read-only when a preset tier is selected**, editable when `Custom`.
- Selecting a preset tier resets the cap fields to that preset's defaults.
- "Calibrate to current usage" sets the tier to `Custom` and fills both caps with the current windowed NCU values, rounded up to the nearest 10. Confirmation alert: *"Set 5h cap to 36.2 → 40 NCU and 7d cap to 143 → 150 NCU?"*
- Settings auto-save on change; no Save button. `Done` just closes the window.
- `Reset to defaults` is a confirmation alert.

### 10.6 First-launch experience — partly historical (no plan tier, no Settings)

No splash screen, no walkthrough wizard. The app belongs in the menu bar — the first launch is the same as any other.

1. App launches, lands in menu bar with the `noData` state (greyscale face, `—` label, tooltip: *"gathering data…"*).
2. Backfill runs in the background (<2s for 7 days of data on a typical machine).
3. As soon as we have any data, face transitions to the appropriate live state.
4. **No Settings prompt by default.** The user can discover Settings via right-click. Default plan tier (`Max 5×`) is wrong for many users — but the "Calibrate" button in Settings makes recovery trivial.

If we ever ship via Mac App Store: a one-time onboarding sheet on first launch with a plan-tier picker. Out of scope for v1 self-distribution.

### 10.7 Empty, error, and edge states

| State | Trigger | Visual |
|---|---|---|
| **No data yet** | First launch, backfill in progress, or no Claude Code transcripts on disk | Greyscale face, `—` label. Popover says *"No usage in the last 7 days. Use Claude Code and this'll fill in."* |
| **Permission denied** | macOS sandbox / TCC blocks reading `~/.claude/projects/` | Face with `?` overlay, `!` label. Popover shows *"Can't read your Claude Code transcripts. Grant Full Disk Access in System Settings → Privacy & Security."* with a button that opens that pane via `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`. |
| **Parse failures** | Malformed JSONL line | Silent. Logged to `~/Library/Logs/ClaudeUsageTracker.log`. Skip the bad line, keep going. |
| **Cap hit** | 5h or 7d ≥ 100% | Skull face, `MAX` label. Popover shows reset countdown prominently. |
| **Window just reset** | 5h sum drops to 0 after being >0 | Evil grin face for 3 seconds, then settle to `healthy`. `0%` label. |
| **Paused** | User selected Pause | Greyscale face, `‖` label. Popover shows "Paused — click Resume in the menu to continue tracking." |

### 10.8 Animation & motion

Minimal. We're a HUD, not an arcade.

| Moment | Treatment |
|---|---|
| Face bucket change | Instant swap. No crossfade. (Doom didn't crossfade either.) |
| % label tick | No animation; just changes. Monospaced digits prevent jitter. |
| Bar fill in popover | Animate width with `withAnimation(.easeOut(duration: 0.2))` on popover open and on data refresh while open. |
| Popover open/close | System default (`NSPopover` spring). |
| Evil grin transient | 3-second hold, then face transitions to `healthy` instantly. |
| Cap hit | One-shot subtle shake of the menu bar icon (`±2 pt` over 0.3s). Once per cap hit, never repeated until window resets. **Respects "Reduce motion" — no shake when that's on.** |

### 10.9 Accessibility

- **VoiceOver** — status item exposes accessibility label like *"Claude usage 73 percent, bloodied"* (bucket name + percent). Popover elements are individually labeled.
- **Reduce Motion** — disables the cap-hit shake and the evil-grin transient (cuts straight to healthy).
- **Increase Contrast** — bar fills switch to higher-contrast colors; face sprites get a 1px outline.
- **Color blindness** — never rely on red alone. Bar style (segment count visibly filled) and face state both convey severity. Label text always present.
- **Keyboard nav** — popover supports `Tab` between bars and footer buttons; `Esc` dismisses.

### 10.10 Dark / Light mode

Both supported via system `NSAppearance`. Face sprites are full color and identical in both modes (Doomguy doesn't change with the OS theme). Backgrounds, dividers, secondary text all use system semantic colors so they adapt automatically. The popover uses `.popover` material which already does the right thing.

### 10.11 Typography & spacing reference

| Token | Value |
|---|---|
| Title (popover header) | SF Pro Text, 14 pt, semibold |
| Section header | SF Pro Text, 11 pt, semibold, uppercase, secondary color |
| Body | SF Pro Text, 13 pt |
| Numbers | SF Mono, 13 pt |
| Menu bar label | SF Pro Text, 12 pt, monospaced digits |
| Padding (popover) | 16 pt |
| Section gap | 16 pt |
| Inline gap | 8 pt |
| Bar height | 8 pt |
| Corner radius | 6 pt (bars), 10 pt (popover) |

### 10.12 Microcopy reference

Centralized so we keep voice consistent. Voice: dry, terse, slightly amused. Never cute, never alarmist.

| Context | Copy |
|---|---|
| App name | `claude-usage-tracker` |
| Popover title | `Claude Usage` — not "Claude Code Usage": the meters are account-wide |
| Section labels | `ALL CLAUDE USAGE`, `CLAUDE CODE ONLY` |
| Scope captions | `Desktop, web, mobile and Claude Code · share of your limit` / `Share of this block's Claude Code activity, not of your limit` |
| Meter labels | `5-hour block`, `Weekly window` |
| Session expired | `claude.ai session expired` · `Usage data is paused until you log in again.` |
| Login button | `Open claude.ai in Chrome` |
| Reset countdown | `resets in 1h 12m` (auto-formatted: seconds → minutes → hours → days) |
| No data | `No usage in the last 7 days. Use Claude Code and this'll fill in.` |
| Permission denied | `Can't read your Claude Code transcripts. Grant Full Disk Access in System Settings.` |
| Permission button | `Open System Settings` |
| Cap hit tooltip | `cap hit · resets in 47m` |
| Healthy tooltip | `you're fine` |
| Bloody tooltip | `getting tight` |
| Critical tooltip | `slow down` |
| Evil grin tooltip | `fresh window — go nuts` |
| About credits | `Face sprites from Freedoom (BSD). Doomguy is in the public domain spirit.` |

We avoid jargon in user-facing copy: no "JSONL", no "FSEvents", no "ring buffer". `NCU` is no longer exposed at all — the breakdown rows show shares as percentages, which resolves the open question v0.3 left here.

## 11. Settings — HISTORICAL (never built)

| Setting | Default | Notes |
|---|---|---|
| Plan tier | Max 5× | Pro / Max 5× / Max 20× / Custom |
| 5h cap (NCU) | per tier | Editable when tier = Custom |
| 7d cap (NCU) | per tier | Editable when tier = Custom |
| Refresh interval | 5s | 1s / 5s / 15s / 60s |
| Show % label | on | Hide for icon-only |
| Launch at login | off | `SMAppService.mainApp.register()` |
| Calibrate to current usage | button | Sets cap = current 5h/7d sum × 1.0 |

Persisted in `UserDefaults` under suite `com.eriklissinger.ClaudeUsageTracker`.

## 12. Persistence

```
~/Library/Application Support/ClaudeUsageTracker/
  ├── offsets.json     # { "/path/to/session.jsonl": 12345, ... }
  └── settings.plist   # mirrors UserDefaults; backup convenience
```

`UsageEntry` ring is **not** persisted in v1 — we recompute from JSONL on launch (cheap, <1s for 7d of data). Persistence comes if startup time becomes a problem.

## 13. Performance budget

| Metric | Target |
|---|---|
| Idle CPU | <1% |
| Idle memory (RSS) | <50 MB |
| Cold start to first menu bar render | <500 ms |
| Refresh latency (file write → face update) | <1 s |
| 7-day backfill on first launch | <2 s |

## 14. Testing strategy

| Layer | Approach |
|---|---|
| `JSONLParser` | Unit tests with golden fixtures of real JSONL lines. Test schema drift (extra keys, missing optional keys, unknown model). |
| `UsageAggregator` | Unit tests for sliding sum correctness around boundaries; clock-skew clamping. |
| `ClaudeUsageSync` | Multi-org resolution: an account with a busy org and an idle one must report the busy one even when `lastActiveOrg` points at the idle one. |
| `HealthModel` | Snapshot test: bucket boundaries at 19.9%, 20%, 20.1%, etc. |
| `OffsetStore` | Round-trip tests; corruption handling (malformed JSON → reset offsets, full re-scan). |
| End-to-end | Manual: send messages in a real Claude Code session, watch face update within 1s. |
| Bucket behavior | Manual: set the `cct.debugMenu` default and force each bucket from the right-click menu. (Replaces the old "set cap to 1 NCU" test — there are no caps.) |
| Cross-check | Sum NCU vs `npx ccusage@latest blocks` output for the same window — should be within 5%. |

## 15. Risks & open questions

| Risk | Mitigation |
|---|---|
| Default cap heuristics are wrong → false sense of safety/panic | "Calibrate" button that records current usage as new cap when user hits the wall. Custom tier always available. |
| Anthropic changes JSONL schema | Defensive parsing; CI fixture set; tracker for `ccusage` updates. |
| FSEvents misses writes (rare but documented) | Backstop poll every 60s as a safety net. |
| Multiple Macs / shared work account | Out of scope for v1. Each Mac shows its own usage. |
| Sprite licensing if we ever ship with original Doom faces | Use Freedoom only (BSD); document attribution in About box. |

**Open questions:**

1. Should the % label use NCU-based percent or Anthropic's own message-count semantics? → NCU is more honest; revisit if it confuses users.
2. Should we expose model breakdown in the menu-bar tooltip, or only in the popover? → Popover only for v1; tooltip is too cramped.
3. How do we handle interactive Plan-mode messages that don't consume cap? → They still appear in the JSONL with `usage`; trust the data.
4. Should the icon be template-rendered (auto monochrome with menu bar tinting) or full color? → **Full color** — we want the blood. Template rendering would defeat the joke.

## 16. Milestones

| ID | Deliverable | Definition of done |
|---|---|---|
| M1 | Static face demo | Xcode project scaffolded; menu bar shows hardcoded face; manual face-bucket switcher in debug menu. |
| M2 | Standalone parser CLI | Swift command-line tool computes 5h/7d NCU from local JSONL; output matches `ccusage` within 5%. |
| M3 | Live aggregation | App reads JSONL on launch + FSEvents updates; face changes in real time as you use Claude Code. |
| M4 | Detail popover | Click icon → SwiftUI popover with both progress bars, reset countdowns, model split. |
| M5 | Settings + persistence | Plan picker, custom caps, launch-at-login, offset persistence across relaunches. |
| M6 | Notarized release | Codesigned, notarized `.dmg` distributable; clean Gatekeeper launch on a fresh user account. |

## 17. Out of scope (future work parking lot)

- Animated faces (idle blink, "ouch" reactions, evil grin idle)
- Optional Doom sound effects on threshold crossings
- Notification when crossing 80% / 95%
- Historical usage chart (last 30 days)
- Multi-machine sync via iCloud
- Web `claude.ai` support if Anthropic ever exposes a usage endpoint
- Linux / Windows ports (`tauri` rewrite if ever)

## 18. References

- [ccusage](https://github.com/ryoppippi/ccusage) — canonical local parser; reference for NCU semantics
- [Freedoom](https://freedoom.github.io/) — BSD-licensed Doom face sprites
- Apple [`SMAppService`](https://developer.apple.com/documentation/servicemanagement/smappservice) for login-item registration
- Apple [`NSStatusItem`](https://developer.apple.com/documentation/appkit/nsstatusitem) menu bar integration
- Apple [FSEvents Programming Guide](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/FSEvents_ProgGuide/)
