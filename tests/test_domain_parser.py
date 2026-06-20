"""Tests for transcript parsing and deduplication semantics."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

UsageEntry = importlib.import_module("claude_usage_tracker.domain.models").UsageEntry
parse_transcript_line = importlib.import_module(
    "claude_usage_tracker.domain.parser"
).parse_transcript_line
transcripts = importlib.import_module("claude_usage_tracker.domain.transcripts")
load_entries = transcripts.load_entries
load_fixture_entries = transcripts.load_fixture_entries


def test_parse_transcript_line_accepts_assistant_rows_and_drops_other_shapes() -> None:
    assistant = json.dumps(
        {
            "timestamp": "2026-05-03T12:00:00Z",
            "role": "assistant",
            "model": "claude-3-7-sonnet",
            "project": "cli-redesign",
            "tokens": 1600,
            "requestId": "req-1",
            "messageId": "msg-1",
        }
    )
    user_row = json.dumps(
        {
            "timestamp": "2026-05-03T12:01:00Z",
            "role": "user",
            "model": "claude-3-7-sonnet",
            "tokens": 100,
        }
    )
    synthetic = json.dumps(
        {
            "timestamp": "2026-05-03T12:02:00Z",
            "role": "assistant",
            "model": "<synthetic>",
            "tokens": 100,
        }
    )

    parsed = parse_transcript_line(assistant)

    assert parsed == UsageEntry.from_flat_record(
        timestamp="2026-05-03T12:00:00Z",
        model="claude-3-7-sonnet",
        project="cli-redesign",
        tokens=1600,
        request_id="req-1",
        message_id="msg-1",
    )
    assert parse_transcript_line(user_row) is None
    assert parse_transcript_line(synthetic) is None
    assert parse_transcript_line("not-json") is None


def test_load_fixture_entries_deduplicates_by_message_and_request_id() -> None:
    entries = load_fixture_entries("tests/fixtures/transcripts/complex_block")

    assert len(entries) == 4
    assert [entry.message_id for entry in entries] == ["msg-1", "msg-2", "msg-3", "msg-4"]


def test_truncated_or_rotated_file_does_not_duplicate_entries(tmp_path: Path) -> None:
    suite = tmp_path / "transcripts"
    suite.mkdir()

    rotated = suite / "session-a.jsonl"
    rotated.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-03T12:00:00Z",
                        "role": "assistant",
                        "model": "claude-3-7-sonnet",
                        "project": "cli-redesign",
                        "tokens": 100,
                        "requestId": "req-1",
                        "messageId": "msg-1",
                    }
                ),
                '{"timestamp":"2026-05-03T12:10:00Z","role":"assistant","model":"claude-3-5-haiku"',
            ]
        ),
        encoding="utf-8",
    )

    replacement = suite / "session-b.jsonl"
    replacement.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-03T12:00:00Z",
                        "role": "assistant",
                        "model": "claude-3-7-sonnet",
                        "project": "cli-redesign",
                        "tokens": 100,
                        "requestId": "req-1",
                        "messageId": "msg-1",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-03T12:15:00Z",
                        "role": "assistant",
                        "model": "claude-3-5-haiku",
                        "project": "release-notes",
                        "tokens": 200,
                        "requestId": "req-2",
                        "messageId": "msg-2",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    entries = load_entries(suite)

    assert [(entry.message_id, entry.request_id) for entry in entries] == [
        ("msg-1", "req-1"),
        ("msg-2", "req-2"),
    ]


def test_entries_without_dedup_keys_are_preserved(tmp_path: Path) -> None:
    suite = tmp_path / "transcripts"
    suite.mkdir()
    session = suite / "session.jsonl"
    session.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-03T12:00:00Z",
                        "role": "assistant",
                        "model": "claude-3-7-sonnet",
                        "project": "cli-redesign",
                        "tokens": 100,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-03T12:00:00Z",
                        "role": "assistant",
                        "model": "claude-3-7-sonnet",
                        "project": "cli-redesign",
                        "tokens": 100,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    entries = load_entries(suite)

    assert len(entries) == 2
    assert all(entry.dedup_key is None for entry in entries)
