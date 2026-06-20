"""Live claude.ai usage sync client and typed authority semantics."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

import httpx

from claude_usage_tracker.browser.cookies import read_domain_cookies
from claude_usage_tracker.browser.profiles import ResolvedProfile
from claude_usage_tracker.domain.models import parse_timestamp


class SyncError(RuntimeError):
    """Base class for live sync failures."""


class MissingSessionCookieError(SyncError):
    """Raised when the browser cookie jar lacks a Claude session."""

    def __init__(self) -> None:
        super().__init__("session cookie missing for claude.ai")


class MissingOrgCookieError(SyncError):
    """Raised when the browser cookie jar lacks a last active organization."""

    def __init__(self) -> None:
        super().__init__("organization cookie missing for claude.ai")


class SyncHTTPStatusError(SyncError):
    """Raised when the live usage endpoint returns a non-success HTTP status."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"claude.ai usage request failed with HTTP {status_code}")


class SyncParseError(SyncError):
    """Raised when a sync payload cannot be parsed into typed usage windows."""


class SyncAuthority(str, Enum):
    """Whether a synced payload is authoritative for display and alerts."""

    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SyncedUsage:
    """Typed live usage snapshot from claude.ai."""

    percent5h: int
    percent7d: int
    reset5h_at: datetime | None
    reset7d_at: datetime | None
    synced_at: datetime
    authority: SyncAuthority

    @property
    def is_fresh(self) -> bool:
        return self.authority is SyncAuthority.FRESH

    @property
    def has_authoritative_percentages(self) -> bool:
        return self.is_fresh

    @property
    def notifications_allowed(self) -> bool:
        return self.is_fresh

    @property
    def authoritative_percent5h(self) -> int | None:
        return self.percent5h if self.has_authoritative_percentages else None

    @property
    def authoritative_percent7d(self) -> int | None:
        return self.percent7d if self.has_authoritative_percentages else None


class SyncHTTPClient(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> "SyncHTTPResponse": ...


class SyncHTTPResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


def fetch_live_usage(
    profile: ResolvedProfile,
    *,
    client: SyncHTTPClient | None = None,
    timeout: float = 10.0,
    now: datetime | None = None,
) -> SyncedUsage:
    """Fetch live usage for the browser session resolved by Task 6's cookie adapter."""

    cookies = read_domain_cookies(profile, domain="claude.ai")
    session_key = cookies.get("sessionKey")
    if not session_key:
        raise MissingSessionCookieError()

    org_id = cookies.get("lastActiveOrg")
    if not org_id:
        raise MissingOrgCookieError()

    url = f"https://claude.ai/api/organizations/{org_id}/usage"
    headers = {
        "Accept": "application/json",
        "Referer": "https://claude.ai/settings/usage",
        "Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items()),
    }
    synced_at = parse_timestamp(now) if now is not None else datetime.now(UTC)

    response = _get_sync_response(url, headers=headers, timeout=timeout, client=client)

    if not 200 <= response.status_code < 300:
        raise SyncHTTPStatusError(response.status_code)

    try:
        payload = response.json()
    except Exception as exc:  # pragma: no cover - concrete client error type varies
        raise SyncParseError(f"invalid JSON payload: {exc}") from exc

    return parse_sync_payload(payload, synced_at=synced_at)


def _get_sync_response(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    client: SyncHTTPClient | None,
) -> SyncHTTPResponse:
    if client is None:
        with httpx.Client(follow_redirects=True) as default_client:
            return default_client.get(url, headers=headers, timeout=timeout)
    return client.get(url, headers=headers, timeout=timeout)


def parse_sync_fixture(path: str | Path, *, now: datetime | None = None) -> SyncedUsage:
    """Parse a repository sync fixture into the typed synced-usage model."""

    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    synced_at = parse_timestamp(now) if now is not None else datetime.now(UTC)
    return parse_sync_payload(payload, synced_at=synced_at)


def parse_sync_payload(payload: object, *, synced_at: datetime) -> SyncedUsage:
    """Parse either the real endpoint envelope or the repo's shorthand fixture shape."""

    if not isinstance(payload, dict):
        raise SyncParseError("sync payload must be a JSON object")

    five_hour = payload.get("five_hour")
    seven_day = payload.get("seven_day")
    if isinstance(five_hour, dict) or isinstance(seven_day, dict):
        percent5h = _parse_window_percent(five_hour, "five_hour")
        percent7d = _parse_window_percent(seven_day, "seven_day")
        reset5h_at = _parse_window_reset(five_hour, "five_hour")
        reset7d_at = _parse_window_reset(seven_day, "seven_day")
        authority = SyncAuthority.FRESH
    else:
        percent5h = _require_int(payload.get("percent5h", 0), "percent5h")
        percent7d = _require_int(payload.get("percent7d", 0), "percent7d")
        reset5h_at = _parse_optional_timestamp(payload.get("reset5hAt"), "reset5hAt")
        reset7d_at = _parse_optional_timestamp(payload.get("reset7dAt"), "reset7dAt")
        authority = _authority_from_fixture(payload)

    return SyncedUsage(
        percent5h=percent5h,
        percent7d=percent7d,
        reset5h_at=reset5h_at,
        reset7d_at=reset7d_at,
        synced_at=parse_timestamp(synced_at),
        authority=authority,
    )


def _authority_from_fixture(payload: dict[str, object]) -> SyncAuthority:
    is_fresh = payload.get("isFresh", True)
    if not isinstance(is_fresh, bool):
        raise SyncParseError("isFresh must be a boolean when provided")
    return SyncAuthority.FRESH if is_fresh else SyncAuthority.STALE


def _parse_window_percent(window: object, field_name: str) -> int:
    if window is None:
        return 0
    if not isinstance(window, dict):
        raise SyncParseError(f"{field_name} must be an object when provided")
    utilization = window.get("utilization")
    if utilization is None:
        return 0
    if isinstance(utilization, bool) or not isinstance(utilization, int | float):
        raise SyncParseError(f"{field_name}.utilization must be numeric when provided")
    return int(math.floor(float(utilization) + 0.5))


def _parse_window_reset(window: object, field_name: str) -> datetime | None:
    if window is None:
        return None
    if not isinstance(window, dict):
        raise SyncParseError(f"{field_name} must be an object when provided")
    return _parse_optional_timestamp(window.get("resets_at"), f"{field_name}.resets_at")


def _parse_optional_timestamp(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SyncParseError(f"{field_name} must be an ISO-8601 string when provided")
    try:
        return parse_timestamp(value)
    except ValueError as exc:
        raise SyncParseError(f"{field_name} must be an ISO-8601 timestamp") from exc


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyncParseError(f"{field_name} must be an integer")
    return value
