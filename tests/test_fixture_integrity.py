"""Integrity checks for Task 3 fixture suites."""

import shutil
from pathlib import Path

import pytest

from tests.fixture_contracts import assert_fixture_suite

FIXTURES = Path("tests/fixtures")

SUITES: dict[str, tuple[str, ...]] = {
    "configs/default.toml": (),
    "transcripts/complex_block": ("session-a.jsonl", "session-b.jsonl"),
    "transcripts/weekly_rollup": ("weekly-a.jsonl", "weekly-b.jsonl"),
    "transcripts/missing_session": ("session.jsonl",),
    "browser_catalog/chrome_default": (
        "manifest.json",
        "google-chrome/Default/Cookies.sqlite.json",
        "google-chrome/Local State",
    ),
    "browser_catalog/brave_default": (
        "manifest.json",
        "BraveSoftware/Brave-Browser/Default/Cookies.sqlite.json",
        "BraveSoftware/Brave-Browser/Local State",
    ),
    "browser_catalog/missing_cookies": ("manifest.json", "google-chrome/Local State"),
    "sync/live_ok": ("usage.json", "meta.json"),
    "sync/stale_live": ("usage.json", "meta.json"),
    "sync/missing_session": ("error.json",),
    "render/live_ok": ("expected.json", "snapshot.json"),
    "render/stale_live": ("expected.json", "snapshot.json"),
    "render/missing_session": ("expected.json", "snapshot.json"),
    "notifications/block_50_first_fire": (
        "state-before.json",
        "snapshot.json",
        "expected-notifications.json",
        "state-after.json",
    ),
    "notifications/block_50_deduped": (
        "state-before.json",
        "snapshot.json",
        "expected-notifications.json",
        "state-after.json",
    ),
    "notifications/week_80_first_fire": (
        "state-before.json",
        "snapshot.json",
        "expected-notifications.json",
        "state-after.json",
    ),
}
def test_fixture_suites_include_expected_members_and_valid_content():
    assert FIXTURES.exists(), "missing tests/fixtures directory"

    for suite, members in SUITES.items():
        assert_fixture_suite(FIXTURES, suite, members)


def test_missing_fixture_member_fails_with_clear_error(tmp_path: Path):
    source_suite = FIXTURES / "render" / "live_ok"
    render_root = tmp_path / "render"
    copied_suite = render_root / "live_ok"
    shutil.copytree(source_suite, copied_suite)

    missing_file = copied_suite / "expected.json"
    missing_file.unlink()

    with pytest.raises(
        AssertionError,
        match=r"missing fixture member: render/live_ok/expected\.json",
    ):
        assert_fixture_suite(
            tmp_path,
            "render/live_ok",
            ("expected.json", "snapshot.json"),
        )
