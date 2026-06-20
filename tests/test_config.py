"""Tests for config schema and XDG path handling."""

from pathlib import Path

import pytest

from claude_usage_tracker.config import (
    Config,
    config_path,
    load_config,
    save_config,
)

FIXTURE_PATH = Path("tests/fixtures/configs/default.toml")


def test_config_path_uses_xdg_defaults(monkeypatch, tmp_path):
    """Config path should resolve to the XDG config location."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert config_path() == home / ".config/claude-usage-tracker/config.toml"


def test_load_config_from_default_fixture():
    """Default fixture should load into the expected schema."""
    config = load_config(FIXTURE_PATH)

    assert config == Config()
    assert config.browser_mode == "auto"
    assert config.profile_override is None
    assert config.refresh_interval_seconds == 60
    assert config.notifications.block_thresholds == [50, 75, 90]
    assert config.notifications.week_thresholds == [50, 75, 90]


def test_load_config_accepts_explicit_browser_id(tmp_path):
    """Known explicit browser ids should be accepted."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '\n'.join(
            [
                'browser_mode = "brave"',
                'profile_override = "Profile 1"',
                'refresh_interval_seconds = 120',
                '',
                '[tooltip]',
                'show_block = true',
                'show_week = true',
                'show_model_breakdown = false',
                'show_project_breakdown = true',
                'show_reset_times = true',
                '',
                '[notifications]',
                'enabled = false',
                'block_thresholds = [25, 50, 75]',
                'week_thresholds = [10, 20, 30]',
                '',
                '[settings_window]',
                'open_on_click = true',
                'remember_position = true',
                'remember_size = false',
                'stay_on_top = false',
                '',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.browser_mode == "brave"
    assert config.profile_override == "Profile 1"
    assert config.refresh_interval_seconds == 120


def test_round_trip_default_config(tmp_path):
    """Saving the default config should produce canonical TOML."""
    config = load_config(FIXTURE_PATH)
    output_path = tmp_path / "config.toml"

    save_config(config, output_path)

    assert output_path.read_text(encoding="utf-8") == FIXTURE_PATH.read_text(encoding="utf-8")


def test_rejects_invalid_thresholds(tmp_path):
    """Thresholds outside the 0-100 range should be rejected."""
    config_file = tmp_path / "invalid.toml"
    config_file.write_text(
        '\n'.join(
            [
                'browser_mode = "auto"',
                'refresh_interval_seconds = 60',
                '',
                '[tooltip]',
                'show_block = true',
                'show_week = true',
                'show_model_breakdown = true',
                'show_project_breakdown = true',
                'show_reset_times = true',
                '',
                '[notifications]',
                'enabled = true',
                'block_thresholds = [50, 101]',
                'week_thresholds = [50, 75, 90]',
                '',
                '[settings_window]',
                'open_on_click = true',
                'remember_position = true',
                'remember_size = true',
                'stay_on_top = false',
                '',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="threshold"):
        load_config(config_file)
