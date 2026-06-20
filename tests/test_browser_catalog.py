"""Tests for Chromium-family browser catalog and profile resolution."""

from pathlib import Path

import pytest

from claude_usage_tracker.browser.catalog import browser_catalog
from claude_usage_tracker.browser.profiles import (
    ProfileResolutionError,
    resolve_profile,
)

FIXTURES = Path("tests/fixtures/browser_catalog")
CONFIGS = Path("tests/fixtures/configs")


def write_config(
    tmp_path: Path,
    *,
    browser_mode: str = "auto",
    profile_override: str | None = None,
) -> Path:
    lines = [f'browser_mode = "{browser_mode}"']
    if profile_override is not None:
        lines.append(f'profile_override = "{profile_override}"')
    lines.extend(
        [
            "refresh_interval_seconds = 60",
            "",
            "[tooltip]",
            "show_block = true",
            "show_week = true",
            "show_model_breakdown = true",
            "show_project_breakdown = true",
            "show_reset_times = true",
            "",
            "[notifications]",
            "enabled = true",
            "block_thresholds = [50, 75, 90]",
            "week_thresholds = [50, 75, 90]",
            "",
            "[settings_window]",
            "open_on_click = true",
            "remember_position = true",
            "remember_size = true",
            "stay_on_top = false",
            "",
        ]
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def test_browser_catalog_lists_supported_linux_chromium_family_in_order():
    catalog = browser_catalog()

    assert [browser.browser_id for browser in catalog] == [
        "chrome",
        "chromium",
        "brave",
        "edge",
        "vivaldi",
        "opera",
    ]
    assert [browser.user_data_dir.name for browser in catalog] == [
        "google-chrome",
        "chromium",
        "BraveSoftware/Brave-Browser".split("/")[-1],
        "microsoft-edge",
        "vivaldi",
        "opera",
    ]


def test_auto_mode_resolves_first_supported_profile_from_fixture():
    resolved = resolve_profile(
        FIXTURES / "brave_default",
        CONFIGS / "browser-auto.toml",
    )

    assert resolved.browser_id == "brave"
    assert resolved.profile_name == "Default"
    assert resolved.user_data_dir == (
        FIXTURES / "brave_default" / "BraveSoftware" / "Brave-Browser"
    )
    assert resolved.cookies_db_path == (
        FIXTURES
        / "brave_default"
        / "BraveSoftware"
        / "Brave-Browser"
        / "Default"
        / "Cookies.sqlite.json"
    )


def test_explicit_browser_override_limits_resolution_to_requested_browser(tmp_path: Path):
    config_path = write_config(tmp_path, browser_mode="chrome")

    with pytest.raises(
        ProfileResolutionError,
        match=(
            "browser_mode='chrome' requested but no viable cookies database was found "
            "in supported profile paths"
        ),
    ):
        resolve_profile(FIXTURES / "brave_default", config_path)


def test_explicit_profile_override_uses_requested_profile(tmp_path: Path):
    config_path = write_config(tmp_path, profile_override="Default")

    resolved = resolve_profile(FIXTURES / "chrome_default", config_path)

    assert resolved.browser_id == "chrome"
    assert resolved.profile_name == "Default"


def test_unsupported_layout_reports_clear_error():
    with pytest.raises(
        ProfileResolutionError,
        match="no supported browser profile contains a Cookies database",
    ):
        resolve_profile(
            FIXTURES / "missing_cookies",
            CONFIGS / "browser-auto.toml",
        )
