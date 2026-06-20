"""Resolve supported Chromium-family browser profiles from fixed Linux paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_usage_tracker.browser.catalog import BrowserDefinition, browser_catalog
from claude_usage_tracker.config import Config, load_config


class ProfileResolutionError(RuntimeError):
    """Raised when no supported browser profile can be resolved."""


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    """Resolved browser profile with the files needed for later cookie work."""

    browser_id: str
    profile_name: str
    user_data_dir: Path
    profile_dir: Path
    cookies_db_path: Path
    local_state_path: Path


def resolve_profile(
    browser_root: str | Path,
    config_path: str | Path | None = None,
) -> ResolvedProfile:
    """Resolve a supported browser/profile from deterministic Linux catalog data."""

    root = Path(browser_root)
    config = load_config(config_path)
    browsers = _candidate_browsers(config)

    for browser in browsers:
        resolved = _resolve_browser(root, browser, config.profile_override)
        if resolved is not None:
            return resolved

    raise ProfileResolutionError(_failure_message(config))


def _candidate_browsers(config: Config) -> tuple[BrowserDefinition, ...]:
    if config.browser_mode == "auto":
        return browser_catalog()
    return tuple(
        browser for browser in browser_catalog() if browser.browser_id == config.browser_mode
    )


def _resolve_browser(
    root: Path,
    browser: BrowserDefinition,
    profile_override: str | None,
) -> ResolvedProfile | None:
    user_data_dir = root / browser.user_data_dir
    local_state_path = browser.local_state_path(root)
    if not user_data_dir.is_dir() or not local_state_path.is_file():
        return None

    profile_names = (profile_override,) if profile_override is not None else browser.profile_names
    for profile_name in profile_names:
        profile_dir = browser.profile_path(root, profile_name)
        for cookie_filename in browser.cookie_db_filenames:
            cookies_db_path = profile_dir / cookie_filename
            if cookies_db_path.is_file():
                return ResolvedProfile(
                    browser_id=browser.browser_id,
                    profile_name=profile_name,
                    user_data_dir=user_data_dir,
                    profile_dir=profile_dir,
                    cookies_db_path=cookies_db_path,
                    local_state_path=local_state_path,
                )
    return None


def _failure_message(config: Config) -> str:
    if config.browser_mode != "auto":
        return (
            f"browser_mode='{config.browser_mode}' requested but no viable cookies "
            "database was found in supported profile paths"
        )
    return "no supported browser profile contains a Cookies database"
