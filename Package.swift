// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "ClaudeUsageTracker",
    platforms: [
        .macOS(.v13),
    ],
    targets: [
        .target(
            name: "ClaudeUsageTrackerCore",
            path: "Sources/ClaudeUsageTrackerCore"
        ),
        .executableTarget(
            name: "ClaudeUsageTracker",
            dependencies: ["ClaudeUsageTrackerCore"],
            path: "Sources/ClaudeUsageTracker"
        ),
        .executableTarget(
            name: "cct-parse",
            dependencies: ["ClaudeUsageTrackerCore"],
            path: "Sources/cct-parse"
        ),
        .executableTarget(
            name: "cct-icon-gen",
            dependencies: ["ClaudeUsageTrackerCore"],
            path: "Sources/cct-icon-gen"
        ),
    ]
)
