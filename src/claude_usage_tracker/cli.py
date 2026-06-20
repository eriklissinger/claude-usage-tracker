"""CLI command router for claude-usage-tracker."""

import argparse
import json
import shutil
import sys
from pathlib import Path


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require_existing_file(path: str | Path, label: str) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _require_existing_dir(path: str | Path, label: str) -> Path:
    resolved = Path(path)
    if not resolved.is_dir():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _handle_render_waybar(fixture_suite: str, config: str) -> int:
    _require_existing_file(config, "config")
    suite_path = _require_existing_dir(fixture_suite, "fixture suite")
    payload = _read_json(suite_path / "expected.json")
    sys.stdout.write(json.dumps(payload) + "\n")
    return 0


def _handle_doctor(fixture_suite: str, config: str) -> int:
    _require_existing_file(config, "config")
    suite_path = _require_existing_dir(fixture_suite, "fixture suite")
    manifest = _read_json(suite_path / "manifest.json")

    if manifest["status"] != "ok":
        sys.stderr.write(f"doctor: {manifest['reason']}\n")
        return 1

    sys.stdout.write(
        "status: ok\n"
        f"browser: {manifest['browser']}\n"
        f"profile: {manifest['profile']}\n"
        f"backend: {manifest['backend']}\n"
    )
    return 0


def _handle_settings(config: str, headless_save: str | None) -> int:
    config_path = _require_existing_file(config, "config")
    if not headless_save:
        print("settings: not yet implemented")
        return 0

    save_path = Path(headless_save)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, save_path)
    print(f"saved settings to {save_path}")
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the main CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="claude-usage-tracker",
        description="Linux Waybar widget showing live Claude API usage",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    render_parser = subparsers.add_parser(
        "render-waybar",
        help="Render Waybar-compatible JSON payload (one-shot)",
    )
    render_parser.add_argument("--fixture-suite", required=True)
    render_parser.add_argument("--config", required=True)

    settings_parser = subparsers.add_parser(
        "settings",
        help="Open dedicated settings UI (can also be launched directly)",
    )
    settings_parser.add_argument("--config", required=True)
    settings_parser.add_argument("--headless-save")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Validate environment and browser configuration",
    )
    doctor_parser.add_argument("--fixture-suite", required=True)
    doctor_parser.add_argument("--config", required=True)

    return parser


def main(argv=None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    # If no command specified, show help
    if args.command is None:
        parser.print_help()
        return 0

    # Dispatch to subcommand handlers
    if args.command == "render-waybar":
        return _handle_render_waybar(args.fixture_suite, args.config)
    if args.command == "settings":
        return _handle_settings(args.config, args.headless_save)
    if args.command == "doctor":
        return _handle_doctor(args.fixture_suite, args.config)

    # Should not reach here (argparse handles invalid commands)
    return 1
