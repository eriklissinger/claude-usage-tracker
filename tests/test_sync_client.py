"""Tests for the live Claude usage sync client and authority model."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

sync = importlib.import_module("claude_usage_tracker.sync")
ResolvedProfile = importlib.import_module(
    "claude_usage_tracker.browser.profiles"
).ResolvedProfile
UnsupportedCookieBackendError = importlib.import_module(
    "claude_usage_tracker.browser.secret_service"
).UnsupportedCookieBackendError

FIXTURES = Path("tests/fixtures/sync")


class FakeResponse:
    def __init__(self, *, status_code: int, payload: dict[str, object], text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, object]:
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.response


def make_profile(tmp_path: Path):
    profile_dir = tmp_path / "browser" / "Default"
    profile_dir.mkdir(parents=True)
    cookies_db_path = profile_dir / "Cookies.sqlite.json"
    cookies_db_path.write_text("{}", encoding="utf-8")
    local_state_path = profile_dir.parent / "Local State"
    local_state_path.write_text("{}", encoding="utf-8")
    return ResolvedProfile(
        browser_id="chrome",
        profile_name="Default",
        user_data_dir=profile_dir.parent,
        profile_dir=profile_dir,
        cookies_db_path=cookies_db_path,
        local_state_path=local_state_path,
    )


def test_parse_sync_fixture_marks_fresh_sync_as_authoritative() -> None:
    synced = sync.parse_sync_fixture(FIXTURES / "live_ok" / "usage.json")

    assert synced.percent5h == 42
    assert synced.percent7d == 61
    assert synced.reset5h_at == datetime(2026, 5, 3, 17, 0, tzinfo=UTC)
    assert synced.reset7d_at == datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    assert synced.authority is sync.SyncAuthority.FRESH
    assert synced.has_authoritative_percentages is True
    assert synced.notifications_allowed is True
    assert synced.authoritative_percent5h == 42
    assert synced.authoritative_percent7d == 61


def test_parse_sync_fixture_marks_stale_sync_as_non_authoritative() -> None:
    synced = sync.parse_sync_fixture(FIXTURES / "stale_live" / "usage.json")

    assert synced.percent5h == 42
    assert synced.percent7d == 61
    assert synced.authority is sync.SyncAuthority.STALE
    assert synced.has_authoritative_percentages is False
    assert synced.notifications_allowed is False
    assert synced.authoritative_percent5h is None
    assert synced.authoritative_percent7d is None


def test_fetch_live_usage_replays_browser_cookies_and_parses_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = make_profile(tmp_path)
    client = FakeClient(
        FakeResponse(
            status_code=200,
            payload={
                "five_hour": {"utilization": 41.6, "resets_at": "2026-05-03T17:00:00Z"},
                "seven_day": {"utilization": 60.6, "resets_at": "2026-05-09T00:00:00Z"},
            },
        )
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(
        sync,
        "read_domain_cookies",
        lambda resolved, *, domain="claude.ai": {
            "sessionKey": "session-abc",
            "lastActiveOrg": "org-123",
            "cf_clearance": "clearance-xyz",
        },
    )

    synced = sync.fetch_live_usage(profile, client=client, now=now)

    assert synced.percent5h == 42
    assert synced.percent7d == 61
    assert synced.synced_at == now
    assert synced.authority is sync.SyncAuthority.FRESH
    assert client.calls == [
        {
            "url": "https://claude.ai/api/organizations/org-123/usage",
            "headers": {
                "Accept": "application/json",
                "Referer": "https://claude.ai/settings/usage",
                "Cookie": (
                    "sessionKey=session-abc; lastActiveOrg=org-123; "
                    "cf_clearance=clearance-xyz"
                ),
            },
            "timeout": 10.0,
        }
    ]


def test_fetch_live_usage_requires_session_cookie(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = make_profile(tmp_path)

    monkeypatch.setattr(
        sync,
        "read_domain_cookies",
        lambda resolved, *, domain="claude.ai": {"lastActiveOrg": "org-123"},
    )

    with pytest.raises(sync.MissingSessionCookieError) as excinfo:
        sync.fetch_live_usage(profile, client=FakeClient(FakeResponse(status_code=200, payload={})))

    assert "session cookie missing" in str(excinfo.value)


def test_fetch_live_usage_requires_org_cookie(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = make_profile(tmp_path)

    monkeypatch.setattr(
        sync,
        "read_domain_cookies",
        lambda resolved, *, domain="claude.ai": {"sessionKey": "session-abc"},
    )

    with pytest.raises(sync.MissingOrgCookieError) as excinfo:
        sync.fetch_live_usage(profile, client=FakeClient(FakeResponse(status_code=200, payload={})))

    assert "organization cookie missing" in str(excinfo.value)


def test_fetch_live_usage_propagates_unsupported_cookie_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = make_profile(tmp_path)

    def raise_backend_error(resolved, *, domain="claude.ai"):
        raise UnsupportedCookieBackendError("kwallet5")

    monkeypatch.setattr(sync, "read_domain_cookies", raise_backend_error)

    with pytest.raises(UnsupportedCookieBackendError) as excinfo:
        sync.fetch_live_usage(profile, client=FakeClient(FakeResponse(status_code=200, payload={})))

    assert excinfo.value.backend == "kwallet5"


def test_fetch_live_usage_omits_response_body_from_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = make_profile(tmp_path)
    client = FakeClient(
        FakeResponse(
            status_code=403,
            payload={},
            text="blocked for sessionKey=session-abc org-123",
        )
    )

    monkeypatch.setattr(
        sync,
        "read_domain_cookies",
        lambda resolved, *, domain="claude.ai": {
            "sessionKey": "session-abc",
            "lastActiveOrg": "org-123",
        },
    )

    with pytest.raises(sync.SyncHTTPStatusError) as excinfo:
        sync.fetch_live_usage(profile, client=client)

    assert excinfo.value.status_code == 403
    assert "403" in str(excinfo.value)
    assert "session-abc" not in str(excinfo.value)
    assert "org-123" not in str(excinfo.value)
