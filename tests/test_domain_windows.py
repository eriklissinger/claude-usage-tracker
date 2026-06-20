"""Tests for active 5-hour and weekly transcript windows."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

UsageEntry = importlib.import_module("claude_usage_tracker.domain.models").UsageEntry
load_fixture_entries = importlib.import_module(
    "claude_usage_tracker.domain.transcripts"
).load_fixture_entries
windows = importlib.import_module("claude_usage_tracker.domain.windows")
active_block = windows.active_block
active_week = windows.active_week


def test_active_block_uses_utc_hour_anchor_for_fixture_suite() -> None:
    entries = load_fixture_entries("tests/fixtures/transcripts/complex_block")

    block = active_block(entries, now=datetime(2026, 5, 3, 16, 0, tzinfo=UTC))

    assert block is not None
    assert block.started_at == datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    assert block.ends_at == datetime(2026, 5, 3, 17, 0, tzinfo=UTC)
    assert len(block.entries) == 4


def test_active_block_splits_when_gap_exceeds_five_hours() -> None:
    entries = [
        UsageEntry.from_flat_record(
            timestamp="2026-05-03T12:15:00Z",
            model="claude-3-7-sonnet",
            tokens=100,
            message_id="msg-1",
            request_id="req-1",
        ),
        UsageEntry.from_flat_record(
            timestamp="2026-05-03T17:30:00Z",
            model="claude-3-7-sonnet",
            tokens=100,
            message_id="msg-2",
            request_id="req-2",
        ),
    ]

    block = active_block(entries, now=datetime(2026, 5, 3, 18, 0, tzinfo=UTC))

    assert block is not None
    assert block.started_at == datetime(2026, 5, 3, 17, 0, tzinfo=UTC)
    assert [entry.message_id for entry in block.entries] == ["msg-2"]


def test_active_week_uses_latest_open_window_from_fixture_suite() -> None:
    entries = load_fixture_entries("tests/fixtures/transcripts/weekly_rollup")

    week = active_week(entries, now=datetime(2026, 5, 3, 19, 0, tzinfo=UTC))

    assert week is not None
    assert week.started_at == datetime(2026, 4, 28, 9, 0, tzinfo=UTC)
    assert week.ends_at == datetime(2026, 5, 5, 9, 0, tzinfo=UTC)
    assert len(week.entries) == 4


def test_active_week_can_anchor_to_synced_reset_time() -> None:
    entries = load_fixture_entries("tests/fixtures/transcripts/weekly_rollup")

    week = active_week(
        entries,
        now=datetime(2026, 5, 3, 19, 0, tzinfo=UTC),
        reset_at=datetime(2026, 5, 6, 0, 0, tzinfo=UTC),
    )

    assert week is not None
    assert week.started_at == datetime(2026, 4, 29, 0, 0, tzinfo=UTC)
    assert week.ends_at == datetime(2026, 5, 6, 0, 0, tzinfo=UTC)
    assert [entry.message_id for entry in week.entries] == ["wmsg-2", "wmsg-3", "wmsg-4"]
