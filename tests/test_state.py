"""Tests for dedupe-only notification state."""

import json

import pytest

from claude_usage_tracker.state import State, load_state, save_state, state_path


def test_state_path_uses_xdg_defaults(monkeypatch, tmp_path):
    """State path should resolve to the XDG state location."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    assert state_path() == home / ".local/state/claude-usage-tracker/state.json"


def test_default_state_is_notification_dedupe_only(tmp_path):
    """Default state should serialize to the supported dedupe-only shape."""
    output_path = tmp_path / "state.json"

    save_state(State(), output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == {"notification_dedupe": {}}


def test_state_round_trip(tmp_path):
    """Valid dedupe state should round-trip through JSON."""
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "notification_dedupe": {
                    "reset5hAt": {
                        "window_id": "2026-05-03T15:00:00Z",
                        "sent_thresholds": [50, 75],
                    },
                    "reset7dAt": {
                        "window_id": "2026-05-04T00:00:00Z",
                        "sent_thresholds": [25],
                    },
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state = load_state(state_file)
    output_path = tmp_path / "roundtrip.json"
    save_state(state, output_path)

    assert load_state(output_path) == state


def test_rejects_unexpected_state_payloads(tmp_path):
    """Unexpected top-level state fields should be rejected."""
    state_file = tmp_path / "invalid.json"
    state_file.write_text(
        json.dumps(
            {
                "notification_dedupe": {},
                "last_response_body": {"secret": "nope"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unexpected state keys"):
        load_state(state_file)
