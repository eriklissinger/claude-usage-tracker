"""Tests for transcript aggregation and breakdown calculations."""

from __future__ import annotations

import importlib

import pytest

ModelFamily = importlib.import_module("claude_usage_tracker.domain.models").ModelFamily
UsageEntry = importlib.import_module("claude_usage_tracker.domain.models").UsageEntry
load_fixture_entries = importlib.import_module(
    "claude_usage_tracker.domain.transcripts"
).load_fixture_entries
aggregation = importlib.import_module("claude_usage_tracker.domain.aggregation")
aggregate_entries = aggregation.aggregate_entries
model_breakdown = aggregation.model_breakdown
project_breakdown = aggregation.project_breakdown


def test_aggregate_entries_applies_ncu_weights() -> None:
    entries = [
        UsageEntry.from_usage(
            timestamp="2026-05-03T12:00:00Z",
            model="claude-3-opus",
            project="migration",
            input_tokens=100,
            cache_creation_tokens=20,
            cache_read_tokens=999,
            output_tokens=10,
            message_id="msg-1",
            request_id="req-1",
        ),
        UsageEntry.from_usage(
            timestamp="2026-05-03T12:05:00Z",
            model="claude-3-5-haiku",
            project="ops",
            input_tokens=100,
            output_tokens=10,
            message_id="msg-2",
            request_id="req-2",
        ),
    ]

    summary = aggregate_entries(entries)

    assert summary.entry_count == 2
    assert summary.total_tokens == 1239
    assert summary.total_ncu == pytest.approx(912.5)


def test_model_breakdown_groups_entries_by_family_order() -> None:
    entries = load_fixture_entries("tests/fixtures/transcripts/weekly_rollup")

    breakdown = model_breakdown(entries)

    assert [row.label for row in breakdown] == ["opus", "sonnet", "haiku"]
    assert [row.family for row in breakdown] == [
        ModelFamily.OPUS,
        ModelFamily.SONNET,
        ModelFamily.HAIKU,
    ]
    assert [row.entry_count for row in breakdown] == [1, 2, 1]


def test_project_breakdown_uses_basename_unknown_and_top_three() -> None:
    entries = [
        UsageEntry.from_flat_record(
            timestamp="2026-05-03T12:00:00Z",
            model="claude-3-7-sonnet",
            project="/tmp/team/alpha",
            tokens=400,
            message_id="msg-1",
            request_id="req-1",
        ),
        UsageEntry.from_flat_record(
            timestamp="2026-05-03T12:05:00Z",
            model="claude-3-opus",
            project="/tmp/team/beta",
            tokens=100,
            message_id="msg-2",
            request_id="req-2",
        ),
        UsageEntry.from_flat_record(
            timestamp="2026-05-03T12:10:00Z",
            model="claude-3-5-haiku",
            project=None,
            tokens=300,
            message_id="msg-3",
            request_id="req-3",
        ),
        UsageEntry.from_flat_record(
            timestamp="2026-05-03T12:15:00Z",
            model="unknown-model",
            project="/tmp/team/gamma",
            tokens=200,
            message_id="msg-4",
            request_id="req-4",
        ),
    ]

    breakdown = project_breakdown(entries, limit=3)

    assert [row.label for row in breakdown] == ["beta", "alpha", "gamma"]
    assert [row.entry_count for row in breakdown] == [1, 1, 1]
    assert [row.share for row in breakdown] == pytest.approx(
        [0.425531914893617, 0.3404255319148936, 0.1702127659574468]
    )
