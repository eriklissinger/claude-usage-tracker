"""Transcript discovery, loading, and deduplication helpers."""

from __future__ import annotations

from pathlib import Path

from .models import UsageEntry
from .parser import parse_transcript_line


def discover_transcripts(root: str | Path) -> list[Path]:
    """Return all transcript JSONL files beneath a root path."""
    root_path = Path(root)
    if root_path.is_file():
        return [root_path]
    return sorted(path for path in root_path.rglob("*.jsonl") if path.is_file())


def load_entries(root: str | Path) -> list[UsageEntry]:
    """Load, parse, sort, and deduplicate transcript entries."""
    parsed_entries: list[UsageEntry] = []
    for path in discover_transcripts(root):
        for line in _complete_lines(path):
            entry = parse_transcript_line(line)
            if entry is not None:
                parsed_entries.append(entry)

    parsed_entries.sort(
        key=lambda entry: (
            entry.timestamp,
            entry.message_id or "",
            entry.request_id or "",
            entry.model,
        )
    )
    return deduplicate_entries(parsed_entries)


def load_fixture_entries(root: str | Path) -> list[UsageEntry]:
    """Convenience wrapper used by fixture-backed tests and smoke commands."""
    return load_entries(root)


def deduplicate_entries(entries: list[UsageEntry]) -> list[UsageEntry]:
    """Deduplicate only entries with both message and request IDs."""
    deduped: list[UsageEntry] = []
    seen_keys: set[tuple[str, str]] = set()
    for entry in entries:
        if entry.dedup_key is None:
            deduped.append(entry)
            continue
        if entry.dedup_key in seen_keys:
            continue
        seen_keys.add(entry.dedup_key)
        deduped.append(entry)
    return deduped


def _complete_lines(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    return [line.rstrip("\r\n") for line in lines if line.endswith(("\n", "\r"))]
