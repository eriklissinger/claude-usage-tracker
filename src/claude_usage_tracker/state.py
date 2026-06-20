"""Notification dedupe state schema and XDG path helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import PlatformDirs

APP_NAME = "claude-usage-tracker"


@dataclass(frozen=True, slots=True)
class NotificationDedupeWindow:
    """Notification dedupe record for one logical reset window."""

    window_id: str
    sent_thresholds: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class State:
    """Persisted state limited to notification dedupe data."""

    notification_dedupe: dict[str, NotificationDedupeWindow] = field(default_factory=dict)


def state_path() -> Path:
    """Return the XDG state path for the app-owned JSON file."""
    return Path(PlatformDirs(appname=APP_NAME, appauthor=False).user_state_dir) / "state.json"


def load_state(path: str | Path | None = None) -> State:
    """Load notification dedupe state from JSON."""
    state_file = Path(path) if path is not None else state_path()
    if not state_file.exists():
        if path is None:
            return State()
        raise FileNotFoundError(state_file)

    data = json.loads(state_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("State payload must be a JSON object")
    _reject_unknown_state_keys(data)

    notification_dedupe = data.get("notification_dedupe", {})
    if not isinstance(notification_dedupe, dict):
        raise ValueError("notification_dedupe must be an object")

    dedupe_windows: dict[str, NotificationDedupeWindow] = {}
    for key, value in notification_dedupe.items():
        if not isinstance(key, str) or not key:
            raise ValueError("notification_dedupe keys must be non-empty strings")
        dedupe_windows[key] = _window_from_dict(key, value)

    return State(notification_dedupe=dedupe_windows)


def save_state(state: State, path: str | Path | None = None) -> Path:
    """Write notification dedupe state as canonical JSON."""
    state_file = Path(path) if path is not None else state_path()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "notification_dedupe": {
            key: asdict(value) for key, value in state.notification_dedupe.items()
        }
    }
    state_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state_file


def _reject_unknown_state_keys(data: dict[str, Any]) -> None:
    unexpected = sorted(set(data) - {"notification_dedupe"})
    if unexpected:
        raise ValueError(f"Unexpected state keys: {unexpected}")


def _window_from_dict(key: str, data: Any) -> NotificationDedupeWindow:
    if not isinstance(data, dict):
        raise ValueError(f"notification_dedupe.{key} must be an object")
    unexpected = sorted(set(data) - {"window_id", "sent_thresholds"})
    if unexpected:
        raise ValueError(f"Unexpected notification_dedupe.{key} keys: {unexpected}")

    window_id = data.get("window_id")
    if not isinstance(window_id, str) or not window_id:
        raise ValueError(f"notification_dedupe.{key}.window_id must be a non-empty string")

    sent_thresholds = _validate_thresholds(data.get("sent_thresholds", []), key)
    return NotificationDedupeWindow(window_id=window_id, sent_thresholds=sent_thresholds)


def _validate_thresholds(value: Any, key: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"notification_dedupe.{key}.sent_thresholds must be a list")
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise ValueError(f"notification_dedupe.{key}.sent_thresholds must contain integers")
    if any(item < 0 or item > 100 for item in value):
        raise ValueError(f"notification_dedupe.{key}.sent_thresholds must be between 0 and 100")
    if sorted(value) != value or len(set(value)) != len(value):
        raise ValueError(f"notification_dedupe.{key}.sent_thresholds must be unique and sorted")
    return list(value)
