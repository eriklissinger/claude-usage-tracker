"""Data-driven catalog for supported Chromium-family browsers on Linux."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BrowserDefinition:
    """Static browser metadata used for profile resolution."""

    browser_id: str
    user_data_dir: Path
    profile_names: tuple[str, ...] = ("Default",)
    cookie_db_filenames: tuple[str, ...] = ("Cookies", "Cookies.sqlite.json")
    local_state_filename: str = "Local State"

    def local_state_path(self, root: Path) -> Path:
        return root / self.user_data_dir / self.local_state_filename

    def profile_path(self, root: Path, profile_name: str) -> Path:
        return root / self.user_data_dir / profile_name


_BROWSER_CATALOG: tuple[BrowserDefinition, ...] = (
    BrowserDefinition(browser_id="chrome", user_data_dir=Path("google-chrome")),
    BrowserDefinition(browser_id="chromium", user_data_dir=Path("chromium")),
    BrowserDefinition(
        browser_id="brave",
        user_data_dir=Path("BraveSoftware") / "Brave-Browser",
    ),
    BrowserDefinition(browser_id="edge", user_data_dir=Path("microsoft-edge")),
    BrowserDefinition(browser_id="vivaldi", user_data_dir=Path("vivaldi")),
    BrowserDefinition(browser_id="opera", user_data_dir=Path("opera")),
)


def browser_catalog() -> tuple[BrowserDefinition, ...]:
    """Return supported Chromium-family browsers in deterministic order."""

    return _BROWSER_CATALOG


def browser_definition(browser_id: str) -> BrowserDefinition:
    """Return the catalog entry for a supported browser id."""

    for browser in _BROWSER_CATALOG:
        if browser.browser_id == browser_id:
            return browser
    raise KeyError(browser_id)
