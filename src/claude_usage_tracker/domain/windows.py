"""Anchored 5-hour and weekly transcript window detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import UsageBlock, UsageEntry, UsageWeek, parse_timestamp

FIVE_HOURS = timedelta(hours=5)
SEVEN_DAYS = timedelta(days=7)


def active_block(entries: list[UsageEntry], now: datetime | None = None) -> UsageBlock | None:
    """Return the latest active 5-hour anchored block, if any."""
    if not entries:
        return None

    current_time = _resolve_now(now)
    blocks = _detect_blocks(entries)
    if not blocks:
        return None

    candidate = blocks[-1]
    if current_time - candidate.last_entry_at >= FIVE_HOURS:
        return None
    if current_time >= candidate.ends_at:
        return None
    return candidate


def active_week(
    entries: list[UsageEntry],
    now: datetime | None = None,
    reset_at: datetime | None = None,
) -> UsageWeek | None:
    """Return the latest active weekly window or a synced-reset anchored fallback."""
    current_time = _resolve_now(now)
    if reset_at is not None:
        reset_time = parse_timestamp(reset_at)
        if current_time >= reset_time:
            return None
        start_time = reset_time - SEVEN_DAYS
        window_entries = [
            entry
            for entry in _sorted_entries(entries)
            if start_time <= entry.timestamp < reset_time
        ]
        return UsageWeek(started_at=start_time, ends_at=reset_time, entries=tuple(window_entries))

    windows = _detect_weeks(entries)
    if not windows:
        return None

    candidate = windows[-1]
    if current_time >= candidate.ends_at:
        return None
    return candidate


def _detect_blocks(entries: list[UsageEntry]) -> list[UsageBlock]:
    ordered = _sorted_entries(entries)
    if not ordered:
        return []

    blocks: list[UsageBlock] = []
    current_entries = [ordered[0]]
    current_start = _floor_to_hour(ordered[0].timestamp)
    last_entry = ordered[0]

    for entry in ordered[1:]:
        if (
            (entry.timestamp - current_start) > FIVE_HOURS
            or (entry.timestamp - last_entry.timestamp) > FIVE_HOURS
        ):
            blocks.append(
                UsageBlock(
                    started_at=current_start,
                    ends_at=current_start + FIVE_HOURS,
                    last_entry_at=last_entry.timestamp,
                    entries=tuple(current_entries),
                )
            )
            current_entries = [entry]
            current_start = _floor_to_hour(entry.timestamp)
        else:
            current_entries.append(entry)
        last_entry = entry

    blocks.append(
        UsageBlock(
            started_at=current_start,
            ends_at=current_start + FIVE_HOURS,
            last_entry_at=last_entry.timestamp,
            entries=tuple(current_entries),
        )
    )
    return blocks


def _detect_weeks(entries: list[UsageEntry]) -> list[UsageWeek]:
    ordered = _sorted_entries(entries)
    if not ordered:
        return []

    windows: list[UsageWeek] = []
    current_entries = [ordered[0]]
    current_start = ordered[0].timestamp

    for entry in ordered[1:]:
        if (entry.timestamp - current_start) > SEVEN_DAYS:
            windows.append(
                UsageWeek(
                    started_at=current_start,
                    ends_at=current_start + SEVEN_DAYS,
                    entries=tuple(current_entries),
                )
            )
            current_entries = [entry]
            current_start = entry.timestamp
        else:
            current_entries.append(entry)

    windows.append(
        UsageWeek(
            started_at=current_start,
            ends_at=current_start + SEVEN_DAYS,
            entries=tuple(current_entries),
        )
    )
    return windows


def _sorted_entries(entries: list[UsageEntry]) -> list[UsageEntry]:
    return sorted(entries, key=lambda entry: entry.timestamp)


def _floor_to_hour(value: datetime) -> datetime:
    utc_value = parse_timestamp(value).astimezone(UTC)
    return utc_value.replace(minute=0, second=0, microsecond=0)


def _resolve_now(now: datetime | None) -> datetime:
    return parse_timestamp(now) if now is not None else datetime.now(UTC)
