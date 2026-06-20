"""Config schema and XDG path helpers."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import PlatformDirs

APP_NAME = "claude-usage-tracker"
ALLOWED_BROWSER_MODES = {
    "auto",
    "chrome",
    "chromium",
    "brave",
    "edge",
    "vivaldi",
    "opera",
}


@dataclass(frozen=True, slots=True)
class TooltipConfig:
    """Tooltip visibility toggles."""

    show_block: bool = True
    show_week: bool = True
    show_model_breakdown: bool = True
    show_project_breakdown: bool = True
    show_reset_times: bool = True


@dataclass(frozen=True, slots=True)
class NotificationsConfig:
    """Notification threshold settings."""

    enabled: bool = True
    block_thresholds: list[int] = field(default_factory=lambda: [50, 75, 90])
    week_thresholds: list[int] = field(default_factory=lambda: [50, 75, 90])


@dataclass(frozen=True, slots=True)
class SettingsWindowConfig:
    """Settings-window behavior defaults."""

    open_on_click: bool = True
    remember_position: bool = True
    remember_size: bool = True
    stay_on_top: bool = False


@dataclass(frozen=True, slots=True)
class Config:
    """Application config."""

    browser_mode: str = "auto"
    profile_override: str | None = None
    refresh_interval_seconds: int = 60
    tooltip: TooltipConfig = field(default_factory=TooltipConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    settings_window: SettingsWindowConfig = field(default_factory=SettingsWindowConfig)


def config_path() -> Path:
    """Return the XDG config path for the app-owned TOML file."""
    return Path(PlatformDirs(appname=APP_NAME, appauthor=False).user_config_dir) / "config.toml"


def load_config(path: str | Path | None = None) -> Config:
    """Load config from TOML, defaulting to built-in values when absent."""
    config_file = Path(path) if path is not None else config_path()
    if not config_file.exists():
        if path is None:
            return Config()
        raise FileNotFoundError(config_file)

    with config_file.open("rb") as handle:
        data = tomllib.load(handle)

    return _config_from_dict(data)


def save_config(config: Config, path: str | Path | None = None) -> Path:
    """Write config to TOML in the app's canonical field order."""
    config_file = Path(path) if path is not None else config_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(_dump_toml(_config_to_dict(config)), encoding="utf-8")
    return config_file


def _config_from_dict(data: dict[str, Any]) -> Config:
    _reject_unknown_keys(
        data,
        {
            "browser_mode",
            "profile_override",
            "refresh_interval_seconds",
            "tooltip",
            "notifications",
            "settings_window",
        },
        "config",
    )

    browser_mode = data.get("browser_mode", "auto")
    if not isinstance(browser_mode, str) or browser_mode not in ALLOWED_BROWSER_MODES:
        raise ValueError(f"browser_mode must be one of {sorted(ALLOWED_BROWSER_MODES)}")

    profile_override = data.get("profile_override")
    if profile_override is not None and not isinstance(profile_override, str):
        raise ValueError("profile_override must be a string when provided")

    refresh_interval_seconds = data.get("refresh_interval_seconds", 60)
    if not isinstance(refresh_interval_seconds, int) or refresh_interval_seconds <= 0:
        raise ValueError("refresh_interval_seconds must be a positive integer")

    tooltip_data = _section_dict(data, "tooltip")
    _reject_unknown_keys(
        tooltip_data,
        {
            "show_block",
            "show_week",
            "show_model_breakdown",
            "show_project_breakdown",
            "show_reset_times",
        },
        "tooltip",
    )

    notifications_data = _section_dict(data, "notifications")
    _reject_unknown_keys(
        notifications_data,
        {"enabled", "block_thresholds", "week_thresholds"},
        "notifications",
    )

    settings_data = _section_dict(data, "settings_window")
    _reject_unknown_keys(
        settings_data,
        {"open_on_click", "remember_position", "remember_size", "stay_on_top"},
        "settings_window",
    )

    tooltip = TooltipConfig(
        show_block=_require_bool(tooltip_data.get("show_block", True), "tooltip.show_block"),
        show_week=_require_bool(tooltip_data.get("show_week", True), "tooltip.show_week"),
        show_model_breakdown=_require_bool(
            tooltip_data.get("show_model_breakdown", True),
            "tooltip.show_model_breakdown",
        ),
        show_project_breakdown=_require_bool(
            tooltip_data.get("show_project_breakdown", True),
            "tooltip.show_project_breakdown",
        ),
        show_reset_times=_require_bool(
            tooltip_data.get("show_reset_times", True),
            "tooltip.show_reset_times",
        ),
    )
    notifications = NotificationsConfig(
        enabled=_require_bool(notifications_data.get("enabled", True), "notifications.enabled"),
        block_thresholds=_validate_thresholds(
            notifications_data.get("block_thresholds", [50, 75, 90]),
            "notifications.block_thresholds",
        ),
        week_thresholds=_validate_thresholds(
            notifications_data.get("week_thresholds", [50, 75, 90]),
            "notifications.week_thresholds",
        ),
    )
    settings_window = SettingsWindowConfig(
        open_on_click=_require_bool(
            settings_data.get("open_on_click", True),
            "settings_window.open_on_click",
        ),
        remember_position=_require_bool(
            settings_data.get("remember_position", True),
            "settings_window.remember_position",
        ),
        remember_size=_require_bool(
            settings_data.get("remember_size", True),
            "settings_window.remember_size",
        ),
        stay_on_top=_require_bool(
            settings_data.get("stay_on_top", False),
            "settings_window.stay_on_top",
        ),
    )

    return Config(
        browser_mode=browser_mode,
        profile_override=profile_override,
        refresh_interval_seconds=refresh_interval_seconds,
        tooltip=tooltip,
        notifications=notifications,
        settings_window=settings_window,
    )


def _config_to_dict(config: Config) -> dict[str, Any]:
    data: dict[str, Any] = {"browser_mode": config.browser_mode}
    if config.profile_override is not None:
        data["profile_override"] = config.profile_override
    data["refresh_interval_seconds"] = config.refresh_interval_seconds
    data["tooltip"] = asdict(config.tooltip)
    data["notifications"] = asdict(config.notifications)
    data["settings_window"] = asdict(config.settings_window)
    return data


def _section_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    section = data.get(key, {})
    if not isinstance(section, dict):
        raise ValueError(f"{key} must be a table")
    return section


def _reject_unknown_keys(data: dict[str, Any], allowed: set[str], section: str) -> None:
    unexpected = sorted(set(data) - allowed)
    if unexpected:
        raise ValueError(f"Unexpected {section} keys: {unexpected}")


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _validate_thresholds(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} threshold list must be a non-empty list")
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise ValueError(f"{field_name} thresholds must be integers")
    if any(item < 0 or item > 100 for item in value):
        raise ValueError(f"{field_name} thresholds must be between 0 and 100")
    if sorted(value) != value or len(set(value)) != len(value):
        raise ValueError(f"{field_name} thresholds must be unique and sorted")
    return list(value)


def _dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    scalar_items = [(key, value) for key, value in data.items() if not isinstance(value, dict)]
    table_items = [(key, value) for key, value in data.items() if isinstance(value, dict)]

    for key, value in scalar_items:
        lines.append(f"{key} = {_format_toml_value(value)}")

    for key, value in table_items:
        if lines:
            lines.append("")
        lines.append(f"[{key}]")
        for nested_key, nested_value in value.items():
            lines.append(f"{nested_key} = {_format_toml_value(nested_value)}")

    return "\n".join(lines) + "\n"


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")
