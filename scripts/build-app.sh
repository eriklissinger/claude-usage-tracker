#!/usr/bin/env bash
# Builds ClaudeUsageTracker as a proper .app bundle so macOS treats it as a
# menu bar application (LSUIElement). Without this, the NSStatusItem may not
# appear on recent macOS versions.

set -euo pipefail

CONFIG="${1:-debug}"   # debug | release
APP_NAME="ClaudeUsageTracker"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/build/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS}/MacOS"
RESOURCES_DIR="${CONTENTS}/Resources"

cd "${ROOT_DIR}"

# Two pins, both needed on a Command Line Tools install without Xcode:
#
#  * --build-system native. SwiftPM 6.4 defaults to the "swiftbuild" (XCBuild)
#    engine, which fails to start under CLT-only with "Could not initialize
#    build system: Unknown error parsing property list" — on any package, not
#    just this one. The native engine is deprecated but works.
#  * SDKROOT pinned to the macOS 26 SDK. In the macOS 27 SDK, SwiftUI's @State
#    became a macro whose SwiftUIMacros plugin ships only with Xcode, so
#    PopoverView fails to compile against it. We deploy to macOS 13 anyway.
#
# Drop both if Xcode gets installed.
SDKROOT="${SDKROOT:-$(ls -d /Library/Developer/CommandLineTools/SDKs/MacOSX26*.sdk 2>/dev/null | sort -V | tail -1)}"
export SDKROOT

echo "==> swift build (${CONFIG}) — SDK ${SDKROOT:-default}"
swift build -c "${CONFIG}" --build-system native

BIN_PATH=".build/${CONFIG}/${APP_NAME}"
if [[ ! -f "${BIN_PATH}" ]]; then
    echo "error: built binary not found at ${BIN_PATH}" >&2
    exit 1
fi

echo "==> assembling ${APP_DIR}"
rm -rf "${APP_DIR}"
mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}"
cp "${BIN_PATH}" "${MACOS_DIR}/${APP_NAME}"

# App icon is generated from MascotRenderer so it always matches the menu bar
# mascot (healthy / 0% used).
echo "==> generating AppIcon.icns from mascot"
".build/${CONFIG}/cct-icon-gen" "${RESOURCES_DIR}/AppIcon.icns"

cat > "${CONTENTS}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.eriklissinger.ClaudeUsageTracker</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>Claude Usage Tracker</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
PLIST

# Ad-hoc codesign so Gatekeeper / TCC treat it as a stable identity. Strip
# extended attributes first — copying from an iCloud-backed checkout leaves
# Finder metadata behind, which codesign rejects as "detritus".
echo "==> ad-hoc codesigning"
xattr -cr "${APP_DIR}"
codesign --force --sign - --timestamp=none "${APP_DIR}" >/dev/null

echo "==> done: ${APP_DIR}"
echo "    run with: open '${APP_DIR}'"
